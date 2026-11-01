"""Guardrails that run before any model call: rate limit, input checks,
human-request detection, and the monthly spend cap."""
import re
import threading
import time
from collections import defaultdict, deque

# Phrases that mean "let me talk to a person". Checked before the model is
# called, so asking for a human costs nothing and always works.
HUMAN_REQUEST = re.compile(
    r"\b(a human|human agent|real person|live agent|live person|representative|"
    r"(speak|talk|chat) (to|with) (a person|someone|somebody|support|sales|your team|an agent|a member of)|"
    r"contact (support|sales)|call me back|phone call)\b",
    re.IGNORECASE,
)

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")

# Strip anything that looks like our own prompt delimiters, so visitor text
# can't close the <visitor_question> tag and pose as system content.
_TAG = re.compile(r"</?\s*(visitor_question|conversation_history|document|knowledge_base|system)[^>]*>", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def wants_human(text: str) -> bool:
    return bool(HUMAN_REQUEST.search(text))


def clean_text(text: str) -> str:
    return _TAG.sub("", _CONTROL.sub("", text)).strip()


def valid_email(email: str) -> bool:
    return bool(EMAIL.match(email)) and len(email) <= 254


class RateLimiter:
    """Sliding-window limiter per client key (IP). In memory, so it is per
    process: fine for one small instance, use Redis if you scale out."""

    def __init__(self, per_minute: int, per_day: int, clock=time.monotonic):
        self.per_minute, self.per_day = per_minute, per_day
        self.clock = clock
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> float:
        """Record a hit. Returns 0 if allowed, else seconds to wait."""
        now = self.clock()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > 86400:
                hits.popleft()
            last_minute = sum(1 for t in hits if now - t < 60)
            if len(hits) >= self.per_day:
                return max(1.0, 86400 - (now - hits[0]))
            if last_minute >= self.per_minute:
                oldest_in_minute = next(t for t in hits if now - t < 60)
                return max(1.0, 60 - (now - oldest_in_minute))
            hits.append(now)
            return 0.0


def estimate_cost(input_tokens: int, output_tokens: int, price_in: float, price_out: float) -> float:
    return input_tokens / 1_000_000 * price_in + output_tokens / 1_000_000 * price_out

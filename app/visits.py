"""Privacy-friendly visit counter for the public demo.

Counts page loads of /, loads of /widget.js and /chat requests so the owner can see
whether anyone actually tries the demo. No cookies and no personal data: each event
holds the time, the path, an optional ?src= tag (so links in different places can be
told apart), the referring site's domain only, and a coarse user-agent class
(desktop, mobile, bot, monitor, unknown). No IP address and no full user agent.

Events go to a JSONL file. Hosts without a persistent disk (Render's free plan) lose
it on restart, so GET /stats (Bearer STATS_TOKEN, off when no token is set) lets a
scheduled job pull new events into durable storage."""
import json
import logging
import re
import threading
import time
import uuid
from pathlib import Path
from typing import List, Optional
from urllib.parse import parse_qs, urlsplit

log = logging.getLogger("support_chatbot")

MAX_FILE_BYTES = 5_000_000  # a bot flood stops being recorded rather than filling the disk
_SRC_OK = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
# Our own uptime checks and keep-alive pings: recorded as "monitor" so they are never counted.
_MONITORS = ("neouptime", "neo-keepalive", "chatbot-uptime-check", "render", "uptimerobot",
             "pingdom", "statuscake", "betteruptime", "monitor")
_BOTS = ("bot", "crawl", "spider", "slurp", "preview", "facebookexternalhit", "embedly", "curl",
         "wget", "python", "httpx", "aiohttp", "go-http", "java/", "okhttp", "node-fetch", "axios",
         "headless", "lighthouse", "phantomjs", "scrapy", "postman", "insomnia", "libwww", "feed")


def ua_class(user_agent: str) -> str:
    ua = (user_agent or "").lower()
    if not ua:
        return "unknown"
    if any(m in ua for m in _MONITORS):
        return "monitor"
    if any(b in ua for b in _BOTS):
        return "bot"
    if "mozilla/" not in ua:
        return "unknown"
    return "mobile" if any(m in ua for m in ("mobile", "android", "iphone", "ipad")) else "desktop"


def clean_src(value: Optional[str]) -> str:
    value = (value or "").strip().lower()
    if not value:
        return ""
    return value if _SRC_OK.match(value) else "other"


def referrer_parts(referer: str):
    """(domain, src tag carried in the referring URL). The widget script and the chat
    requests come from the demo page itself, so their referrer carries the page's ?src=."""
    try:
        parts = urlsplit(referer or "")
    except ValueError:
        return "", ""
    return (parts.hostname or "")[:80], clean_src((parse_qs(parts.query).get("src") or [""])[0])


class VisitLog:
    def __init__(self, path: Path, clock=time.time):
        self.path = Path(path)
        self.clock = clock
        self._lock = threading.Lock()

    def record(self, path: str, query_src: Optional[str], referer: str, user_agent: str,
               own_host: str = "") -> None:
        """Never raises: counting must not break the demo."""
        try:
            ref_domain, ref_src = referrer_parts(referer)
            now = self.clock()
            event = {
                "id": uuid.uuid4().hex[:16],
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                "path": path,
                "src": clean_src(query_src) or ref_src,
                # Our own domain says nothing about where the visitor came from.
                "ref": "" if own_host and ref_domain == own_host else ref_domain,
                "ua": ua_class(user_agent),
            }
            line = json.dumps(event, separators=(",", ":")) + "\n"
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.path.exists() and self.path.stat().st_size > MAX_FILE_BYTES:
                    return
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(line)
        except Exception:
            log.exception("Visit counter could not record an event")

    def since(self, ts: str = "") -> List[dict]:
        """Events at or after the given UTC timestamp (the caller de-duplicates by id)."""
        if not self.path.exists():
            return []
        out = []
        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        for line in lines:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("ts", "") >= ts:
                out.append(event)
        return out

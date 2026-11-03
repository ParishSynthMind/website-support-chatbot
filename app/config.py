"""Settings, read once from environment variables (or a local .env)."""
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Tiny .env loader so the app has no extra dependency for it.
    Existing environment variables always win over the file."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    company_name: str = "Orbitly"
    knowledge_base_dir: Path = ROOT / "knowledge_base"
    database_path: Path = ROOT / "data" / "chatbot.sqlite3"

    model_provider: str = "anthropic"  # anthropic | openai | gemini
    llm_model: str = "claude-sonnet-5-5"
    llm_max_tokens: int = 1200
    # USD per million tokens, used by the spend cap. from_env() fills in the chosen provider's list prices.
    price_input_per_mtok: float = 2.00
    price_output_per_mtok: float = 10.00
    monthly_spend_cap_usd: float = 20.00

    max_message_chars: int = 500
    max_history_turns: int = 6
    rate_limit_per_minute: int = 8
    rate_limit_per_day: int = 100
    trust_proxy_headers: bool = False
    top_k: int = 5

    allowed_origins: list = field(default_factory=lambda: ["*"])

    notifier: str = "console"  # console | smtp | slack
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    smtp_from: str = ""
    smtp_to: str = ""
    slack_webhook_url: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        from .llm import PROVIDERS

        _load_dotenv(ROOT / ".env")
        e = os.environ.get
        provider = e("MODEL_PROVIDER", "anthropic").strip().lower()
        if provider not in PROVIDERS:
            raise ValueError(f"MODEL_PROVIDER must be one of {sorted(PROVIDERS)}, got {provider!r}")
        _, default_model, default_in, default_out, _ = PROVIDERS[provider]
        origins = [o.strip() for o in e("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
        return cls(
            company_name=e("COMPANY_NAME", "Orbitly"),
            knowledge_base_dir=Path(e("KNOWLEDGE_BASE_DIR", str(ROOT / "knowledge_base"))),
            database_path=Path(e("DATABASE_PATH", str(ROOT / "data" / "chatbot.sqlite3"))),
            model_provider=provider,
            llm_model=e("LLM_MODEL", "").strip() or default_model,
            llm_max_tokens=_int("LLM_MAX_TOKENS", 1200),
            price_input_per_mtok=_float("PRICE_INPUT_PER_MTOK", default_in),
            price_output_per_mtok=_float("PRICE_OUTPUT_PER_MTOK", default_out),
            monthly_spend_cap_usd=_float("MONTHLY_SPEND_CAP_USD", 20.00),
            max_message_chars=_int("MAX_MESSAGE_CHARS", 500),
            max_history_turns=_int("MAX_HISTORY_TURNS", 6),
            rate_limit_per_minute=_int("RATE_LIMIT_PER_MINUTE", 8),
            rate_limit_per_day=_int("RATE_LIMIT_PER_DAY", 100),
            trust_proxy_headers=_bool("TRUST_PROXY_HEADERS", False),
            top_k=_int("TOP_K", 5),
            allowed_origins=origins,
            notifier=e("NOTIFIER", "console").lower(),
            smtp_host=e("SMTP_HOST", ""),
            smtp_port=_int("SMTP_PORT", 587),
            smtp_username=e("SMTP_USERNAME", ""),
            smtp_password=e("SMTP_PASSWORD", ""),
            smtp_use_tls=_bool("SMTP_USE_TLS", True),
            smtp_from=e("SMTP_FROM", ""),
            smtp_to=e("SMTP_TO", ""),
            slack_webhook_url=e("SLACK_WEBHOOK_URL", ""),
        )

import os
from dataclasses import dataclass


def _get_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    coingecko_api_key: str = os.getenv("COINGECKO_API_KEY", "")
    coingecko_base_url: str = os.getenv("COINGECKO_BASE_URL", "https://pro-api.coingecko.com/api/v3")
    vs_currency: str = os.getenv("VS_CURRENCY", "usd")
    per_page: int = int(os.getenv("PER_PAGE", "250"))
    pages: int = int(os.getenv("PAGES", "1"))
    timezone: str = os.getenv("TIMEZONE", "America/Sao_Paulo")
    overnight_hour: int = int(os.getenv("OVERNIGHT_HOUR", "21"))
    overnight_minute: int = int(os.getenv("OVERNIGHT_MINUTE", "0"))
    scan_interval_minutes: int = int(os.getenv("SCAN_INTERVAL_MINUTES", "60"))
    top_n: int = int(os.getenv("TOP_N", "5"))
    overnight_top_n: int = int(os.getenv("OVERNIGHT_TOP_N", "3"))
    min_mcap: float = float(os.getenv("MIN_MCAP", "2000000"))
    max_mcap: float = float(os.getenv("MAX_MCAP", "300000000"))
    min_vol24: float = float(os.getenv("MIN_VOL24", "1500000"))
    exclude_stables: bool = _get_bool("EXCLUDE_STABLES", True)
    snapshot_ttl_minutes: int = int(os.getenv("SNAPSHOT_TTL_MINUTES", "15"))
    review_hours_after_pick: int = int(os.getenv("REVIEW_HOURS_AFTER_PICK", "12"))
    risk_freeze_exhaustion: float = float(os.getenv("RISK_FREEZE_EXHAUSTION", "72"))
    adapt_weights: bool = _get_bool("ADAPT_WEIGHTS", True)
    send_startup_message: bool = _get_bool("SEND_STARTUP_MESSAGE", False)


SETTINGS = Settings()

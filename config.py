import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

@dataclass(frozen=True)
class Settings:
    tg_bot_token: str

    coingecko_base_url: str
    coingecko_api_key: str
    vs_currency: str

    # scanning
    top_n: int
    candidates: int

    # filters
    min_mcap: float
    max_mcap: float
    min_vol24: float
    exclude_stables: bool

    # http
    http_timeout: float
    http_retries: int

    # dex (optional)
    geckoterminal_base_url: str
    use_dex_signal: bool

    # scheduler
    tz: ZoneInfo
    daily_hour: int
    daily_minute: int

def _env_bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip() == "1"

def load_settings() -> Settings:
    tg = os.getenv("TG_BOT_TOKEN", "").strip()
    if not tg:
        raise RuntimeError("❌ TG_BOT_TOKEN não definido.")

    base = os.getenv("COINGECKO_BASE_URL", "https://pro-api.coingecko.com/api/v3").rstrip("/")
    key = (
        os.getenv("COINGECKO_API_KEY", "").strip()
        or os.getenv("COINGECKO_PRO_API_KEY", "").strip()
        or os.getenv("COINGECKO_KEY", "").strip()
    )

    vs = os.getenv("VS_CURRENCY", "usd").strip().lower()

    return Settings(
        tg_bot_token=tg,
        coingecko_base_url=base,
        coingecko_api_key=key,
        vs_currency=vs,

        top_n=int(os.getenv("TOP_N", "5")),
        candidates=int(os.getenv("CANDIDATES", "120")),

        min_mcap=float(os.getenv("MIN_MCAP", "2000000")),
        max_mcap=float(os.getenv("MAX_MCAP", "250000000")),
        min_vol24=float(os.getenv("MIN_VOL24", "1500000")),
        exclude_stables=_env_bool("EXCLUDE_STABLES", "1"),

        http_timeout=float(os.getenv("HTTP_TIMEOUT", "20")),
        http_retries=int(os.getenv("HTTP_RETRIES", "2")),

        geckoterminal_base_url=os.getenv("GECKOTERMINAL_BASE_URL", "https://api.geckoterminal.com/api/v2").rstrip("/"),
        use_dex_signal=_env_bool("USE_DEX_SIGNAL", "1"),

        tz=ZoneInfo(os.getenv("TZ", "America/Sao_Paulo")),
        daily_hour=int(os.getenv("DAILY_HOUR", "21")),
        daily_minute=int(os.getenv("DAILY_MINUTE", "0")),
    )
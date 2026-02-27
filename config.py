import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

def _env(key: str, default: str = "") -> str:
    return (os.getenv(key, default) or "").strip()

def _env_int(key: str, default: int) -> int:
    try:
        return int(_env(key, str(default)))
    except Exception:
        return default

def _env_float(key: str, default: float) -> float:
    try:
        return float(_env(key, str(default)))
    except Exception:
        return default

def _env_bool(key: str, default: bool = False) -> bool:
    v = _env(key, "1" if default else "0").lower()
    return v in ("1", "true", "yes", "y", "on")

@dataclass
class Settings:
    # Telegram
    tg_bot_token: str

    # CoinGecko (Lite)
    cg_api_key: str
    # preferir pro-api se a chave for paga; se der 401, fallback automático
    cg_base_url_pro: str
    cg_base_url_free: str
    vs_currency: str

    # Scanner
    top_n: int
    candidates: int

    min_mcap: float
    max_mcap: float
    min_vol24: float
    exclude_stables: bool

    # regra extra: “se Mcap < Volume, priorizar”
    prefer_mcap_lt_vol: bool
    min_vm: float  # vol/mcap mínimo para entrar

    # HTTP
    http_timeout: float
    http_retries: int

    # Cache
    cache_ttl_sec: int

    # Broadcast
    alert_channel_id: str  # opcional: se vazio, manda só pros inscritos
    scheduler_enabled: bool
    scheduler_hour_brt: int  # 21 = 21h BRT

    tz: ZoneInfo

def load_settings() -> Settings:
    tg_bot_token = _env("TG_BOT_TOKEN")
    if not tg_bot_token:
        raise RuntimeError("❌ TG_BOT_TOKEN não definido.")

    s = Settings(
        tg_bot_token=tg_bot_token,

        # Aceita COINGECKO_API_KEY ou COINGECKO_PRO_API_KEY
        cg_api_key=_env("COINGECKO_API_KEY") or _env("COINGECKO_PRO_API_KEY") or _env("COINGECKO_KEY"),

        cg_base_url_pro=_env("COINGECKO_BASE_URL", "https://pro-api.coingecko.com/api/v3").rstrip("/"),
        cg_base_url_free=_env("COINGECKO_FREE_BASE_URL", "https://api.coingecko.com/api/v3").rstrip("/"),
        vs_currency=_env("VS_CURRENCY", "usd").lower(),

        top_n=_env_int("TOP_N", 5),
        candidates=_env_int("CANDIDATES", 200),

        min_mcap=_env_float("MIN_MCAP", 2_000_000),
        max_mcap=_env_float("MAX_MCAP", 250_000_000),
        min_vol24=_env_float("MIN_VOL24", 1_500_000),
        exclude_stables=_env_bool("EXCLUDE_STABLES", True),

        prefer_mcap_lt_vol=_env_bool("PREFER_MCAP_LT_VOL", True),
        min_vm=_env_float("MIN_VM", 0.15),  # vol/mcap >= 0.15

        http_timeout=_env_float("HTTP_TIMEOUT", 20.0),
        http_retries=_env_int("HTTP_RETRIES", 2),

        cache_ttl_sec=_env_int("CACHE_TTL_SEC", 120),

        alert_channel_id=_env("ALERT_CHANNEL_ID", ""),
        scheduler_enabled=_env_bool("SCHEDULER_ENABLED", False),
        scheduler_hour_brt=_env_int("SCHEDULER_HOUR_BRT", 21),

        tz=ZoneInfo(_env("TZ", "America/Sao_Paulo")),
    )
    return s
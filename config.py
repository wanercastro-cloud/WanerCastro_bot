import os
from dataclasses import dataclass

def _env(name: str, default: str = "") -> str:
    return (os.getenv(name, default) or "").strip()

def _env_bool(name: str, default: str = "0") -> bool:
    return _env(name, default) in ("1", "true", "True", "yes", "YES")

def _env_int(name: str, default: str) -> int:
    try:
        return int(_env(name, default))
    except Exception:
        return int(default)

def _env_float(name: str, default: str) -> float:
    try:
        return float(_env(name, default))
    except Exception:
        return float(default)

@dataclass(frozen=True)
class Settings:
    # Telegram
    TG_BOT_TOKEN: str = _env("TG_BOT_TOKEN")

    # CoinGecko (Lite -> pro-api + header x-cg-pro-api-key)
    COINGECKO_BASE_URL: str = _env("COINGECKO_BASE_URL", "https://pro-api.coingecko.com/api/v3").rstrip("/")
    COINGECKO_API_KEY: str = (
        _env("COINGECKO_API_KEY")
        or _env("COINGECKO_PRO_API_KEY")
        or _env("COINGECKO_KEY")
    )

    # GeckoTerminal (endpoints 4 e 5 do seu PDF)
    GECKOTERMINAL_BASE_URL: str = _env("GECKOTERMINAL_BASE_URL", "https://api.geckoterminal.com/api/v2").rstrip("/")
    USE_DEX_SIGNAL: bool = _env_bool("USE_DEX_SIGNAL", "1")

    # Scanner
    VS_CURRENCY: str = _env("VS_CURRENCY", "usd").lower()
    TOP_N: int = _env_int("TOP_N", "5")
    CANDIDATES: int = _env_int("CANDIDATES", "120")  # quantos ativos avaliar antes do top final

    # Filtros (você pode ajustar via Railway Variables)
    MIN_MCAP: float = _env_float("MIN_MCAP", "2000000")          # 2M
    MAX_MCAP: float = _env_float("MAX_MCAP", "250000000")        # 250M
    MIN_VOL24: float = _env_float("MIN_VOL24", "1500000")        # 1.5M
    MIN_VM: float = _env_float("MIN_VM", "0.05")                 # vol/mcap mínimo (0.05 = 5%)
    EXCLUDE_STABLES: bool = _env_bool("EXCLUDE_STABLES", "1")

    # “mcap menor que volume” = super destaque (boost)
    BOOST_IF_MCAP_LT_VOL: bool = _env_bool("BOOST_IF_MCAP_LT_VOL", "1")

    # Controle de “fervura”
    OVERHEAT_24H: float = _env_float("OVERHEAT_24H", "35.0")      # 24h acima disso começa penalizar

    # HTTP
    HTTP_TIMEOUT: float = _env_float("HTTP_TIMEOUT", "20")
    HTTP_RETRIES: int = _env_int("HTTP_RETRIES", "2")

    # Broadcast/alertas
    ALERT_HOUR_BRT: int = _env_int("ALERT_HOUR_BRT", "21")
    ALERT_MINUTE_BRT: int = _env_int("ALERT_MINUTE_BRT", "0")

SETTINGS = Settings()

if not SETTINGS.TG_BOT_TOKEN:
    raise RuntimeError("❌ Variável TG_BOT_TOKEN não definida.")
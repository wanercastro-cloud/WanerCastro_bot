import os

def _get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

def _get_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()

COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "").strip()
COINGECKO_BASE_URL = os.getenv("COINGECKO_BASE_URL", "https://pro-api.coingecko.com/api/v3").strip()
COINGECKO_FALLBACK_URL = os.getenv("COINGECKO_FALLBACK_URL", "https://api.coingecko.com/api/v3").strip()
COINGECKO_KEY_HEADER = os.getenv("COINGECKO_KEY_HEADER", "x-cg-pro-api-key").strip()

VS_CURRENCY = os.getenv("VS_CURRENCY", "usd").strip()

PER_PAGE = _get_int("PER_PAGE", 200)
TOP_N = _get_int("TOP_N", 50)
TOP_SHOW = _get_int("TOP_SHOW", 20)

MIN_MCAP = _get_float("MIN_MCAP", 0.0)
MIN_VOL24 = _get_float("MIN_VOL24", 0.0)

CACHE_TTL_SEC = _get_int("CACHE_TTL_SEC", 90)
HTTP_TIMEOUT_SEC = _get_int("HTTP_TIMEOUT_SEC", 20)
HTTP_RETRIES = _get_int("HTTP_RETRIES", 5)
CONCURRENCY = _get_int("CONCURRENCY", 3)

RUN_MODE = os.getenv("RUN_MODE", "polling").strip().lower()  # polling | webhook (não usamos aqui)
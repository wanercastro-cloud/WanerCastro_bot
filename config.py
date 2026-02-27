import os

def env(name: str, default: str | None = None) -> str:
    v = os.getenv(name, default)
    if v is None or v == "":
        raise RuntimeError(f"Missing env var: {name}")
    return v

def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default

def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default

# Telegram
TG_BOT_TOKEN = env("TG_BOT_TOKEN")

# CoinGecko (Lite/Pro)
COINGECKO_BASE_URL = env("COINGECKO_BASE_URL", "https://pro-api.coingecko.com/api/v3")
COINGECKO_PRO_API_KEY = env("COINGECKO_PRO_API_KEY")  # header x-cg-pro-api-key

VS_CURRENCY = env("VS_CURRENCY", "usd")

# Ranking / filtros
PER_PAGE = env_int("PER_PAGE", 250)          # máximo típico 250
TOP_N = env_int("TOP_N", 30)                 # quantos mostrar
MIN_MCAP = env_float("MIN_MCAP", 3_000_000)  # default 3M
MAX_MCAP = env_float("MAX_MCAP", 300_000_000) # default 300M
MIN_VOL24 = env_float("MIN_VOL24", 5_000_000) # default 5M

# Regra principal
REQUIRE_VOL_GT_MCAP = env("REQUIRE_VOL_GT_MCAP", "1") == "1"

# Rate limit / robustez
CACHE_TTL_SEC = env_int("CACHE_TTL_SEC", 90)
HTTP_TIMEOUT_SEC = env_int("HTTP_TIMEOUT_SEC", 20)
HTTP_RETRIES = env_int("HTTP_RETRIES", 4)
HTTP_BACKOFF_BASE = env_float("HTTP_BACKOFF_BASE", 1.8)

# Score científico (pesos)
W_RATIO = env_float("W_RATIO", 0.55)     # Vol/Mcap
W_MOM_1H = env_float("W_MOM_1H", 0.15)
W_MOM_12H = env_float("W_MOM_12H", 0.10)
W_MOM_24H = env_float("W_MOM_24H", 0.10)
W_MOM_7D = env_float("W_MOM_7D", 0.10)
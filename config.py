import os

# Telegram
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
ALERT_CHAT_ID = os.getenv("ALERT_CHAT_ID", "").strip()  # opcional (ex: -100123...)

# CoinGecko Pro
COINGECKO_BASE_URL = os.getenv("COINGECKO_BASE_URL", "https://pro-api.coingecko.com/api/v3").rstrip("/")
COINGECKO_API_KEY = (
    os.getenv("COINGECKO_PRO_API_KEY", "").strip()
    or os.getenv("COINGECKO_API_KEY", "").strip()
    or os.getenv("COINGECKO_KEY", "").strip()
)

# Radar params
VS_CURRENCY = os.getenv("VS_CURRENCY", "usd").strip().lower()
TOP_N = int(os.getenv("TOP_N", "5"))
CANDIDATES = int(os.getenv("CANDIDATES", "200"))  # até 250

# Filtros de universo
MIN_MCAP = float(os.getenv("MIN_MCAP", "2000000"))       # 2M
MAX_MCAP = float(os.getenv("MAX_MCAP", "500000000"))     # 500M
MIN_VOL24 = float(os.getenv("MIN_VOL24", "1500000"))     # 1.5M

# Anti-bag / overheat
MAX_1H_P = float(os.getenv("MAX_1H_P", "25"))            # rejeita se 1h > isso
MAX_24H_P = float(os.getenv("MAX_24H_P", "120"))         # rejeita se 24h > isso
OVERHEAT_24H = float(os.getenv("OVERHEAT_24H", "35"))    # penaliza no score acima disso

# “Surf continuação” (trailing simples com base no preço)
TRAIL_PCT = float(os.getenv("TRAIL_PCT", "0.06"))        # 6%

# HTTP
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "20"))
HTTP_RETRIES = int(os.getenv("HTTP_RETRIES", "2"))

# Stables cutoff
EXCLUDE_STABLES = os.getenv("EXCLUDE_STABLES", "1").strip() == "1"
STABLE_SYMBOLS = {
    "USDT", "USDC", "DAI", "TUSD", "USDE", "FDUSD", "PYUSD",
    "EUR", "GBP", "JPY", "TRY", "BRL"
}

if not TG_BOT_TOKEN:
    raise RuntimeError("TG_BOT_TOKEN não definido no Railway.")
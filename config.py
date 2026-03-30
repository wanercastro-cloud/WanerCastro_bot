import os

# =====================================================
#  Configurações gerais
# =====================================================
USE_DYNAMIC_FILTER = os.getenv("USE_DYNAMIC_FILTER", "true").lower() == "true"
STATIC_COINS = os.getenv("STATIC_COINS", "").split(",") if os.getenv("STATIC_COINS") else []
ADAPT_WEIGHTS = os.getenv("ADAPT_WEIGHTS", "false").lower() == "true"

# =====================================================
#  Filtros de mercado
# =====================================================
VS_CURRENCY = os.getenv("VS_CURRENCY", "usd")
PER_PAGE = int(os.getenv("PER_PAGE", "250"))
PAGES = int(os.getenv("PAGES", "1"))
CANDIDATES = int(os.getenv("CANDIDATES", "35"))
MIN_MCAP = float(os.getenv("MIN_MCAP", "2000000"))
MAX_MCAP = float(os.getenv("MAX_MCAP", "300000000"))
MIN_VOL24 = float(os.getenv("MIN_VOL24", "1500000"))
EXCLUDE_STABLES = os.getenv("EXCLUDE_STABLES", "true").lower() == "true"

# =====================================================
#  Indicadores técnicos
# =====================================================
RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
EMA_SHORT = 20
EMA_LONG = 50

WEIGHTS = {
    'rsi': 0.3,
    'macd': 0.4,
    'ema': 0.2,
    'volume': 0.1
}
BUY_THRESHOLD = 0.3
SELL_THRESHOLD = -0.3
MIN_SCORE_FOR_RANKING = float(os.getenv("MIN_SCORE_FOR_RANKING", "0.4"))

# =====================================================
#  Volume
# =====================================================
VOLUME_MA_PERIOD = 20
VOLUME_SPIKE_FACTOR = 1.5

# =====================================================
#  API CoinGecko
# =====================================================
COINGECKO_BASE_URL = os.getenv("COINGECKO_BASE_URL", "https://api.coingecko.com/api/v3")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")

# =====================================================
#  Telegram
# =====================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SEND_STARTUP_MESSAGE = os.getenv("SEND_STARTUP_MESSAGE", "false").lower() == "true"

# =====================================================
#  Comportamento do bot
# =====================================================
SCAN_INTERVAL_MINUTES = int(os.getenv("SCAN_INTERVAL_MINUTES", "60"))
SLEEP_INTERVAL = SCAN_INTERVAL_MINUTES * 60
TOP_BUY_COUNT = int(os.getenv("TOP_N", "5"))

# =====================================================
#  Funcionalidades avançadas
# =====================================================
TIMEZONE = os.getenv("TIMEZONE", "America/Sao_Paulo")
OVERNIGHT_TIME = os.getenv("OVERNIGHT_TIME", "21:00")
OVERNIGHT_TOP_N = int(os.getenv("OVERNIGHT_TOP_N", "3"))
RISK_FREEZE_EXHAUSTION = int(os.getenv("RISK_FREEZE_EXHAUSTION", "72"))
REVIEW_HOURS_AFTER_PICK = int(os.getenv("REVIEW_HOURS_AFTER_PICK", "12"))
SNAPSHOT_TTL_MINUTES = int(os.getenv("SNAPSHOT_TTL_MINUTES", "15"))
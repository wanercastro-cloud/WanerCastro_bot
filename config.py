import os

# Lista estática (opcional, se quiser fallback)
STATIC_COINS = os.getenv("STATIC_COINS", "").split(",") if os.getenv("STATIC_COINS") else []
USE_DYNAMIC_FILTER = os.getenv("USE_DYNAMIC_FILTER", "true").lower() == "true"

# Parâmetros de filtro
VS_CURRENCY = os.getenv("VS_CURRENCY", "usd")
PER_PAGE = int(os.getenv("PER_PAGE", "250"))
PAGES = int(os.getenv("PAGES", "1"))
CANDIDATES = int(os.getenv("CANDIDATES", "35"))
MIN_MCAP = float(os.getenv("MIN_MCAP", "2000000"))      # 2M USD
MAX_MCAP = float(os.getenv("MAX_MCAP", "300000000"))    # 300M USD
MIN_VOL24 = float(os.getenv("MIN_VOL24", "1500000"))    # 1.5M USD
EXCLUDE_STABLES = os.getenv("EXCLUDE_STABLES", "true").lower() == "true"

TIMEFRAME = '1h'
LIMIT = 100               # mínimo de velas para indicadores
SLEEP_INTERVAL = int(os.getenv("SLEEP_INTERVAL", "7200"))

# Indicadores
RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
EMA_SHORT = 20
EMA_LONG = 50

# Pesos
WEIGHTS = {
    'rsi': 0.3,
    'macd': 0.4,
    'ema': 0.3
}
BUY_THRESHOLD = 0.2
SELL_THRESHOLD = -0.2

# CoinGecko
COINGECKO_BASE_URL = os.getenv("COINGECKO_BASE_URL", "https://api.coingecko.com/api/v3")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")  # pode ser None para plano Lite

# Telegram (opcional)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Arquivo de alertas enviados
ALERTS_FILE = "sent_alerts.json"
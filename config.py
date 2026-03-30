import os

# =====================================================
#  Configurações gerais
# =====================================================

# Se True, busca moedas dinamicamente com filtros de market cap e volume.
# Se False, usa a lista estática STATIC_COINS.
USE_DYNAMIC_FILTER = os.getenv("USE_DYNAMIC_FILTER", "true").lower() == "true"

# Lista estática (usada se USE_DYNAMIC_FILTER = false)
STATIC_COINS = os.getenv("STATIC_COINS", "").split(",") if os.getenv("STATIC_COINS") else []

# =====================================================
#  Filtros de mercado (para busca dinâmica)
# =====================================================
VS_CURRENCY = os.getenv("VS_CURRENCY", "usd")
PER_PAGE = int(os.getenv("PER_PAGE", "250"))
PAGES = int(os.getenv("PAGES", "1"))
CANDIDATES = int(os.getenv("CANDIDATES", "35"))
MIN_MCAP = float(os.getenv("MIN_MCAP", "10000000"))      # 10M USD (maior liquidez)
MAX_MCAP = float(os.getenv("MAX_MCAP", "500000000"))     # 500M USD
MIN_VOL24 = float(os.getenv("MIN_VOL24", "5000000"))     # 5M USD (volume diário mínimo)
EXCLUDE_STABLES = os.getenv("EXCLUDE_STABLES", "true").lower() == "true"

# =====================================================
#  Indicadores técnicos
# =====================================================
TIMEFRAME = '1h'               # usado apenas para referência
LIMIT = 100                    # mínimo de velas necessárias

RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
EMA_SHORT = 20
EMA_LONG = 50

# Pesos ajustados para dar mais peso ao MACD e RSI
WEIGHTS = {
    'rsi': 0.4,
    'macd': 0.5,
    'ema': 0.1
}

# Score mínimo para ser considerado compra forte (evita ruído)
BUY_THRESHOLD = 0.4
SELL_THRESHOLD = -0.4

# Score mínimo para entrar no ranking (apenas oportunidades realmente fortes)
MIN_SCORE_FOR_RANKING = float(os.getenv("MIN_SCORE_FOR_RANKING", "0.6"))

# =====================================================
#  API CoinGecko
# =====================================================
COINGECKO_BASE_URL = os.getenv("COINGECKO_BASE_URL", "https://api.coingecko.com/api/v3")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")

# =====================================================
#  Telegram (obrigatório)
# =====================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# =====================================================
#  Comportamento do bot
# =====================================================
SLEEP_INTERVAL = int(os.getenv("SLEEP_INTERVAL", "3600"))   # 1 hora (para operações diárias)
TOP_BUY_COUNT = int(os.getenv("TOP_BUY_COUNT", "5"))         # número de melhores compras
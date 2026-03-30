import os

# =====================================================
#  Configurações gerais
# =====================================================

# Adaptação de pesos (ainda não implementado, mas preparado)
ADAPT_WEIGHTS = os.getenv("ADAPT_WEIGHTS", "false").lower() == "true"

# Lista estática (usada se USE_DYNAMIC_FILTER = false)
STATIC_COINS = os.getenv("STATIC_COINS", "").split(",") if os.getenv("STATIC_COINS") else []

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

# Pesos padrão (podem ser ajustados dinamicamente se ADAPT_WEIGHTS = true)
WEIGHTS = {
    'rsi': 0.4,
    'macd': 0.5,
    'ema': 0.1
}
BUY_THRESHOLD = 0.4
SELL_THRESHOLD = -0.4
MIN_SCORE_FOR_RANKING = float(os.getenv("MIN_SCORE_FOR_RANKING", "0.6"))

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
SCAN_INTERVAL_MINUTES = int(os.getenv("SCAN_INTERVAL_MINUTES", "60"))   # minutos entre scans
SLEEP_INTERVAL = SCAN_INTERVAL_MINUTES * 60   # compatibilidade
TOP_BUY_COUNT = int(os.getenv("TOP_N", "5"))  # alias para TOP_N

# =====================================================
#  Funcionalidades avançadas
# =====================================================
TIMEZONE = os.getenv("TIMEZONE", "America/Sao_Paulo")

# Overnight picks
OVERNIGHT_TIME = os.getenv("OVERNIGHT_TIME", "21:00")   # HH:MM
OVERNIGHT_TOP_N = int(os.getenv("OVERNIGHT_TOP_N", "3"))

# Risk freeze (evita alertas repetidos)
RISK_FREEZE_EXHAUSTION = int(os.getenv("RISK_FREEZE_EXHAUSTION", "72"))  # horas

# Revisão após pick (ainda não implementado, mas preparado)
REVIEW_HOURS_AFTER_PICK = int(os.getenv("REVIEW_HOURS_AFTER_PICK", "12"))

# Cache de dados (evita chamadas desnecessárias à API)
SNAPSHOT_TTL_MINUTES = int(os.getenv("SNAPSHOT_TTL_MINUTES", "15"))
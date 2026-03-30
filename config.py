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
MIN_MCAP = float(os.getenv("MIN_MCAP", "2000000"))      # 2M USD
MAX_MCAP = float(os.getenv("MAX_MCAP", "300000000"))    # 300M USD
MIN_VOL24 = float(os.getenv("MIN_VOL24", "1500000"))    # 1.5M USD
EXCLUDE_STABLES = os.getenv("EXCLUDE_STABLES", "true").lower() == "true"

# =====================================================
#  Indicadores técnicos
# =====================================================
TIMEFRAME = '1h'               # usado apenas para referência, a API fornece dados horários
LIMIT = 100                    # mínimo de velas necessárias (na prática usamos 30 dias = ~720 pontos)

RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
EMA_SHORT = 20
EMA_LONG = 50

WEIGHTS = {
    'rsi': 0.3,
    'macd': 0.4,
    'ema': 0.3
}
BUY_THRESHOLD = 0.2
SELL_THRESHOLD = -0.2

# =====================================================
#  API CoinGecko
# =====================================================
COINGECKO_BASE_URL = os.getenv("COINGECKO_BASE_URL", "https://api.coingecko.com/api/v3")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")   # pode ser None para plano Lite

# =====================================================
#  Telegram (obrigatório para receber ranking)
# =====================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# =====================================================
#  Comportamento do bot
# =====================================================
SLEEP_INTERVAL = int(os.getenv("SLEEP_INTERVAL", "7200"))   # segundos entre execuções
ALERTS_FILE = "sent_alerts.json"                            # (não usado mais, mas mantido para compatibilidade)
TOP_BUY_COUNT = int(os.getenv("TOP_BUY_COUNT", "5"))         # número de melhores compras a exibir no ranking
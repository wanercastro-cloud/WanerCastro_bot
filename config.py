import os

# ========== VARIÁVEIS DE AMBIENTE (Railway) ==========
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ========== CONFIGURAÇÕES DA MOEDA ==========
COIN_ID = "siren"            # ID no CoinGecko (ex: bitcoin, ethereum, siren)
VS_CURRENCY = "usd"          # Moeda de cotação

# ========== TEMPOS ==========
CHECK_EVERY_SECONDS = 300    # A cada 5 minutos verifica novos dados
DAYS_TO_FETCH = 100          # Quantos dias de dados históricos buscar (para indicadores)

# ========== PARÂMETROS DOS INDICADORES ==========
RSI_PERIOD = 14
SMA_PERIOD = 20
BB_PERIOD = 20
BB_STD = 2

# ========== LIMIARES PARA ALERTAS ==========
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70

# ========== LOGGING ==========
LOG_LEVEL = "INFO"
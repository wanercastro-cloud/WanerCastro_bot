# Lista de IDs das criptomoedas na CoinGecko (ex: bitcoin, ethereum, binancecoin, solana, cardano, dogecoin, polkadot, avalanche-2, polygon, chainlink)
COINS = [
    'bitcoin', 'ethereum', 'binancecoin', 'solana', 'cardano',
    'dogecoin', 'polkadot', 'avalanche-2', 'polygon', 'chainlink'
]

TIMEFRAME = '1h'          # intervalo: '1h', '1d', etc.
LIMIT = 100               # número de velas (precisa de pelo menos 50 para indicadores)
SLEEP_INTERVAL = 7200     # segundos entre execuções (2 horas) – respeita limites da API

# Parâmetros dos indicadores
RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
EMA_SHORT = 20
EMA_LONG = 50

# Pesos para classificação
WEIGHTS = {
    'rsi': 0.3,
    'macd': 0.4,
    'ema': 0.3
}

# Limiar para classificação COMPRA/VENDA
BUY_THRESHOLD = 0.2
SELL_THRESHOLD = -0.2

# CoinGecko API
COINGECKO_API_URL = "https://api.coingecko.com/api/v3"
# Para plano Lite, não é necessário API key, mas podemos adicionar se tiver
COINGECKO_API_KEY = None   # opcional

# Arquivo para persistir alertas
ALERTS_FILE = "sent_alerts.json"
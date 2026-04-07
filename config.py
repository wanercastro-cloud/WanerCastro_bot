# config.py
# Configurações centralizadas do sistema (apenas CoinGecko)

import os

# ============================================================
# CONFIGURAÇÕES DA API COINGECKO
# ============================================================
# ⚠️ COLE SUA API KEY AQUI (entre as aspas)
headers = {"CG-hde8oM9DqSTH56RQaxdnkbo7": "SUA_KEY"}   # plano Pro/Lite

# Número máximo de moedas a analisar
COINGECKO_MAX_COINS = 150

# Moeda de cotação
COINGECKO_VS_CURRENCY = "usd"

# Dias de histórico
HISTORICAL_DAYS = 90

# ============================================================
# PESOS DOS INDICADORES
# ============================================================
WEIGHTS_LONG = {
    "rsi": 0.20, "macd": 0.25, "ema": 0.20, "adx": 0.10,
    "cci": 0.10, "bbands": 0.05, "stoch": 0.05, "obv": 0.025, "aroon": 0.025
}

WEIGHTS_SHORT = {
    "rsi": 0.20, "macd": 0.25, "ema": 0.20, "adx": 0.10,
    "cci": 0.10, "bbands": 0.05, "stoch": 0.05, "obv": 0.025, "aroon": 0.025
}

# ============================================================
# BACKTESTING
# ============================================================
BACKTEST_ENABLED = True
BACKTEST_TEST_DAYS = 30
BACKTEST_INITIAL_CAPITAL = 10000

# ============================================================
# FILTROS
# ============================================================
STABLECOINS_SYMBOLS = [
    "usdc", "usdt", "dai", "busd", "tusd", "fdusd", "usdp",
    "lusd", "ustc", "usdd", "usde", "fdai", "cdai", "crvusd",
    "alusd", "mim", "fei", "frax"
]
STABLECOINS_NAMES = [
    "tether", "usd coin", "binance usd", "dai stablecoin", "frax",
    "magic internet money"
]
MIN_VOLUME_USD = 500000
MIN_PRICE_USD = 0.01

# ============================================================
# TELEGRAM (OPCIONAL)
# ============================================================
TELEGRAM_ENABLED = True
TELEGRAM_BOT_TOKEN = os.getenv("8576881325:AAEpzquJWGTHYoDqrACJEY5Xrre3-EGi0oQ", "")
TELEGRAM_CHAT_ID = os.getenv("7239115382", "")

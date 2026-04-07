# config.py
import os

# ============================================================
# CONFIGURAÇÕES DA API COINGECKO
# ============================================================
COINGECKO_API_KEY = os.getenv("CG-hde8oM9DqSTH56RQaxdnkbo7", "")  # ← LINHA QUE FALTAVA

COINGECKO_MAX_COINS = 150
COINGECKO_VS_CURRENCY = "usd"
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
# TELEGRAM
# ============================================================
TELEGRAM_ENABLED = True
TELEGRAM_BOT_TOKEN = os.getenv("8576881325:AAEpzquJWGTHYoDqrACJEY5Xrre3-EGi0oQ", "")  # GitHub Secret
TELEGRAM_CHAT_ID = os.getenv("7239115382", "")            # GitHub Secret

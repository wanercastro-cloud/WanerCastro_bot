# config.py
# Configurações centralizadas do sistema

import os
from binance.client import Client

# ============================================================
# CONFIGURAÇÕES DA API COINGECKO
# ============================================================
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "")  # Deixe vazio para uso gratuito
COINGECKO_MAX_COINS = 200
COINGECKO_VS_CURRENCY = "usd"

# ============================================================
# CONFIGURAÇÕES DA BINANCE
# ============================================================
BINANCE_HISTORICAL_DAYS = 90
BINANCE_INTERVAL = Client.KLINE_INTERVAL_1DAY
BINANCE_USE_WEBSOCKET = False  # Ativar apenas se quiser tempo real

# ============================================================
# PESOS DOS INDICADORES PARA SCORE LONG E SHORT
# ============================================================
WEIGHTS_LONG = {
    "rsi": 0.15,
    "macd": 0.20,
    "ema": 0.20,
    "adx": 0.10,
    "cci": 0.10,
    "bbands": 0.10,
    "stoch": 0.05,
    "obv": 0.05,
    "aroon": 0.05
}

WEIGHTS_SHORT = {
    "rsi": 0.15,
    "macd": 0.20,
    "ema": 0.20,
    "adx": 0.10,
    "cci": 0.10,
    "bbands": 0.10,
    "stoch": 0.05,
    "obv": 0.05,
    "aroon": 0.05
}

# ============================================================
# BACKTESTING
# ============================================================
BACKTEST_ENABLED = True
BACKTEST_TEST_DAYS = 30
BACKTEST_INITIAL_CAPITAL = 10000

# ============================================================
# FILTROS (EXCLUIR STABLECOINS E MOEDAS INVÁLIDAS)
# ============================================================
STABLECOINS_SYMBOLS = [
    "usdc", "usdt", "dai", "busd", "tusd", "fdusd", "usdp",
    "lusd", "ustc", "usdd", "usde", "fdai", "cdai", "crvusd",
    "alusd", "mim", "fei", "frax", "lusd"
]
STABLECOINS_NAMES = [
    "tether", "usd coin", "binance usd", "dai stablecoin", "frax",
    "magic internet money"
]
MIN_VOLUME_USD = 500000
MIN_PRICE_USD = 0.01

# ============================================================
# NOTIFICAÇÕES (TELEGRAM)
# ============================================================
TELEGRAM_ENABLED = False
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
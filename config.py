# config.py
# Configurações centralizadas do sistema (apenas CoinGecko)

import os

# ============================================================
# CONFIGURAÇÕES DA API COINGECKO
# ============================================================
# Para usar a API gratuita sem chave, deixe COINGECKO_API_KEY = ""
# Para usar a API paga, insira sua chave aqui ou na variável de ambiente
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "")

# Número máximo de moedas a analisar (recomendado: 100-150 para free tier)
COINGECKO_MAX_COINS = 150

# Moeda de cotação (usd, brl, etc.)
COINGECKO_VS_CURRENCY = "usd"

# Dias de histórico para cálculo dos indicadores (máx 365 na free)
HISTORICAL_DAYS = 90

# ============================================================
# PESOS DOS INDICADORES PARA SCORES (LONG E SHORT)
# Baseados na literatura (Murphy, Wilder, Appel)
# ============================================================
WEIGHTS_LONG = {
    "rsi": 0.20,
    "macd": 0.25,
    "ema": 0.20,
    "adx": 0.10,
    "cci": 0.10,
    "bbands": 0.05,
    "stoch": 0.05,
    "obv": 0.025,
    "aroon": 0.025
}

WEIGHTS_SHORT = {
    "rsi": 0.20,
    "macd": 0.25,
    "ema": 0.20,
    "adx": 0.10,
    "cci": 0.10,
    "bbands": 0.05,
    "stoch": 0.05,
    "obv": 0.025,
    "aroon": 0.025
}

# ============================================================
# BACKTESTING (OPCIONAL)
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
    "alusd", "mim", "fei", "frax"
]
STABLECOINS_NAMES = [
    "tether", "usd coin", "binance usd", "dai stablecoin", "frax",
    "magic internet money"
]
MIN_VOLUME_USD = 500000   # Volume mínimo 24h em USD
MIN_PRICE_USD = 0.01      # Preço mínimo

# ============================================================
# NOTIFICAÇÕES (TELEGRAM)
# ============================================================
TELEGRAM_ENABLED = False   # Altere para True se quiser receber alertas
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

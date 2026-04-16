# config.py
import os

# ============================================================
# CONFIGURAÇÕES DA API COINGECKO
# ============================================================
COINGECKO_API_KEY      = os.environ.get("COINGECKO_API_KEY", "")
COINGECKO_MAX_COINS    = 150
COINGECKO_VS_CURRENCY  = "usd"
HISTORICAL_DAYS        = 90

# ============================================================
# PESOS DOS INDICADORES — LONG
# ============================================================
WEIGHTS_LONG = {
    "rsi": 0.20, "macd": 0.25, "ema": 0.20, "adx": 0.10,
    "cci": 0.10, "bbands": 0.05, "stoch": 0.05, "obv": 0.025, "aroon": 0.025
}

# ============================================================
# PESOS DOS INDICADORES — SHORT
# ============================================================
WEIGHTS_SHORT = {
    "rsi": 0.20, "macd": 0.25, "ema": 0.20, "adx": 0.10,
    "cci": 0.10, "bbands": 0.05, "stoch": 0.05, "obv": 0.025, "aroon": 0.025
}

# ============================================================
# PESOS DOS INDICADORES — PUMP (detecção antecipada)
# Volume spike + momentum + breakout são os drivers principais
# ============================================================
WEIGHTS_PUMP = {
    "volume_spike": 0.35,   # volume muito acima da média = sinal mais forte
    "rsi_momentum": 0.20,   # RSI entre 55-75: momentum sem exaustão
    "macd_hist":    0.20,   # MACD histogram positivo e crescendo
    "price_1h":     0.15,   # variação 1h acelerada
    "ema_position": 0.10    # preço acima das EMAs (tendência confirmada)
}

# ============================================================
# THRESHOLDS DE ALERTA
# ============================================================
THRESHOLD_LONG  = 0.70
THRESHOLD_SHORT = 0.70
THRESHOLD_PUMP  = 0.68     # levemente mais sensível para pegar antes do pico

# ============================================================
# BACKTESTING
# ============================================================
BACKTEST_ENABLED         = True
BACKTEST_TEST_DAYS       = 30
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
MIN_PRICE_USD  = 0.01

# ============================================================
# TELEGRAM
# ============================================================
TELEGRAM_ENABLED = True
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ============================================================
# VALIDAÇÃO NA INICIALIZAÇÃO
# ============================================================
def validate():
    missing = []
    if not COINGECKO_API_KEY:
        missing.append("COINGECKO_API_KEY")
    if not TELEGRAM_TOKEN:
        missing.append("TELEGRAM_TOKEN")
    if not TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")
    if missing:
        raise EnvironmentError(
            f"Variáveis de ambiente ausentes: {', '.join(missing)}"
        )

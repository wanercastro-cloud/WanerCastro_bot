# config.py
# Configurações baseadas na literatura especializada em análise técnica
# Referências: Murphy (1999), Pring (2002), Wilder (1978), Appel (2005)

import os
from binance.client import Client

# ============================================================
# CONFIGURAÇÕES DAS APIS
# ============================================================
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "")  # Deixe vazio para free tier
COINGECKO_MAX_COINS = 200      # Top 200 por market cap (cobre 99% da liquidez)
COINGECKO_VS_CURRENCY = "usd"

# ============================================================
# CONFIGURAÇÕES DA BINANCE (DADOS HISTÓRICOS)
# ============================================================
BINANCE_HISTORICAL_DAYS = 90   # Período suficiente para indicadores de médio prazo
BINANCE_INTERVAL = Client.KLINE_INTERVAL_1DAY  # Dados diários (evita ruído intradiário)
BINANCE_USE_WEBSOCKET = False  # Desativado para foco em análise batch

# ============================================================
# PESOS DOS INDICADORES PARA SCORES (LONG E SHORT)
# Baseados em estudos de eficácia: momentum e seguimento de tendência têm maior peso
# ============================================================
WEIGHTS_LONG = {
    "rsi": 0.20,      # RSI: relevante em mercados laterais (sobrevenda)
    "macd": 0.25,     # MACD: forte sinal de momentum (principal indicador)
    "ema": 0.20,      # EMAs: confirmação de tendência
    "adx": 0.10,      # ADX: força da tendência (suporte)
    "cci": 0.10,      # CCI: detecção de ciclos (complementar)
    "bbands": 0.05,   # Bollinger: volatilidade (menor peso)
    "stoch": 0.05,    # Estocástico: útil em sobrecompra/sobrevenda, mas ruidoso
    "obv": 0.025,     # OBV: confirmação de volume (peso pequeno)
    "aroon": 0.025    # Aroon: força direcional (peso pequeno)
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
# BACKTESTING (VALIDAÇÃO DA ESTRATÉGIA)
# ============================================================
BACKTEST_ENABLED = True
BACKTEST_TEST_DAYS = 30        # Período fora da amostra (walk-forward)
BACKTEST_INITIAL_CAPITAL = 10000  # Capital fictício inicial

# ============================================================
# FILTROS DE SEGURANÇA E LIQUIDEZ
# ============================================================
# Exclusão de stablecoins (evita ativos sem volatilidade)
STABLECOINS_SYMBOLS = [
    "usdc", "usdt", "dai", "busd", "tusd", "fdusd", "usdp",
    "lusd", "ustc", "usdd", "usde", "fdai", "cdai", "crvusd",
    "alusd", "mim", "fei", "frax", "lusd"
]
STABLECOINS_NAMES = [
    "tether", "usd coin", "binance usd", "dai stablecoin", "frax",
    "magic internet money"
]

# Filtros de liquidez (evita moedas "mortas")
MIN_VOLUME_USD = 500000      # Volume mínimo diário de US$ 500k
MIN_PRICE_USD = 0.01         # Preço mínimo de US$ 0,01 (exclui frações extremas)

# ============================================================
# NOTIFICAÇÕES (TELEGRAM) - OPCIONAL
# ============================================================
TELEGRAM_ENABLED = False      # Ative apenas se tiver configurado token e chat_id
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
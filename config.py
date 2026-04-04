# config.py
# Configurações do bot de monitoramento SIREN

# Parâmetros do ativo e intervalo
SYMBOL = "SIRENUSDT"
INTERVAL = "15m"                # 1m, 5m, 15m, 1h, 4h, 1d
LIMIT = 100                     # número de velas para cálculo

# Parâmetros dos indicadores
EMA_SHORT = 7
EMA_MEDIUM = 14
EMA_LONG = 28
RSI_PERIOD = 14
RSI_OVERBOUGHT = 75             # limite para sobrecompra
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# Lógica do alerta (anti falso sinal)
# Se EMA7 > EMA14 > EMA28 -> tendência explosiva, NÃO gera alerta
IGNORE_STRONG_TREND = True

# Controle de execução
CHECK_EVERY_SECONDS = 300       # 5 minutos
TELEGRAM_ENABLED = True
DISCORD_ENABLED = False         # opcional

# URLs
BINANCE_BASE_URL = "https://api.binance.com/api/v3/klines"
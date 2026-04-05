# config.py

# Lista de moedas a monitorar (usando os IDs da CoinGecko)
# Para obter os IDs corretos, consulte: https://api.coingecko.com/api/v3/coins/list
COINS_TO_MONITOR = [
    {"id": "bitcoin", "name": "Bitcoin"},
    {"id": "ethereum", "name": "Ethereum"},
    {"id": "solana", "name": "Solana"},
    {"id": "binancecoin", "name": "BNB"},
    {"id": "ripple", "name": "XRP"},
    # Adicione ou remova moedas conforme desejar
]

# Parâmetros dos indicadores
LOOKBACK_DAYS = 30         # Quantos dias de dados históricos baixar
RSI_PERIOD = 14
RSI_OVERBOUGHT = 75        # Limite para considerar sobrecomprado

# Controle de execução
# (O intervalo é definido no workflow do GitHub Actions)
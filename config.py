# config.py

# Lista de moedas a monitorar (usando os IDs da CoinGecko)
# Para obter a lista completa: https://api.coingecko.com/api/v3/coins/list
COINS_TO_MONITOR = [
    {"id": "bitcoin", "name": "Bitcoin"},
    {"id": "ethereum", "name": "Ethereum"},
    {"id": "solana", "name": "Solana"},
    {"id": "binancecoin", "name": "BNB"},
    {"id": "ripple", "name": "XRP"},
    {"id": "cardano", "name": "Cardano"},
    {"id": "dogecoin", "name": "Dogecoin"},
    {"id": "polkadot", "name": "Polkadot"},
    {"id": "chainlink", "name": "Chainlink"},
    {"id": "litecoin", "name": "Litecoin"},
]

# Parâmetros dos indicadores
LOOKBACK_DAYS = 30          # Quantos dias de dados históricos baixar
RSI_PERIOD = 14
RSI_OVERBOUGHT = 75         # Limite para considerar sobrecomprado

# Filtro anti-falso sinal: se True, NÃO gera alerta quando EMA7 > EMA14 > EMA28
IGNORE_STRONG_TREND = True
# config.py

# Lista de moedas a monitorar (usando os IDs da CoinGecko)
# Para obter a lista completa: https://api.coingecko.com/api/v3/coins/list
# Você pode adicionar ou remover moedas livremente.
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
    {"id": "avalanche-2", "name": "Avalanche"},
    {"id": "uniswap", "name": "Uniswap"},
    {"id": "matic-network", "name": "Polygon"},
    {"id": "toncoin", "name": "Toncoin"},
    {"id": "shiba-inu", "name": "Shiba Inu"},
    {"id": "bitcoin-cash", "name": "Bitcoin Cash"},
    {"id": "cosmos", "name": "Cosmos"},
    {"id": "stellar", "name": "Stellar"},
    {"id": "vechain", "name": "VeChain"},
    {"id": "algorand", "name": "Algorand"},
]

# Parâmetros dos indicadores
LOOKBACK_DAYS = 30          # Quantos dias de dados históricos baixar
RSI_PERIOD = 14             # Período padrão do RSI
# Os limites de sobrecompra/sobrevenda estão definidos na lógica do bot (70 e 30)
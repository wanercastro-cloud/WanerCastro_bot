# config.py

# Lista ampla de moedas (top 30 por capitalização)
# IDs obtidos da CoinGecko
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

# Parâmetros dos indicadores (ajustáveis)
LOOKBACK_DAYS = 30
RSI_PERIOD = 14
# Limites usados na lógica do bot (não precisa mudar aqui)
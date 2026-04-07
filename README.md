# Crypto Analyzer Bot (apenas CoinGecko)

Sistema de análise de criptomoedas utilizando apenas a API da CoinGecko, com indicadores técnicos implementados manualmente, scoring e backtesting.

## Funcionalidades

- Busca as top N moedas (exclui stablecoins automaticamente)
- Obtém dados históricos de preço via CoinGecko
- Calcula 9 indicadores técnicos: RSI, MACD, EMAs, ADX, CCI, Bollinger Bands, Estocástico, OBV, Aroon
- Gera scores de LONG e SHORT com pesos configuráveis (base

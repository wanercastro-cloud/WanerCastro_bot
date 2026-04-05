# Crypto Analyzer Bot (apenas CoinGecko)

Sistema de análise de criptomoedas utilizando apenas a API da CoinGecko, com indicadores técnicos, scoring e backtesting. Não requer integração com exchanges.

## Funcionalidades

- Busca as top N moedas (exclui stablecoins automaticamente)
- Obtém dados históricos de preço via CoinGecko
- Calcula 9 indicadores técnicos: RSI, MACD, EMAs, ADX, CCI, Bollinger Bands, Estocástico, OBV, Aroon
- Gera scores de LONG e SHORT com pesos configuráveis (baseados na literatura)
- Backtesting da estratégia nos últimos 30 dias
- Envio de alertas via Telegram (opcional)
- Processamento síncrono com pausas para respeitar rate limit (30 chamadas/min)

## Instalação

1. Instale as dependências:
   ```bash
   pip install -r requirements.txt
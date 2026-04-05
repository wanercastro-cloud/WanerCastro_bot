# Crypto Analyzer Bot

Sistema avançado de análise de criptomoedas utilizando APIs da CoinGecko e Binance.

## Funcionalidades

- Busca as top moedas (exclui stablecoins automaticamente)
- Obtém dados históricos OHLCV da Binance
- Calcula 9 indicadores técnicos: RSI, MACD, EMAs, ADX, CCI, Bollinger Bands, Estocástico, OBV, Aroon
- Gera scores de LONG e SHORT com pesos configuráveis
- Backtesting da estratégia nos últimos 30 dias
- Envio de alertas via Telegram (configurável)
- Processamento assíncrono para maior velocidade

## Instalação

1. Clone o repositório
2. Instale as dependências:
   ```bash
   pip install -r requirements.txt
# Overnight Radar Bot v2

Bot de Telegram focado em **overnight** e **continuação com fôlego**, sem scalp.

## O que ele faz
- escolhe os melhores tokens do dia para carregar às 21:00 de Brasília
- usa CoinGecko Lite na URL `https://pro-api.coingecko.com/api/v3`
- calcula RSI, MACD, EMA20/EMA50, ATR, ROC, MFI, Bollinger e ADX
- classifica em:
  - 🌙 OVERNIGHT PREMIUM
  - 📈 CONTINUAÇÃO VÁLIDA
  - 🟡 OBSERVAR
  - ⛔ EXAUSTO
- registra os picks
- revisa os picks depois de algumas horas
- calcula win rate e retorno médio
- ajusta levemente os pesos do score com base no desempenho recente

## Arquivos principais
- `bot.py`: scheduler principal e envio ao Telegram
- `coingecko_client.py`: cliente CoinGecko
- `indicators.py`: cálculo de indicadores
- `strategy.py`: score overnight e classificação
- `performance_tracker.py`: registro, revisão e estatísticas
- `adaptive_weights.py`: ajuste simples de pesos
- `config.py`: leitura das variáveis de ambiente

## Deploy no Railway
1. Suba os arquivos para um repositório GitHub.
2. Crie um projeto no Railway apontando para o repositório.
3. Configure as variáveis do `.env.example`.
4. Start command: `python bot.py`

## Variáveis de ambiente
Use o conteúdo de `.env.example`.

## Observações importantes
- O `market_chart` da CoinGecko não entrega OHLCV puro de exchange. Aqui ele é usado para montar candles horários aproximados a partir de `prices` e `total_volumes`.
- Isso é adequado para **overnight/swing leve**. Para scalp, não serve bem.
- O módulo de “aprendizado” não é IA mágica. Ele só recalibra levemente pesos a partir do resultado recente. Isso é útil, mas não substitui backtest sério.

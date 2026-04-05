# Crypto Alert Bot (CoinGecko + Telegram)

Bot que monitora indicadores técnicos (RSI, MACD, Bollinger Bands) de uma criptomoeda via CoinGecko e envia alertas para o Telegram.

## 🚀 Deploy no Railway

1. Faça fork deste repositório.
2. Crie um projeto no Railway e conecte ao GitHub.
3. Adicione as variáveis de ambiente:
   - `COINGECKO_API_KEY`
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
4. O deploy será automático.

## ⚙️ Configuração

Edite `config.py` para alterar:
- Moeda (`COIN_ID`)
- Períodos dos indicadores
- Limiares de RSI
- Intervalo de verificação

## 📊 Indicadores suportados

- RSI (sobrecompra/sobrevenda)
- MACD (cruzamento de linha e sinal)
- Bandas de Bollinger (preço acima/abaixo)
- SMA 20 (usada internamente)

## 🧪 Teste local

```bash
pip install -r requirements.txt
export COINGECKO_API_KEY="..."
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
python main.py
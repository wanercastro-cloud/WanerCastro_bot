# Crypto Monitor – Alertas Técnicos com GitHub Actions

Este projeto monitora automaticamente várias criptomoedas usando a API do CoinGecko, calcula indicadores (EMA, RSI, MACD) e envia alertas para o Telegram quando identifica uma possível **queda iminente**, com filtro anti‑falso sinal.

## Funcionalidades

- Monitora múltiplas moedas (configurável)
- Busca dados OHLC dos últimos 30 dias
- Calcula EMA7, EMA14, EMA28, RSI(14) e MACD
- Dispara alerta quando:
  - Preço fecha abaixo da EMA7 (perda de força)
  - RSI > 75 (sobrecomprado)
  - Histograma do MACD está diminuindo
  - **Ignora** se a tendência estiver explosiva (EMA7 > EMA14 > EMA28)
- Envia mensagens formatadas para o Telegram
- Cache de alertas (evita spam, cooldown de 1 hora por moeda)
- Executa automaticamente a cada 15 minutos via GitHub Actions (gratuito)

## Como configurar

### 1. Obter credenciais

- **Telegram:** Crie um bot com [@BotFather](https://t.me/botfather) e obtenha o token. Envie uma mensagem para o bot e acesse `https://api.telegram.org/bot<SEU_TOKEN>/getUpdates` para pegar o `chat_id`.
- **CoinGecko API Key:** Acesse [CoinGecko Developers Dashboard](https://www.coingecko.com/en/developers/dashboard), crie uma chave (plano Lite é gratuito).

### 2. Adicionar secrets no GitHub

No repositório: **Settings → Secrets and variables → Actions** → adicione:

| Secret | Valor |
|--------|-------|
| `TELEGRAM_TOKEN` | token do bot |
| `TELEGRAM_CHAT_ID` | seu chat ID |
| `COINGECKO_API_KEY` | sua chave da API |

### 3. Personalizar moedas e parâmetros

Edite `config.py` para alterar a lista de moedas, os limites de RSI, etc.

### 4. Fazer push para o GitHub

O workflow será executado automaticamente a cada 15 minutos. Você também pode disparar manualmente na aba **Actions** do repositório.

## Estrutura do projeto

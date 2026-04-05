name: Monitor SIREN - Queda Iminente

on:
  schedule:
    # Executa a cada 5 minutos (ajuste conforme necessário)
    - cron: '*/5 * * * *'
  workflow_dispatch:  # permite rodar manualmente

jobs:
  check-signal:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout do código
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Cache de dependências pip
        uses: actions/cache@v3
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-${{ hashFiles('requirements.txt') }}
          restore-keys: |
            ${{ runner.os }}-pip-

      - name: Instalar dependências
        run: pip install -r requirements.txt

      - name: Restaurar cache de último alerta
        uses: actions/cache@v3
        id: cache-alerta
        with:
          path: last_alert.json
          key: last-alert-${{ github.run_id }}
          restore-keys: |
            last-alert-

      - name: Executar bot
        env:
          TELEGRAM_TOKEN: ${{ secrets.TELEGRAM_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: python bot.py

      - name: Salvar cache de último alerta (para próximas execuções)
        uses: actions/cache@v3
        with:
          path: last_alert.json
          key: last-alert-${{ github.run_id }}
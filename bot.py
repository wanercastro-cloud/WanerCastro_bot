import os
import logging
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"})
        if r.status_code == 200:
            logger.info("✅ Mensagem enviada")
        else:
            logger.error(f"Erro: {r.text}")
    except Exception as e:
        logger.error(f"Falha: {e}")

def main():
    logger.info("Iniciando bot de teste...")
    
    # 1. TESTE IMEDIATO (sempre envia)
    send_telegram("🤖 Bot ativo! Teste de conexão com Telegram. Em breve você receberá sinais reais.")
    
    # 2. Buscar top 10 moedas (para não sobrecarregar)
    url = "https://api.coingecko.com/api/v3/coins/markets"
    headers = {"x-cg-demo-api-key": COINGECKO_API_KEY}
    params = {"vs_currency": "usd", "order": "market_cap_desc", "per_page": 10, "page": 1}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        coins = resp.json()
        msg = "📊 <b>Top 10 moedas monitoradas:</b>\n"
        for c in coins:
            msg += f"• {c['name']} ({c['symbol'].upper()}) - ${c['current_price']:,.2f}\n"
        send_telegram(msg)
    except Exception as e:
        logger.error(f"Erro ao buscar moedas: {e}")
    
    # 3. Simular um sinal de exemplo (apenas para mostrar o formato)
    send_telegram(
        "🟢 <b>EXEMPLO DE SINAL - LONG</b> 🟢\n"
        "📌 BITCOIN (BTC)\n"
        "🎯 COMPRAR (LONG)\n"
        "💰 $65,432.10\n"
        "📊 RSI: 58.3\n"
        "📈 EMA7: 64,800\n"
        "⚠️ Bybit Futuros: use stop-loss"
    )
    
    logger.info("Bot finalizado. Verifique seu Telegram.")

if __name__ == "__main__":
    main()
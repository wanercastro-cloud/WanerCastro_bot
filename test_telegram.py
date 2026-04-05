#!/usr/bin/env python3
# test_telegram.py - Teste rápido do Telegram

import os
import requests

# Substitua pelos seus valores reais ou use variáveis de ambiente
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "SEU_TOKEN_AQUI")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "SEU_CHAT_ID_AQUI")

def send_test_message():
    if not TOKEN or TOKEN == "SEU_TOKEN_AQUI":
        print("❌ Token não configurado. Defina a variável TELEGRAM_BOT_TOKEN ou edite o script.")
        return
    if not CHAT_ID or CHAT_ID == "SEU_CHAT_ID_AQUI":
        print("❌ Chat ID não configurado. Defina a variável TELEGRAM_CHAT_ID ou edite o script.")
        return

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": "🧪 Teste do Crypto Analyzer Bot - funcionando!"}

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        print("✅ Mensagem enviada com sucesso!")
        print("Resposta:", response.json())
    except Exception as e:
        print(f"❌ Erro: {e}")

if __name__ == "__main__":
    send_test_message()
import os
import sys

print("🚀 BOT INICIANDO...")

required_vars = [
    "TG_BOT_TOKEN",
    "TG_CHAT_ID",
    "COINGECKO_API_KEY",
    "COINGECKO_BASE_URL",
    "TIMEZONE",
    "OVERNIGHT_TIME"
]

missing = []

for var in required_vars:
    if not os.getenv(var):
        missing.append(var)

if missing:
    print("❌ ERRO: Variáveis obrigatórias faltando:")
    for v in missing:
        print(f" - {v}")
    sys.exit(1)

print("✅ Todas as variáveis obrigatórias carregadas")
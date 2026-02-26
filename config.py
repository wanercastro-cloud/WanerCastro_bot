import os

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()

if not TG_BOT_TOKEN:
    raise RuntimeError("TG_BOT_TOKEN não definido")
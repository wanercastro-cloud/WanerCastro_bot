import os
import asyncio
import logging

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("TG_BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Bot online no Railway!")

async def main():
    if not TOKEN:
        raise RuntimeError("❌ TG_BOT_TOKEN não definido nas Variables do Railway")

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))

    logging.info("✅ Iniciando app (initialize/start)...")

    # 1) prepara recursos internos
    await app.initialize()

    # 2) inicia o bot (conecta e começa a receber updates)
    await app.start()

    logging.info("✅ Bot rodando. Mantendo processo vivo...")

    # 3) mantém o processo vivo para o Railway não derrubar
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
import os
import asyncio
import logging

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Log básico para aparecer bonito no Railway (Logs)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

TOKEN = os.getenv("TG_BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Bot online no Railway!")

async def main():
    if not TOKEN:
        raise RuntimeError("❌ TG_BOT_TOKEN não definido nas Variables do Railway")

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))

    logging.info("✅ Bot iniciado. Entrando em polling...")
    await app.run_polling(close_loop=False)

if __name__ == "__main__":
    asyncio.run(main())
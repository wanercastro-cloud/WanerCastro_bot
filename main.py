import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Bot online no Railway!")

def main():
    if not TOKEN:
        raise RuntimeError("TG_BOT_TOKEN não definido")

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))

    logging.info("✅ Bot iniciado com run_polling")
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
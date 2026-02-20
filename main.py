import os
import asyncio
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
from telegram import Update

TOKEN = os.getenv("TG_BOT_$moeda_bot")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot online 🚀")

async def main():
    app = ApplicationBuilder().$moeda_bot.build()
    app.add_handler(CommandHandler("start", start))
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
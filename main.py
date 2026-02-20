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
        raise RuntimeError("TG_BOT_TOKEN não definido")

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))

    logging.info("Bot iniciado")
    await app.initialize()
    await app.start()
    await app.bot.initialize()

    # 👇 ISSO mantém o processo vivo no Railway
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
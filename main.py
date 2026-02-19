from telegram.ext import Application, CommandHandler
import os

TOKEN = os.getenv("TG_BOT_TOKEN")

async def start(update, context):
    await update.message.reply_text("Bot online 🚀")

app = Application.builder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))

print("Bot iniciado")
app.run_polling()
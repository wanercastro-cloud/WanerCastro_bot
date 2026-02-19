import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TOKEN = os.getenv("TG_BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ WanerCastro Bot ativo!\n"
        "Envie /id para ver seu chat_id."
    )

async def chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"📌 Seu chat_id é: {update.effective_chat.id}")

def main():
    if not TOKEN:
        raise RuntimeError("TG_BOT_TOKEN não definido (configure no Railway).")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", chat_id))
    app.run_polling()

if __name__ == "__main__":
    main()
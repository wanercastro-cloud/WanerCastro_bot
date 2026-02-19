import os
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# ========= CONFIG =========
BOT_TOKEN = os.getenv("TG_BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("TG_BOT_TOKEN não definido nas variáveis de ambiente")

# ========= HANDLERS =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"🤖 Bot ativo!\n\nSeu chat_id:\n{chat_id}"
    )

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📊 Top Spot Bybit\n\n(Score combinado em construção 🚧)"
    )

# ========= MAIN =========
async def main():
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("top", top))

    print("🤖 Bot iniciado com polling...")
    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
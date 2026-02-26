from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import TG_BOT_TOKEN
from ranking import build_fomo_report
from smartmoney import build_candidates


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Smart Money Bot online")


async def cmd_radar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔎 Escaneando mercado...")
    data = await build_candidates()
    msg = build_fomo_report(data[:5])
    await update.message.reply_text(msg)


def main():
    app = Application.builder().token(TG_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("radar", cmd_radar))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
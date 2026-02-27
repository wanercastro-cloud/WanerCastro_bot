import asyncio
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from config import TG_BOT_TOKEN, TOP_N
from providers import CoinGeckoClient
from ranking import fetch_rank, format_table, method_text

cg = CoinGeckoClient()

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("pong ✅")

async def rank_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        items = await fetch_rank(cg)
        if not items:
            await update.message.reply_text("⚠️ Sem candidatos no filtro atual (ajuste MIN_MCAP / MAX_MCAP / MIN_VOL24).")
            return
        msg = format_table(items, TOP_N)
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"⚠️ Erro no rank: {type(e).__name__}: {e}")

async def method_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(method_text(), parse_mode=ParseMode.MARKDOWN)

async def on_start(app: Application) -> None:
    # nada aqui, mas fica pronto
    return

def main() -> None:
    app = Application.builder().token(TG_BOT_TOKEN).build()
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("rank", rank_cmd))
    app.add_handler(CommandHandler("method", method_cmd))

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
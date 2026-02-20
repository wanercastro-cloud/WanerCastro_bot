import os
import asyncio
import requests
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes
)

TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()

if not TOKEN:
    raise RuntimeError("TG_BOT_TOKEN não definido")

# ======================
# COINGECKO (fallback)
# ======================
def get_top_volatility():
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        "vs_currency": "usd",
        "order": "volume_desc",
        "per_page": 50,
        "page": 1,
        "price_change_percentage": "1h,24h"
    }

    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()

    # filtro: volatilidade + volume
    filtered = [
        c for c in data
        if abs(c.get("price_change_percentage_1h_in_currency", 0)) >= 2
        and c.get("total_volume", 0) > 100_000_000
    ]

    filtered.sort(
        key=lambda x: abs(x["price_change_percentage_1h_in_currency"]),
        reverse=True
    )

    return filtered[:5]

# ======================
# COMANDOS
# ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Bot online!\n\n"
        "Comandos:\n"
        "/topspot → Top volatilidade (pré-pump)\n"
    )

async def topspot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        coins = get_top_volatility()

        if not coins:
            await update.message.reply_text("Nenhuma moeda com volatilidade forte agora.")
            return

        msg = "🚨 *TOP PRÉ-PUMP (Volatilidade + Volume)*\n\n"

        for i, c in enumerate(coins, 1):
            msg += (
                f"{i}. {c['symbol'].upper()} | "
                f"{c['current_price']:.4f} | "
                f"1h {c['price_change_percentage_1h_in_currency']:+.2f}% | "
                f"Vol ${c['total_volume']:,}\n"
            )

        await update.message.reply_text(msg, parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(
            f"⚠️ Erro ao montar Top Premium.\n{e}"
        )

# ======================
# ALERTA AUTOMÁTICO
# ======================
async def alert_job(context: ContextTypes.DEFAULT_TYPE):
    coins = get_top_volatility()
    if not coins:
        return

    msg = "🐳 *BALEIAS / PRÉ-PUMP DETECTADO*\n\n"
    for c in coins:
        msg += (
            f"{c['symbol'].upper()} | "
            f"1h {c['price_change_percentage_1h_in_currency']:+.2f}% | "
            f"Vol ${c['total_volume']:,}\n"
        )

    await context.bot.send_message(
        chat_id=context.job.chat_id,
        text=msg,
        parse_mode="Markdown"
    )

# ======================
# MAIN
# ======================
async def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("topspot", topspot))

    await app.initialize()
    await app.start()

    # ALERTA A CADA 10 MIN (ANTES DO PUMP)
    app.job_queue.run_repeating(
        alert_job,
        interval=600,
        first=30,
        chat_id=os.getenv("ALERT_CHAT_ID")
    )

    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
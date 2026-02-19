import os
import requests
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes
)

# ===============================
# CONFIG
# ===============================
BOT_TOKEN = os.getenv("TG_BOT_TOKEN")

BYBIT_BASE = "https://api.bybit.com"

# ===============================
# BYBIT HELPERS
# ===============================
def get_spot_symbols():
    url = f"{BYBIT_BASE}/v5/market/instruments-info"
    params = {"category": "spot"}
    r = requests.get(url, params=params, timeout=10)
    data = r.json()
    return [
        s["symbol"]
        for s in data["result"]["list"]
        if s["quoteCoin"] == "USDT"
    ]


def get_ticker(symbol):
    url = f"{BYBIT_BASE}/v5/market/tickers"
    params = {"category": "spot", "symbol": symbol}
    r = requests.get(url, params=params, timeout=10)
    t = r.json()["result"]["list"][0]

    return {
        "symbol": symbol,
        "volume": float(t["turnover24h"]),
        "change": abs(float(t["price24hPcnt"]))
    }


# ===============================
# SCORE COMBINADO
# ===============================
def score_coin(t):
    # pesos ajustáveis
    return (t["volume"] * 0.7) + (t["change"] * 100 * 0.3)


# ===============================
# TELEGRAM COMMANDS
# ===============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Bot ativo!\n\n"
        "Use /top para ver a melhor moeda SPOT da Bybit agora."
    )


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔎 Analisando mercado SPOT da Bybit...")

    symbols = get_spot_symbols()
    results = []

    for s in symbols:
        try:
            t = get_ticker(s)
            t["score"] = score_coin(t)
            results.append(t)
        except:
            continue

    results.sort(key=lambda x: x["score"], reverse=True)
    best = results[0]

    msg = (
        f"🏆 *MELHOR MOEDA SPOT (Score Combinado)*\n\n"
        f"📌 Par: `{best['symbol']}`\n"
        f"💰 Volume 24h: {best['volume']:,.0f}\n"
        f"📈 Variação 24h: {best['change']:.2f}%\n"
        f"⭐ Score: {best['score']:,.0f}"
    )

    await update.message.reply_text(msg, parse_mode="Markdown")


# ===============================
# MAIN
# ===============================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("top", top))

    print("Bot rodando...")
    app.run_polling()


if __name__ == "__main__":
    main()
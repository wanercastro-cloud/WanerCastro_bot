import os
import asyncio
import time
from typing import List, Dict, Any, Optional

import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()

# ======================
# CONFIG
# ======================
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
if not TG_BOT_TOKEN:
    raise RuntimeError("TG_BOT_TOKEN não definido")

BASE_URL = "https://api.coingecko.com/api/v3"
VS = os.getenv("VS_CURRENCY", "usd").lower()

TOP_N = int(os.getenv("TOP_N", "10"))
FETCH_N = int(os.getenv("FETCH_N", "200"))

MIN_MCAP = float(os.getenv("MIN_MCAP", "1000000"))
MIN_VOL = float(os.getenv("MIN_VOL24", "500000"))

RATE_DELAY = 0.4

# ======================
# HELPERS
# ======================
def safe_float(x):
    try:
        return float(x or 0)
    except:
        return 0.0

def fmt_money(x):
    if x >= 1e9: return f"${x/1e9:.2f}B"
    if x >= 1e6: return f"${x/1e6:.2f}M"
    if x >= 1e3: return f"${x/1e3:.2f}K"
    return f"${x:.0f}"

# ======================
# COINGECKO
# ======================
async def fetch_markets(client):
    await asyncio.sleep(RATE_DELAY)
    r = await client.get(
        f"{BASE_URL}/coins/markets",
        params={
            "vs_currency": VS,
            "order": "volume_desc",
            "per_page": min(FETCH_N, 250),
            "page": 1,
            "sparkline": "false",
        },
    )
    r.raise_for_status()
    return r.json()

# ======================
# RANKING VOL > MCAP
# ======================
async def build_volume_ratio_ranking(client):

    markets = await fetch_markets(client)
    candidates = []

    for m in markets:
        mcap = safe_float(m.get("market_cap"))
        vol = safe_float(m.get("total_volume"))

        if mcap < MIN_MCAP or vol < MIN_VOL:
            continue

        if mcap <= 0:
            continue

        ratio = vol / mcap

        if ratio <= 1:  # Volume deve ser maior que Mcap
            continue

        candidates.append({
            "symbol": m["symbol"].upper(),
            "name": m["name"],
            "price": m["current_price"],
            "mcap": mcap,
            "vol": vol,
            "ratio": ratio,
            "chg24": safe_float(m.get("price_change_percentage_24h"))
        })

    # Ordena pelo maior ratio
    ranked = sorted(candidates, key=lambda x: x["ratio"], reverse=True)

    return ranked[:TOP_N]

# ======================
# TELEGRAM
# ======================
async def cmd_rank(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text("🔎 Buscando Volume > Market Cap...")

    client = context.application.bot_data["http"]
    top = await build_volume_ratio_ranking(client)

    if not top:
        await update.message.reply_text("⚠️ Nenhuma moeda com Volume > Mcap encontrada.")
        return

    lines = ["🔥 <b>RANKING VOL > MCAP</b>\n"]

    for i, c in enumerate(top, 1):
        lines.append(
            f"\n<b>{i}) {c['symbol']}</b>\n"
            f"• Ratio: {c['ratio']:.2f}\n"
            f"• Mcap: {fmt_money(c['mcap'])}\n"
            f"• Vol24: {fmt_money(c['vol'])}\n"
            f"• 24h: {c['chg24']:+.2f}%"
        )

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

async def on_startup(app):
    app.bot_data["http"] = httpx.AsyncClient(timeout=20)

async def on_shutdown(app):
    await app.bot_data["http"].aclose()

def main():
    app = (
        Application.builder()
        .token(TG_BOT_TOKEN)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("rank", cmd_rank))

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
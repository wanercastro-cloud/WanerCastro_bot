import os
import math
import asyncio
from typing import List, Dict

import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# =====================
# ENV
# =====================
load_dotenv()

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")

TOP_N = int(os.getenv("TOP_N", "5"))
CANDIDATES = int(os.getenv("CANDIDATES", "1000"))
TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "20"))

if not TG_BOT_TOKEN:
    raise RuntimeError("❌ TG_BOT_TOKEN não definido")

if not COINGECKO_API_KEY:
    raise RuntimeError("❌ COINGECKO_API_KEY não definido")

# =====================
# CONSTANTES
# =====================
CG_BASE_URL = "https://pro-api.coingecko.com/api/v3"

STABLE_IDS = {
    "tether", "usd-coin", "dai", "binance-usd",
    "true-usd", "frax", "usdd", "paypal-usd"
}

# =====================
# COINGECKO
# =====================
async def fetch_markets(page: int, per_page: int) -> List[Dict]:
    headers = {
        "x-cg-pro-api-key": COINGECKO_API_KEY
    }
    params = {
        "vs_currency": "usd",
        "order": "volume_desc",
        "per_page": per_page,
        "page": page,
        "sparkline": "false",
        "price_change_percentage": "1h,24h"
    }

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.get(
            f"{CG_BASE_URL}/coins/markets",
            headers=headers,
            params=params
        )
        r.raise_for_status()
        return r.json()

# =====================
# SCORE SMART MONEY
# =====================
def score_coin(c: Dict) -> float | None:
    mcap = c.get("market_cap") or 0
    vol = c.get("total_volume") or 0
    p1h = c.get("price_change_percentage_1h_in_currency") or 0.0
    p24 = c.get("price_change_percentage_24h_in_currency") or 0.0

    if mcap <= 0 or vol <= 0:
        return None

    # Liquidez relativa (proxy de smart money)
    liq = math.log10(vol / mcap)
    liq_norm = max(0, min(1, (liq + 3) / 3))

    # Momentum curto
    mom = (p1h * 2) + p24
    mom_norm = max(0, min(1, (mom + 10) / 20))

    # Penaliza pump já feito
    penalty = max(0, (p24 - 12) / 30)

    score = (
        0.45 * liq_norm +
        0.35 * mom_norm +
        0.20 * (1 - penalty)
    ) * 100

    return round(score, 1)

# =====================
# CORE SMART MONEY
# =====================
async def compute_smart_money() -> str:
    coins: List[Dict] = []

    pages = math.ceil(CANDIDATES / 250)
    for p in range(1, pages + 1):
        coins.extend(await fetch_markets(p, 250))

    ranked = []

    for c in coins:
        if c["id"] in STABLE_IDS:
            continue

        mcap = c.get("market_cap") or 0
        vol = c.get("total_volume") or 0
        p24 = c.get("price_change_percentage_24h_in_currency") or 0.0

        if mcap < 10_000_000:
            continue
        if vol < 5_000_000:
            continue
        if abs(p24) > 30:
            continue

        s = score_coin(c)
        if s is None:
            continue

        ranked.append((s, c))

    ranked.sort(key=lambda x: x[0], reverse=True)
    top = ranked[:TOP_N]

    lines = ["🔥 *SMART MONEY PRÉ-PUMP (Top 5)*\n"]

    for i, (score, c) in enumerate(top, 1):
        sym = c["symbol"].upper()
        mcap = c["market_cap"]
        vol = c["total_volume"]
        p1h = c.get("price_change_percentage_1h_in_currency") or 0
        p24 = c.get("price_change_percentage_24h_in_currency") or 0

        lines.append(
            f"*{i}) {sym}/USDT* | Score `{score}`\n"
            f"• Mcap: `${mcap:,.0f}`\n"
            f"• Vol24: `${vol:,.0f}`\n"
            f"• 1h: `{p1h:+.2f}%` | 24h: `{p24:+.2f}%`\n"
        )

    return "\n".join(lines)

# =====================
# TELEGRAM HANDLERS
# =====================
async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("pong ✅")

async def smartmoney(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔎 Escaneando CoinGecko PRO…")
    try:
        text = await compute_smart_money()
        await msg.edit_text(text, parse_mode="Markdown")
    except Exception as e:
        await msg.edit_text(f"⚠️ Erro no scanner:\n`{e}`")

# =====================
# MAIN
# =====================
def main():
    app = Application.builder().token(TG_BOT_TOKEN).build()

    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("smartmoney", smartmoney))

    app.run_polling()

if __name__ == "__main__":
    main()
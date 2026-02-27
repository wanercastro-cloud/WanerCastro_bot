# ===== IMPORTS =====
import os
import time
import math
import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()

# ===== ENV =====
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
if not TG_BOT_TOKEN:
    raise RuntimeError("TG_BOT_TOKEN não definido")

BASE_URL = os.getenv("COINGECKO_BASE_URL", "https://api.coingecko.com/api/v3")
VS = os.getenv("VS_CURRENCY", "usd")

PER_PAGE = int(os.getenv("PER_PAGE", "250"))
TOP_SHOW = int(os.getenv("TOP_SHOW", "20"))
TOP_12H = int(os.getenv("TOP_12H", "20"))

HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "20"))
HTTP_RETRIES = int(os.getenv("HTTP_RETRIES", "3"))
CONCURRENCY = int(os.getenv("CONCURRENCY", "4"))

REQUIRE_VOL_GT_MCAP = os.getenv("REQUIRE_VOL_GT_MCAP", "1") == "1"

# ===== CACHE =====
class TTLCache:
    def __init__(self, ttl=300):
        self.ttl = ttl
        self.data = {}

    def get(self, key):
        val = self.data.get(key)
        if not val:
            return None
        ts, data = val
        if time.time() - ts > self.ttl:
            self.data.pop(key, None)
            return None
        return data

    def set(self, key, val):
        self.data[key] = (time.time(), val)

CACHE = TTLCache()

# ===== HELPERS =====
def safe_div(a, b):
    return a / b if b else 0

def clamp(x, lo, hi):
    return max(lo, min(hi, x))

async def http_get(client, url, params, cache_key=None):
    if cache_key:
        cached = CACHE.get(cache_key)
        if cached:
            return cached

    backoff = 0.7
    for i in range(HTTP_RETRIES + 1):
        r = await client.get(url, params=params)
        if r.status_code == 429:
            await asyncio.sleep(backoff * (2 ** i))
            continue
        r.raise_for_status()
        data = r.json()
        if cache_key:
            CACHE.set(cache_key, data)
        return data
    raise RuntimeError("Falha HTTP")

# ===== DATA MODEL =====
@dataclass
class Coin:
    id: str
    symbol: str
    price: float
    mcap: float
    vol: float
    ratio: float
    chg1h: float
    chg24h: float
    chg7d: float
    chg12h: Optional[float] = None
    momentum: Optional[float] = None

# ===== FETCH MARKETS =====
async def fetch_markets(client):
    url = f"{BASE_URL}/coins/markets"
    params = {
        "vs_currency": VS,
        "order": "volume_desc",
        "per_page": PER_PAGE,
        "page": 1,
        "sparkline": "false",
        "price_change_percentage": "1h,24h,7d"
    }
    return await http_get(client, url, params, "markets")

# ===== FETCH 12H =====
async def fetch_12h(client, coin_id):
    url = f"{BASE_URL}/coins/{coin_id}/market_chart"
    params = {"vs_currency": VS, "days": 1, "interval": "hourly"}
    data = await http_get(client, url, params, f"chart:{coin_id}")
    prices = data.get("prices")
    if not prices or len(prices) < 6:
        return None
    last_ts, last_price = prices[-1]
    target = last_ts - 12*60*60*1000
    best = min(prices, key=lambda x: abs(x[0] - target))
    old_price = best[1]
    return (last_price/old_price - 1) * 100

# ===== BUILD COINS =====
async def build_coins(client, filter_vol=True):
    markets = await fetch_markets(client)
    coins = []
    for c in markets:
        try:
            mcap = c["market_cap"] or 0
            vol = c["total_volume"] or 0
            if mcap <= 0 or vol <= 0:
                continue
            if filter_vol and not (vol > mcap):
                continue

            coins.append(
                Coin(
                    id=c["id"],
                    symbol=c["symbol"].upper(),
                    price=c["current_price"],
                    mcap=mcap,
                    vol=vol,
                    ratio=vol/mcap,
                    chg1h=c.get("price_change_percentage_1h_in_currency") or 0,
                    chg24h=c.get("price_change_percentage_24h_in_currency") or 0,
                    chg7d=c.get("price_change_percentage_7d_in_currency") or 0
                )
            )
        except:
            continue

    coins.sort(key=lambda x: x.ratio, reverse=True)

    sem = asyncio.Semaphore(CONCURRENCY)

    async def enrich(c):
        async with sem:
            try:
                c.chg12h = await fetch_12h(client, c.id)
            except:
                pass

    await asyncio.gather(*(enrich(c) for c in coins[:TOP_12H]))
    return coins

# ===== MOMENTUM SCORE =====
def compute_momentum(c: Coin):
    if c.chg12h is None:
        return 0

    overheat = 1 if c.chg24h > 40 else 0

    score = (
        0.35 * clamp(c.chg1h/10, -1, 2) +
        0.30 * clamp(c.chg12h/20, -1, 2) +
        0.20 * clamp(c.chg24h/40, -1, 2) +
        0.10 * clamp(c.chg7d/80, -1, 2) +
        0.15 * clamp(c.ratio/3, 0, 2)
    )

    if overheat:
        score -= 0.5

    return round(score * 100, 2)

# ===== FORMAT =====
def format_list(coins, mode):
    if not coins:
        return "⚠️ Nenhuma moeda encontrada"

    lines = [f"<b>{mode}</b>\n"]
    for i, c in enumerate(coins[:TOP_SHOW], 1):
        lines.append(
            f"{i}) {c.symbol} | Vol/Mcap {c.ratio:.2f}x\n"
            f"1h {c.chg1h:+.2f}% | 12h {c.chg12h or 0:+.2f}% | "
            f"24h {c.chg24h:+.2f}% | 7d {c.chg7d:+.2f}%\n"
            + (f"MomentumScore {c.momentum}\n" if c.momentum else "")
        )
    return "\n".join(lines)

# ===== COMMANDS =====
async def cmd_rank(update, context):
    client = context.application.bot_data["http"]
    coins = await build_coins(client, filter_vol=True)
    await update.message.reply_text(format_list(coins, "RANK Vol>Mcap"), parse_mode=ParseMode.HTML)

async def cmd_rank_all(update, context):
    client = context.application.bot_data["http"]
    coins = await build_coins(client, filter_vol=False)
    await update.message.reply_text(format_list(coins, "RANK ALL"), parse_mode=ParseMode.HTML)

async def cmd_rank_momentum(update, context):
    client = context.application.bot_data["http"]
    coins = await build_coins(client, filter_vol=False)

    for c in coins:
        c.momentum = compute_momentum(c)

    coins.sort(key=lambda x: x.momentum or 0, reverse=True)

    await update.message.reply_text(format_list(coins, "RANK MOMENTUM"), parse_mode=ParseMode.HTML)

# ===== LIFECYCLE =====
async def on_startup(app):
    app.bot_data["http"] = httpx.AsyncClient(timeout=HTTP_TIMEOUT)

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
    app.add_handler(CommandHandler("rank_all", cmd_rank_all))
    app.add_handler(CommandHandler("rank_momentum", cmd_rank_momentum))

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
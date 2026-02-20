import os
import math
import time
import logging
import asyncio
import requests

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

load_dotenv()
logging.basicConfig(level=logging.INFO)

TG_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
CG_KEY = (os.getenv("COINGECKO_API_KEY", "") or "").strip()

TELEGRAM_MAX = 4096

# Bybit
BYBIT_TICKERS_URL = "https://api.bybit.com/v5/market/tickers"

# CoinGecko (public)
CG_BASE = "https://api.coingecko.com/api/v3"
CG_SIMPLE_PRICE = f"{CG_BASE}/simple/price"
CG_COINS_MARKETS = f"{CG_BASE}/coins/markets"
CG_COINS_LIST = f"{CG_BASE}/coins/list"

# Cache
CACHE_TTL_TOP = 60
_cache_top_text: str | None = None
_cache_top_ts: float = 0.0

COINLIST_TTL = 24 * 3600
_coinlist_cache: list[dict] | None = None
_coinlist_ts: float = 0.0


def _headers_default():
    return {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def _headers_cg():
    h = _headers_default()
    # CoinGecko docs mostram header de demo/pro key; usamos o demo header por compatibilidade.
    # Se sua chave for Pro, muitos ambientes aceitam x-cg-pro-api-key também.
    if CG_KEY:
        h["x-cg-demo-api-key"] = CG_KEY
        h["x-cg-pro-api-key"] = CG_KEY
    return h


def safe_float(x, default=0.0) -> float:
    try:
        if x is None or x == "":
            return default
        return float(x)
    except Exception:
        return default


async def http_get_json(url: str, params: dict | None = None, headers: dict | None = None, timeout: int = 10):
    def _req():
        r = requests.get(url, params=params, headers=headers or _headers_default(), timeout=timeout)
        status = r.status_code
        try:
            data = r.json()
        except Exception:
            data = None
        return status, data

    return await asyncio.to_thread(_req)


# -------------------------
# BYBIT (fonte 1)
async def bybit_spot_tickers() -> tuple[int | None, list[dict]]:
    status, data = await http_get_json(BYBIT_TICKERS_URL, {"category": "spot"}, timeout=10)
    if status is None or not isinstance(data, dict):
        return status, []
    if status != 200 or data.get("retCode") != 0:
        return status, []
    lst = data.get("result", {}).get("list", [])
    return status, (lst if isinstance(lst, list) else [])


async def bybit_spot_price(symbol: str) -> tuple[int | None, dict | None]:
    status, data = await http_get_json(BYBIT_TICKERS_URL, {"category": "spot", "symbol": symbol}, timeout=10)
    if status is None or not isinstance(data, dict):
        return status, None
    if status != 200 or data.get("retCode") != 0:
        return status, None
    lst = data.get("result", {}).get("list", [])
    if not lst:
        return status, None
    t = lst[0]
    return status, {
        "source": "Bybit",
        "symbol": symbol,
        "last": safe_float(t.get("lastPrice")),
        "pct24h": safe_float(t.get("price24hPcnt")) * 100.0,
        "vol24h": safe_float(t.get("turnover24h")),
    }


def bybit_score(t: dict) -> float:
    try:
        s = t.get("symbol", "")
        if not isinstance(s, str) or not s.endswith("USDT"):
            return -1e18
        vol = safe_float(t.get("turnover24h"))
        if vol <= 0:
            return -1e18
        sc = math.log10(vol)
        return sc if math.isfinite(sc) else -1e18
    except Exception:
        return -1e18


# -------------------------
# COINGECKO (fonte 2)
# mapeamento rápido para os maiores (evita coins/list em todo /price)
SYMBOL_TO_CGID = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "ADA": "cardano",
    "AVAX": "avalanche-2",
    "DOGE": "dogecoin",
    "LINK": "chainlink",
    "MATIC": "polygon-pos",
    "TON": "the-open-network",
    "TRX": "tron",
    "DOT": "polkadot",
    "LTC": "litecoin",
}


async def cg_get_coinlist() -> list[dict]:
    global _coinlist_cache, _coinlist_ts
    now = time.time()
    if _coinlist_cache and (now - _coinlist_ts) < COINLIST_TTL:
        return _coinlist_cache

    status, data = await http_get_json(CG_COINS_LIST, None, headers=_headers_cg(), timeout=15)
    if status != 200 or not isinstance(data, list):
        return _coinlist_cache or []

    _coinlist_cache = data
    _coinlist_ts = now
    return data


async def cg_resolve_id_from_symbol(base_symbol: str) -> str | None:
    base_symbol = base_symbol.upper().strip()
    if base_symbol in SYMBOL_TO_CGID:
        return SYMBOL_TO_CGID[base_symbol]

    # fallback: coins/list e pega o primeiro que bater no "symbol"
    cl = await cg_get_coinlist()
    if not cl:
        return None

    target = base_symbol.lower()
    for item in cl:
        if item.get("symbol") == target:
            return item.get("id")
    return None


async def coingecko_price_usd(base_symbol: str) -> dict | None:
    coin_id = await cg_resolve_id_from_symbol(base_symbol)
    if not coin_id:
        return None

    # /simple/price precisa do id e vs_currencies
    status, data = await http_get_json(
        CG_SIMPLE_PRICE,
        params={"ids": coin_id, "vs_currencies": "usd"},
        headers=_headers_cg(),
        timeout=10,
    )
    if status != 200 or not isinstance(data, dict) or coin_id not in data:
        return None

    price = safe_float(data.get(coin_id, {}).get("usd"))
    if price <= 0:
        return None

    return {
        "source": "CoinGecko",
        "symbol": f"{base_symbol}USDT",
        "last": price,
        "pct24h": 0.0,   # não vem no simple/price por padrão
        "vol24h": 0.0,   # idem
        "note": f"id={coin_id}",
    }


async def coingecko_topspot_usd(limit: int = 10) -> tuple[str, list[dict]] | None:
    # coins/markets traz volume e variação 24h (dependendo do plano/dados)
    params = {
        "vs_currency": "usd",
        "order": "volume_desc",
        "per_page": limit,
        "page": 1,
        "sparkline": "false",
        "price_change_percentage": "24h",
    }
    status, data = await http_get_json(CG_COINS_MARKETS, params=params, headers=_headers_cg(), timeout=15)

    # alguns ambientes podem rejeitar order=volume_desc; fallback simples:
    if status != 200 or not isinstance(data, list) or not data:
        params["order"] = "market_cap_desc"
        status, data = await http_get_json(CG_COINS_MARKETS, params=params, headers=_headers_cg(), timeout=15)

    if status != 200 or not isinstance(data, list) or not data:
        return None

    rows = []
    for item in data[:limit]:
        sym = (item.get("symbol") or "").upper()
        rows.append({
            "symbol": f"{sym}USDT",
            "last": safe_float(item.get("current_price")),
            "pct24h": safe_float(item.get("price_change_percentage_24h")),
            "vol24h": safe_float(item.get("total_volume")),
        })

    return "CoinGecko", rows


# -------------------------
# Telegram commands
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Bot Spot ONLINE (Bybit → CoinGecko fallback)\n\n"
        "Comandos:\n"
        "/price BTCUSDT\n"
        "/topspot"
    )


async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /price BTCUSDT")
        return

    symbol = context.args[0].upper().replace("/", "").strip()
    if not symbol.endswith("USDT"):
        await update.message.reply_text("Use pares no formato *USDT* (ex: BTCUSDT).")
        return

    base = symbol.replace("USDT", "")

    msg = await update.message.reply_text("⏳ Consultando...")

    # 1) Bybit
    status, info = await bybit_spot_price(symbol)
    if info:
        await msg.edit_text(
            f"📌 {info['symbol']} ({info['source']})\n"
            f"💰 Preço: {info['last']}\n"
            f"📈 24h: {info['pct24h']:+.2f}%\n"
            f"🔄 Volume 24h: {info['vol24h']:,.0f}"
        )
        return

    # 2) CoinGecko
    cg = await coingecko_price_usd(base)
    if cg:
        await msg.edit_text(
            f"📌 {cg['symbol']} ({cg['source']})\n"
            f"💰 Preço: {cg['last']}\n"
            f"ℹ️ {cg.get('note','')}\n"
            f"(CoinGecko: preço agregado, pode diferir da Bybit)"
        )
        return

    # Falhou geral
    code = f"HTTP {status}" if status is not None else "sem conexão"
    await msg.edit_text(f"⚠️ Falhou em Bybit ({code}) e CoinGecko. Tente novamente.")


async def topspot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _cache_top_text, _cache_top_ts

    now = time.time()
    if _cache_top_text and (now - _cache_top_ts) < CACHE_TTL_TOP:
        await update.message.reply_text(_cache_top_text)
        return

    msg = await update.message.reply_text("⏳ Montando Top Premium Spot...")

    # 1) Bybit
    status, tickers = await bybit_spot_tickers()
    if tickers:
        ranked = [(bybit_score(t), t) for t in tickers]
        ranked = [x for x in ranked if x[0] > 0]
        ranked.sort(key=lambda x: x[0], reverse=True)
        top = ranked[:10]

        lines = []
        for i, (_, t) in enumerate(top, start=1):
            sym = t.get("symbol", "?")
            last = safe_float(t.get("lastPrice"))
            pct = safe_float(t.get("price24hPcnt")) * 100.0
            vol = safe_float(t.get("turnover24h"))
            lines.append(f"{i:02d}. {sym} | {last:.8g} | 24h {pct:+.2f}% | vol {vol:,.0f}")

        text = "🏆 Top Premium Spot (Bybit)\n" + "\n".join(lines)
        if len(text) > TELEGRAM_MAX:
            text = text[:TELEGRAM_MAX - 50] + "\n..."

        _cache_top_text = text
        _cache_top_ts = time.time()
        await msg.edit_text(text)
        return

    # 2) CoinGecko
    cg = await coingecko_topspot_usd(limit=10)
    if cg:
        source, rows = cg
        lines = []
        for i, r in enumerate(rows, start=1):
            lines.append(f"{i:02d}. {r['symbol']} | {r['last']:.8g} | 24h {r['pct24h']:+.2f}% | vol {r['vol24h']:,.0f}")

        text = f"🏆 Top Premium (fallback: {source})\n" + "\n".join(lines)
        if len(text) > TELEGRAM_MAX:
            text = text[:TELEGRAM_MAX - 50] + "\n..."

        _cache_top_text = text
        _cache_top_ts = time.time()
        await msg.edit_text(text)
        return

    code = f"HTTP {status}" if status is not None else "sem conexão"
    await msg.edit_text(f"⚠️ Falhou em Bybit ({code}) e CoinGecko. Tente novamente.")


def main():
    if not TG_TOKEN:
        raise RuntimeError("TG_BOT_TOKEN não definido (.env)")

    app = ApplicationBuilder().token(TG_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price_cmd))
    app.add_handler(CommandHandler("topspot", topspot_cmd))

    logging.info("✅ Bot iniciado (Bybit → CoinGecko fallback)")
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
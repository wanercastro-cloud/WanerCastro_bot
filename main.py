import os
import math
import time
import logging
import asyncio
import requests

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
BYBIT_TICKERS_URL = "https://api.bybit.com/v5/market/tickers"
TELEGRAM_MAX = 4096

# Cache simples em memória (por instância)
CACHE_TTL = 60  # segundos
_cache_topspot_text: str | None = None
_cache_topspot_ts: float = 0.0


def safe_float(x, default=0.0) -> float:
    try:
        if x is None or x == "":
            return default
        return float(x)
    except Exception:
        return default


def _fetch_spot_tickers_sync() -> list[dict]:
    # timeout mais curto para não “morrer abraçado”
    r = requests.get(
        BYBIT_TICKERS_URL,
        params={"category": "spot"},
        timeout=8,  # <<< importante
        headers={"User-Agent": "Mozilla/5.0"},
    )
    r.raise_for_status()
    data = r.json()

    if not isinstance(data, dict) or data.get("retCode") != 0:
        logging.error("Bybit resposta inválida: %s", data)
        return []

    result = data.get("result", {})
    lst = result.get("list", [])
    return lst if isinstance(lst, list) else []


async def fetch_spot_tickers() -> list[dict]:
    # roda o requests em thread separada (não trava o async)
    return await asyncio.to_thread(_fetch_spot_tickers_sync)


def premium_score(t: dict) -> float:
    symbol = t.get("symbol", "")
    if not symbol.endswith("USDT"):
        return -1e18

    last = safe_float(t.get("lastPrice"))
    turnover = safe_float(t.get("turnover24h"))

    if last <= 0 or turnover <= 0:
        return -1e18

    return math.log10(turnover)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Bot Bybit Spot online!\n\n"
        "Comandos:\n"
        "/price BTCUSDT\n"
        "/topspot"
    )


def _fetch_one_ticker_sync(symbol: str) -> dict | None:
    r = requests.get(
        BYBIT_TICKERS_URL,
        params={"category": "spot", "symbol": symbol},
        timeout=8,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict) or data.get("retCode") != 0:
        return None
    lst = data.get("result", {}).get("list", [])
    return lst[0] if lst else None


async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /price BTCUSDT")
        return

    symbol = context.args[0].upper().replace("/", "").strip()

    try:
        t = await asyncio.to_thread(_fetch_one_ticker_sync, symbol)
        if not t:
            await update.message.reply_text("❌ Par não encontrado na Spot da Bybit.")
            return

        last = safe_float(t.get("lastPrice"))
        chg = safe_float(t.get("price24hPcnt")) * 100.0
        turnover = safe_float(t.get("turnover24h"))

        await update.message.reply_text(
            f"📌 {symbol} (Bybit Spot)\n"
            f"💰 Preço: {last}\n"
            f"📈 24h: {chg:+.2f}%\n"
            f"🔄 Volume 24h: {turnover:,.0f}"
        )

    except Exception:
        logging.exception("Erro no /price")
        await update.message.reply_text("⚠️ Erro ao consultar a Bybit.")


async def topspot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _cache_topspot_text, _cache_topspot_ts

    # 1) responde rápido com cache, se tiver
    now = time.time()
    if _cache_topspot_text and (now - _cache_topspot_ts) < CACHE_TTL:
        await update.message.reply_text(_cache_topspot_text)
        return

    # 2) dá feedback imediato (pra não parecer travado)
    status_msg = await update.message.reply_text("⏳ Montando Top Premium Spot...")

    try:
        tickers = await fetch_spot_tickers()
        if not tickers:
            await status_msg.edit_text("⚠️ Bybit não retornou dados agora. Tente novamente.")
            return

        scored = []
        for t in tickers:
            s = premium_score(t)
            if s > 0:
                scored.append((s, t))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:10]

        if not top:
            await status_msg.edit_text("⚠️ Nenhum par Spot premium agora.")
            return

        lines = []
        for i, (_, t) in enumerate(top, start=1):
            sym = t.get("symbol", "?")
            last = safe_float(t.get("lastPrice"))
            chg = safe_float(t.get("price24hPcnt")) * 100.0
            turnover = safe_float(t.get("turnover24h"))

            lines.append(f"{i:02d}. {sym} | {last:.8g} | 24h {chg:+.2f}% | vol {turnover:,.0f}")

        text = "🏆 Top Premium Spot (Bybit – Liquidez)\n" + "\n".join(lines)
        if len(text) > TELEGRAM_MAX:
            text = text[: TELEGRAM_MAX - 50] + "\n..."

        # cache
        _cache_topspot_text = text
        _cache_topspot_ts = time.time()

        await status_msg.edit_text(text)

    except requests.Timeout:
        logging.exception("Timeout no /topspot")
        await status_msg.edit_text("⚠️ Bybit demorou demais (timeout). Tente novamente.")
    except Exception:
        logging.exception("Erro no /topspot")
        await status_msg.edit_text("⚠️ Erro ao montar o Top Premium Spot (veja Logs no Railway).")


def main():
    if not TOKEN:
        raise RuntimeError("TG_BOT_TOKEN não definido")

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price_cmd))
    app.add_handler(CommandHandler("topspot", topspot_cmd))

    logging.info("✅ Bot iniciado (Bybit Spot)")
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
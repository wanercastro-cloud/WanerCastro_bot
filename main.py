import os
import math
import logging
import requests

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
BYBIT_TICKERS_URL = "https://api.bybit.com/v5/market/tickers"


def safe_float(x, default=0.0) -> float:
    try:
        if x is None or x == "":
            return default
        return float(x)
    except Exception:
        return default


def bybit_spot_tickers() -> list[dict]:
    r = requests.get(
        BYBIT_TICKERS_URL,
        params={"category": "spot"},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()

    if data.get("retCode") != 0:
        return []

    result = data.get("result", {})
    return result.get("list", []) if isinstance(result.get("list"), list) else []


def bybit_spot_ticker(symbol: str) -> dict | None:
    r = requests.get(
        BYBIT_TICKERS_URL,
        params={"category": "spot", "symbol": symbol},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()

    if data.get("retCode") != 0:
        return None

    lst = data.get("result", {}).get("list", [])
    return lst[0] if lst else None


def premium_score(t: dict) -> float:
    """
    TOP PREMIUM SPOT (Bybit):
    - maior turnover24h
    - preço válido
    """
    symbol = t.get("symbol", "")
    if not symbol.endswith("USDT"):
        return -1e18

    last = safe_float(t.get("lastPrice"))
    turnover = safe_float(t.get("turnover24h"))

    if last <= 0 or turnover <= 0:
        return -1e18

    # Score simples, estável e correto para Spot
    return math.log10(turnover)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Bot Bybit Spot online!\n\n"
        "Comandos:\n"
        "/price BTCUSDT\n"
        "/topspot"
    )


async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /price BTCUSDT")
        return

    symbol = context.args[0].upper().replace("/", "").strip()

    try:
        t = bybit_spot_ticker(symbol)
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
    try:
        tickers = bybit_spot_tickers()
        if not tickers:
            await update.message.reply_text("⚠️ Bybit não retornou dados agora.")
            return

        scored = []
        for t in tickers:
            score = premium_score(t)
            if score > 0:
                scored.append((score, t))

        if not scored:
            await update.message.reply_text("⚠️ Nenhum par Spot premium agora.")
            return

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:15]

        lines = []
        for i, (_, t) in enumerate(top, start=1):
            sym = t.get("symbol")
            last = safe_float(t.get("lastPrice"))
            chg = safe_float(t.get("price24hPcnt")) * 100.0
            turnover = safe_float(t.get("turnover24h"))

            lines.append(
                f"{i:02d}. {sym} | {last:.8g} | 24h {chg:+.2f}% | vol {turnover:,.0f}"
            )

        await update.message.reply_text(
            "🏆 Top Premium Spot (Bybit – Liquidez)\n" + "\n".join(lines)
        )

    except Exception:
        logging.exception("Erro no /topspot")
        await update.message.reply_text("⚠️ Erro ao montar o Top Premium Spot.")


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
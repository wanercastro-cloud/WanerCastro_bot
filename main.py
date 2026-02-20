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
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()

    if not isinstance(data, dict):
        return []

    if data.get("retCode") != 0:
        logging.error("Bybit retCode != 0: %s", data)
        return []

    result = data.get("result")
    if not result or not isinstance(result, dict):
        return []

    lst = result.get("list")
    if not lst or not isinstance(lst, list):
        return []

    return lst


def bybit_spot_ticker(symbol: str) -> dict | None:
    r = requests.get(
        BYBIT_TICKERS_URL,
        params={"category": "spot", "symbol": symbol},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("retCode") != 0:
        return None
    lst = data.get("result", {}).get("list", [])
    return lst[0] if lst else None


def premium_score(t: dict) -> float:
    symbol = t.get("symbol", "")
    if not symbol.endswith("USDT"):
        return -1e18

    last = safe_float(t.get("lastPrice"))
    bid = safe_float(t.get("bid1Price"))
    ask = safe_float(t.get("ask1Price"))
    turnover = safe_float(t.get("turnover24h"))

    # descarta ticker incompleto
    if last <= 0 or bid <= 0 or ask <= 0:
        return -1e18
    if ask <= bid:
        return -1e18
    if turnover <= 0:
        return -1e18

    spread_pct = (ask - bid) / last
    return math.log10(turnover) / (spread_pct + 1e-6)


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
        bid = safe_float(t.get("bid1Price"))
        ask = safe_float(t.get("ask1Price"))
        chg = safe_float(t.get("price24hPcnt")) * 100.0
        spread_pct = ((ask - bid) / last) * 100.0 if last > 0 and bid > 0 and ask > 0 else 0.0

        await update.message.reply_text(
            f"📌 {symbol} (Bybit Spot)\n"
            f"💰 Last: {last}\n"
            f"🟩 Bid:  {bid}\n"
            f"🟥 Ask:  {ask}\n"
            f"↔️ Spread: {spread_pct:.4f}%\n"
            f"📈 24h:  {chg:+.2f}%"
        )

    except Exception:
        logging.exception("Erro no /price")
        await update.message.reply_text("⚠️ Erro ao consultar a Bybit (Spot).")


async def topspot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        tickers = bybit_spot_tickers()

        if not tickers:
            await update.message.reply_text("⚠️ Bybit não retornou dados agora. Tente novamente.")
            return

        scored = []
        for t in tickers:
            try:
                score = premium_score(t)
                if score > 0:
                    scored.append((score, t))
            except Exception:
                continue

        if not scored:
            await update.message.reply_text("⚠️ Nenhum par Spot premium disponível agora.")
            return

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:15]

        lines = []
        for i, (_, t) in enumerate(top, start=1):
            sym = t.get("symbol", "?")
            last = safe_float(t.get("lastPrice"))
            bid = safe_float(t.get("bid1Price"))
            ask = safe_float(t.get("ask1Price"))
            turnover = safe_float(t.get("turnover24h"))
            spread_pct = ((ask - bid) / last) * 100 if last > 0 else 0.0

            lines.append(
                f"{i:02d}. {sym} | {last:.8g} | spr {spread_pct:.3f}% | vol {turnover:,.0f}"
            )

        await update.message.reply_text("🏆 Top Premium Spot (Bybit)\n" + "\n".join(lines))

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
import os
import math
import logging
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()

BYBIT_TICKERS = "https://api.bybit.com/v5/market/tickers"

def bybit_spot_tickers() -> list[dict]:
    r = requests.get(BYBIT_TICKERS, params={"category": "spot"}, timeout=15)
    r.raise_for_status()
    data = r.json()
    if data.get("retCode") != 0:
        raise RuntimeError(f"Bybit retCode != 0: {data}")
    return data["result"]["list"]

def safe_float(x, default=0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default

def premium_score(t: dict) -> float:
    """
    Score "top premium" = muito volume + spread pequeno.
    Opcionalmente penaliza volatilidade extrema.
    """
    turnover = safe_float(t.get("turnover24h"))   # volume em moeda de cotação (ex: USDT)
    bid = safe_float(t.get("bid1Price"))
    ask = safe_float(t.get("ask1Price"))
    last = safe_float(t.get("lastPrice"))
    chg = safe_float(t.get("price24hPcnt"))       # ex: 0.0123 = +1.23%

    if last <= 0 or bid <= 0 or ask <= 0:
        return -1e18

    spread = (ask - bid) / last                   # percentual
    vol_component = math.log10(turnover + 1.0)    # cresce devagar
    spread_penalty = spread * 800.0               # quanto menor, melhor
    vol_penalty = abs(chg) * 3.0                  # penaliza “doideira” (opcional)

    return (vol_component * 10.0) - spread_penalty - vol_penalty

def format_symbol(t: dict) -> str:
    return t.get("symbol", "?")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Bot Bybit online!\n\n"
        "Comandos:\n"
        "/price BTCUSDT  (spot)\n"
        "/topspot        (Top Premium Spot)\n"
        "/alpha          (status Alpha)\n"
    )

async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /price BTCUSDT")
        return

    symbol = context.args[0].upper().replace("/", "").strip()

    try:
        r = requests.get(BYBIT_TICKERS, params={"category": "spot", "symbol": symbol}, timeout=10)
        r.raise_for_status()
        data = r.json()

        if data.get("retCode") != 0 or not data["result"]["list"]:
            await update.message.reply_text("❌ Par não encontrado na Spot da Bybit.")
            return

        t = data["result"]["list"][0]
        last = t.get("lastPrice")
        bid = t.get("bid1Price")
        ask = t.get("ask1Price")
        chg = safe_float(t.get("price24hPcnt")) * 100.0

        await update.message.reply_text(
            f"📌 {symbol} (Spot Bybit)\n"
            f"💰 Last: {last}\n"
            f"🟩 Bid:  {bid}\n"
            f"🟥 Ask:  {ask}\n"
            f"📈 24h:  {chg:+.2f}%"
        )

    except Exception as e:
        logging.exception(e)
        await update.message.reply_text("⚠️ Erro ao consultar a Bybit (Spot).")

async def topspot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        tickers = bybit_spot_tickers()

        # Filtra só pares USDT (ajuste se quiser incluir USDC, BRL etc.)
        usdt = [t for t in tickers if format_symbol(t).endswith("USDT")]

        # Ordena por score premium
        usdt.sort(key=premium_score, reverse=True)

        top = usdt[:15]
        lines = []
        for i, t in enumerate(top, start=1):
            sym = format_symbol(t)
            last = safe_float(t.get("lastPrice"))
            bid = safe_float(t.get("bid1Price"))
            ask = safe_float(t.get("ask1Price"))
            turnover = safe_float(t.get("turnover24h"))
            chg = safe_float(t.get("price24hPcnt")) * 100.0
            spread_pct = ((ask - bid) / last) * 100.0 if last > 0 and bid > 0 and ask > 0 else 0.0

            lines.append(
                f"{i:02d}. {sym} | {last:.8g} | spr {spread_pct:.3f}% | 24h {chg:+.2f}% | vol {turnover:,.0f}"
            )

        await update.message.reply_text("🏆 Top Premium Spot (Bybit)\n" + "\n".join(lines))

    except Exception as e:
        logging.exception(e)
        await update.message.reply_text("⚠️ Erro ao montar o Top Premium Spot.")

async def alpha_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🧩 Bybit Alpha:\n"
        "A Bybit não expõe (publicamente) um endpoint oficial simples para listar todos os tokens Alpha como no Spot.\n"
        "Dá pra fazer de 2 jeitos:\n"
        "1) ✅ Lista manual (estável): você me diz quais tokens Alpha quer acompanhar.\n"
        "2) ⚠️ Scraping da página Alpha (frágil): pode quebrar quando a Bybit mudar o site.\n\n"
        "Se você me disser qual opção prefere, eu já implemento."
    )

def main():
    if not TOKEN:
        raise RuntimeError("TG_BOT_TOKEN não definido")

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price_cmd))
    app.add_handler(CommandHandler("topspot", topspot_cmd))
    app.add_handler(CommandHandler("alpha", alpha_cmd))

    logging.info("✅ Bot Bybit (Spot) iniciado")
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
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

# Cache simples por instância
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
    r = requests.get(
        BYBIT_TICKERS_URL,
        params={"category": "spot"},
        timeout=8,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    r.raise_for_status()
    data = r.json()

    if not isinstance(data, dict):
        logging.error("Bybit retornou JSON não-dict: %s", type(data))
        return []

    if data.get("retCode") != 0:
        logging.error("Bybit retCode != 0: %s", data)
        return []

    result = data.get("result")
    if not isinstance(result, dict):
        logging.error("Bybit result inválido: %s", result)
        return []

    lst = result.get("list")
    if not isinstance(lst, list):
        logging.error("Bybit list inválida: %s", lst)
        return []

    return lst


async def fetch_spot_tickers() -> list[dict]:
    # Roda requests em thread para não travar o loop async
    return await asyncio.to_thread(_fetch_spot_tickers_sync)


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


def premium_score(t: dict) -> float:
    """
    'À prova de API quebrada' = nunca levanta exceção e nunca retorna NaN/Inf.
    Critério: liquidez (turnover24h) em USDT, para pares *USDT.
    """
    try:
        symbol = t.get("symbol", "")
        if not isinstance(symbol, str) or not symbol.endswith("USDT"):
            return -1e18

        turnover_raw = t.get("turnover24h", None)
        if turnover_raw is None or turnover_raw == "":
            return -1e18

        turnover = float(turnover_raw)
        if turnover <= 0:
            return -1e18

        score = math.log10(turnover)

        # proteção final contra NaN/Inf
        if not math.isfinite(score):
            return -1e18

        return score

    except Exception:
        return -1e18


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

    except Exception as e:
        logging.exception("Erro no /price")
        await update.message.reply_text(f"⚠️ Erro ao consultar a Bybit. ({type(e).__name__})")


async def topspot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _cache_topspot_text, _cache_topspot_ts

    # Cache: se tiver resultado recente, responde instantâneo
    now = time.time()
    if _cache_topspot_text and (now - _cache_topspot_ts) < CACHE_TTL:
        await update.message.reply_text(_cache_topspot_text)
        return

    # Feedback imediato
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

        if not scored:
            await status_msg.edit_text("⚠️ Nenhum par Spot premium agora.")
            return

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:10]  # limita para não estourar mensagem

        lines = []
        for i, (_, t) in enumerate(top, start=1):
            sym = t.get("symbol", "?")
            last = safe_float(t.get("lastPrice"))
            chg = safe_float(t.get("price24hPcnt")) * 100.0
            turnover = safe_float(t.get("turnover24h"))

            lines.append(
                f"{i:02d}. {sym} | {last:.8g} | 24h {chg:+.2f}% | vol {turnover:,.0f}"
            )

        text = "🏆 Top Premium Spot (Bybit – Liquidez)\n" + "\n".join(lines)

        # blindagem final do tamanho
        if len(text) > TELEGRAM_MAX:
            text = text[: TELEGRAM_MAX - 50] + "\n..."

        # atualiza cache
        _cache_topspot_text = text
        _cache_topspot_ts = time.time()

        await status_msg.edit_text(text)

    except requests.Timeout as e:
        logging.exception("Timeout no /topspot")
        await status_msg.edit_text("⚠️ Bybit demorou demais (timeout). Tente novamente.")
    except Exception as e:
        logging.exception("Erro no /topspot")
        await status_msg.edit_text(
            "⚠️ Erro ao montar o Top Premium Spot.\n"
            f"Erro: {type(e).__name__}"
        )


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
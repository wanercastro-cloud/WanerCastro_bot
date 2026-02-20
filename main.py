> main.py
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

# Cache simples
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


def _bybit_get_spot_tickers_sync() -> tuple[int | None, dict | None]:
    """
    Retorna (status_code, json_dict) sem levantar HTTPError.
    """
    try:
        r = requests.get(
            BYBIT_TICKERS_URL,
            params={"category": "spot"},
            timeout=10,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
            },
        )
        status = r.status_code

        # tenta parsear JSON mesmo em erro (às vezes vem body explicando)
        try:
            data = r.json()
        except Exception:
            data = None

        return status, data

    except requests.RequestException as e:
        logging.exception("Falha de rede ao chamar Bybit: %s", e)
        return None, None


def _extract_list(data: dict | None) -> list[dict]:
    if not isinstance(data, dict):
        return []

    # Bybit padrão: retCode 0 = ok
    if data.get("retCode") != 0:
        logging.error("Bybit retCode != 0: %s", data)
        return []

    result = data.get("result")
    if not isinstance(result, dict):
        return []

    lst = result.get("list")
    return lst if isinstance(lst, list) else []


async def fetch_spot_tickers() -> tuple[int | None, list[dict]]:
    status, data = await asyncio.to_thread(_bybit_get_spot_tickers_sync)
    return status, _extract_list(data)


def premium_score(t: dict) -> float:
    # blindado contra dados ruins
    try:
        symbol = t.get("symbol", "")
        if not isinstance(symbol, str) or not symbol.endswith("USDT"):
            return -1e18

        turnover_raw = t.get("turnover24h")
        if turnover_raw is None or turnover_raw == "":
            return -1e18

        turnover = float(turnover_raw)
        if turnover <= 0:
            return -1e18

        score = math.log10(turnover)
        if not math.isfinite(score):
            return -1e18

        return score
    except Exception:
        return -1e18


def _fetch_one_ticker_sync(symbol: str) -> tuple[int | None, dict | None]:
    try:
        r = requests.get(
            BYBIT_TICKERS_URL,
            params={"category": "spot", "symbol": symbol},
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        )
        status = r.status_code
        try:
            data = r.json()
        except Exception:
            data = None
        return status, data
    except requests.RequestException as e:
        logging.exception("Falha de rede /price: %s", e)
        return None, None


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

    status, data = await asyncio.to_thread(_fetch_one_ticker_sync, symbol)
    if status is None:
        await update.message.reply_text("⚠️ Sem conexão com a Bybit agora.")
        return

    if status != 200:
        await update.message.reply_text(f"⚠️ Bybit respondeu HTTP {status} no /price.")
        return

    if not isinstance(data, dict) or data.get("retCode") != 0:
        await update.message.reply_text("⚠️ Resposta inválida da Bybit no /price.")
        return

    lst = data.get("result", {}).get("list", [])
    if not lst:
        await update.message.reply_text("❌ Par não encontrado na Spot da Bybit.")
        return

    t = lst[0]
    last = safe_float(t.get("lastPrice"))
    chg = safe_float(t.get("price24hPcnt")) * 100.0
    turnover = safe_float(t.get("turnover24h"))

    await update.message.reply_text(
        f"📌 {symbol} (Bybit Spot)\n"
        f"💰 Preço: {last}\n"
        f"📈 24h: {chg:+.2f}%\n"
        f"🔄 Volume 24h: {turnover:,.0f}"
    )


async def topspot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _cache_topspot_text, _cache_topspot_ts

    # cache rápido
    now = time.time()
    if _cache_topspot_text and (now - _cache_topspot_ts) < CACHE_TTL:
        await update.message.reply_text(_cache_topspot_text)
        return

    status_msg = await update.message.reply_text("⏳ Montando Top Premium Spot...")

    # retry leve (1 vez) só para instabilidade momentânea
    for attempt in (1, 2):
        status, tickers = await fetch_spot_tickers()

        # sem conexão
        if status is None:
            await status_msg.edit_text("⚠️ Sem conexão com a Bybit agora. Tente novamente.")
            return

        # rate limit
        if status == 429:
            await status_msg.edit_text("⛔ Bybit limitou (HTTP 429). Aguarde 30–60s e tente de novo.")
            return

        # bloqueio/região/proxy/anti-bot
        if status == 403:
            await status_msg.edit_text("⛔ Bybit recusou (HTTP 403). Verifique rede/região/VPN.")
            return

        # instabilidade temporária
        if status >= 500:
            if attempt == 1:
                await asyncio.sleep(1.2)
                continue
            await status_msg.edit_text(f"⚠️ Bybit instável (HTTP {status}). Tente novamente em 1 min.")
            return

        # outros erros HTTP
        if status != 200:
            await status_msg.edit_text(f"⚠️ Bybit respondeu HTTP {status}. Tente novamente.")
            return

        # OK: monta ranking
        if not tickers:
            await status_msg.edit_text("⚠️ Bybit não retornou lista agora.")
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
        top = scored[:10]

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

        _cache_topspot_text = text
        _cache_topspot_ts = time.time()

        await status_msg.edit_text(text)
        return

    # nunca deve chegar aqui
    await status_msg.edit_text("⚠️ Falha inesperada no /topspot.")


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
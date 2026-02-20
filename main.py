import os
import time
import math
import logging
import asyncio
import requests
from dataclasses import dataclass

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

load_dotenv()
logging.basicConfig(level=logging.INFO)

TG_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
TELEGRAM_MAX = 4096

# ====== CONFIG ALERTA "ANTES DO PUMP" ======
# Timeframe para vigiar: "1"=1min, "5"=5min, "15"=15min (Bybit usa strings)
DEFAULT_INTERVAL = "5"

LOOKBACK_RANGE = 20            # candles para definir "range"
VOL_SPIKE_MULT = 2.0           # volume atual precisa ser >= 2x média
COOLDOWN_SEC = 15 * 60         # não repetir alerta do mesmo par por 15 min
CHECK_EVERY_SEC = 60           # checagem a cada 60s

# Bybit endpoints
BYBIT_KLINE_URL = "https://api.bybit.com/v5/market/kline"

@dataclass
class WatchItem:
    symbol: str
    interval: str
    chat_id: int
    last_alert_ts: float = 0.0


WATCHLIST: dict[str, WatchItem] = {}  # chave = f"{chat_id}:{symbol}:{interval}"


def safe_float(x, default=0.0) -> float:
    try:
        if x is None or x == "":
            return default
        return float(x)
    except Exception:
        return default


async def http_get_json(url: str, params: dict, timeout: int = 12):
    def _req():
        r = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        return r.status_code, r.json()
    return await asyncio.to_thread(_req)


async def bybit_kline_spot(symbol: str, interval: str, limit: int = 200) -> tuple[int | None, list[list[str]]]:
    """
    Retorna lista de candles no formato Bybit:
    [startTime, open, high, low, close, volume, turnover]
    """
    params = {"category": "spot", "symbol": symbol, "interval": interval, "limit": str(limit)}
    status, data = await http_get_json(BYBIT_KLINE_URL, params=params, timeout=12)
    if status != 200 or not isinstance(data, dict) or data.get("retCode") != 0:
        return status, []
    lst = data.get("result", {}).get("list", [])
    return status, (lst if isinstance(lst, list) else [])


def detect_prepump(candles: list[list[str]]) -> tuple[bool, str]:
    """
    Lógica:
    - usa os últimos LOOKBACK_RANGE candles fechados para range (max high)
    - volume spike no candle mais recente (o último da lista)
    - rompimento: close atual > max_high do range anterior
    """
    if len(candles) < LOOKBACK_RANGE + 5:
        return False, "poucos candles"

    # Bybit normalmente retorna mais recente primeiro. Vamos garantir ordem cronológica.
    candles_sorted = sorted(candles, key=lambda x: int(x[0]))

    # candle atual (mais recente)
    cur = candles_sorted[-1]
    cur_open = safe_float(cur[1])
    cur_high = safe_float(cur[2])
    cur_low = safe_float(cur[3])
    cur_close = safe_float(cur[4])
    cur_vol = safe_float(cur[5])

    # range anterior (exclui o candle atual)
    past = candles_sorted[-(LOOKBACK_RANGE + 1):-1]
    max_high = max(safe_float(c[2]) for c in past)
    min_low = min(safe_float(c[3]) for c in past)

    # compressão simples: range pequeno vs preço (evita sinais em candle gigante pós-pump)
    rng = max_high - min_low
    compression_ok = (cur_close > 0) and (rng / cur_close) < 0.06  # 6% de range (ajuste)

    # volume spike: vol atual >= mult * média dos LOOKBACK_RANGE candles anteriores
    avg_vol = sum(safe_float(c[5]) for c in past) / max(1, len(past))
    vol_spike_ok = avg_vol > 0 and cur_vol >= (VOL_SPIKE_MULT * avg_vol)

    # rompimento: close > max_high
    breakout_ok = cur_close > max_high

    if compression_ok and vol_spike_ok and breakout_ok:
        reason = (
            f"compressão OK (range~{(rng/cur_close)*100:.1f}%), "
            f"vol spike {cur_vol/avg_vol:.2f}x, "
            f"breakout acima de {max_high:.8g}"
        )
        return True, reason

    # Para debug
    return False, (
        f"compression={compression_ok}, volSpike={vol_spike_ok} ({(cur_vol/avg_vol if avg_vol else 0):.2f}x), "
        f"breakout={breakout_ok}"
    )


async def watcher_job(context: ContextTypes.DEFAULT_TYPE):
    # roda para todos os watchlist itens
    for key, w in list(WATCHLIST.items()):
        # cooldown
        now = time.time()
        if w.last_alert_ts and (now - w.last_alert_ts) < COOLDOWN_SEC:
            continue

        status, candles = await bybit_kline_spot(w.symbol, w.interval, limit=200)

        if status == 403:
            # Bybit bloqueou seu IP/região
            await context.bot.send_message(
                chat_id=w.chat_id,
                text=f"⛔ Bybit recusou (HTTP 403) para {w.symbol}. Troque IP/região do servidor ou use outra fonte.",
            )
            # evita spam
            w.last_alert_ts = now
            continue

        if not candles:
            continue

        ok, reason = detect_prepump(candles)
        if ok:
            w.last_alert_ts = now
            await context.bot.send_message(
                chat_id=w.chat_id,
                text=(
                    f"🐳🚀 **ALERTA PRÉ-PUMP** ({w.symbol} | {w.interval}m)\n"
                    f"✅ Sinal: entrada forte + rompimento\n"
                    f"📌 Motivo: {reason}\n\n"
                    f"📍 Sugestão objetiva:\n"
                    f"- Entrada: no reteste do rompimento ou no próximo candle forte\n"
                    f"- Stop: abaixo do range (mínima recente)\n"
                    f"- Se não confirmar em 1–3 candles, sai sem dó"
                ),
                parse_mode="Markdown",
            )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Bot de Alertas ONLINE\n\n"
        "Comandos:\n"
        "/watch AZTECUSDT 5    (vigia pré-pump no 5m)\n"
        "/unwatch AZTECUSDT 5\n"
        "/watchlist\n\n"
        "Regra do alerta: compressão + volume spike + rompimento do range."
    )


async def watch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /watch AZTECUSDT 5")
        return
    symbol = context.args[0].upper().replace("/", "").strip()
    interval = context.args[1].strip() if len(context.args) > 1 else DEFAULT_INTERVAL

    if not symbol.endswith("USDT"):
        await update.message.reply_text("Use par USDT (ex: AZTECUSDT).")
        return
    if interval not in {"1", "5", "15"}:
        await update.message.reply_text("Intervalo válido: 1, 5, 15")
        return

    key = f"{update.effective_chat.id}:{symbol}:{interval}"
    WATCHLIST[key] = WatchItem(symbol=symbol, interval=interval, chat_id=update.effective_chat.id)
    await update.message.reply_text(f"✅ Agora vigiando {symbol} no {interval}m (pré-pump).")


async def unwatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /unwatch AZTECUSDT 5")
        return
    symbol = context.args[0].upper().replace("/", "").strip()
    interval = context.args[1].strip() if len(context.args) > 1 else DEFAULT_INTERVAL
    key = f"{update.effective_chat.id}:{symbol}:{interval}"
    if key in WATCHLIST:
        del WATCHLIST[key]
        await update.message.reply_text(f"🗑️ Removido: {symbol} {interval}m.")
    else:
        await update.message.reply_text("Esse par não está na watchlist.")


async def watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    items = [w for w in WATCHLIST.values() if w.chat_id == cid]
    if not items:
        await update.message.reply_text("📭 Watchlist vazia. Use /watch AZTECUSDT 5")
        return
    lines = [f"• {w.symbol} ({w.interval}m)" for w in items]
    await update.message.reply_text("👀 Watchlist:\n" + "\n".join(lines))


def main():
    if not TG_TOKEN:
        raise RuntimeError("TG_BOT_TOKEN não definido no .env")

    app = ApplicationBuilder().token(TG_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("watch", watch))
    app.add_handler(CommandHandler("unwatch", unwatch))
    app.add_handler(CommandHandler("watchlist", watchlist))

    # Job de verificação contínua
    app.job_queue.run_repeating(watcher_job, interval=CHECK_EVERY_SEC, first=10)

    logging.info("✅ Bot iniciado com watcher")
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
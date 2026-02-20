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

# =========================
# CONFIG: ENTRAR "AINDA ANTES"
# =========================
DEFAULT_INTERVAL = "1"      # 1m pega mais cedo
LOOKBACK_RANGE = 30         # range dos últimos 30 candles (no 1m -> 30min)
VOL_SPIKE_MULT = 1.25       # volume atual >= 1.25x média do lookback
COOLDOWN_SEC = 7 * 60       # anti-spam por símbolo
CHECK_EVERY_SEC = 25        # checar a cada 25s (se rate-limit, use 45)

# =========================
# CONFIG: FILTRO DE RETESTE (melhor entrada)
# =========================
RETEST_WINDOW = 8          # janela em candles (1m -> 8 minutos)
RETEST_TOL = 0.0035        # 0.35%: quão perto precisa "tocar" o nível do topo
RETEST_CONFIRM = 0.0020    # 0.20%: precisa recuperar acima do nível após tocar

# Guarda estado do "pré-breakout" para cada watch (chat+symbol+interval)
_pending_retest = {}  # key -> {"ts": float, "level": float}

# =========================
# BYBIT
# =========================
BYBIT_KLINE_URL = "https://api.bybit.com/v5/market/kline"


@dataclass
class WatchItem:
    symbol: str
    interval: str
    chat_id: int
    last_alert_ts: float = 0.0


WATCHLIST: dict[str, WatchItem] = {}  # key = f"{chat_id}:{symbol}:{interval}"


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
        # Se vier HTML/erro, .json pode explodir
        try:
            data = r.json()
        except Exception:
            data = None
        return r.status_code, data

    return await asyncio.to_thread(_req)


async def bybit_kline_spot(symbol: str, interval: str, limit: int = 200) -> tuple[int | None, list[list[str]]]:
    """
    Retorna lista de candles (Bybit):
    [startTime, open, high, low, close, volume, turnover]
    """
    params = {"category": "spot", "symbol": symbol, "interval": interval, "limit": str(limit)}
    status, data = await http_get_json(BYBIT_KLINE_URL, params=params, timeout=12)

    if status != 200 or not isinstance(data, dict):
        return status, []
    if data.get("retCode") != 0:
        return status, []

    lst = data.get("result", {}).get("list", [])
    return status, (lst if isinstance(lst, list) else [])


def _calc_range_levels(candles_sorted: list[list[str]]) -> tuple[float, float, float]:
    """
    Retorna (max_high, min_low, avg_vol) do lookback (exclui candle atual).
    """
    past = candles_sorted[-(LOOKBACK_RANGE + 1):-1]
    max_high = max(safe_float(c[2]) for c in past)
    min_low = min(safe_float(c[3]) for c in past)
    avg_vol = sum(safe_float(c[5]) for c in past) / max(1, len(past))
    return max_high, min_low, avg_vol


def _detect_early(cur, max_high: float, min_low: float, avg_vol: float) -> tuple[bool, str]:
    """
    EARLY: compressão + volume spike + buy pressure + encosta no topo do range
    CONFIRMADO: se fechar acima do topo
    """
    cur_open = safe_float(cur[1])
    cur_high = safe_float(cur[2])
    cur_low = safe_float(cur[3])
    cur_close = safe_float(cur[4])
    cur_vol = safe_float(cur[5])

    if cur_close <= 0:
        return False, "close inválido"

    rng = max_high - min_low

    # compressão (mais permissivo)
    compression_ok = (rng / cur_close) < 0.09

    # volume spike (mais cedo)
    vol_mult = (cur_vol / avg_vol) if avg_vol > 0 else 0.0
    vol_spike_ok = avg_vol > 0 and vol_mult >= VOL_SPIKE_MULT

    # buy pressure simples: candle verde ou fechando perto da máxima
    candle_body = cur_close - cur_open
    close_near_high = (cur_high > 0) and ((cur_high - cur_close) / cur_high) < 0.0025
    buy_pressure_ok = candle_body > 0 or close_near_high

    # “quase rompendo”
    near_breakout_ok = cur_high >= (max_high * 0.998)

    # confirmação
    breakout_ok = cur_close > max_high

    if compression_ok and vol_spike_ok and buy_pressure_ok and near_breakout_ok:
        level = "🟡 EARLY" if not breakout_ok else "🟢 CONFIRMADO"
        reason = (
            f"{level} | range~{(rng/cur_close)*100:.1f}% | "
            f"vol {vol_mult:.2f}x | topo {max_high:.8g} | close {cur_close:.8g}"
        )
        return True, reason

    return False, (
        f"compression={compression_ok}, vol={vol_mult:.2f}x({vol_spike_ok}), "
        f"buyPressure={buy_pressure_ok}, nearBreakout={near_breakout_ok}, breakout={breakout_ok}"
    )


def _detect_retest(cur, level: float) -> tuple[bool, str]:
    """
    RETESTE:
    - tocou perto do nível (low <= level*(1+tol))
    - recuperou acima do nível (close >= level*(1+confirm))
    """
    cur_low = safe_float(cur[3])
    cur_close = safe_float(cur[4])

    touched = cur_low <= (level * (1 + RETEST_TOL))
    recovered = cur_close >= (level * (1 + RETEST_CONFIRM))

    if touched and recovered:
        return True, f"low {cur_low:.8g} → close {cur_close:.8g}"
    return False, f"touched={touched}, recovered={recovered}, level={level:.8g}"


async def watcher_job(context: ContextTypes.DEFAULT_TYPE):
    now = time.time()

    for key, w in list(WATCHLIST.items()):
        # anti-spam por símbolo
        if w.last_alert_ts and (now - w.last_alert_ts) < COOLDOWN_SEC:
            continue

        status, candles = await bybit_kline_spot(w.symbol, w.interval, limit=200)

        if status == 403:
            await context.bot.send_message(
                chat_id=w.chat_id,
                text=f"⛔ Bybit recusou (HTTP 403) para {w.symbol}. Verifique rede/região/VPN do servidor.",
            )
            w.last_alert_ts = now
            continue

        if not candles:
            continue

        # Bybit pode vir invertido, garantimos cronologia
        candles_sorted = sorted(candles, key=lambda x: int(x[0]))

        if len(candles_sorted) < LOOKBACK_RANGE + 5:
            continue

        cur = candles_sorted[-1]
        max_high, min_low, avg_vol = _calc_range_levels(candles_sorted)

        # 1) EARLY detect: arma reteste
        ok_early, reason = _detect_early(cur, max_high, min_low, avg_vol)
        if ok_early:
            # arma reteste no nível do topo do range
            _pending_retest[key] = {"ts": now, "level": float(max_high)}

            # manda alerta early
            w.last_alert_ts = now
            await context.bot.send_message(
                chat_id=w.chat_id,
                text=(
                    f"🐳🚀 PRÉ-PUMP {w.symbol} | {w.interval}m\n"
                    f"{reason}\n\n"
                    f"🎯 Vou buscar RETESTE do topo {max_high:.8g} nos próximos ~{RETEST_WINDOW} candles."
                ),
            )
            continue

        # 2) Se não deu early agora, pode estar em reteste (se tiver pendente)
        pend = _pending_retest.get(key)
        if not pend:
            continue

        # expira janela de reteste
        interval_min = int(w.interval)
        if now - pend["ts"] > (RETEST_WINDOW * interval_min * 60):
            _pending_retest.pop(key, None)
            continue

        level = float(pend["level"])
        ok_rt, rt_reason = _detect_retest(cur, level)
        if ok_rt:
            _pending_retest.pop(key, None)
            w.last_alert_ts = now
            await context.bot.send_message(
                chat_id=w.chat_id,
                text=(
                    f"✅🐳 RETESTE CONFIRMADO {w.symbol} | {w.interval}m\n"
                    f"📌 Nível: {level:.8g}\n"
                    f"📍 Candle: {rt_reason}\n\n"
                    f"🎯 Entrada (técnica): no reteste confirmado ou próximo candle forte\n"
                    f"🛑 Stop: abaixo do low do reteste (ou abaixo do range)\n"
                    f"⚠️ Se perder o nível e não recuperar em 1–2 candles, sai."
                ),
            )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Bot de Alertas PRÉ-PUMP + RETESTE ONLINE\n\n"
        "Comandos:\n"
        "/watch AZTECUSDT 1    (vigia pré-pump no 1m)\n"
        "/unwatch AZTECUSDT 1\n"
        "/watchlist\n\n"
        "Sinais:\n"
        "- PRÉ-PUMP: compressão + volume spike + encosta no topo\n"
        "- RETESTE: toca o topo e recupera (melhor entrada)"
    )


async def watch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /watch AZTECUSDT 1")
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
    await update.message.reply_text(f"✅ Agora vigiando {symbol} no {interval}m (pré-pump + reteste).")


async def unwatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /unwatch AZTECUSDT 1")
        return

    symbol = context.args[0].upper().replace("/", "").strip()
    interval = context.args[1].strip() if len(context.args) > 1 else DEFAULT_INTERVAL

    key = f"{update.effective_chat.id}:{symbol}:{interval}"
    WATCHLIST.pop(key, None)
    _pending_retest.pop(key, None)
    await update.message.reply_text(f"🗑️ Removido: {symbol} {interval}m (e reteste pendente).")


async def watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    items = [w for w in WATCHLIST.values() if w.chat_id == cid]
    if not items:
        await update.message.reply_text("📭 Watchlist vazia. Use /watch AZTECUSDT 1")
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

    # Job contínuo
    app.job_queue.run_repeating(watcher_job, interval=CHECK_EVERY_SEC, first=10)

    logging.info("✅ Bot iniciado com watcher (early + reteste)")
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
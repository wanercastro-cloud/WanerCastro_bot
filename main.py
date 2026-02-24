import os
import json
import time
import math
import requests
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
BYBIT_CATEGORY = os.getenv("BYBIT_CATEGORY", "spot").strip()
QUOTE = os.getenv("QUOTE", "USDT").strip()

SCAN_EVERY_SEC = int(os.getenv("SCAN_EVERY_SEC", "180"))
ALERT_SCORE = float(os.getenv("ALERT_SCORE", "80"))
ALERT_COOLDOWN_SEC = int(os.getenv("ALERT_COOLDOWN_SEC", "1800"))
TOP_N = int(os.getenv("TOP_N", "10"))

ALLOWED_SYMBOLS_ENV = os.getenv("ALLOWED_SYMBOLS", "").strip()
ALLOWED_SYMBOLS = set(s.strip().upper() for s in ALLOWED_SYMBOLS_ENV.split(",") if s.strip()) if ALLOWED_SYMBOLS_ENV else None

STATE_FILE = "state.json"
BYBIT_TICKERS_URL = "https://api.bybit.com/v5/market/tickers"

# -------------------- Helpers --------------------

def now_ts() -> int:
    return int(time.time())

def safe_float(x, default=0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def zscore_like(x: float) -> float:
    # compressão suave 0..100 usando tanh
    # valores típicos: x ~ 0..3 -> 0..~95
    return 50.0 * (math.tanh(x) + 1.0)

def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {
            "chat_id": None,
            "prev": {},          # symbol -> snapshot anterior
            "cooldown": {},      # symbol -> last_alert_ts
            "last_scan_ts": 0,
        }
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "chat_id": None,
            "prev": {},
            "cooldown": {},
            "last_scan_ts": 0,
        }

def save_state(state: dict) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

@dataclass
class Ticker:
    symbol: str
    last: float
    pct_24h: float
    turnover_24h: float      # USDT
    volume_24h: float        # base coin volume (se vier)
    high_24h: float
    low_24h: float

def fetch_bybit_spot_usdt_tickers() -> List[Ticker]:
    params = {"category": BYBIT_CATEGORY}
    r = requests.get(BYBIT_TICKERS_URL, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    items = data.get("result", {}).get("list", []) or []
    out: List[Ticker] = []

    for it in items:
        sym = (it.get("symbol") or "").upper()
        if not sym.endswith(QUOTE):
            continue
        if ALLOWED_SYMBOLS is not None and sym not in ALLOWED_SYMBOLS:
            continue

        last = safe_float(it.get("lastPrice"))
        pct_24h = safe_float(it.get("price24hPcnt")) * 100.0  # vem em decimal
        turnover = safe_float(it.get("turnover24h"))          # quote turnover
        vol = safe_float(it.get("volume24h"))                 # base volume
        high = safe_float(it.get("highPrice24h"))
        low = safe_float(it.get("lowPrice24h"))

        if last <= 0 or turnover <= 0:
            continue

        out.append(Ticker(
            symbol=sym,
            last=last,
            pct_24h=pct_24h,
            turnover_24h=turnover,
            volume_24h=vol,
            high_24h=high,
            low_24h=low
        ))
    return out

def compute_score(t: Ticker, prev: Optional[dict]) -> Tuple[float, dict]:
    """
    Score composto (0..100):
      - aceleração de turnover (proxy de fluxo/whales)
      - aceleração de preço (compressão + início de deslocamento)
      - volatilidade (range 24h)
      - penalidades (pump já foi / volatilidade absurda)
    """
    # --------- Features base ----------
    # Range 24h relativo
    rng = 0.0
    if t.low_24h > 0:
        rng = (t.high_24h - t.low_24h) / t.low_24h  # ex: 0.12 = 12%

    # Turnover accel (comparando com snapshot anterior)
    turnover_acc = 1.0
    price_acc = 0.0
    if prev:
        prev_turn = safe_float(prev.get("turnover_24h"), 0.0)
        prev_last = safe_float(prev.get("last"), 0.0)
        if prev_turn > 0:
            turnover_acc = t.turnover_24h / prev_turn
        if prev_last > 0:
            price_acc = (t.last / prev_last) - 1.0  # var desde último scan

    # Whale proxy: turnover alto + accel alto
    # (não é on-chain; é proxy de agressão/atividade)
    whale_proxy = math.log10(max(t.turnover_24h, 1.0)) * max(turnover_acc - 1.0, 0.0)

    # Compressão: preço quase parado no curto prazo mas turnover acelerando
    compression = max(0.0, (turnover_acc - 1.0) - abs(price_acc) * 5.0)

    # --------- Normalizações (0..100) ----------
    s_turn_acc = zscore_like(2.0 * (turnover_acc - 1.0))      # accel 1.2 -> ~69
    s_price_acc = zscore_like(40.0 * price_acc)               # +0.5% -> ~60
    s_vol = zscore_like(3.0 * rng)                            # range 10% -> ~65
    s_whale = zscore_like(0.8 * whale_proxy)
    s_comp = zscore_like(2.5 * compression)

    # --------- Penalidades ----------
    penalty = 0.0
    # se já subiu demais nas 24h, pode ser tardio
    if t.pct_24h > 25:
        penalty += 10
    if t.pct_24h > 60:
        penalty += 20
    # se volatilidade muito alta, risco (evita “loteria”)
    if rng > 0.6:
        penalty += 15

    # --------- Score final ----------
    # pesos (ajustáveis)
    score = (
        0.30 * s_turn_acc +
        0.20 * s_whale +
        0.20 * s_comp +
        0.15 * s_price_acc +
        0.15 * s_vol
    ) - penalty

    score = clamp(score, 0.0, 100.0)

    features = {
        "turnover_acc": turnover_acc,
        "price_acc": price_acc,
        "range_24h": rng,
        "s_turn_acc": s_turn_acc,
        "s_whale": s_whale,
        "s_comp": s_comp,
        "s_price_acc": s_price_acc,
        "s_vol": s_vol,
        "penalty": penalty
    }
    return score, features

def format_top_message(rows: List[dict], title: str) -> str:
    lines = [f"🔥 <b>{title}</b>"]
    for i, r in enumerate(rows, start=1):
        sym = r["symbol"]
        score = r["score"]
        last = r["last"]
        pct24 = r["pct_24h"]
        turn = r["turnover_24h"]
        ta = r["features"]["turnover_acc"]
        pa = r["features"]["price_acc"]

        lines.append(
            f"\n<b>{i}) {sym}</b> | <b>Score {score:.1f}</b>\n"
            f"Preço: {last:.8g} | 24h: {pct24:+.2f}%\n"
            f"Turnover24h: ${turn:,.0f}\n"
            f"AccelTurn: x{ta:.2f} | ΔPreço(scan): {pa*100:+.2f}%"
        )
    return "\n".join(lines)

# -------------------- Bot Commands --------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = load_state()
    chat_id = update.effective_chat.id
    state["chat_id"] = chat_id
    save_state(state)

    await update.message.reply_text(
        "✅ Registrado. Use /smartmoney para rodar agora.\n"
        "Eu também faço scan automático e aviso quando bater o limiar.",
    )

async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("pong ✅")

async def cmd_smartmoney(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔎 Rodando scanner Bybit SPOT...")
    rows, _alerts = run_scan_and_update_state(send_alerts=False)
    msg = format_top_message(rows[:TOP_N], "SMART MONEY PRÉ-PUMP (Bybit SPOT)")
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

# -------------------- Scanner Core --------------------

def run_scan_and_update_state(send_alerts: bool) -> Tuple[List[dict], List[dict]]:
    state = load_state()
    prev_map: Dict[str, dict] = state.get("prev", {}) or {}
    cooldown: Dict[str, int] = state.get("cooldown", {}) or {}

    tickers = fetch_bybit_spot_usdt_tickers()

    scored: List[dict] = []
    for t in tickers:
        prev = prev_map.get(t.symbol)
        score, features = compute_score(t, prev)
        scored.append({
            "symbol": t.symbol,
            "score": score,
            "last": t.last,
            "pct_24h": t.pct_24h,
            "turnover_24h": t.turnover_24h,
            "features": features
        })

    scored.sort(key=lambda x: x["score"], reverse=True)

    # Atualiza snapshots
    new_prev = {}
    for t in tickers:
        new_prev[t.symbol] = {
            "last": t.last,
            "turnover_24h": t.turnover_24h,
            "ts": now_ts(),
        }

    alerts: List[dict] = []
    if send_alerts:
        ts = now_ts()
        for r in scored[:TOP_N]:
            sym = r["symbol"]
            score = r["score"]
            last_alert = int(cooldown.get(sym, 0))

            if score >= ALERT_SCORE and (ts - last_alert) >= ALERT_COOLDOWN_SEC:
                alerts.append(r)
                cooldown[sym] = ts

    state["prev"] = new_prev
    state["cooldown"] = cooldown
    state["last_scan_ts"] = now_ts()
    save_state(state)

    return scored, alerts

async def job_scan(context: ContextTypes.DEFAULT_TYPE) -> None:
    state = load_state()
    chat_id = state.get("chat_id")

    # Se ninguém deu /start ainda, não tem pra quem avisar
    if not chat_id:
        run_scan_and_update_state(send_alerts=False)
        return

    _rows, alerts = run_scan_and_update_state(send_alerts=True)
    if not alerts:
        return

    # manda alertas (top 1..3)
    top_alerts = alerts[:3]
    msg = format_top_message(top_alerts, "ALERTA SMART MONEY (pré-pump)")
    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.HTML)

# -------------------- Main --------------------

def main() -> None:
    if not TG_BOT_TOKEN:
        raise RuntimeError("TG_BOT_TOKEN não definido")

    app = Application.builder().token(TG_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("smartmoney", cmd_smartmoney))

    # Job automático
    app.job_queue.run_repeating(job_scan, interval=SCAN_EVERY_SEC, first=10)

    # Um único polling (evita conflito)
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
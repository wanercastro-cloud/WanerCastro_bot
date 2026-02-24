# main.py
import os
import math
import time
import asyncio
import requests
from dataclasses import dataclass
from typing import List, Dict, Any, Tuple

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

BYBIT_BASE_URL = os.getenv("BYBIT_BASE_URL", "https://api.bybit.com")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")
MIN_TURNOVER_USDT = float(os.getenv("MIN_TURNOVER_USDT", "1500000"))  # 1.5M
TOP_N_PRESELECT = int(os.getenv("TOP_N_PRESELECT", "40"))             # pega top 40 por liquidez p/ calcular kline
TOP_K_RESULT = int(os.getenv("TOP_K_RESULT", "3"))

# Evita “stable roulette”
STABLE_BASE_BLACKLIST = {
    "USDT", "USDC", "DAI", "TUSD", "USDE", "FDUSD", "BUSD", "PYUSD",
    "USDQ", "USDD", "USDP", "USDS", "USTC", "EURC", "EURT", "XAUT"
}
# Alguns símbolos “meme stable”/derivados aparecem como base "U", etc.
WEIRD_BASE_BLACKLIST = {"U", "USD", "USDU", "USDQ"}

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "WanerCastro_bot/1.0"})

@dataclass
class Candidate:
    symbol: str
    last_price: float
    turnover24h: float
    price24hPcnt: float
    score: float
    accel_vol: float
    chg_1h: float

def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default

def bybit_get(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{BYBIT_BASE_URL}{path}"
    r = SESSION.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json()

def fetch_spot_tickers_usdt() -> List[Dict[str, Any]]:
    # GET /v5/market/tickers?category=spot  (Bybit V5)  [oai_citation:2‡bybit-exchange.github.io](https://bybit-exchange.github.io/docs/v5/market/tickers)
    data = bybit_get("/v5/market/tickers", {"category": "spot"})
    result = data.get("result", {})
    items = result.get("list", []) or []
    # Filtra só ...USDT (Spot)
    items = [it for it in items if str(it.get("symbol", "")).endswith("USDT")]
    return items

def fetch_kline_1h(symbol: str, limit: int = 60) -> List[List[Any]]:
    # GET /v5/market/kline?category=spot&symbol=...&interval=60 (Bybit V5)  [oai_citation:3‡bybit-exchange.github.io](https://bybit-exchange.github.io/docs/v5/market/tickers)
    data = bybit_get("/v5/market/kline", {
        "category": "spot",
        "symbol": symbol,
        "interval": "60",
        "limit": str(limit)
    })
    # result.list: array de velas. Cada vela normalmente: [startTime, open, high, low, close, volume, turnover]
    kl = (data.get("result", {}) or {}).get("list", []) or []
    return kl

def base_from_symbol(symbol: str) -> str:
    # BTCUSDT -> BTC
    if symbol.endswith("USDT"):
        return symbol[:-4]
    return symbol

def is_allowed_symbol(symbol: str) -> bool:
    base = base_from_symbol(symbol)
    if base in STABLE_BASE_BLACKLIST or base in WEIRD_BASE_BLACKLIST:
        return False
    # evita par com base muito curta esquisita tipo "U"
    if len(base) <= 1:
        return False
    return True

def score_candidate(turnover24h: float, accel_vol: float, chg_1h: float, chg_24h: float) -> float:
    """
    Score heurístico pré-pump:
    - Liquidez: log(turnover24h)
    - Aceleração: clamp(accel_vol)
    - 1h contido: melhor perto de 0~+1% (evita já ter pumpado)
    - 24h contido: penaliza extremos (muito esticado ou muito dumpado)
    """
    liq = math.log10(max(turnover24h, 1.0))  # ~ 0..10
    accel = max(0.0, min(accel_vol, 6.0))    # corta acima de 6x
    # “contido” = quanto mais perto de +0.6% melhor (janela suave)
    target_1h = 0.006
    contido_1h = max(0.0, 1.0 - (abs(chg_1h - target_1h) / 0.03))  # zera se muito longe (~3%)
    # 24h: favorece entre -3% e +8% (nem morto nem já explodido)
    if chg_24h < -0.03:
        contido_24h = max(0.0, 1.0 - (abs(chg_24h + 0.03) / 0.12))
    elif chg_24h > 0.08:
        contido_24h = max(0.0, 1.0 - ((chg_24h - 0.08) / 0.25))
    else:
        contido_24h = 1.0

    # Pesos
    score = (
        (liq * 12.0) +
        (accel * 10.0) +
        (contido_1h * 20.0) +
        (contido_24h * 12.0)
    )
    return round(score, 2)

def build_candidates() -> List[Candidate]:
    tickers = fetch_spot_tickers_usdt()

    pre = []
    for it in tickers:
        symbol = str(it.get("symbol", ""))
        if not symbol:
            continue
        if not is_allowed_symbol(symbol):
            continue

        turnover24h = _safe_float(it.get("turnover24h"))
        if turnover24h < MIN_TURNOVER_USDT:
            continue

        last_price = _safe_float(it.get("lastPrice"))
        chg_24h = _safe_float(it.get("price24hPcnt"))  # ex: "0.0123" = +1.23%  [oai_citation:4‡bybit-exchange.github.io](https://bybit-exchange.github.io/docs/v5/market/tickers)
        pre.append((symbol, last_price, turnover24h, chg_24h))

    # pré-seleção por liquidez (turnover)
    pre.sort(key=lambda x: x[2], reverse=True)
    pre = pre[:TOP_N_PRESELECT]

    out: List[Candidate] = []
    for symbol, last_price, turnover24h, chg_24h in pre:
        try:
            kl = fetch_kline_1h(symbol, limit=12)  # últimas 12h
            if len(kl) < 8:
                continue

            # bybit pode retornar em ordem decrescente; vamos ordenar pelo startTime
            kl_sorted = sorted(kl, key=lambda x: int(x[0]))

            # vela mais recente e anterior
            last = kl_sorted[-1]
            prev = kl_sorted[-2]

            close_last = _safe_float(last[4])
            close_prev = _safe_float(prev[4])
            chg_1h = 0.0 if close_prev == 0 else (close_last / close_prev - 1.0)

            # aceleração: vol da última 1h / média das 6 anteriores
            vol_last = _safe_float(last[5])
            vols_prev6 = [_safe_float(v[5]) for v in kl_sorted[-8:-2]]  # 6 velas antes da anterior
            avg_prev6 = sum(vols_prev6) / max(len(vols_prev6), 1)
            accel_vol = (vol_last / avg_prev6) if avg_prev6 > 0 else 0.0

            sc = score_candidate(turnover24h, accel_vol, chg_1h, chg_24h)

            out.append(Candidate(
                symbol=symbol,
                last_price=last_price,
                turnover24h=turnover24h,
                price24hPcnt=chg_24h,
                score=sc,
                accel_vol=accel_vol,
                chg_1h=chg_1h
            ))
        except Exception:
            continue

    # maior score primeiro
    out.sort(key=lambda c: c.score, reverse=True)
    return out

def format_report(cands: List[Candidate], topk: int) -> str:
    top = cands[:topk]
    if not top:
        return "⚠️ SMART MONEY PRÉ-PUMP\nNenhuma moeda passou nos filtros (liquidez/USDT/stable)."

    lines = [f"🔥 SMART MONEY PRÉ-PUMP (TOP {len(top)}) | Bybit SPOT USDT"]
    for i, c in enumerate(top, 1):
        lines.append(f"{i}) {c.symbol} | Score {c.score}")
        lines.append(f"   Turnover24h ≈ ${c.turnover24h:,.0f}")
        lines.append(f"   1h {c.chg_1h*100:+.2f}% | 24h {c.price24hPcnt*100:+.2f}%")
        lines.append(f"   VolAccel(1h/6h) x{c.accel_vol:.2f}")
    return "\n".join(lines)

# -------- Telegram Handlers --------

async def cmd_smartmoney(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔎 Rodando scanner Bybit SPOT...")

    loop = asyncio.get_event_loop()
    cands = await loop.run_in_executor(None, build_candidates)

    msg = format_report(cands, TOP_K_RESULT)
    await update.message.reply_text(msg)

async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("pong ✅")

def main():
    if not TG_BOT_TOKEN:
        raise RuntimeError("Defina a variável TG_BOT_TOKEN no Railway.")

    app = Application.builder().token(TG_BOT_TOKEN).build()
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("smartmoney", cmd_smartmoney))

    # Railway: roda “forever” com polling
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
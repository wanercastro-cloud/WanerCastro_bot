import os
import re
import json
import math
import asyncio
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()

# =========================
# ENV / CONFIG
# =========================
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
ALERT_CHAT_ID = os.getenv("ALERT_CHAT_ID", "").strip()
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "").strip()

TOP_N = int(os.getenv("TOP_N", "5"))
PAGES = int(os.getenv("PAGES", "4"))  # pages of /coins/markets (per_page=250) => up to 1000
TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "20"))

MIN_MCAP = float(os.getenv("MIN_MCAP", "5000000"))
MAX_MCAP = float(os.getenv("MAX_MCAP", "300000000"))
MIN_VOL_RATIO = float(os.getenv("MIN_VOL_RATIO", "0.30"))

MAX_24H_PUMP = float(os.getenv("MAX_24H_PUMP", "15"))  # percent
MAX_ABS_1H = float(os.getenv("MAX_ABS_1H", "3.0"))     # percent

# score weights (auto-tuned by /result)
WEIGHTS_PATH = os.getenv("WEIGHTS_PATH", "weights.json")

if not TG_BOT_TOKEN:
    raise RuntimeError("❌ Falta TG_BOT_TOKEN nas variáveis do Railway.")
if not COINGECKO_API_KEY:
    raise RuntimeError("❌ Falta COINGECKO_API_KEY (CoinGecko Premium) nas variáveis do Railway.")
if not ALERT_CHAT_ID:
    # still works for reply in chat, but scheduled alerts need this
    ALERT_CHAT_ID = ""

# =========================
# FILTERS
# =========================
STABLE_HINTS = {
    "usd", "usdt", "usdc", "dai", "tusd", "usde", "usdq",
    "eur", "gbp", "jpy", "try", "brl", "mxn", "aud", "cad",
}
SYMBOL_RE = re.compile(r"^[a-z0-9]+$", re.I)

# Some common stable/peg tickers or names
BLACKLIST_TICKERS = {
    "USDT", "USDC", "DAI", "TUSD", "USDE", "FDUSD", "USDP", "USDD",
    "EUR", "GBP", "JPY", "TRY",
}

BLACKLIST_NAME_HINTS = {
    "usd", "stable", "tether", "usd coin", "dai", "trueusd", "first digital",
    "euro", "yen", "pound", "peg"
}

# =========================
# DATA MODELS
# =========================
@dataclass
class Candidate:
    id: str
    symbol: str
    name: str
    mcap: float
    vol24: float
    vol_ratio: float
    chg_1h: float
    chg_24h: float
    score: float
    reasons: List[str]

# =========================
# UTIL
# =========================
def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default

def now_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

def load_weights() -> Dict[str, float]:
    default = {
        "liquidity": 1.00,
        "momentum_control": 1.00,
        "accumulation": 1.00,
        "risk": 1.00,
    }
    try:
        if os.path.exists(WEIGHTS_PATH):
            with open(WEIGHTS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k in default:
                if k in data:
                    default[k] = float(data[k])
    except Exception:
        pass
    return default

def save_weights(w: Dict[str, float]) -> None:
    try:
        with open(WEIGHTS_PATH, "w", encoding="utf-8") as f:
            json.dump(w, f, ensure_ascii=False, indent=2)
    except Exception:
        # railway filesystem might be read-only in some setups, so fail gracefully
        pass

def is_probably_stable(symbol: str, name: str) -> bool:
    sym = symbol.upper().strip()
    nm = (name or "").lower().strip()
    if sym in BLACKLIST_TICKERS:
        return True
    for h in BLACKLIST_NAME_HINTS:
        if h in nm:
            return True
    # heuristic: symbols like "USDx", "USDTsomething" etc
    if "USD" in sym and len(sym) <= 6:
        return True
    return False

# =========================
# COINGECKO CLIENT
# =========================
CG_BASE = "https://pro-api.coingecko.com/api/v3"

async def cg_get(client: httpx.AsyncClient, path: str, params: Dict[str, Any]) -> Any:
    headers = {"x-cg-pro-api-key": COINGECKO_API_KEY}
    url = f"{CG_BASE}{path}"
    r = await client.get(url, params=params, headers=headers, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

async def fetch_markets() -> List[Dict[str, Any]]:
    """
    Pull multiple pages from /coins/markets for USD with 1h & 24h price change + sparkline.
    """
    out: List[Dict[str, Any]] = []
    async with httpx.AsyncClient() as client:
        for page in range(1, PAGES + 1):
            data = await cg_get(
                client,
                "/coins/markets",
                params={
                    "vs_currency": "usd",
                    "order": "volume_desc",
                    "per_page": 250,
                    "page": page,
                    "sparkline": "true",
                    "price_change_percentage": "1h,24h,7d",
                },
            )
            if not isinstance(data, list) or not data:
                break
            out.extend(data)
    return out

# =========================
# FEATURE ENGINEERING / SCORE
# =========================
def compute_spark_volatility(spark: Optional[Dict[str, Any]]) -> Tuple[float, float]:
    """
    Returns (volatility, slope) from sparkline_7d prices (if available).
    volatility ~ stddev of returns, slope ~ trend over last segment.
    """
    if not spark or "price" not in spark:
        return 0.0, 0.0
    prices = spark.get("price") or []
    if len(prices) < 30:
        return 0.0, 0.0

    # returns
    rets = []
    for i in range(1, len(prices)):
        p0 = prices[i - 1]
        p1 = prices[i]
        if p0 and p1 and p0 > 0:
            rets.append((p1 / p0) - 1.0)
    if len(rets) < 10:
        return 0.0, 0.0

    # volatility (std)
    mean = sum(rets) / len(rets)
    var = sum((x - mean) ** 2 for x in rets) / max(1, (len(rets) - 1))
    vol = math.sqrt(var)

    # slope (last 25% vs first 25%)
    n = len(prices)
    a = prices[: n // 4]
    b = prices[-n // 4 :]
    if not a or not b:
        slope = 0.0
    else:
        slope = (sum(b) / len(b)) / (sum(a) / len(a)) - 1.0

    return float(vol), float(slope)

def score_coin(row: Dict[str, Any], weights: Dict[str, float]) -> Optional[Candidate]:
    coin_id = str(row.get("id", "")).strip()
    symbol = str(row.get("symbol", "")).upper().strip()
    name = str(row.get("name", "")).strip()

    if not coin_id or not symbol or not SYMBOL_RE.match(row.get("symbol", "") or ""):
        return None

    if is_probably_stable(symbol, name):
        return None

    mcap = safe_float(row.get("market_cap"))
    vol24 = safe_float(row.get("total_volume"))
    if mcap <= 0 or vol24 <= 0:
        return None

    # Core filters: quality
    if not (MIN_MCAP <= mcap <= MAX_MCAP):
        return None
    vol_ratio = vol24 / mcap
    if vol_ratio < MIN_VOL_RATIO:
        return None

    chg_1h = safe_float(row.get("price_change_percentage_1h_in_currency"))
    chg_24h = safe_float(row.get("price_change_percentage_24h_in_currency"))

    # Avoid "already pumped" or violent 1h
    if chg_24h > MAX_24H_PUMP:
        return None
    if abs(chg_1h) > MAX_ABS_1H:
        return None

    # Sparkline-based: volatility + slope
    vol, slope = compute_spark_volatility(row.get("sparkline_in_7d"))

    reasons: List[str] = []

    # 1) Liquidity & interest (0-25)
    # vol_ratio: 0.30 -> baseline, 1.0+ -> excellent
    liq = clamp((vol_ratio - 0.30) / (1.20 - 0.30), 0.0, 1.0)  # normalized
    liq_score = 25.0 * liq
    if liq_score > 16:
        reasons.append(f"Liquidez forte (Vol/Mcap {vol_ratio:.2f})")

    # 2) Momentum controlled (0-25)
    # We want mild positive 24h, not explosive; 1h near neutral/slight green.
    # Ideal: 24h in [1..10], 1h in [0..1.5]
    m24 = clamp((chg_24h - 1.0) / (10.0 - 1.0), 0.0, 1.0)
    m1 = 1.0 - clamp(abs(chg_1h) / 3.0, 0.0, 1.0)
    mom_score = 25.0 * (0.65 * m24 + 0.35 * m1)
    if chg_24h > 0:
        reasons.append(f"Momentum controlado (24h {chg_24h:+.2f}%, 1h {chg_1h:+.2f}%)")

    # 3) Accumulation (0-25)
    # We prefer: slope mildly positive OR flat, volatility not too high (quiet).
    # Ideal vol ~ 0.01..0.03 (very rough); slope > 0 but not huge.
    vol_good = 1.0 - clamp((vol - 0.01) / (0.06 - 0.01), 0.0, 1.0)  # lower vol => higher
    slope_good = clamp((slope + 0.02) / (0.10 + 0.02), 0.0, 1.0)      # allow slight negative to mild pos
    acc_score = 25.0 * (0.55 * vol_good + 0.45 * slope_good)
    if acc_score > 14:
        reasons.append("Acumulação provável (volatilidade contida + tendência leve)")

    # 4) Risk (0-25)
    # Proxy risk: penalize higher volatility and too negative 24h; reward stability.
    risk_score = 25.0 * clamp((vol_good * 0.7 + (1.0 - clamp(max(0.0, -chg_24h) / 10.0, 0.0, 1.0)) * 0.3), 0.0, 1.0)
    if risk_score > 14:
        reasons.append("Risco aceitável (sem estresse de volatilidade)")

    # Weighted total (normalized to 100)
    w_liq = weights["liquidity"]
    w_mom = weights["momentum_control"]
    w_acc = weights["accumulation"]
    w_rsk = weights["risk"]
    w_sum = max(0.0001, (w_liq + w_mom + w_acc + w_rsk))

    total = (liq_score * w_liq + mom_score * w_mom + acc_score * w_acc + risk_score * w_rsk) / w_sum
    total = round(clamp(total, 0.0, 100.0), 1)

    return Candidate(
        id=coin_id,
        symbol=symbol,
        name=name,
        mcap=mcap,
        vol24=vol24,
        vol_ratio=vol_ratio,
        chg_1h=chg_1h,
        chg_24h=chg_24h,
        score=total,
        reasons=reasons[:3],
    )

def format_money(x: float) -> str:
    # short format
    if x >= 1e9:
        return f"${x/1e9:.2f}B"
    if x >= 1e6:
        return f"${x/1e6:.2f}M"
    if x >= 1e3:
        return f"${x/1e3:.2f}K"
    return f"${x:.0f}"

def format_report(cands: List[Candidate], top_n: int) -> str:
    lines = []
    lines.append("🔥 <b>SMART MONEY PRÉ-PUMP (Top {})</b>".format(top_n))
    lines.append(f"<i>{now_utc_str()}</i>")
    lines.append("")
    for i, c in enumerate(cands[:top_n], start=1):
        lines.append(f"<b>{i}) {c.symbol}/USD</b> | Score <b>{c.score}</b>")
        lines.append(f"• Mcap: {format_money(c.mcap)} | Vol24: {format_money(c.vol24)} | Vol/Mcap: <b>{c.vol_ratio:.2f}</b>")
        lines.append(f"• 1h: {c.chg_1h:+.2f}% | 24h: {c.chg_24h:+.2f}%")
        if c.reasons:
            lines.append("• " + " | ".join(c.reasons))
        lines.append("")
    return "\n".join(lines).strip()

# =========================
# AUTO-TUNING (simple, robust)
# =========================
# You report results: /result SYMBOL pnl_percent hold_hours
# Example: /result SONIC 12.5 6
# Bot nudges weights toward components that were strong in that pick.

LAST_SCAN_CACHE: Dict[str, Candidate] = {}

def tune_weights(weights: Dict[str, float], candidate: Candidate, pnl_pct: float) -> Dict[str, float]:
    """
    Very simple online learning:
    - If pnl positive: slightly increase all weights, but more on the components likely responsible:
      liquidity, momentum_control, accumulation, risk (we used proxies)
    - If pnl negative: slightly decrease momentum (overfitting to short spikes) and increase risk weight a bit.
    """
    lr = 0.03  # learning rate
    pnl = clamp(pnl_pct / 20.0, -1.0, 1.0)  # normalize

    # base nudges
    weights["liquidity"] = clamp(weights["liquidity"] * (1.0 + lr * pnl * 0.6), 0.4, 2.0)
    weights["accumulation"] = clamp(weights["accumulation"] * (1.0 + lr * pnl * 0.9), 0.4, 2.0)

    # momentum: if pnl negative, reduce momentum bias
    weights["momentum_control"] = clamp(weights["momentum_control"] * (1.0 + lr * pnl * 0.5), 0.4, 2.0)

    # risk: if pnl negative, increase risk weight slightly (be more picky)
    if pnl_pct < 0:
        weights["risk"] = clamp(weights["risk"] * (1.0 + lr * 0.8), 0.4, 2.0)
    else:
        weights["risk"] = clamp(weights["risk"] * (1.0 + lr * pnl * 0.2), 0.4, 2.0)

    return weights

# =========================
# TELEGRAM HANDLERS
# =========================
async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("pong ✅")

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = (
        "✅ <b>Bot online.</b>\n\n"
        "<b>Comandos:</b>\n"
        "/ping\n"
        "/smartmoney  → Top pré-pump (CoinGecko)\n"
        "/weights → ver pesos\n"
        "/weights set liquidity=1.1 momentum_control=0.9 accumulation=1.2 risk=1.0\n"
        "/result SYMBOL pnl_percent hold_hours  → autoajuste (ex: /result SONIC 12.5 6)\n"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def cmd_weights(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    w = load_weights()

    if context.args and context.args[0].lower() == "set":
        # parse key=value pairs
        for kv in context.args[1:]:
            if "=" not in kv:
                continue
            k, v = kv.split("=", 1)
            k = k.strip()
            try:
                val = float(v.strip())
            except Exception:
                continue
            if k in w:
                w[k] = clamp(val, 0.4, 2.0)
        save_weights(w)
        await update.message.reply_text(f"✅ Pesos atualizados: <code>{json.dumps(w)}</code>", parse_mode=ParseMode.HTML)
        return

    await update.message.reply_text(f"⚙️ Pesos atuais: <code>{json.dumps(w)}</code>", parse_mode=ParseMode.HTML)

async def cmd_smartmoney(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔎 Rodando scanner CoinGecko (pré-pump)...")

    try:
        markets = await fetch_markets()
        weights = load_weights()

        scored: List[Candidate] = []
        for row in markets:
            c = score_coin(row, weights)
            if c:
                scored.append(c)

        scored.sort(key=lambda x: x.score, reverse=True)

        # cache last scan
        LAST_SCAN_CACHE.clear()
        for c in scored[: max(TOP_N, 10)]:
            LAST_SCAN_CACHE[c.symbol.upper()] = c

        if not scored:
            await update.message.reply_text("⚠️ Nada passou nos filtros agora. (Liquidez/MCAP/pump já aconteceu).")
            return

        text = format_report(scored, TOP_N)
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)

    except httpx.HTTPStatusError as e:
        await update.message.reply_text(f"⚠️ CoinGecko HTTP error: {e.response.status_code}")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Erro no scanner: {type(e).__name__}: {e}")

async def cmd_result(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /result SYMBOL pnl_percent hold_hours
    """
    if len(context.args) < 2:
        await update.message.reply_text("Use: /result SYMBOL pnl_percent hold_hours (hold_hours opcional)\nEx: /result SONIC 12.5 6")
        return

    sym = context.args[0].upper().strip()
    pnl = safe_float(context.args[1], default=0.0)

    c = LAST_SCAN_CACHE.get(sym)
    if not c:
        await update.message.reply_text("⚠️ Não achei esse SYMBOL no último /smartmoney. Rode /smartmoney e tente de novo.")
        return

    w = load_weights()
    before = dict(w)
    w = tune_weights(w, c, pnl)
    save_weights(w)

    await update.message.reply_text(
        "✅ Resultado registrado.\n"
        f"• {sym} pnl: {pnl:+.2f}%\n"
        f"• Pesos antes: <code>{json.dumps(before)}</code>\n"
        f"• Pesos agora: <code>{json.dumps(w)}</code>",
        parse_mode=ParseMode.HTML
    )

# =========================
# MAIN
# =========================
def build_app() -> Application:
    app = Application.builder().token(TG_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("smartmoney", cmd_smartmoney))
    app.add_handler(CommandHandler("weights", cmd_weights))
    app.add_handler(CommandHandler("result", cmd_result))
    return app

def main() -> None:
    app = build_app()

    # IMPORTANT:
    # Conflict error happens if you run the same bot token in two places (local + Railway) OR multiple Railway instances.
    # Keep only ONE running instance.
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        close_loop=False,  # avoid event loop "already running" issues in some environments
    )

if __name__ == "__main__":
    main()
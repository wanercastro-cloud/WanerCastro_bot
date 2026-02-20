import os
import time
import math
import asyncio
import logging
import requests
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

load_dotenv()
logging.basicConfig(level=logging.INFO)

TG_TOKEN = (os.getenv("TG_BOT_TOKEN") or "").strip()
CG_KEY = (os.getenv("COINGECKO_API_KEY") or "").strip()

if not TG_TOKEN:
    raise RuntimeError("TG_BOT_TOKEN não definido (Railway Variables ou .env)")

# =========================
# CONFIG
# =========================
TOP_N = 10

# filtros "pré-pump" (proxy CoinGecko)
MIN_VOL_USD = 50_000_000         # volume 24h mínimo
MAX_ABS_1H = 18.0                # remove quem já explodiu demais na 1h
MIN_ABS_1H = 1.2                 # precisa estar mexendo na 1h
MAX_ABS_24H = 35.0               # remove quem já foi longe demais no dia

# Smart Money Score (0–100)
SCORE_SHOW_MIN = 45
WHALE_MIN = 75
SUS_MIN = 60
MON_MIN = 45

STABLES = {"USDT", "USDC", "DAI", "TUSD", "FDUSD", "USD1", "BUSD", "USDP", "EURT", "PYUSD"}

CG_BASE = "https://api.coingecko.com/api/v3"
CG_MARKETS = f"{CG_BASE}/coins/markets"

TELEGRAM_MAX = 3900  # margem

def cg_headers() -> Dict[str, str]:
    h = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    # Aceita demo/pro em alguns ambientes; se não tiver, ignora.
    if CG_KEY:
        h["x-cg-demo-api-key"] = CG_KEY
        h["x-cg-pro-api-key"] = CG_KEY
    return h

def safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None or x == "":
            return default
        return float(x)
    except Exception:
        return default

def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))

# =========================
# COINGECKO FETCH (sem travar Telegram)
# =========================
def _fetch_markets_page(per_page: int = 250, page: int = 1) -> List[Dict[str, Any]]:
    params = {
        "vs_currency": "usd",
        "order": "volume_desc",
        "per_page": per_page,
        "page": page,
        "sparkline": "false",
        "price_change_percentage": "1h,24h",
    }
    r = requests.get(CG_MARKETS, params=params, headers=cg_headers(), timeout=12)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else []

async def cg_markets(per_page: int = 250, page: int = 1) -> List[Dict[str, Any]]:
    return await asyncio.to_thread(_fetch_markets_page, per_page, page)

def normalize_rows(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for it in data:
        sym = (it.get("symbol") or "").upper()
        if not sym or sym in STABLES:
            continue

        price = safe_float(it.get("current_price"))
        vol = safe_float(it.get("total_volume"))
        ch1h = safe_float(it.get("price_change_percentage_1h_in_currency"))
        ch24 = safe_float(it.get("price_change_percentage_24h_in_currency"))

        if price <= 0 or vol <= 0:
            continue

        rows.append({
            "symbol": f"{sym}USDT",
            "base": sym,
            "price": price,
            "vol24h": vol,
            "ch1h": ch1h,
            "ch24h": ch24,
        })
    return rows

# =========================
# TOPSPOT (pré-pump proxy)
# =========================
def topspot_filter(r: Dict[str, Any]) -> bool:
    # remove quem já “foi”
    if abs(r["ch1h"]) > MAX_ABS_1H:
        return False
    if abs(r["ch24h"]) > MAX_ABS_24H:
        return False
    # precisa estar mexendo agora
    if abs(r["ch1h"]) < MIN_ABS_1H:
        return False
    # precisa ter liquidez/volume
    if r["vol24h"] < MIN_VOL_USD:
        return False
    return True

def topspot_rank_score(r: Dict[str, Any]) -> float:
    # Proxy: mistura volume + volatilidade 1h (mas penaliza “muito esticado”)
    vol_component = math.log10(max(1.0, r["vol24h"]))
    volat_component = abs(r["ch1h"])
    stretch_penalty = clamp((abs(r["ch1h"]) - 10.0) / 10.0, 0.0, 1.0)  # penaliza >10%/h
    return vol_component * 3.0 + volat_component * 2.5 - stretch_penalty * 8.0

# =========================
# SMART MONEY SCORE (0–100) proxy CoinGecko
# =========================
def smartmoney_score(r: Dict[str, Any], vol_med: float) -> Tuple[int, str, List[str]]:
    """
    Score baseado em:
    - volume relativo (vs mediana do universo)
    - volatilidade 1h (movimento inicial)
    - “ainda cedo”: 24h não muito esticado
    - penaliza 1h muito esticado (provável atraso)
    """
    flags: List[str] = []

    vol_ratio = r["vol24h"] / max(1.0, vol_med)
    vol_boost = clamp((math.log10(max(1.0, vol_ratio)) + 1.0) / 2.0, 0.0, 1.0)  # 0..1

    # movimento 1h ideal: 1.2% a ~8%
    ch1h_abs = abs(r["ch1h"])
    ch24_abs = abs(r["ch24h"])

    early_move = 1.0 if (ch1h_abs >= MIN_ABS_1H and ch1h_abs <= 8.0) else 0.0
    if early_move:
        flags.append("early_move")

    # “não esticado no dia”
    not_stretched = 1.0 if ch24_abs <= 12.0 else 0.0
    if not_stretched:
        flags.append("not_stretched")

    # penaliza se já está estourado na 1h
    late_penalty = clamp((ch1h_abs - 10.0) / 10.0, 0.0, 1.0)
    if late_penalty > 0:
        flags.append("late_1h")

    # base score
    score = 20
    score += int(35 * vol_boost)
    score += int(20 * early_move)
    score += int(15 * not_stretched)
    score += int(10 * clamp(ch1h_abs / 8.0, 0.0, 1.0))
    score -= int(25 * late_penalty)

    # ajuste por direção (preferir positivo, mas sem descartar reversões)
    if r["ch1h"] > 0:
        score += 5
        flags.append("positive_1h")

    score = int(clamp(score, 0, 100))

    if score >= WHALE_MIN:
        status = "🐋"
    elif score >= SUS_MIN:
        status = "⚠️"
    elif score >= MON_MIN:
        status = "👀"
    else:
        status = "❌"

    return score, status, flags

# =========================
# TELEGRAM COMMANDS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Smart Money (CoinGecko-only) ONLINE\n\n"
        "Comandos:\n"
        "/topspot  → Top pré-pump (proxy: 1h + volume)\n"
        "/smartmoney → Score 0–100 (🐋/⚠️/👀)\n"
        "/sniper  → modo agressivo (proxy)\n\n"
        "Obs: CoinGecko não tem 1m/5m candles reais, então é detecção por sinais agregados."
    )

async def topspot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔎 Montando Top Premium (pré-pump proxy)…")
    try:
        data = await cg_markets(250, 1)
        rows = normalize_rows(data)

        filt = [r for r in rows if topspot_filter(r)]
        filt.sort(key=topspot_rank_score, reverse=True)

        top = filt[:TOP_N]
        if not top:
            await update.message.reply_text("📭 Nada forte no filtro agora. Tente de novo em 2–3 min.")
            return

        lines = ["🏆 Top Premium (pré-pump proxy: 1h + volume)"]
        for i, r in enumerate(top, 1):
            lines.append(
                f"{i:02d}. {r['symbol']} | {r['price']:.8g} | 1h {r['ch1h']:+.2f}% | 24h {r['ch24h']:+.2f}% | vol ${r['vol24h']:,.0f}"
            )

        msg = "\n".join(lines)
        await update.message.reply_text(msg[:TELEGRAM_MAX])

    except Exception as e:
        logging.exception("Erro /topspot")
        await update.message.reply_text(f"⚠️ Erro no /topspot: {type(e).__name__}")

async def smartmoney(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧠 Calculando Smart Money Score…")
    try:
        data = await cg_markets(250, 1)
        rows = normalize_rows(data)

        vols = sorted([r["vol24h"] for r in rows if r["vol24h"] > 0])
        vol_med = vols[len(vols)//2] if vols else 1.0

        scored = []
        for r in rows:
            # filtro “já foi”
            if abs(r["ch1h"]) > MAX_ABS_1H or abs(r["ch24h"]) > MAX_ABS_24H:
                continue
            if r["vol24h"] < MIN_VOL_USD:
                continue

            score, status, flags = smartmoney_score(r, vol_med)
            if score >= SCORE_SHOW_MIN and status != "❌":
                scored.append((score, status, r, flags))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:15]

        if not top:
            await update.message.reply_text("📭 Sem candidatos fortes agora (no score).")
            return

        lines = ["📊 SMART MONEY SCORE – TOP 15"]
        for i, (score, status, r, flags) in enumerate(top, 1):
            flags_txt = ",".join(flags[:3])
            lines.append(
                f"{i:02d}) {r['symbol']} | Score {score}/100 | {status}\n"
                f"• 1h {r['ch1h']:+.2f}% | 24h {r['ch24h']:+.2f}% | vol ${r['vol24h']:,.0f}\n"
                f"• Flags: {flags_txt}"
            )

        msg = "\n".join(lines)
        await update.message.reply_text(msg[:TELEGRAM_MAX])

    except Exception as e:
        logging.exception("Erro /smartmoney")
        await update.message.reply_text(f"⚠️ Erro no /smartmoney: {type(e).__name__}")

async def sniper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Sniper agressivo (proxy com CoinGecko):
    - procura 1h “subindo agora” mas ainda não esticado no 24h
    - volume alto
    """
    await update.message.reply_text("🏴‍☠️ Sniper (proxy CoinGecko) varrendo…")
    try:
        data = await cg_markets(250, 1)
        rows = normalize_rows(data)

        # Sniper proxy:
        # - 1h entre 1.5% e 7.5% (movimento inicial)
        # - 24h <= 10% (ainda cedo no dia)
        # - volume alto
        cand = []
        for r in rows:
            ch1 = abs(r["ch1h"])
            ch24 = abs(r["ch24h"])
            if r["vol24h"] < (MIN_VOL_USD * 1.2):
                continue
            if not (1.5 <= ch1 <= 7.5):
                continue
            if ch24 > 10.0:
                continue
            # direção positiva favorece “pré-pump”
            dir_bonus = 1.0 if r["ch1h"] > 0 else 0.0
            score = (math.log10(r["vol24h"]) * 6.0) + (ch1 * 6.0) + (dir_bonus * 6.0)
            cand.append((score, r))

        cand.sort(key=lambda x: x[0], reverse=True)
        top = [r for _, r in cand[:7]]

        if not top:
            await update.message.reply_text("📭 Sniper: nada no critério agora.")
            return

        lines = ["🏴‍☠️ SNIPER SMART MONEY (proxy) – Top 7"]
        for i, r in enumerate(top, 1):
            lines.append(
                f"{i:02d}. {r['symbol']} | {r['price']:.8g} | 1h {r['ch1h']:+.2f}% | 24h {r['ch24h']:+.2f}% | vol ${r['vol24h']:,.0f}\n"
                f"• Confirmação: se 1h continuar acelerando com volume alto (checar em 2–3 min)."
            )

        msg = "\n".join(lines)
        await update.message.reply_text(msg[:TELEGRAM_MAX])

    except Exception as e:
        logging.exception("Erro /sniper")
        await update.message.reply_text(f"⚠️ Erro no /sniper: {type(e).__name__}")

def main():
    app = ApplicationBuilder().token(TG_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("topspot", topspot))
    app.add_handler(CommandHandler("smartmoney", smartmoney))
    app.add_handler(CommandHandler("sniper", sniper))

    logging.info("✅ Bot iniciado (CoinGecko-only)")
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
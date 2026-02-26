# main.py (COMPLETO e CORRIGIDO) — CoinGecko PRO + Telegram Bot (PTB v21.6)
# Comandos:
#  /ping
#  /smartmoney  -> Top N pré-pump (CoinGecko)
#  /radar       -> alias do /smartmoney
#
# Variáveis Railway (Service Variables):
#  TG_BOT_TOKEN=...
#  COINGECKO_PRO_API_KEY=...   (chave PRO)
#  TOP_N=5                     (opcional)
#  CANDIDATES=250              (opcional)
#  SCAN_EVERY_MIN=60           (opcional; 0 desliga varredura automática)
#  ALERT_CHAT_ID=...           (opcional; id do chat para alertas automáticos)

import os
import re
import math
import time
import asyncio
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple

import httpx
from dotenv import load_dotenv

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

# ------------------------
# Load env
# ------------------------
load_dotenv()

TG_BOT_TOKEN = (os.getenv("TG_BOT_TOKEN") or "").strip()
COINGECKO_PRO_API_KEY = (os.getenv("COINGECKO_PRO_API_KEY") or "").strip()

TOP_N = int(os.getenv("TOP_N", "5"))
CANDIDATES = int(os.getenv("CANDIDATES", "250"))
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "20"))
SCAN_EVERY_MIN = int(os.getenv("SCAN_EVERY_MIN", "0"))  # 0 = desliga
ALERT_CHAT_ID = (os.getenv("ALERT_CHAT_ID") or "").strip()  # opcional

if not TG_BOT_TOKEN:
    raise RuntimeError("❌ Variável TG_BOT_TOKEN não definida.")
if not COINGECKO_PRO_API_KEY:
    raise RuntimeError("❌ Variável COINGECKO_PRO_API_KEY não definida (CoinGecko PRO).")

# ------------------------
# Helpers / Filters
# ------------------------
STABLE_SYMBOLS = {
    "USDT", "USDC", "DAI", "TUSD", "USDE", "USDQ", "FDUSD", "USDP", "USDD",
    "EUR", "GBP", "JPY", "TRY", "BRL", "AUD", "CHF", "CAD", "HKD", "SGD"
}

BAD_WORDS = re.compile(
    r"(bear|bull|3l|3s|5l|5s|leveraged|hedge|inverse|short|long|etf|fi|"
    r"wrapped|wbtc|weth|staked|staking|liquid staking|lido|reth|steth)",
    re.IGNORECASE,
)

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def fmt_money(x: float) -> str:
    try:
        if x >= 1_000_000_000:
            return f"${x/1_000_000_000:.2f}B"
        if x >= 1_000_000:
            return f"${x/1_000_000:.2f}M"
        if x >= 1_000:
            return f"${x/1_000:.2f}K"
        return f"${x:.2f}"
    except Exception:
        return "$0"

def fmt_pct(x: Optional[float]) -> str:
    if x is None:
        return "n/a"
    return f"{x:+.2f}%"

def looks_like_stable(symbol: str, name: str) -> bool:
    sym = (symbol or "").upper()
    nm = (name or "").lower()
    if sym in STABLE_SYMBOLS:
        return True
    if "stable" in nm or "usd" in sym:
        # cuidado: nem todo token com USD é stable, mas aqui é filtro de radar
        # (você pode afrouxar depois)
        return True
    return False

def is_bad_asset(symbol: str, name: str) -> bool:
    text = f"{symbol} {name}"
    return bool(BAD_WORDS.search(text))

# ------------------------
# Scoring (pré-pump)
# ------------------------
def score_candidate(mcap: float, vol24: float, chg1h: float, chg24h: float) -> float:
    """
    Score 0–100 para detecção de pré-pump (Smart Money)
    Combina:
    - Turnover (vol/mcap)
    - Aceleração curta (1h)
    - Não estar esticado demais no 24h
    """
    if mcap <= 0 or vol24 <= 0:
        return 0.0

    turnover = vol24 / mcap  # giro em 24h

    turnover_n = clamp(math.log10(1 + turnover * 10), 0.0, 2.0) / 2.0   # 0..1
    vol_n = clamp(math.log10(1 + vol24 / 1_000_000), 0.0, 4.0) / 4.0   # 0..1
    mcap_n = clamp(math.log10(1 + mcap / 1_000_000), 0.0, 4.0) / 4.0   # 0..1

    # favorece leve aceleração em 1h (+1 a +5)
    chg1h_n = clamp((chg1h + 5) / 15, 0.0, 1.0)

    # penaliza muito esticado no 24h
    chg24h_penalty = clamp(abs(chg24h) / 60, 0.0, 1.0)

    score = (
        0.30 * turnover_n +
        0.25 * vol_n +
        0.20 * chg1h_n +
        0.15 * (1 - chg24h_penalty) +
        0.10 * mcap_n
    )
    return round(score * 100, 2)

@dataclass
class Candidate:
    symbol: str
    name: str
    mcap: float
    vol24: float
    chg1h: float
    chg24h: float
    score: float

# ------------------------
# CoinGecko PRO Client
# ------------------------
CG_PRO_BASE = "https://pro-api.coingecko.com/api/v3"

def cg_headers() -> Dict[str, str]:
    return {
        "accept": "application/json",
        # Header correto do PRO:
        "x-cg-pro-api-key": COINGECKO_PRO_API_KEY,
        # User-Agent ajuda a evitar bloqueios bestas
        "user-agent": "WanerCastsBot/1.0 (CoinGecko PRO; httpx)"
    }

async def cg_get_markets(limit: int) -> List[Dict[str, Any]]:
    """
    Puxa lista de moedas via /coins/markets.
    Usa dados de:
    - market_cap
    - total_volume
    - price_change_percentage_1h_in_currency
    - price_change_percentage_24h_in_currency
    """
    per_page = min(250, max(1, limit))
    pages = (limit + per_page - 1) // per_page

    out: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, headers=cg_headers()) as client:
        for page in range(1, pages + 1):
            params = {
                "vs_currency": "usd",
                "order": "volume_desc",
                "per_page": per_page,
                "page": page,
                "sparkline": "false",
                "price_change_percentage": "1h,24h",
            }
            r = await client.get(f"{CG_PRO_BASE}/coins/markets", params=params)
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, list):
                break
            out.extend(data)
            if len(data) < per_page:
                break

    return out[:limit]

def build_candidates(rows: List[Dict[str, Any]]) -> List[Candidate]:
    cands: List[Candidate] = []
    for row in rows:
        symbol = (row.get("symbol") or "").upper()
        name = row.get("name") or ""
        mcap = float(row.get("market_cap") or 0.0)
        vol24 = float(row.get("total_volume") or 0.0)

        # CoinGecko retorna esses campos quando pede price_change_percentage=1h,24h:
        chg1h = row.get("price_change_percentage_1h_in_currency")
        chg24h = row.get("price_change_percentage_24h_in_currency")

        try:
            chg1h_f = float(chg1h) if chg1h is not None else 0.0
        except Exception:
            chg1h_f = 0.0
        try:
            chg24h_f = float(chg24h) if chg24h is not None else 0.0
        except Exception:
            chg24h_f = 0.0

        # Filtros
        if not symbol or looks_like_stable(symbol, name):
            continue
        if is_bad_asset(symbol, name):
            continue
        if mcap <= 0 or vol24 <= 0:
            continue

        score = score_candidate(mcap=mcap, vol24=vol24, chg1h=chg1h_f, chg24h=chg24h_f)

        cands.append(Candidate(
            symbol=symbol,
            name=name,
            mcap=mcap,
            vol24=vol24,
            chg1h=chg1h_f,
            chg24h=chg24h_f,
            score=score
        ))
    return cands

def format_top(cands: List[Candidate], top_n: int) -> str:
    top = sorted(cands, key=lambda x: x.score, reverse=True)[:top_n]
    if not top:
        return "⚠️ Nenhum candidato encontrado com os filtros atuais."

    lines = [f"🔥 <b>SMART MONEY PRÉ-PUMP</b> (Top {len(top)})"]
    for i, c in enumerate(top, 1):
        lines.append(
            f"\n<b>{i}) {c.symbol}/USDT</b> | Score <b>{c.score}</b>\n"
            f"• Mcap: {fmt_money(c.mcap)} | Vol24: {fmt_money(c.vol24)}\n"
            f"• 1h: {fmt_pct(c.chg1h)} | 24h: {fmt_pct(c.chg24h)}"
        )
    lines.append("\n🧪 Fonte: CoinGecko PRO (/coins/markets)")
    return "\n".join(lines)

# ------------------------
# Telegram Commands
# ------------------------
async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("pong ✅")

async def cmd_smartmoney(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔎 Rodando scanner CoinGecko PRO…", disable_web_page_preview=True)

    try:
        rows = await cg_get_markets(CANDIDATES)
        cands = build_candidates(rows)
        msg = format_top(cands, TOP_N)
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except httpx.HTTPStatusError as e:
        await update.message.reply_text(
            f"⚠️ Erro HTTP no CoinGecko PRO: {e.response.status_code} {e.response.reason_phrase}\n"
            f"URL: {str(e.request.url)}",
            disable_web_page_preview=True,
        )
    except Exception as e:
        await update.message.reply_text(f"⚠️ Erro no /smartmoney: {type(e).__name__}: {e}", disable_web_page_preview=True)

async def cmd_radar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Alias do /smartmoney
    await cmd_smartmoney(update, context)

# ------------------------
# Job (opcional) - varredura automática
# ------------------------
_last_auto_msg: Optional[str] = None
_last_auto_ts: float = 0.0

async def job_scan(context: ContextTypes.DEFAULT_TYPE) -> None:
    global _last_auto_msg, _last_auto_ts

    if not ALERT_CHAT_ID:
        return

    # anti-spam simples (não repetir igual)
    try:
        rows = await cg_get_markets(CANDIDATES)
        cands = build_candidates(rows)
        msg = format_top(cands, TOP_N)

        now = time.time()
        if msg == _last_auto_msg and (now - _last_auto_ts) < max(300, SCAN_EVERY_MIN * 60):
            return

        _last_auto_msg = msg
        _last_auto_ts = now

        await context.bot.send_message(
            chat_id=ALERT_CHAT_ID,
            text=msg,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        # não derruba o bot por falha de job
        return

async def post_init(app: Application) -> None:
    # Agenda a varredura automática depois que o app inicia
    if SCAN_EVERY_MIN > 0 and ALERT_CHAT_ID:
        app.job_queue.run_repeating(job_scan, interval=SCAN_EVERY_MIN * 60, first=10)

# ------------------------
# Main
# ------------------------
def main() -> None:
    application = (
        Application.builder()
        .token(TG_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    application.add_handler(CommandHandler("ping", cmd_ping))
    application.add_handler(CommandHandler("smartmoney", cmd_smartmoney))
    application.add_handler(CommandHandler("radar", cmd_radar))

    # run_polling sem asyncio.run -> evita os erros de event loop
    application.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
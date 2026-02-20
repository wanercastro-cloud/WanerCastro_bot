import os
import time
import math
import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple
import requests

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

load_dotenv()
logging.basicConfig(level=logging.INFO)

TG_TOKEN = (os.getenv("TG_BOT_TOKEN") or "").strip()
CG_KEY = (os.getenv("COINGECKO_API_KEY") or "").strip()
ALERT_CHAT_ID_ENV = (os.getenv("ALERT_CHAT_ID") or "").strip()

if not TG_TOKEN:
    raise RuntimeError("TG_BOT_TOKEN não definido (Railway Variables ou .env)")

# =========================
# CONFIG
# =========================
CG_BASE = "https://api.coingecko.com/api/v3"
CG_MARKETS = f"{CG_BASE}/coins/markets"

TOP_N = 10

# Anti-rate-limit
CACHE_TTL_SEC = 90
PER_PAGE = 150  # seguro (100–200)
RETRY_429_WAIT_MAX = 6.0

# Filtros “pré-pump” (proxy CoinGecko)
MIN_VOL_USD = 35_000_000
MAX_ABS_1H = 18.0
MIN_ABS_1H = 1.2
MAX_ABS_24H = 40.0

# Smart Money Score
SCORE_SHOW_MIN = 45
WHALE_MIN = 78
SUS_MIN = 62
MON_MIN = 45

STABLES = {"USDT","USDC","DAI","TUSD","FDUSD","USD1","BUSD","USDP","EURT","PYUSD"}

TELEGRAM_MAX = 3900

# =========================
# RUNTIME STATE (memória)
# =========================
_cache_markets: Optional[List[Dict[str, Any]]] = None
_cache_ts: float = 0.0

# por chat: watchlist + settings
watchlists: Dict[int, set] = {}
alert_enabled: Dict[int, bool] = {}
alert_min_score: Dict[int, int] = {}
alert_cooldown_s: Dict[int, int] = {}
last_alert_ts: Dict[Tuple[int, str], float] = {}  # (chat_id, symbol) -> ts

# =========================
# HELPERS
# =========================
def cg_headers() -> Dict[str, str]:
    h = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    if CG_KEY:
        # cobre variações (demo/pro). Se sua key for “app premium”, pode ser ignorada, mas não atrapalha.
        h["x-cg-pro-api-key"] = CG_KEY
        h["x-cg-demo-api-key"] = CG_KEY
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

def now_ts() -> float:
    return time.time()

def parse_symbol(arg: str) -> str:
    s = (arg or "").strip().upper()
    if not s:
        return ""
    # padrão USDT final
    if not s.endswith("USDT"):
        s = s + "USDT"
    # remove espaços/char estranhos
    return "".join(ch for ch in s if ch.isalnum())

# =========================
# COINGECKO FETCH (robusto)
# =========================
def _fetch_markets_page(per_page: int = PER_PAGE, page: int = 1) -> List[Dict[str, Any]]:
    params = {
        "vs_currency": "usd",
        "order": "volume_desc",
        "per_page": per_page,
        "page": page,
        "sparkline": "false",
        "price_change_percentage": "1h,24h",
    }

    for attempt in range(2):
        r = requests.get(CG_MARKETS, params=params, headers=cg_headers(), timeout=12)

        if r.status_code == 200:
            data = r.json()
            return data if isinstance(data, list) else []

        if r.status_code == 429 and attempt == 0:
            retry_after = r.headers.get("Retry-After")
            wait = float(retry_after) if (retry_after and retry_after.isdigit()) else 2.5
            time.sleep(min(wait, RETRY_429_WAIT_MAX))
            continue

        # Erro com contexto
        try:
            r.raise_for_status()
        except requests.HTTPError as e:
            raise requests.HTTPError(
                f"{type(e).__name__} status={r.status_code} body={r.text[:180]}"
            ) from e

    return []

async def cg_markets(per_page: int = PER_PAGE, page: int = 1) -> List[Dict[str, Any]]:
    global _cache_markets, _cache_ts
    t = now_ts()
    if _cache_markets is not None and (t - _cache_ts) < CACHE_TTL_SEC:
        return _cache_markets

    data = await asyncio.to_thread(_fetch_markets_page, per_page, page)
    _cache_markets = data
    _cache_ts = t
    return data

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
        mcap = safe_float(it.get("market_cap"))

        if price <= 0 or vol <= 0:
            continue

        rows.append({
            "symbol": f"{sym}USDT",
            "base": sym,
            "price": price,
            "vol24h": vol,
            "mcap": mcap,
            "ch1h": ch1h,
            "ch24h": ch24,
        })
    return rows

# =========================
# TOPSPOT / SMART MONEY LOGIC (proxy)
# =========================
def topspot_filter(r: Dict[str, Any]) -> bool:
    if abs(r["ch1h"]) > MAX_ABS_1H:
        return False
    if abs(r["ch24h"]) > MAX_ABS_24H:
        return False
    if abs(r["ch1h"]) < MIN_ABS_1H:
        return False
    if r["vol24h"] < MIN_VOL_USD:
        return False
    return True

def topspot_rank_score(r: Dict[str, Any]) -> float:
    vol_component = math.log10(max(1.0, r["vol24h"]))
    volat_component = abs(r["ch1h"])
    stretch_penalty = clamp((abs(r["ch1h"]) - 10.0) / 10.0, 0.0, 1.0)
    return vol_component * 3.0 + volat_component * 2.5 - stretch_penalty * 8.0

def smartmoney_score(r: Dict[str, Any], vol_med: float) -> Tuple[int, str, List[str]]:
    """
    “Smart money” inferido (proxy) com CoinGecko:
    - Liquidez (volume)
    - Volume relativo (vs mediana)
    - Mov. 1h “início”
    - 24h ainda não esticado
    - Volume/MarketCap (se market cap existir)
    """
    flags: List[str] = []

    vol_ratio = r["vol24h"] / max(1.0, vol_med)
    vol_boost = clamp((math.log10(max(1.0, vol_ratio)) + 1.0) / 2.0, 0.0, 1.0)

    ch1h_abs = abs(r["ch1h"])
    ch24_abs = abs(r["ch24h"])

    early = 1.0 if (ch1h_abs >= MIN_ABS_1H and ch1h_abs <= 8.0) else 0.0
    if early: flags.append("early_move")

    not_stretched = 1.0 if ch24_abs <= 14.0 else 0.0
    if not_stretched: flags.append("not_stretched")

    late_penalty = clamp((ch1h_abs - 10.0) / 10.0, 0.0, 1.0)
    if late_penalty > 0: flags.append("late_1h")

    # vol/mcap (melhor proxy de “fluxo” quando disponível)
    vm = 0.0
    if r["mcap"] and r["mcap"] > 0:
        vm = r["vol24h"] / r["mcap"]
        if vm >= 0.12: flags.append("vol_over_cap")
    vm_boost = clamp(vm / 0.20, 0.0, 1.0)  # 0..1 (>=0.20 fica 1)

    score = 20
    score += int(34 * vol_boost)
    score += int(18 * early)
    score += int(14 * not_stretched)
    score += int(10 * clamp(ch1h_abs / 8.0, 0.0, 1.0))
    score += int(14 * vm_boost)
    score -= int(25 * late_penalty)

    if r["ch1h"] > 0:
        score += 4
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
    chat_id = update.effective_chat.id
    alert_enabled.setdefault(chat_id, False)
    alert_min_score.setdefault(chat_id, 70)
    alert_cooldown_s.setdefault(chat_id, 240)
    watchlists.setdefault(chat_id, set())

    await update.message.reply_text(
        "🤖 Smart Money (CoinGecko proxy) ONLINE\n\n"
        "Comandos:\n"
        "/topspot → Top pré-pump (1h + volume)\n"
        "/smartmoney → Score 0–100 (🐋/⚠️/👀)\n"
        "/sniper → agressivo (proxy)\n\n"
        "Watchlist:\n"
        "/watch AZTECUSDT\n"
        "/unwatch AZTECUSDT\n"
        "/mywatch\n\n"
        "Alertas:\n"
        "/alerts_on\n"
        "/alerts_off\n"
        "/setscore 70\n"
        "/setcooldown 240\n"
    )

async def topspot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔎 Montando Top Premium (pré-pump proxy)…")
    try:
        data = await cg_markets(PER_PAGE, 1)
        rows = normalize_rows(data)

        filt = [r for r in rows if topspot_filter(r)]
        filt.sort(key=topspot_rank_score, reverse=True)
        top = filt[:TOP_N]

        if not top:
            await update.message.reply_text("📭 Nada forte no filtro agora. Tente em 2–3 min.")
            return

        lines = ["🏆 Top Premium (pré-pump proxy: 1h + volume)"]
        for i, r in enumerate(top, 1):
            lines.append(
                f"{i:02d}. {r['symbol']} | {r['price']:.8g} | 1h {r['ch1h']:+.2f}% | 24h {r['ch24h']:+.2f}% | vol ${r['vol24h']:,.0f}"
            )
        await update.message.reply_text("\n".join(lines)[:TELEGRAM_MAX])

    except requests.HTTPError as e:
        await update.message.reply_text(f"⚠️ CoinGecko falhou: {e}")
        logging.exception("HTTPError /topspot")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Erro no /topspot: {type(e).__name__}")
        logging.exception("Erro /topspot")

async def smartmoney(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧠 Calculando Smart Money Score…")
    try:
        data = await cg_markets(PER_PAGE, 1)
        rows = normalize_rows(data)

        if not rows:
            await update.message.reply_text("📭 CoinGecko não retornou dados agora. Tente em 1 min.")
            return

        vols = sorted([r["vol24h"] for r in rows if r["vol24h"] > 0])
        vol_med = vols[len(vols)//2] if vols else 1.0

        scored = []
        for r in rows:
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

        await update.message.reply_text("\n".join(lines)[:TELEGRAM_MAX])

    except requests.HTTPError as e:
        tip = "Se aparecer 429: aguarde 1–2 min. Cache já reduz bastante."
        await update.message.reply_text(f"⚠️ CoinGecko falhou: {e}\n{tip}")
        logging.exception("HTTPError /smartmoney")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Erro no /smartmoney: {type(e).__name__}")
        logging.exception("Erro geral /smartmoney")

async def sniper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏴‍☠️ Sniper (proxy CoinGecko) varrendo…")
    try:
        data = await cg_markets(PER_PAGE, 1)
        rows = normalize_rows(data)

        cand = []
        for r in rows:
            ch1 = abs(r["ch1h"])
            ch24 = abs(r["ch24h"])
            if r["vol24h"] < (MIN_VOL_USD * 1.2):
                continue
            if not (1.5 <= ch1 <= 7.5):
                continue
            if ch24 > 12.0:
                continue
            dir_bonus = 1.0 if r["ch1h"] > 0 else 0.0
            vm = (r["vol24h"] / r["mcap"]) if (r["mcap"] and r["mcap"] > 0) else 0.0
            score = (math.log10(r["vol24h"]) * 6.0) + (ch1 * 6.0) + (dir_bonus * 6.0) + (clamp(vm/0.2,0,1)*10)
            cand.append((score, r))

        cand.sort(key=lambda x: x[0], reverse=True)
        top = [r for _, r in cand[:7]]

        if not top:
            await update.message.reply_text("📭 Sniper: nada no critério agora.")
            return

        lines = ["🏴‍☠️ SNIPER (proxy) – Top 7"]
        for i, r in enumerate(top, 1):
            lines.append(
                f"{i:02d}. {r['symbol']} | {r['price']:.8g} | 1h {r['ch1h']:+.2f}% | 24h {r['ch24h']:+.2f}% | vol ${r['vol24h']:,.0f}"
            )
        await update.message.reply_text("\n".join(lines)[:TELEGRAM_MAX])

    except requests.HTTPError as e:
        await update.message.reply_text(f"⚠️ CoinGecko falhou: {e}")
        logging.exception("HTTPError /sniper")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Erro no /sniper: {type(e).__name__}")
        logging.exception("Erro /sniper")

# =========================
# WATCHLIST + ALERT CONTROLS
# =========================
async def watch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    watchlists.setdefault(chat_id, set())
    if not context.args:
        await update.message.reply_text("Use: /watch AZTECUSDT")
        return
    sym = parse_symbol(context.args[0])
    if not sym:
        await update.message.reply_text("Símbolo inválido.")
        return
    watchlists[chat_id].add(sym)
    await update.message.reply_text(f"✅ Adicionado: {sym}")

async def unwatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Use: /unwatch AZTECUSDT")
        return
    sym = parse_symbol(context.args[0])
    watchlists.setdefault(chat_id, set())
    watchlists[chat_id].discard(sym)
    await update.message.reply_text(f"✅ Removido: {sym}")

async def mywatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    wl = sorted(list(watchlists.get(chat_id, set())))
    if not wl:
        await update.message.reply_text("📭 Watchlist vazia. Use /watch AZTECUSDT")
        return
    await update.message.reply_text("📌 Watchlist:\n" + "\n".join(wl))

async def alerts_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    alert_enabled[chat_id] = True
    alert_min_score.setdefault(chat_id, 70)
    alert_cooldown_s.setdefault(chat_id, 240)
    watchlists.setdefault(chat_id, set())
    await update.message.reply_text(
        f"🔔 Alertas ON\n"
        f"• min score: {alert_min_score[chat_id]}\n"
        f"• cooldown: {alert_cooldown_s[chat_id]}s\n"
        f"• watchlist: {len(watchlists[chat_id])} ativos\n\n"
        f"Dica: adicione ativos com /watch AZTECUSDT"
    )

async def alerts_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    alert_enabled[chat_id] = False
    await update.message.reply_text("🔕 Alertas OFF")

async def setscore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Use: /setscore 70")
        return
    try:
        v = int(context.args[0])
        v = int(clamp(v, 30, 95))
        alert_min_score[chat_id] = v
        await update.message.reply_text(f"✅ min score = {v}")
    except Exception:
        await update.message.reply_text("Valor inválido. Ex: /setscore 70")

async def setcooldown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Use: /setcooldown 240")
        return
    try:
        v = int(context.args[0])
        v = int(clamp(v, 60, 3600))
        alert_cooldown_s[chat_id] = v
        await update.message.reply_text(f"✅ cooldown = {v}s")
    except Exception:
        await update.message.reply_text("Valor inválido. Ex: /setcooldown 240")

# =========================
# BACKGROUND ALERT JOB
# =========================
async def alert_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        # pega universe uma vez
        data = await cg_markets(PER_PAGE, 1)
        rows = normalize_rows(data)
        if not rows:
            return

        vols = sorted([r["vol24h"] for r in rows if r["vol24h"] > 0])
        vol_med = vols[len(vols)//2] if vols else 1.0

        # index por symbol
        idx = {r["symbol"]: r for r in rows}

        # para cada chat com alertas on:
        for chat_id, enabled in list(alert_enabled.items()):
            if not enabled:
                continue

            wl = watchlists.get(chat_id, set())
            if not wl:
                continue

            minscore = alert_min_score.get(chat_id, 70)
            cooldown = alert_cooldown_s.get(chat_id, 240)

            for sym in list(wl):
                r = idx.get(sym)
                if not r:
                    continue

                # filtros base
                if r["vol24h"] < MIN_VOL_USD:
                    continue
                if abs(r["ch1h"]) > MAX_ABS_1H or abs(r["ch24h"]) > MAX_ABS_24H:
                    continue

                score, status, flags = smartmoney_score(r, vol_med)
                if score < minscore:
                    continue

                key = (chat_id, sym)
                last = last_alert_ts.get(key, 0.0)
                if (now_ts() - last) < cooldown:
                    continue

                flags_txt = ",".join(flags[:4])
                msg = (
                    f"{status} ALERTA SMART MONEY (proxy)\n"
                    f"{sym} | Score {score}/100\n"
                    f"Preço: {r['price']:.8g}\n"
                    f"1h: {r['ch1h']:+.2f}% | 24h: {r['ch24h']:+.2f}%\n"
                    f"Vol 24h: ${r['vol24h']:,.0f}\n"
                    f"Flags: {flags_txt}\n\n"
                    f"Dica: confirme no gráfico (15m/1h) antes de entrar."
                )

                await context.bot.send_message(chat_id=chat_id, text=msg[:TELEGRAM_MAX])
                last_alert_ts[key] = now_ts()

    except Exception:
        # nunca derruba o bot por erro de job
        logging.exception("Erro no alert_job")

# =========================
# MAIN
# =========================
def main():
    app = ApplicationBuilder().token(TG_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("topspot", topspot))
    app.add_handler(CommandHandler("smartmoney", smartmoney))
    app.add_handler(CommandHandler("sniper", sniper))

    app.add_handler(CommandHandler("watch", watch))
    app.add_handler(CommandHandler("unwatch", unwatch))
    app.add_handler(CommandHandler("mywatch", mywatch))

    app.add_handler(CommandHandler("alerts_on", alerts_on))
    app.add_handler(CommandHandler("alerts_off", alerts_off))
    app.add_handler(CommandHandler("setscore", setscore))
    app.add_handler(CommandHandler("setcooldown", setcooldown))

    # se você definiu ALERT_CHAT_ID no Railway, já ativa alertas pra ele (opcional)
    if ALERT_CHAT_ID_ENV.isdigit():
        cid = int(ALERT_CHAT_ID_ENV)
        alert_enabled[cid] = True
        watchlists.setdefault(cid, set())
        alert_min_score.setdefault(cid, 70)
        alert_cooldown_s.setdefault(cid, 240)
        logging.info(f"Alertas pré-ativados para chat {cid}")

    # Job a cada 60s (não abuse)
    app.job_queue.run_repeating(alert_job, interval=60, first=15)

    logging.info("✅ Bot iniciado (CoinGecko proxy + alertas)")
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
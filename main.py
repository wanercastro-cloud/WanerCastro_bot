import os
import math
import time
import logging
import asyncio
import requests

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

load_dotenv()
logging.basicConfig(level=logging.INFO)

TG_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
CG_KEY = (os.getenv("COINGECKO_API_KEY", "") or "").strip()

TELEGRAM_MAX = 4096

# ---------- CONFIG ----------
TOP_N = 10

# Top premium por volatilidade:
MIN_ABS_PCT_24H = 1.0     # >= 1% (ajuste)
MAX_ABS_PCT_24H = 50.0    # <= 50% (ajuste)

# Whale proxy (aceleração):
VOL_ACCEL_MIN = 1.30      # 1.30 = +30% vs snapshot anterior
MIN_POSITIVE_PCT_24H = 0.20  # precisa estar positivo (>= +0.20%)

STABLE_BASES = {
    "USDT", "USDC", "DAI", "TUSD", "FDUSD", "USD1", "BUSD", "USDP", "EURT", "PYUSD"
}

# Bybit
BYBIT_TICKERS_URL = "https://api.bybit.com/v5/market/tickers"

# CoinGecko
CG_BASE = "https://api.coingecko.com/api/v3"
CG_COINS_MARKETS = f"{CG_BASE}/coins/markets"

# Cache (texto)
CACHE_TTL_TOP = 60
_cache_top_text: str | None = None
_cache_top_ts: float = 0.0

# Snapshot de volume para detectar aceleração (por fonte)
# { "Bybit": { "BTCUSDT": vol, ... }, "CoinGecko": { ... } }
_prev_vol_snap: dict[str, dict[str, float]] = {}
_prev_vol_ts: dict[str, float] = {}


def safe_float(x, default=0.0) -> float:
    try:
        if x is None or x == "":
            return default
        return float(x)
    except Exception:
        return default


def _headers_default():
    return {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def _headers_cg():
    h = _headers_default()
    if CG_KEY:
        h["x-cg-demo-api-key"] = CG_KEY
        h["x-cg-pro-api-key"] = CG_KEY
    return h


async def http_get_json(url: str, params: dict | None = None, headers: dict | None = None, timeout: int = 12):
    def _req():
        r = requests.get(url, params=params, headers=headers or _headers_default(), timeout=timeout)
        status = r.status_code
        try:
            data = r.json()
        except Exception:
            data = None
        return status, data

    return await asyncio.to_thread(_req)


def is_volatile(pct_24h: float) -> bool:
    ap = abs(pct_24h)
    return ap >= MIN_ABS_PCT_24H and ap <= MAX_ABS_PCT_24H


# -------------------------
# BYBIT (fonte 1)
async def bybit_spot_tickers() -> tuple[int | None, list[dict]]:
    status, data = await http_get_json(BYBIT_TICKERS_URL, {"category": "spot"}, timeout=12)
    if status is None or not isinstance(data, dict):
        return status, []
    if status != 200 or data.get("retCode") != 0:
        return status, []
    lst = data.get("result", {}).get("list", [])
    return status, (lst if isinstance(lst, list) else [])


def bybit_row(t: dict) -> dict | None:
    try:
        sym = t.get("symbol", "")
        if not isinstance(sym, str) or not sym.endswith("USDT"):
            return None
        base = sym.replace("USDT", "")
        if base in STABLE_BASES:
            return None

        last = safe_float(t.get("lastPrice"))
        pct = safe_float(t.get("price24hPcnt")) * 100.0
        vol = safe_float(t.get("turnover24h"))

        if last <= 0 or vol <= 0:
            return None

        return {
            "symbol": sym,
            "last": last,
            "pct24h": pct,
            "vol24h": vol,
        }
    except Exception:
        return None


# -------------------------
# COINGECKO (fonte 2)
async def coingecko_markets_usd(per_page: int = 250, page: int = 1) -> tuple[int | None, list[dict]]:
    params = {
        "vs_currency": "usd",
        "order": "volume_desc",
        "per_page": per_page,
        "page": page,
        "sparkline": "false",
        "price_change_percentage": "24h",
    }
    status, data = await http_get_json(CG_COINS_MARKETS, params=params, headers=_headers_cg(), timeout=15)
    if status is None or not isinstance(data, list):
        return status, []
    return status, data


def cg_row(item: dict) -> dict | None:
    try:
        base = (item.get("symbol") or "").upper()
        if not base or base in STABLE_BASES:
            return None

        last = safe_float(item.get("current_price"))
        pct = safe_float(item.get("price_change_percentage_24h"))
        vol = safe_float(item.get("total_volume"))

        if last <= 0 or vol <= 0:
            return None

        return {
            "symbol": f"{base}USDT",
            "last": last,
            "pct24h": pct,
            "vol24h": vol,
        }
    except Exception:
        return None


# -------------------------
# Snapshot util
def _update_and_get_vol_accel(source: str, rows: list[dict]) -> dict[str, float]:
    """
    Retorna aceleração por símbolo: vol_now / vol_prev
    Atualiza snapshot anterior.
    """
    now = time.time()
    prev = _prev_vol_snap.get(source, {})
    accel: dict[str, float] = {}

    for r in rows:
        sym = r["symbol"]
        v_now = float(r["vol24h"])
        v_prev = float(prev.get(sym, 0.0))
        if v_prev > 0:
            accel[sym] = v_now / v_prev

    _prev_vol_snap[source] = {r["symbol"]: float(r["vol24h"]) for r in rows}
    _prev_vol_ts[source] = now
    return accel


# -------------------------
# Commands
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Bot ONLINE\n\n"
        "/topspot  -> Top Premium (volatilidade)\n"
        "/whale    -> Baleia entrando (proxy: aceleração de volume)\n\n"
        f"Filtros:\n"
        f"- abs(24h%) >= {MIN_ABS_PCT_24H:.1f}% e <= {MAX_ABS_PCT_24H:.1f}%\n"
        f"- Whale: aceleração >= {VOL_ACCEL_MIN:.2f} e 24h >= +{MIN_POSITIVE_PCT_24H:.2f}%\n"
        f"- Sem stablecoins"
    )


async def topspot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _cache_top_text, _cache_top_ts

    now = time.time()
    if _cache_top_text and (now - _cache_top_ts) < CACHE_TTL_TOP:
        await update.message.reply_text(_cache_top_text)
        return

    msg = await update.message.reply_text("⏳ Montando Top Premium (volatilidade)…")

    # 1) Bybit
    status, tickers = await bybit_spot_tickers()
    if tickers:
        rows = [bybit_row(t) for t in tickers]
        rows = [r for r in rows if r and is_volatile(r["pct24h"])]

        # rank por volume
        rows.sort(key=lambda r: r["vol24h"], reverse=True)
        top = rows[:TOP_N]

        lines = [
            f"{i:02d}. {r['symbol']} | {r['last']:.8g} | 24h {r['pct24h']:+.2f}% | vol {r['vol24h']:,.0f}"
            for i, r in enumerate(top, 1)
        ]
        text = "🏆 Top Premium (volatilidade) (Bybit)\n" + "\n".join(lines)
        if len(text) > TELEGRAM_MAX:
            text = text[:TELEGRAM_MAX - 50] + "\n..."

        _cache_top_text, _cache_top_ts = text, time.time()
        await msg.edit_text(text)
        return

    # 2) CoinGecko fallback (pega mais e filtra)
    cg_status, data = await coingecko_markets_usd(per_page=250, page=1)
    rows = [cg_row(x) for x in data]
    rows = [r for r in rows if r and is_volatile(r["pct24h"])]

    if rows:
        rows.sort(key=lambda r: r["vol24h"], reverse=True)
        top = rows[:TOP_N]
        lines = [
            f"{i:02d}. {r['symbol']} | {r['last']:.8g} | 24h {r['pct24h']:+.2f}% | vol {r['vol24h']:,.0f}"
            for i, r in enumerate(top, 1)
        ]
        text = "🏆 Top Premium (volatilidade) (fallback: CoinGecko)\n" + "\n".join(lines)
        if len(text) > TELEGRAM_MAX:
            text = text[:TELEGRAM_MAX - 50] + "\n..."
        _cache_top_text, _cache_top_ts = text, time.time()
        await msg.edit_text(text)
        return

    code = f"HTTP {status}" if status is not None else "sem conexão"
    await msg.edit_text(f"⚠️ Falhou em Bybit ({code}) e CoinGecko. Tente novamente.")


async def whale_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Baleia entrando (proxy): aceleração de volume vs snapshot anterior + 24h positivo.
    Precisa de 2 chamadas em momentos diferentes para ter aceleração.
    """
    msg = await update.message.reply_text("🐳 Escaneando entrada forte… (precisa de 2 snapshots)")

    # tenta Bybit primeiro
    status, tickers = await bybit_spot_tickers()
    if tickers:
        source = "Bybit"
        rows_all = [bybit_row(t) for t in tickers]
        rows_all = [r for r in rows_all if r]

        # atualiza e calcula aceleração
        accel = _update_and_get_vol_accel(source, rows_all)

        # filtra: volatilidade + 24h positivo + aceleração
        candidates = []
        for r in rows_all:
            pct = r["pct24h"]
            if not is_volatile(pct):
                continue
            if pct < MIN_POSITIVE_PCT_24H:
                continue
            a = accel.get(r["symbol"], 0.0)
            if a >= VOL_ACCEL_MIN:
                candidates.append((a, r))

        candidates.sort(key=lambda x: x[0], reverse=True)
        top = candidates[:TOP_N]

        if not top:
            ts = _prev_vol_ts.get(source, 0.0)
            if ts <= 0:
                await msg.edit_text("🐳 Primeira leitura feita. Rode /whale de novo em 2–5 min para medir aceleração.")
            else:
                await msg.edit_text("🐳 Sem sinal forte agora. Rode /whale novamente em alguns minutos.")
            return

        lines = []
        for i, (a, r) in enumerate(top, 1):
            lines.append(
                f"{i:02d}. {r['symbol']} | {r['last']:.8g} | 24h {r['pct24h']:+.2f}% | "
                f"vol {r['vol24h']:,.0f} | acel {a:.2f}x"
            )

        text = (
            "🐳 Baleia entrando forte (Bybit)\n"
            f"Regras: acel≥{VOL_ACCEL_MIN:.2f}x, 24h≥+{MIN_POSITIVE_PCT_24H:.2f}%, abs(24h%)≥{MIN_ABS_PCT_24H:.1f}%\n"
            + "\n".join(lines)
        )
        if len(text) > TELEGRAM_MAX:
            text = text[:TELEGRAM_MAX - 50] + "\n..."
        await msg.edit_text(text)
        return

    # fallback CoinGecko
    cg_status, data = await coingecko_markets_usd(per_page=250, page=1)
    source = "CoinGecko"
    rows_all = [cg_row(x) for x in data]
    rows_all = [r for r in rows_all if r]

    accel = _update_and_get_vol_accel(source, rows_all)

    candidates = []
    for r in rows_all:
        pct = r["pct24h"]
        if not is_volatile(pct):
            continue
        if pct < MIN_POSITIVE_PCT_24H:
            continue
        a = accel.get(r["symbol"], 0.0)
        if a >= VOL_ACCEL_MIN:
            candidates.append((a, r))

    candidates.sort(key=lambda x: x[0], reverse=True)
    top = candidates[:TOP_N]

    if not top:
        ts = _prev_vol_ts.get(source, 0.0)
        if ts <= 0:
            await msg.edit_text("🐳 Primeira leitura feita (CoinGecko). Rode /whale de novo em 2–5 min.")
        else:
            await msg.edit_text("🐳 Sem sinal forte agora (CoinGecko). Rode /whale novamente em alguns minutos.")
        return

    lines = []
    for i, (a, r) in enumerate(top, 1):
        lines.append(
            f"{i:02d}. {r['symbol']} | {r['last']:.8g} | 24h {r['pct24h']:+.2f}% | "
            f"vol {r['vol24h']:,.0f} | acel {a:.2f}x"
        )

    text = (
        "🐳 Baleia entrando forte (fallback: CoinGecko)\n"
        f"Regras: acel≥{VOL_ACCEL_MIN:.2f}x, 24h≥+{MIN_POSITIVE_PCT_24H:.2f}%, abs(24h%)≥{MIN_ABS_PCT_24H:.1f}%\n"
        + "\n".join(lines)
    )
    if len(text) > TELEGRAM_MAX:
        text = text[:TELEGRAM_MAX - 50] + "\n..."
    await msg.edit_text(text)


def main():
    if not TG_TOKEN:
        raise RuntimeError("TG_BOT_TOKEN não definido (.env)")

    app = ApplicationBuilder().token(TG_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("topspot", topspot_cmd))
    app.add_handler(CommandHandler("whale", whale_cmd))

    logging.info("✅ Bot iniciado")
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
import os
import asyncio
import math
import time
from typing import List, Dict, Any, Optional, Tuple

import httpx
from dotenv import load_dotenv

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()

# ======================
# CONFIG (CoinGecko Lite)
# ======================
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
if not TG_BOT_TOKEN:
    raise RuntimeError("❌ TG_BOT_TOKEN não definido.")

COINGECKO_BASE_URL = os.getenv("COINGECKO_BASE_URL", "https://api.coingecko.com/api/v3").rstrip("/")
VS = os.getenv("VS_CURRENCY", "usd").strip().lower()

TOP_N = int(os.getenv("TOP_N", "10"))
FETCH_N = int(os.getenv("FETCH_N", "200"))  # max 250

MIN_MCAP = float(os.getenv("MIN_MCAP", "2000000"))
MAX_MCAP = float(os.getenv("MAX_MCAP", "250000000"))
MIN_VOL24 = float(os.getenv("MIN_VOL24", "1000000"))

EXCLUDE_STABLES = os.getenv("EXCLUDE_STABLES", "1").strip() == "1"

HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "20"))
HTTP_RETRIES = int(os.getenv("HTTP_RETRIES", "2"))

CACHE_TTL_SEC = int(os.getenv("CACHE_TTL_SEC", "90"))
MIN_REQ_INTERVAL_SEC = float(os.getenv("MIN_REQ_INTERVAL_SEC", "0.45"))  # seguro pro Lite

STABLE_SYMBOLS = {
    "USDT", "USDC", "DAI", "TUSD", "USDE", "USDQ", "FDUSD", "PYUSD",
    "EUR", "GBP", "JPY", "TRY", "BRL"
}

# Avalia com market_chart só os top K por liquidez (evita 429)
EVAL_TOP_K = int(os.getenv("EVAL_TOP_K", "50"))
PROXY_CONCURRENCY = int(os.getenv("PROXY_CONCURRENCY", "3"))


# ======================
# UTILS
# ======================
def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def safe_float(x: Any) -> float:
    try:
        return float(x or 0.0)
    except Exception:
        return 0.0


def safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def fmt_money(x: float) -> str:
    if x >= 1e12:
        return f"${x/1e12:.2f}T"
    if x >= 1e9:
        return f"${x/1e9:.2f}B"
    if x >= 1e6:
        return f"${x/1e6:.2f}M"
    if x >= 1e3:
        return f"${x/1e3:.2f}K"
    return f"${x:.0f}"


def is_stable_like(symbol: str) -> bool:
    s = (symbol or "").upper().strip()
    return (s in STABLE_SYMBOLS) or s.endswith("USD") or s.endswith("USDT") or s.endswith("USDC")


class TTLCache:
    def __init__(self, ttl_sec: int):
        self.ttl = ttl_sec
        self._data: Dict[str, Tuple[float, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        it = self._data.get(key)
        if not it:
            return None
        ts, val = it
        if time.time() - ts > self.ttl:
            self._data.pop(key, None)
            return None
        return val

    def set(self, key: str, value: Any) -> None:
        self._data[key] = (time.time(), value)


class RateLimiter:
    def __init__(self, min_interval_sec: float):
        self.min_interval = max(0.0, min_interval_sec)
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.time()
            dt = now - self._last
            if dt < self.min_interval:
                await asyncio.sleep(self.min_interval - dt)
            self._last = time.time()


CACHE = TTLCache(CACHE_TTL_SEC)
RL = RateLimiter(MIN_REQ_INTERVAL_SEC)


async def http_get_json(client: httpx.AsyncClient, url: str, params: Dict[str, Any], cache_key: str) -> Any:
    cached = CACHE.get(cache_key)
    if cached is not None:
        return cached

    last_exc: Optional[Exception] = None
    for attempt in range(HTTP_RETRIES + 1):
        try:
            await RL.wait()
            r = await client.get(url, params=params)
            if r.status_code == 429:
                ra = r.headers.get("Retry-After")
                sleep_s = 1.0 + attempt * 1.2
                if ra and ra.isdigit():
                    sleep_s = min(20.0, float(ra))
                await asyncio.sleep(sleep_s)
                continue

            r.raise_for_status()
            data = r.json()
            CACHE.set(cache_key, data)
            return data
        except Exception as e:
            last_exc = e
            await asyncio.sleep(min(6.0, 0.8 * (attempt + 1)))

    raise last_exc or RuntimeError("Erro desconhecido no http_get_json")


# ======================
# COINGECKO (Lite)
# ======================
async def fetch_markets(client: httpx.AsyncClient) -> List[Dict[str, Any]]:
    url = f"{COINGECKO_BASE_URL}/coins/markets"
    params = {
        "vs_currency": VS,
        "order": "volume_desc",
        "per_page": min(max(FETCH_N, 50), 250),
        "page": 1,
        "sparkline": "false",
    }
    data = await http_get_json(client, url, params, cache_key=f"markets:{VS}:{params['per_page']}")
    return data if isinstance(data, list) else []


async def fetch_chart_1d_hourly(client: httpx.AsyncClient, coin_id: str) -> Dict[str, Any]:
    url = f"{COINGECKO_BASE_URL}/coins/{coin_id}/market_chart"
    params = {"vs_currency": VS, "days": "1", "interval": "hourly"}
    return await http_get_json(client, url, params, cache_key=f"chart1d:{VS}:{coin_id}")


# ======================
# PROXY 1h e 12h
# ======================
def proxy_1h_12h(prices: List[List[float]]) -> Tuple[float, float]:
    """
    prices: [[ts, price], ...] hourly
    1h = last vs -2
    12h = last vs -13
    """
    if not prices or len(prices) < 13:
        return 0.0, 0.0

    last = float(prices[-1][1] or 0.0)
    p1 = float(prices[-2][1] or 0.0)
    p12 = float(prices[-13][1] or 0.0)

    r1 = ((last - p1) / p1) * 100.0 if p1 > 0 else 0.0
    r12 = ((last - p12) / p12) * 100.0 if p12 > 0 else 0.0
    return r1, r12


# ======================
# SCORE MOMENTUM (1h + 12h)
# ======================
def compute_score(mcap: float, vol24: float, r1: float, r12: float) -> Tuple[float, str]:
    """
    Score científico (manual -> automatizado):
    - Momentum 1h + 12h
    - Aceleração: r1 vs (r12/12)
    - Confirmação: vol/mcap
    - Penalidade: overheat no 12h
    """
    vm = safe_div(vol24, mcap)
    vm_n = clamp(vm / 1.2, 0.0, 1.2)

    accel = r1 - (r12 / 12.0)
    accel_n = clamp(accel / 2.5, -1.0, 1.5)

    mom1 = clamp(r1 / 5.0, -1.0, 1.5)
    mom12 = clamp(r12 / 20.0, -1.0, 1.5)

    overheat = clamp((r12 - 35.0) / 25.0, 0.0, 1.0)

    raw = (
        40.0 * mom1 +
        25.0 * mom12 +
        20.0 * accel_n +
        15.0 * vm_n
        - 30.0 * overheat
    )
    score = clamp(raw, 0.0, 100.0)
    notes = f"accel={accel:.2f} vm={vm:.2f} overheat={overheat:.2f}"
    return score, notes


# ======================
# RANKING
# ======================
async def build_momentum_ranking(client: httpx.AsyncClient) -> List[Dict[str, Any]]:
    markets = await fetch_markets(client)

    # Universo
    base: List[Dict[str, Any]] = []
    for m in markets:
        sym = (m.get("symbol") or "").upper().strip()
        cid = (m.get("id") or "").strip()
        name = (m.get("name") or "").strip()

        if not sym or not cid:
            continue
        if EXCLUDE_STABLES and is_stable_like(sym):
            continue

        mcap = safe_float(m.get("market_cap"))
        vol24 = safe_float(m.get("total_volume"))
        price = safe_float(m.get("current_price"))
        chg24 = safe_float(m.get("price_change_percentage_24h"))

        if mcap < MIN_MCAP or mcap > MAX_MCAP:
            continue
        if vol24 < MIN_VOL24:
            continue
        if mcap <= 0 or price <= 0:
            continue

        base.append({
            "id": cid,
            "symbol": sym,
            "name": name,
            "price": price,
            "mcap": mcap,
            "vol24": vol24,
            "chg24": chg24,
        })

    if not base:
        return []

    # Avalia só os mais líquidos para reduzir 429
    base.sort(key=lambda x: x["vol24"], reverse=True)
    eval_list = base[:min(EVAL_TOP_K, len(base))]

    sem = asyncio.Semaphore(max(1, PROXY_CONCURRENCY))

    async def enrich(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        async with sem:
            try:
                chart = await fetch_chart_1d_hourly(client, item["id"])
                prices = (chart or {}).get("prices") or []
                r1, r12 = proxy_1h_12h(prices)
                score, notes = compute_score(item["mcap"], item["vol24"], r1, r12)
                item["r1"] = r1
                item["r12"] = r12
                item["score"] = score
                item["notes"] = notes
                return item
            except Exception:
                return None

    enriched = await asyncio.gather(*[enrich(x) for x in eval_list])
    ranked = [x for x in enriched if x and "score" in x]
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[:max(1, TOP_N)]


def format_message(items: List[Dict[str, Any]]) -> str:
    if not items:
        return (
            "⚠️ Sem candidatos no filtro atual.\n\n"
            "Tente:\n"
            "• diminuir MIN_MCAP / MIN_VOL24\n"
            "• aumentar MAX_MCAP\n"
            "• aumentar FETCH_N\n"
            "• aumentar EVAL_TOP_K (com cuidado)\n"
        )

    lines = [f"⚡ <b>MOMENTUM (1h + 12h)</b> (Top {len(items)}) | base={VS.upper()}"]
    for i, it in enumerate(items, 1):
        lines.append(
            f"\n<b>{i}) {it['symbol']}/{VS.upper()}</b> | <b>Score {it['score']:.1f}</b>\n"
            f"• Mcap: {fmt_money(it['mcap'])} | Vol24: {fmt_money(it['vol24'])}\n"
            f"• 1h: {it['r1']:+.2f}% | 12h: {it['r12']:+.2f}% | 24h: {it['chg24']:+.2f}%"
        )
    return "\n".join(lines)


# ======================
# TELEGRAM COMMANDS
# ======================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    txt = (
        "✅ Bot Momentum online.\n\n"
        "Comandos:\n"
        "/momentum  → ranking (1h + 12h)\n"
        "/ping\n\n"
        "Ajustes via ENV:\n"
        "TOP_N, FETCH_N, MIN_MCAP, MAX_MCAP, MIN_VOL24,\n"
        "EVAL_TOP_K, PROXY_CONCURRENCY, MIN_REQ_INTERVAL_SEC\n"
    )
    await update.message.reply_text(txt)


async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("pong ✅")


async def cmd_momentum(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔬 Rodando Momentum Científico (1h + 12h) via CoinGecko Lite...")

    client: httpx.AsyncClient = context.application.bot_data["http"]
    try:
        top = await build_momentum_ranking(client)
        msg = format_message(top)
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    except httpx.HTTPStatusError as e:
        await update.message.reply_text(
            f"⚠️ HTTP {e.response.status_code}\nURL: {str(e.request.url)}"
        )
    except Exception as e:
        await update.message.reply_text(f"⚠️ Erro: {type(e).__name__}: {e}")


# ======================
# APP LIFECYCLE
# ======================
async def on_startup(app: Application) -> None:
    app.bot_data["http"] = httpx.AsyncClient(timeout=httpx.Timeout(HTTP_TIMEOUT))


async def on_shutdown(app: Application) -> None:
    client: Optional[httpx.AsyncClient] = app.bot_data.get("http")
    if client:
        await client.aclose()


def main() -> None:
    application = (
        Application.builder()
        .token(TG_BOT_TOKEN)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("ping", cmd_ping))
    application.add_handler(CommandHandler("momentum", cmd_momentum))

    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
import os
import asyncio
import time
from typing import List, Dict, Any, Optional, Tuple

import httpx
from dotenv import load_dotenv

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()

# ======================
# ENV / CONFIG
# ======================
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
if not TG_BOT_TOKEN:
    raise RuntimeError("❌ TG_BOT_TOKEN não definido.")

COINGECKO_BASE_URL = os.getenv("COINGECKO_BASE_URL", "https://api.coingecko.com/api/v3").rstrip("/")
VS = os.getenv("VS_CURRENCY", "usd").strip().lower()

TOP_N = int(os.getenv("TOP_N", "10"))
FETCH_N = int(os.getenv("FETCH_N", "200"))  # max 250

# Filtros mínimos para evitar lixo
MIN_MCAP = float(os.getenv("MIN_MCAP", "1000000"))      # 1M
MIN_VOL24 = float(os.getenv("MIN_VOL24", "500000"))     # 500k

# Quantas moedas vão para a etapa pesada (market_chart)
EVAL_TOP_K = int(os.getenv("EVAL_TOP_K", "50"))         # 40-60 ideal no Lite
PROXY_CONCURRENCY = int(os.getenv("PROXY_CONCURRENCY", "3"))

# Rate limit / cache
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "20"))
HTTP_RETRIES = int(os.getenv("HTTP_RETRIES", "2"))
CACHE_TTL_SEC = int(os.getenv("CACHE_TTL_SEC", "90"))
MIN_REQ_INTERVAL_SEC = float(os.getenv("MIN_REQ_INTERVAL_SEC", "0.45"))

# Períodos (em horas) que queremos calcular
# “todos os períodos disponíveis” (via hourly points de 1 dia)
PERIOD_HOURS = [1, 2, 3, 4, 6, 8, 12, 18, 24]


# ======================
# UTILS
# ======================
def safe_float(x: Any) -> float:
    try:
        return float(x or 0.0)
    except Exception:
        return 0.0

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
# STATISTICS: multi-período (horas)
# ======================
def pct_change(last: float, base: float) -> float:
    return ((last - base) / base) * 100.0 if base else 0.0

def compute_period_returns_from_hourly(prices: List[List[float]], periods_h: List[int]) -> Dict[int, float]:
    """
    prices: [[ts, price], ...] hourly
    Retorna dict {hours: percent_return}
    Observação: precisa de pelo menos (hours + 1) pontos.
    """
    out: Dict[int, float] = {}
    if not prices or len(prices) < 2:
        return out

    last = float(prices[-1][1] or 0.0)

    for h in periods_h:
        idx = -(h + 1)
        if len(prices) >= (h + 1):
            base = float(prices[idx][1] or 0.0)
            out[h] = pct_change(last, base)
        else:
            # se não tiver dados suficientes, simplesmente não inclui
            continue

    return out


# ======================
# CORE: RANK VOL > MCAP
# ======================
async def build_rank_vol_gt_mcap(client: httpx.AsyncClient) -> List[Dict[str, Any]]:
    markets = await fetch_markets(client)

    # 1) Pré-filtro e condição VOL > MCAP
    candidates: List[Dict[str, Any]] = []
    for m in markets:
        cid = (m.get("id") or "").strip()
        sym = (m.get("symbol") or "").upper().strip()
        name = (m.get("name") or "").strip()

        mcap = safe_float(m.get("market_cap"))
        vol = safe_float(m.get("total_volume"))
        price = safe_float(m.get("current_price"))
        chg24 = safe_float(m.get("price_change_percentage_24h"))

        if not cid or not sym:
            continue
        if mcap < MIN_MCAP or vol < MIN_VOL24:
            continue
        if mcap <= 0:
            continue

        ratio = vol / mcap

        # condição pedida: Volume > Mcap
        if ratio <= 1.0:
            continue

        candidates.append({
            "id": cid,
            "symbol": sym,
            "name": name,
            "price": price,
            "mcap": mcap,
            "vol24": vol,
            "ratio": ratio,
            "chg24": chg24,
        })

    if not candidates:
        return []

    # 2) Ordena por ratio e pega os top K pra calcular estatísticas multi-período
    candidates.sort(key=lambda x: x["ratio"], reverse=True)
    eval_list = candidates[:min(EVAL_TOP_K, len(candidates))]

    sem = asyncio.Semaphore(max(1, PROXY_CONCURRENCY))

    async def enrich(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        async with sem:
            try:
                chart = await fetch_chart_1d_hourly(client, item["id"])
                prices = (chart or {}).get("prices") or []
                returns = compute_period_returns_from_hourly(prices, PERIOD_HOURS)
                item["returns"] = returns  # {1:...,2:..., ...}
                return item
            except Exception:
                return None

    enriched = await asyncio.gather(*[enrich(x) for x in eval_list])
    ready = [x for x in enriched if x and x.get("returns")]

    # Mantém ordenação por ratio (ranking principal)
    ready.sort(key=lambda x: x["ratio"], reverse=True)
    return ready[:max(1, TOP_N)]


def format_rank(items: List[Dict[str, Any]]) -> str:
    if not items:
        return (
            "⚠️ Nenhuma moeda encontrada com <b>Vol24 &gt; Mcap</b> nos filtros atuais.\n\n"
            "Ajuste ENV:\n"
            "• MIN_MCAP / MIN_VOL24\n"
            "• FETCH_N\n"
        )

    lines = [f"🔥 <b>RANK VOL24 &gt; MCAP</b> (Top {len(items)}) | base={VS.upper()}"]
    lines.append(f"<i>Stats por horas (via market_chart hourly): {', '.join(str(h) for h in PERIOD_HOURS)}h</i>")

    for i, it in enumerate(items, 1):
        ret = it.get("returns", {})
        # monta linha compacta de retornos
        stats_parts = []
        for h in PERIOD_HOURS:
            if h in ret:
                stats_parts.append(f"{h}h {ret[h]:+,.2f}%".replace(",", "X").replace(".", ",").replace("X", "."))
        stats = " | ".join(stats_parts) if stats_parts else "sem stats"

        lines.append(
            f"\n<b>{i}) {it['symbol']}/{VS.upper()}</b>  <code>Vol/Mcap={it['ratio']:.2f}</code>\n"
            f"• Mcap: {fmt_money(it['mcap'])} | Vol24: {fmt_money(it['vol24'])}\n"
            f"• 24h(Cg): {it['chg24']:+.2f}% | <b>Stats:</b> {stats}"
        )

    return "\n".join(lines)


# ======================
# TELEGRAM COMMANDS
# ======================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "✅ Bot online.\n\n"
        "Comandos:\n"
        "/rank  → ranking Vol24 > Mcap + estatísticas multi-período (1–24h)\n"
        "/ping\n"
    )

async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("pong ✅")

async def cmd_rank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔎 Rankeando Vol24 > Mcap e calculando estatísticas (1–24h)...")
    client: httpx.AsyncClient = context.application.bot_data["http"]
    try:
        items = await build_rank_vol_gt_mcap(client)
        await update.message.reply_text(format_rank(items), parse_mode=ParseMode.HTML)
    except httpx.HTTPStatusError as e:
        await update.message.reply_text(f"⚠️ HTTP {e.response.status_code}\nURL: {str(e.request.url)}")
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
    application.add_handler(CommandHandler("rank", cmd_rank))

    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
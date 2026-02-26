import os
import re
import math
import time
import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

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

# CoinGecko Pro base
COINGECKO_BASE_URL = os.getenv("COINGECKO_BASE_URL", "https://pro-api.coingecko.com/api/v3").rstrip("/")

# Sua chave Pro (Lite/Top Premium)
COINGECKO_API_KEY = (
    os.getenv("COINGECKO_API_KEY", "").strip()
    or os.getenv("COINGECKO_PRO_API_KEY", "").strip()
    or os.getenv("COINGECKO_KEY", "").strip()
)

# GeckoTerminal (opcional, para boost com DEX)
GECKOTERMINAL_BASE_URL = os.getenv("GECKOTERMINAL_BASE_URL", "https://api.geckoterminal.com/api/v2").rstrip("/")
USE_DEX_SIGNAL = os.getenv("USE_DEX_SIGNAL", "1").strip() == "1"

# Radar params
TOP_N = int(os.getenv("TOP_N", "5"))
CANDIDATES = int(os.getenv("CANDIDATES", "120"))  # quantos ativos avaliar antes do ranking final
VS_CURRENCY = os.getenv("VS_CURRENCY", "usd").strip().lower()

# Filtros base (ajuste livre)
MIN_MCAP = float(os.getenv("MIN_MCAP", "2000000"))       # 2M
MAX_MCAP = float(os.getenv("MAX_MCAP", "250000000"))     # 250M
MIN_VOL24 = float(os.getenv("MIN_VOL24", "1500000"))     # 1.5M
EXCLUDE_STABLES = os.getenv("EXCLUDE_STABLES", "1").strip() == "1"

HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "20"))
HTTP_RETRIES = int(os.getenv("HTTP_RETRIES", "2"))

# Priorização do checklist (quantos retorna)
PICK_N = int(os.getenv("PICK_N", "3"))

if not TG_BOT_TOKEN:
    raise RuntimeError("❌ Variável TG_BOT_TOKEN não definida.")

# Stables para cortar ruído
STABLE_SYMBOLS = {
    "USDT", "USDC", "DAI", "TUSD", "USDE", "USDQ", "FDUSD", "PYUSD",
    "EUR", "GBP", "JPY", "TRY", "BRL"
}

SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,15}$")


# =========================
# HELPERS
# =========================
def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def now_ts() -> float:
    return time.time()


def fmt_money(x: float) -> str:
    if x >= 1e9:
        return f"${x/1e9:.2f}B"
    if x >= 1e6:
        return f"${x/1e6:.2f}M"
    if x >= 1e3:
        return f"${x/1e3:.2f}K"
    return f"${x:.0f}"


def is_stable_like(symbol: str) -> bool:
    if not symbol:
        return False
    s = symbol.upper().strip()
    # evita stable e “quase stable”
    return (s in STABLE_SYMBOLS) or s.endswith("USD") or s.endswith("USDT") or s.endswith("USDC")


@dataclass
class CandidateScore:
    symbol: str
    name: str
    cg_id: str
    price: float
    mcap: float
    vol24: float
    chg_1h: float
    chg_24h: float
    score: float
    support_1h: Optional[float] = None
    notes: str = ""


class TTLCache:
    def __init__(self, ttl_sec: int = 60):
        self.ttl = ttl_sec
        self._data: Dict[str, Tuple[float, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        item = self._data.get(key)
        if not item:
            return None
        ts, value = item
        if now_ts() - ts > self.ttl:
            self._data.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._data[key] = (now_ts(), value)


CACHE = TTLCache(ttl_sec=90)


def cg_headers() -> Dict[str, str]:
    """
    CoinGecko Pro: header oficial é 'x-cg-pro-api-key'.
    """
    headers = {"accept": "application/json"}
    if COINGECKO_API_KEY:
        headers["x-cg-pro-api-key"] = COINGECKO_API_KEY
    return headers


async def http_get_json(client: httpx.AsyncClient, url: str, params: Dict[str, Any]) -> Any:
    last_exc: Optional[Exception] = None
    for _ in range(HTTP_RETRIES + 1):
        try:
            r = await client.get(url, params=params)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_exc = e
            await asyncio.sleep(0.35)
    raise last_exc or RuntimeError("Erro desconhecido no http_get_json")


# =========================
# COINGECKO (Pro)
# =========================
async def cg_markets(client: httpx.AsyncClient, per_page: int) -> List[Dict[str, Any]]:
    """
    /coins/markets: preço, market cap, volume, variações 1h/24h (1 chamada).
    """
    per_page = int(clamp(per_page, 50, 250))
    cache_key = f"cg_markets:{VS_CURRENCY}:{per_page}"
    cached = CACHE.get(cache_key)
    if cached is not None:
        return cached

    url = f"{COINGECKO_BASE_URL}/coins/markets"
    params = {
        "vs_currency": VS_CURRENCY,
        "order": "volume_desc",
        "per_page": per_page,
        "page": 1,
        "sparkline": "false",
        "price_change_percentage": "1h,24h",
    }
    data = await http_get_json(client, url, params)
    if not isinstance(data, list):
        data = []
    CACHE.set(cache_key, data)
    return data


async def cg_coin_by_id(client: httpx.AsyncClient, cg_id: str) -> Dict[str, Any]:
    """
    /coins/{id}: traz community/dev data e market_data enriquecido.
    """
    cache_key = f"cg_coin:{cg_id}"
    cached = CACHE.get(cache_key)
    if cached is not None:
        return cached

    url = f"{COINGECKO_BASE_URL}/coins/{cg_id}"
    params = {
        "localization": "false",
        "tickers": "false",
        "market_data": "true",
        "community_data": "true",
        "developer_data": "true",
        "sparkline": "false",
    }
    data = await http_get_json(client, url, params)
    if not isinstance(data, dict):
        data = {}
    CACHE.set(cache_key, data)
    return data


async def cg_market_chart_hourly(client: httpx.AsyncClient, cg_id: str, days: int = 2) -> Dict[str, Any]:
    """
    /coins/{id}/market_chart: usa histórico para estimar suporte 1H.
    """
    cache_key = f"cg_chart:{cg_id}:{days}"
    cached = CACHE.get(cache_key)
    if cached is not None:
        return cached

    url = f"{COINGECKO_BASE_URL}/coins/{cg_id}/market_chart"
    params = {"vs_currency": VS_CURRENCY, "days": str(days), "interval": "hourly"}
    data = await http_get_json(client, url, params)
    if not isinstance(data, dict):
        data = {}
    CACHE.set(cache_key, data)
    return data


# =========================
# DEX SIGNAL (GeckoTerminal) - opcional
# =========================
async def dex_trending_signal(client: httpx.AsyncClient) -> Dict[str, float]:
    """
    Trending Pools by Network (boost por símbolo).
    """
    if not USE_DEX_SIGNAL:
        return {}

    cache_key = "dex_trending_boost"
    cached = CACHE.get(cache_key)
    if cached is not None:
        return cached

    url = f"{GECKOTERMINAL_BASE_URL}/networks/trending_pools"
    params = {"page": 1}
    try:
        data = await http_get_json(client, url, params)
    except Exception:
        return {}

    boost: Dict[str, float] = {}
    items = (data or {}).get("data", [])
    for it in items[:30]:
        attrs = (it or {}).get("attributes", {}) or {}
        base_token = attrs.get("base_token") or {}
        symbol = (base_token.get("symbol") or "").upper().strip()
        if not symbol:
            continue

        price_change_24h = float((attrs.get("price_change_percentage", {}) or {}).get("h24", 0.0) or 0.0)
        volume_24h = float((attrs.get("volume_usd", {}) or {}).get("h24", 0.0) or 0.0)
        liquidity = float(attrs.get("reserve_in_usd", 0.0) or 0.0)

        b = (
            clamp(math.log10(max(volume_24h, 1.0)) / 6.0, 0.0, 1.2) +
            clamp(math.log10(max(liquidity, 1.0)) / 7.0, 0.0, 1.0) +
            clamp(price_change_24h / 25.0, -0.3, 0.8)
        )
        boost[symbol] = max(boost.get(symbol, 0.0), b)

    CACHE.set(cache_key, boost)
    return boost


# =========================
# SUPORTE 1H (estimado via CoinGecko)
# =========================
def estimate_support_from_hourly(prices: List[List[float]]) -> Optional[float]:
    """
    prices: [[timestamp_ms, price], ...]
    Estratégia simples: “swing low” nas últimas ~24h, ignorando o último ponto.
    """
    if not prices or len(prices) < 10:
        return None

    # pega últimas 30 velas (~30h) e ignora a última (pode estar “aberta”)
    tail = prices[-31:-1] if len(prices) >= 31 else prices[:-1]
    vals = [float(p[1]) for p in tail if isinstance(p, list) and len(p) >= 2]

    if len(vals) < 8:
        return None

    # suporte = mínimo das últimas 24h (ou o que tiver)
    window = vals[-24:] if len(vals) >= 24 else vals
    sup = min(window)
    return float(sup)


# =========================
# SCORING (Pré-Pump + Priorizar Checklist)
# =========================
def compute_score_base(mcap: float, vol24: float, chg_1h: float, chg_24h: float, dex_boost: float = 0.0) -> Tuple[float, str]:
    """
    Base (igual a sua lógica) = vol/mcap + aceleração + momentum + ajuste DEX.
    """
    vm = safe_div(vol24, mcap)
    vm_n = clamp(vm / 1.2, 0.0, 1.2)

    accel = (chg_1h - (chg_24h / 24.0))
    accel_n = clamp(accel / 2.5, -0.6, 1.2)

    mom1 = clamp(chg_1h / 6.0, -0.8, 1.3)
    mom24 = clamp(chg_24h / 18.0, -0.8, 1.3)

    overheat_penalty = clamp((chg_24h - 35.0) / 30.0, 0.0, 1.0)

    raw = (
        45.0 * vm_n +
        20.0 * accel_n +
        20.0 * mom1 +
        15.0 * mom24 +
        10.0 * dex_boost
    )
    score = clamp(raw - 18.0 * overheat_penalty, 0.0, 100.0)

    notes = f"vm={vm:.2f} accel={accel:.2f} dex={dex_boost:.2f} overheat={overheat_penalty:.2f}"
    return score, notes


def compute_premium_boost(coin_by_id: Dict[str, Any]) -> Tuple[float, str]:
    """
    “Premium boost” usando community_data + developer_data (sem inventar indicador mágico).
    Ideia: projeto com tração social/dev tende a sustentar narrativa/fluxo.
    """
    community = coin_by_id.get("community_data") or {}
    dev = coin_by_id.get("developer_data") or {}

    twitter = float(community.get("twitter_followers") or 0.0)
    reddit = float(community.get("reddit_subscribers") or 0.0)
    stars = float(dev.get("stars") or 0.0)
    commits_4w = float(dev.get("commit_count_4_weeks") or 0.0)

    # normalizações log para não virar “ranking de gigantes”
    tw_n = clamp(math.log10(max(twitter, 1.0)) / 6.0, 0.0, 1.0)   # 10^6 seguidores ~ 1.0
    rd_n = clamp(math.log10(max(reddit, 1.0)) / 6.0, 0.0, 1.0)
    st_n = clamp(math.log10(max(stars, 1.0)) / 5.0, 0.0, 1.0)
    cm_n = clamp(math.log10(max(commits_4w, 1.0)) / 3.0, 0.0, 1.0)

    boost = 12.0 * (0.40 * tw_n + 0.20 * rd_n + 0.25 * st_n + 0.15 * cm_n)
    note = f"prem(tw={twitter:.0f}, rd={reddit:.0f}, stars={stars:.0f}, c4w={commits_4w:.0f})"
    return boost, note


async def build_ranking_global(client: httpx.AsyncClient, top_n: int) -> List[CandidateScore]:
    """
    /smartmoney: avalia o universo (top volume), ranqueia e retorna top N.
    """
    markets = await cg_markets(client, per_page=min(max(CANDIDATES, 50), 250))
    dex_boost_map = await dex_trending_signal(client)

    out: List[CandidateScore] = []

    for c in markets:
        try:
            symbol = (c.get("symbol") or "").upper().strip()
            name = (c.get("name") or "").strip()
            cg_id = (c.get("id") or "").strip()

            price = float(c.get("current_price") or 0.0)
            mcap = float(c.get("market_cap") or 0.0)
            vol24 = float(c.get("total_volume") or 0.0)

            chg_1h = float((c.get("price_change_percentage_1h_in_currency") or 0.0) or 0.0)
            chg_24h = float((c.get("price_change_percentage_24h_in_currency") or 0.0) or 0.0)

            if not symbol or not cg_id:
                continue
            if EXCLUDE_STABLES and is_stable_like(symbol):
                continue
            if mcap < MIN_MCAP or mcap > MAX_MCAP:
                continue
            if vol24 < MIN_VOL24:
                continue

            dex_boost = float(dex_boost_map.get(symbol, 0.0))
            score, notes = compute_score_base(mcap, vol24, chg_1h, chg_24h, dex_boost=dex_boost)

            out.append(CandidateScore(
                symbol=symbol, name=name, cg_id=cg_id,
                price=price, mcap=mcap, vol24=vol24,
                chg_1h=chg_1h, chg_24h=chg_24h,
                score=score, notes=notes
            ))
        except Exception:
            continue

    out.sort(key=lambda x: x.score, reverse=True)
    return out[:max(1, top_n)]


async def resolve_symbols_to_market_rows(client: httpx.AsyncClient, symbols: List[str]) -> List[Dict[str, Any]]:
    """
    Resolve symbols (SONIC, TNSR, ZK...) para linhas do /coins/markets
    (usando universo top por volume para reduzir ambiguidades).
    """
    symbols_norm = [s.upper().strip() for s in symbols if s and SYMBOL_RE.match(s.upper().strip())]
    if not symbols_norm:
        return []

    markets = await cg_markets(client, per_page=250)
    best_by_symbol: Dict[str, Dict[str, Any]] = {}

    for row in markets:
        sym = (row.get("symbol") or "").upper().strip()
        if sym not in symbols_norm:
            continue
        # se duplicado, pega o maior market cap
        mcap = float(row.get("market_cap") or 0.0)
        prev = best_by_symbol.get(sym)
        if not prev or mcap > float(prev.get("market_cap") or 0.0):
            best_by_symbol[sym] = row

    return [best_by_symbol[s] for s in symbols_norm if s in best_by_symbol]


async def prioritize_checklist(client: httpx.AsyncClient, symbols: List[str]) -> List[CandidateScore]:
    """
    /priorizar: cruza checklist (lista Bybit) com CoinGecko Premium para ranquear automaticamente.
    """
    rows = await resolve_symbols_to_market_rows(client, symbols)
    if not rows:
        return []

    dex_boost_map = await dex_trending_signal(client)
    out: List[CandidateScore] = []

    for c in rows:
        symbol = (c.get("symbol") or "").upper().strip()
        cg_id = (c.get("id") or "").strip()
        name = (c.get("name") or "").strip()

        price = float(c.get("current_price") or 0.0)
        mcap = float(c.get("market_cap") or 0.0)
        vol24 = float(c.get("total_volume") or 0.0)
        chg_1h = float((c.get("price_change_percentage_1h_in_currency") or 0.0) or 0.0)
        chg_24h = float((c.get("price_change_percentage_24h_in_currency") or 0.0) or 0.0)

        dex_boost = float(dex_boost_map.get(symbol, 0.0))

        base_score, base_notes = compute_score_base(mcap, vol24, chg_1h, chg_24h, dex_boost=dex_boost)

        # Premium enrichment
        premium_boost = 0.0
        premium_note = ""
        support_1h = None

        try:
            coin = await cg_coin_by_id(client, cg_id)
            premium_boost, premium_note = compute_premium_boost(coin)
        except Exception:
            premium_boost, premium_note = 0.0, "prem(unavailable)"

        try:
            chart = await cg_market_chart_hourly(client, cg_id, days=2)
            prices = chart.get("prices") or []
            support_1h = estimate_support_from_hourly(prices)
        except Exception:
            support_1h = None

        # score final de priorização (base + premium)
        final_score = clamp(base_score + premium_boost, 0.0, 100.0)
        notes = f"{base_notes} | {premium_note}"

        out.append(CandidateScore(
            symbol=symbol, name=name, cg_id=cg_id,
            price=price, mcap=mcap, vol24=vol24,
            chg_1h=chg_1h, chg_24h=chg_24h,
            score=final_score, support_1h=support_1h,
            notes=notes
        ))

    out.sort(key=lambda x: x.score, reverse=True)
    return out[:max(1, PICK_N)]


def format_smartmoney_message(items: List[CandidateScore]) -> str:
    if not items:
        return "⚠️ Sem candidatos no filtro atual (ajuste MIN_MCAP / MAX_MCAP / MIN_VOL24)."

    lines = [f"🔥 <b>SMART MONEY PRÉ-PUMP</b> (Top {len(items)})"]
    for i, it in enumerate(items, 1):
        lines.append(
            f"\n<b>{i}) {it.symbol}/{VS_CURRENCY.upper()}</b> | <b>Score {it.score:.1f}</b>\n"
            f"• Mcap: {fmt_money(it.mcap)} | Vol24: {fmt_money(it.vol24)}\n"
            f"• 1h: {it.chg_1h:+.2f}% | 24h: {it.chg_24h:+.2f}%"
        )
    return "\n".join(lines)


def format_prioritize_message(items: List[CandidateScore]) -> str:
    if not items:
        return "⚠️ Não consegui resolver esses símbolos no CoinGecko (tente sem /USDT, só o ticker)."

    lines = ["🎯 <b>PRIORIDADE (Checklist + CoinGecko Premium)</b>"]
    for i, it in enumerate(items, 1):
        sup = f"{it.support_1h:.6f}" if isinstance(it.support_1h, float) else "n/d"
        lines.append(
            f"\n<b>{i}) {it.symbol}</b> | <b>Score {it.score:.1f}</b>\n"
            f"• Preço: {it.price:.6f} | Suporte 1H (est.): <b>{sup}</b>\n"
            f"• Mcap: {fmt_money(it.mcap)} | Vol24: {fmt_money(it.vol24)}\n"
            f"• 1h: {it.chg_1h:+.2f}% | 24h: {it.chg_24h:+.2f}%\n"
            f"• Anotar na Bybit: NetFlow ___ | Large In ___ | Large Out ___"
        )
    return "\n".join(lines)


# =========================
# TELEGRAM HANDLERS
# =========================
async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("pong ✅")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    txt = (
        "✅ Bot online.\n\n"
        "Comandos:\n"
        "/ping\n"
        "/smartmoney [N]  → Top pré-pump (CoinGecko Pro)\n"
        "/radar [N]       → alias do /smartmoney\n"
        "/priorizar <tickers...> → cruza checklist Bybit com CoinGecko Premium\n\n"
        "Ex:\n"
        "/priorizar SONIC TNSR ZK\n"
    )
    await update.message.reply_text(txt)


async def cmd_smartmoney(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    n = TOP_N
    if context.args:
        try:
            n = int(context.args[0])
        except Exception:
            n = TOP_N
    n = int(clamp(n, 1, 15))

    await update.message.reply_text("🔎 Rodando scanner CoinGecko (pré-pump)...")

    client: httpx.AsyncClient = context.application.bot_data["http"]

    try:
        top = await build_ranking_global(client, top_n=n)
        msg = format_smartmoney_message(top)
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    except httpx.HTTPStatusError as e:
        await update.message.reply_text(
            f"⚠️ Erro CoinGecko: {e.response.status_code} {e.response.reason_phrase}\nURL: {str(e.request.url)}"
        )
    except Exception as e:
        await update.message.reply_text(f"⚠️ Erro no scanner: {type(e).__name__}: {e}")


async def cmd_radar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_smartmoney(update, context)


async def cmd_priorizar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Use: /priorizar SONIC TNSR ZK")
        return

    symbols = []
    for a in context.args:
        a = a.upper().replace("/USDT", "").replace("/USD", "").strip()
        if a and SYMBOL_RE.match(a):
            symbols.append(a)

    if not symbols:
        await update.message.reply_text("⚠️ Não entendi os tickers. Ex: /priorizar SONIC TNSR ZK")
        return

    await update.message.reply_text("🧠 Cruzando checklist com CoinGecko Premium...")

    client: httpx.AsyncClient = context.application.bot_data["http"]

    try:
        picks = await prioritize_checklist(client, symbols)
        msg = format_prioritize_message(picks)
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    except httpx.HTTPStatusError as e:
        await update.message.reply_text(
            f"⚠️ Erro CoinGecko: {e.response.status_code} {e.response.reason_phrase}\nURL: {str(e.request.url)}"
        )
    except Exception as e:
        await update.message.reply_text(f"⚠️ Erro no /priorizar: {type(e).__name__}: {e}")


# =========================
# APP LIFECYCLE
# =========================
async def on_startup(app: Application) -> None:
    app.bot_data["http"] = httpx.AsyncClient(
        timeout=httpx.Timeout(HTTP_TIMEOUT),
        headers=cg_headers(),
    )


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
    application.add_handler(CommandHandler("smartmoney", cmd_smartmoney))
    application.add_handler(CommandHandler("radar", cmd_radar))
    application.add_handler(CommandHandler("priorizar", cmd_priorizar))

    # Evita “lixo” de updates antigos.
    # Nota: "Conflict" no Telegram acontece se você tiver 2 instâncias do bot rodando polling ao mesmo tempo.
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
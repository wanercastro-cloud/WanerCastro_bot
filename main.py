import os
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

# GeckoTerminal (opcional, para "híbrido" com on-chain)
GECKOTERMINAL_BASE_URL = os.getenv("GECKOTERMINAL_BASE_URL", "https://api.geckoterminal.com/api/v2").rstrip("/")
USE_DEX_SIGNAL = os.getenv("USE_DEX_SIGNAL", "1").strip() == "1"

# Radar params
TOP_N = int(os.getenv("TOP_N", "5"))
CANDIDATES = int(os.getenv("CANDIDATES", "120"))  # quantos ativos avaliar antes do ranking final
VS_CURRENCY = os.getenv("VS_CURRENCY", "usd").strip().lower()

# Filtros (ajuste se quiser)
MIN_MCAP = float(os.getenv("MIN_MCAP", "2000000"))       # 2M
MAX_MCAP = float(os.getenv("MAX_MCAP", "250000000"))     # 250M (micro/low caps)
MIN_VOL24 = float(os.getenv("MIN_VOL24", "1500000"))     # 1.5M
EXCLUDE_STABLES = os.getenv("EXCLUDE_STABLES", "1").strip() == "1"

HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "20"))
HTTP_RETRIES = int(os.getenv("HTTP_RETRIES", "2"))

if not TG_BOT_TOKEN:
    raise RuntimeError("❌ Variável TG_BOT_TOKEN não definida.")

# Stables para cortar ruído
STABLE_SYMBOLS = {
    "USDT", "USDC", "DAI", "TUSD", "USDE", "USDQ", "FDUSD", "PYUSD",
    "EUR", "GBP", "JPY", "TRY", "BRL"
}


# =========================
# HELPERS
# =========================
def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def now_ts() -> float:
    return time.time()


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
    notes: str = ""


class TTLCache:
    def __init__(self, ttl_sec: int = 45):
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


CACHE = TTLCache(ttl_sec=60)


def cg_headers() -> Dict[str, str]:
    """
    CoinGecko Pro: usar 'x-cg-pro-api-key'.
    (Se sua chave for vazia, tenta sem header, mas endpoints premium vão falhar.)
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
            await asyncio.sleep(0.4)
    raise last_exc or RuntimeError("Erro desconhecido no http_get_json")


# =========================
# COINGECKO DATA (Pro)
# =========================
async def cg_markets(client: httpx.AsyncClient) -> List[Dict[str, Any]]:
    """
    Usa /coins/markets com campos de variação 1h/24h e volume.
    """
    cache_key = f"cg_markets:{VS_CURRENCY}:{CANDIDATES}"
    cached = CACHE.get(cache_key)
    if cached is not None:
        return cached

    url = f"{COINGECKO_BASE_URL}/coins/markets"
    params = {
        "vs_currency": VS_CURRENCY,
        "order": "volume_desc",
        "per_page": min(max(CANDIDATES, 50), 250),
        "page": 1,
        "sparkline": "false",
        "price_change_percentage": "1h,24h",
        # dá pra adicionar "category" se quiser nichar (ai, gaming, etc)
    }
    data = await http_get_json(client, url, params)
    if not isinstance(data, list):
        data = []
    CACHE.set(cache_key, data)
    return data


async def cg_top_gainers_losers(client: httpx.AsyncClient) -> Optional[Dict[str, Any]]:
    """
    Endpoint premium citado por você (top_gainers_losers).
    Se seu plano não liberar, retorna None sem derrubar o bot.
    """
    cache_key = f"cg_tgl:{VS_CURRENCY}"
    cached = CACHE.get(cache_key)
    if cached is not None:
        return cached

    url = f"{COINGECKO_BASE_URL}/coins/top_gainers_losers"
    params = {"vs_currency": VS_CURRENCY, "duration": "24h"}
    try:
        data = await http_get_json(client, url, params)
        CACHE.set(cache_key, data)
        return data
    except Exception:
        return None


# =========================
# DEX SIGNAL (GeckoTerminal) - opcional
# =========================
async def dex_trending_signal(client: httpx.AsyncClient) -> Dict[str, float]:
    """
    Pega pools trending e gera um "boost" por símbolo (heurístico).
    Retorna dict: {SYMBOL: boost_score}
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
    for it in items[:25]:
        attrs = (it or {}).get("attributes", {}) or {}
        base_token = (attrs.get("base_token") or {}) if isinstance(attrs.get("base_token"), dict) else {}
        symbol = (base_token.get("symbol") or "").upper().strip()
        if not symbol:
            continue

        # heurística simples: usa variação 24h e liquidez/volume do pool
        price_change_24h = float(attrs.get("price_change_percentage", {}).get("h24", 0.0) or 0.0)
        volume_24h = float(attrs.get("volume_usd", {}).get("h24", 0.0) or 0.0)
        liquidity = float(attrs.get("reserve_in_usd", 0.0) or 0.0)

        # boost cresce com volume e liquidez (log), e com momentum
        b = (
            clamp(math.log10(max(volume_24h, 1.0)) / 6.0, 0.0, 1.2) +
            clamp(math.log10(max(liquidity, 1.0)) / 7.0, 0.0, 1.0) +
            clamp(price_change_24h / 25.0, -0.3, 0.8)
        )
        boost[symbol] = max(boost.get(symbol, 0.0), b)

    CACHE.set(cache_key, boost)
    return boost


# =========================
# SCORING (Smart Money Pré-Pump)
# =========================
def is_stable_like(symbol: str) -> bool:
    if not symbol:
        return False
    s = symbol.upper().strip()
    return s in STABLE_SYMBOLS or s.endswith("USD") or s.endswith("USDT") or s.endswith("USDC")


def compute_score(
    mcap: float,
    vol24: float,
    chg_1h: float,
    chg_24h: float,
    dex_boost: float = 0.0
) -> Tuple[float, str]:
    """
    Score = Liquidez/atenção (vol/mcap) + aceleração (1h vs 24h) + momentum + ajuste DEX.
    """
    # 1) "Smart money attention": volume relativo à mcap
    vm = safe_div(vol24, mcap)  # ex: 0.5 = vol = 50% da mcap
    vm_n = clamp(vm / 1.2, 0.0, 1.2)  # normaliza

    # 2) aceleração: 1h positivo e 24h ainda não “esticado demais”
    # (muito 24h e pouco 1h = possivel exaustão)
    accel = (chg_1h - (chg_24h / 24.0))
    accel_n = clamp(accel / 2.5, -0.6, 1.2)

    # 3) momentum curto: 1h e 24h
    mom1 = clamp(chg_1h / 6.0, -0.8, 1.3)
    mom24 = clamp(chg_24h / 18.0, -0.8, 1.3)

    # 4) penaliza 24h extremamente alto (já “pumped”)
    overheat_penalty = clamp((chg_24h - 35.0) / 30.0, 0.0, 1.0)

    # 5) compõe
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


async def build_ranking(client: httpx.AsyncClient) -> List[CandidateScore]:
    markets = await cg_markets(client)
    dex_boost_map = await dex_trending_signal(client)

    candidates: List[CandidateScore] = []

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

            score, notes = compute_score(mcap, vol24, chg_1h, chg_24h, dex_boost=dex_boost)

            candidates.append(
                CandidateScore(
                    symbol=symbol,
                    name=name,
                    cg_id=cg_id,
                    price=price,
                    mcap=mcap,
                    vol24=vol24,
                    chg_1h=chg_1h,
                    chg_24h=chg_24h,
                    score=score,
                    notes=notes,
                )
            )
        except Exception:
            continue

    # Ordena por score
    candidates.sort(key=lambda x: x.score, reverse=True)
    return candidates[:max(TOP_N, 1)]


def fmt_money(x: float) -> str:
    if x >= 1e9:
        return f"${x/1e9:.2f}B"
    if x >= 1e6:
        return f"${x/1e6:.2f}M"
    if x >= 1e3:
        return f"${x/1e3:.2f}K"
    return f"${x:.0f}"


def format_top_message(items: List[CandidateScore]) -> str:
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
        "/smartmoney  → Top pré-pump (CoinGecko Pro)\n"
        "/radar       → alias do /smartmoney\n"
    )
    await update.message.reply_text(txt)


async def cmd_smartmoney(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔎 Rodando scanner CoinGecko (pré-pump)...")

    client: httpx.AsyncClient = context.application.bot_data["http"]

    try:
        # opcional: tenta ler top_gainers_losers (premium). Se não tiver acesso, ignora.
        _ = await cg_top_gainers_losers(client)

        top = await build_ranking(client)
        msg = format_top_message(top)
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    except httpx.HTTPStatusError as e:
        await update.message.reply_text(
            f"⚠️ Erro no CoinGecko: {e.response.status_code} {e.response.reason_phrase}\n"
            f"URL: {str(e.request.url)}"
        )
    except Exception as e:
        await update.message.reply_text(f"⚠️ Erro no scanner: {type(e).__name__}: {e}")


async def cmd_radar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_smartmoney(update, context)


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

    # Importante para evitar "sujeira" de updates antigos
    # (OBS: Conflict ocorre quando existe OUTRO bot rodando polling ao mesmo tempo.)
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
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

# Python 3.9+
from datetime import time as dtime
from zoneinfo import ZoneInfo

load_dotenv()

# =========================
# ENV / CONFIG
# =========================
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
if not TG_BOT_TOKEN:
    raise RuntimeError("❌ Variável TG_BOT_TOKEN não definida.")

# CoinGecko Pro base
COINGECKO_BASE_URL = os.getenv(
    "COINGECKO_BASE_URL",
    "https://pro-api.coingecko.com/api/v3"
).rstrip("/")

# Chave Pro
COINGECKO_API_KEY = (
    os.getenv("COINGECKO_PRO_API_KEY", "").strip()
    or os.getenv("COINGECKO_API_KEY", "").strip()
    or os.getenv("COINGECKO_KEY", "").strip()
)

# Onde o bot vai postar automaticamente às 21h (BRT), se definido
ALERT_CHAT_ID = os.getenv("ALERT_CHAT_ID", "").strip()  # ex: "-100123456789" (grupo) ou "123456789" (privado)

# Radar params
TOP_N = int(os.getenv("TOP_N", "5"))
CANDIDATES = int(os.getenv("CANDIDATES", "150"))  # quantos ativos avaliar antes do ranking final
VS_CURRENCY = os.getenv("VS_CURRENCY", "usd").strip().lower()

# Filtros
MIN_MCAP = float(os.getenv("MIN_MCAP", "2000000"))       # 2M
MAX_MCAP = float(os.getenv("MAX_MCAP", "250000000"))     # 250M
MIN_VOL24 = float(os.getenv("MIN_VOL24", "1500000"))     # 1.5M
EXCLUDE_STABLES = os.getenv("EXCLUDE_STABLES", "1").strip() == "1"

# Premium boosts
USE_CG_TRENDING_BOOST = os.getenv("USE_CG_TRENDING_BOOST", "1").strip() == "1"
USE_CG_GAINERS_BOOST = os.getenv("USE_CG_GAINERS_BOOST", "1").strip() == "1"

# CoinGecko Onchain (DEX) via Pro
USE_ONCHAIN_DEX_BOOST = os.getenv("USE_ONCHAIN_DEX_BOOST", "1").strip() == "1"
ONCHAIN_NETWORK = os.getenv("ONCHAIN_NETWORK", "").strip()  # vazio = usar /onchain/networks/trending_pools (todas)

# HTTP
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "20"))
HTTP_RETRIES = int(os.getenv("HTTP_RETRIES", "2"))

# Timezone BRT
TZ = ZoneInfo(os.getenv("TZ", "America/Sao_Paulo"))  # BRT

# Stables para cortar ruído
STABLE_SYMBOLS = {
    "USDT", "USDC", "DAI", "TUSD", "USDE", "USDQ", "FDUSD", "PYUSD",
    "EUR", "GBP", "JPY", "TRY", "BRL",
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


CACHE = TTLCache(ttl_sec=60)


def cg_headers() -> Dict[str, str]:
    """
    CoinGecko Pro: 'x-cg-pro-api-key'
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


def is_stable_like(symbol: str) -> bool:
    s = (symbol or "").upper().strip()
    return (
        s in STABLE_SYMBOLS
        or s.endswith("USD")
        or s.endswith("USDT")
        or s.endswith("USDC")
    )


def fmt_money(x: float) -> str:
    if x >= 1e9:
        return f"${x/1e9:.2f}B"
    if x >= 1e6:
        return f"${x/1e6:.2f}M"
    if x >= 1e3:
        return f"${x/1e3:.2f}K"
    return f"${x:.0f}"


# =========================
# COINGECKO CORE (Pro)
# =========================
async def cg_markets(client: httpx.AsyncClient) -> List[Dict[str, Any]]:
    """
    /coins/markets com variação 1h/24h e volume
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
    }
    data = await http_get_json(client, url, params)
    if not isinstance(data, list):
        data = []
    CACHE.set(cache_key, data)
    return data


async def cg_trending_symbols(client: httpx.AsyncClient) -> Dict[str, float]:
    """
    /search/trending -> boost por símbolo
    (não “pesa” muito, só prioriza o que está ganhando atenção)
    """
    if not USE_CG_TRENDING_BOOST:
        return {}

    cache_key = "cg_trending_boost"
    cached = CACHE.get(cache_key)
    if cached is not None:
        return cached

    url = f"{COINGECKO_BASE_URL}/search/trending"
    try:
        data = await http_get_json(client, url, params={})
    except Exception:
        return {}

    boost: Dict[str, float] = {}
    coins = (data or {}).get("coins", []) or []
    # dá boost decrescente (top 1 maior boost)
    for idx, item in enumerate(coins[:15]):
        it = (item or {}).get("item", {}) or {}
        sym = (it.get("symbol") or "").upper().strip()
        if not sym:
            continue
        # top1 ~1.0, top15 ~0.2
        b = clamp(1.0 - (idx * 0.06), 0.2, 1.0)
        boost[sym] = max(boost.get(sym, 0.0), b)

    CACHE.set(cache_key, boost)
    return boost


async def cg_top_gainers_losers(client: httpx.AsyncClient) -> Dict[str, float]:
    """
    /coins/top_gainers_losers (Premium)
    Se der 401/403, ignora (retorna {})
    """
    if not USE_CG_GAINERS_BOOST:
        return {}

    cache_key = f"cg_tgl_boost:{VS_CURRENCY}"
    cached = CACHE.get(cache_key)
    if cached is not None:
        return cached

    url = f"{COINGECKO_BASE_URL}/coins/top_gainers_losers"
    params = {"vs_currency": VS_CURRENCY, "duration": "24h"}
    try:
        data = await http_get_json(client, url, params)
    except Exception:
        return {}

    boost: Dict[str, float] = {}

    # Estrutura pode variar, então tratamos bem defensivo
    for bucket_key, base_boost in (("top_gainers", 0.8), ("top_losers", -0.4)):
        arr = (data or {}).get(bucket_key, []) or []
        for idx, it in enumerate(arr[:25]):
            sym = (it.get("symbol") or "").upper().strip()
            if not sym:
                continue
            # ganhadores: boost positivo; losers: pequeno boost negativo
            decay = clamp(1.0 - idx * 0.03, 0.3, 1.0)
            boost[sym] = boost.get(sym, 0.0) + base_boost * decay

    CACHE.set(cache_key, boost)
    return boost


# =========================
# COINGECKO ONCHAIN (DEX) - Pro
# =========================
async def cg_onchain_trending_pools_boost(client: httpx.AsyncClient) -> Dict[str, float]:
    """
    /onchain/networks/trending_pools (todas) OU /onchain/networks/{network}/trending_pools
    boost por símbolo baseado em volume/liquidez e momentum de pool.
    """
    if not USE_ONCHAIN_DEX_BOOST:
        return {}

    cache_key = f"cg_onchain_tp:{ONCHAIN_NETWORK or 'ALL'}"
    cached = CACHE.get(cache_key)
    if cached is not None:
        return cached

    if ONCHAIN_NETWORK:
        url = f"{COINGECKO_BASE_URL}/onchain/networks/{ONCHAIN_NETWORK}/trending_pools"
    else:
        url = f"{COINGECKO_BASE_URL}/onchain/networks/trending_pools"

    try:
        data = await http_get_json(client, url, params={"page": 1})
    except Exception:
        return {}

    items = (data or {}).get("data", []) or []
    boost: Dict[str, float] = {}

    for it in items[:40]:
        attrs = (it or {}).get("attributes", {}) or {}

        # base token symbol (estrutura pode variar)
        base_token = attrs.get("base_token") or {}
        sym = (base_token.get("symbol") or "").upper().strip() if isinstance(base_token, dict) else ""
        if not sym:
            continue

        # métricas típicas
        price_change_24h = float(((attrs.get("price_change_percentage") or {}).get("h24", 0.0)) or 0.0)
        volume_24h = float(((attrs.get("volume_usd") or {}).get("h24", 0.0)) or 0.0)
        liquidity = float((attrs.get("reserve_in_usd") or 0.0) or 0.0)

        # boost (log) + momentum
        b = (
            clamp(math.log10(max(volume_24h, 1.0)) / 6.0, 0.0, 1.2) +
            clamp(math.log10(max(liquidity, 1.0)) / 7.0, 0.0, 1.0) +
            clamp(price_change_24h / 25.0, -0.3, 0.8)
        )
        boost[sym] = max(boost.get(sym, 0.0), b)

    CACHE.set(cache_key, boost)
    return boost


# =========================
# SCORING (Pré-Pump + Premium)
# =========================
def compute_score(
    mcap: float,
    vol24: float,
    chg_1h: float,
    chg_24h: float,
    trending_boost: float = 0.0,
    gainers_boost: float = 0.0,
    onchain_boost: float = 0.0,
) -> Tuple[float, str]:
    """
    Score = Liquidez/atenção (vol/mcap) + aceleração (1h vs 24h) + momentum + boosts premium
    """
    # 1) Atenção: volume relativo à mcap
    vm = safe_div(vol24, mcap)  # ex: 0.5 = vol = 50% da mcap
    vm_n = clamp(vm / 1.2, 0.0, 1.2)

    # 2) aceleração (curto vs 24h)
    accel = (chg_1h - (chg_24h / 24.0))
    accel_n = clamp(accel / 2.5, -0.6, 1.2)

    # 3) momentum
    mom1 = clamp(chg_1h / 6.0, -0.8, 1.3)
    mom24 = clamp(chg_24h / 18.0, -0.8, 1.3)

    # 4) penaliza 24h muito “esticado”
    overheat_penalty = clamp((chg_24h - 35.0) / 30.0, 0.0, 1.0)

    # 5) boosts premium (pesos calibrados pra não dominar o core)
    premium = (
        6.0 * trending_boost +
        7.0 * gainers_boost +
        8.0 * onchain_boost
    )

    raw = (
        45.0 * vm_n +
        20.0 * accel_n +
        20.0 * mom1 +
        15.0 * mom24 +
        premium
    )
    score = clamp(raw - 18.0 * overheat_penalty, 0.0, 100.0)

    notes = (
        f"vm={vm:.2f} accel={accel:.2f} "
        f"trend={trending_boost:.2f} tgl={gainers_boost:.2f} onchain={onchain_boost:.2f} "
        f"overheat={overheat_penalty:.2f}"
    )
    return score, notes


async def build_ranking(client: httpx.AsyncClient) -> List[CandidateScore]:
    markets = await cg_markets(client)

    trending_map = await cg_trending_symbols(client)
    tgl_map = await cg_top_gainers_losers(client)
    onchain_map = await cg_onchain_trending_pools_boost(client)

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

            trending_boost = float(trending_map.get(symbol, 0.0))
            gainers_boost = float(tgl_map.get(symbol, 0.0))
            onchain_boost = float(onchain_map.get(symbol, 0.0))

            score, notes = compute_score(
                mcap=mcap,
                vol24=vol24,
                chg_1h=chg_1h,
                chg_24h=chg_24h,
                trending_boost=trending_boost,
                gainers_boost=gainers_boost,
                onchain_boost=onchain_boost,
            )

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

    candidates.sort(key=lambda x: x.score, reverse=True)
    return candidates[:max(TOP_N, 1)]


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


def format_checklist_message(items: List[CandidateScore]) -> str:
    """
    Template rápido para você cruzar no Fluxo de Fundos (Bybit) às 21h
    """
    if not items:
        return "⚠️ Sem candidatos para checklist."

    lines = [
        "🧾 <b>CHECKLIST 21H (Bybit Fluxo de Fundos)</b>",
        "Abra a Bybit → <b>12H</b> e <b>1H</b> no Fluxo de Fundos.",
        "Preencha para os 1–3 melhores abaixo:",
    ]

    for i, it in enumerate(items[:3], 1):
        lines.append(
            f"\n<b>{i}) {it.symbol}/USDT</b> (CG score {it.score:.1f})\n"
            "• 12H Net Flow: ____\n"
            "• 12H Large In / Out: ____ / ____\n"
            "• 1H Suporte (preço): ____\n"
            "✅ Se Net Flow + e Large In > Out + suporte segurando → candidata forte"
        )

    lines.append("\n📌 Dica: se 24h muito esticado, exija suporte perfeito no 1H (sem vacilo).")
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
        "/smartmoney  → Top pré-pump (CoinGecko Pro + Premium boosts)\n"
        "/checklist   → Top + template do checklist Bybit 21h\n"
        "/radar       → alias do /smartmoney\n"
    )
    await update.message.reply_text(txt)


async def cmd_smartmoney(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔎 Rodando scanner CoinGecko (pré-pump + premium)...")
    client: httpx.AsyncClient = context.application.bot_data["http"]

    try:
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


async def cmd_checklist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client: httpx.AsyncClient = context.application.bot_data["http"]
    try:
        top = await build_ranking(client)
        msg = format_checklist_message(top)
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"⚠️ Erro no checklist: {type(e).__name__}: {e}")


async def cmd_radar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_smartmoney(update, context)


# =========================
# AUTO PUSH 21H (BRT)
# =========================
async def job_send_21h_report(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Envia às 21:00 BRT: Top + checklist para o chat definido.
    """
    if not ALERT_CHAT_ID:
        return

    app = context.application
    client: httpx.AsyncClient = app.bot_data["http"]

    try:
        top = await build_ranking(client)
        msg1 = format_top_message(top)
        msg2 = format_checklist_message(top)

        await app.bot.send_message(chat_id=ALERT_CHAT_ID, text=msg1, parse_mode=ParseMode.HTML)
        await app.bot.send_message(chat_id=ALERT_CHAT_ID, text=msg2, parse_mode=ParseMode.HTML)
    except Exception as e:
        # falha silenciosa (não derruba o bot)
        try:
            await app.bot.send_message(chat_id=ALERT_CHAT_ID, text=f"⚠️ Falha no relatório 21h: {type(e).__name__}: {e}")
        except Exception:
            pass


# =========================
# APP LIFECYCLE
# =========================
async def on_startup(app: Application) -> None:
    app.bot_data["http"] = httpx.AsyncClient(
        timeout=httpx.Timeout(HTTP_TIMEOUT),
        headers=cg_headers(),
    )

    # agenda 21:00 BRT (se ALERT_CHAT_ID existir)
    if ALERT_CHAT_ID:
        app.job_queue.run_daily(
            job_send_21h_report,
            time=dtime(hour=21, minute=0, second=0),
            days=(0, 1, 2, 3, 4, 5, 6),
            name="report_21h_brt",
            timezone=TZ,
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
    application.add_handler(CommandHandler("checklist", cmd_checklist))

    # Importante: evita “sujeira” de updates antigos.
    # (Conflict acontece quando existe OUTRO processo rodando polling ao mesmo tempo.)
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
import os
import time
import math
import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import httpx
from dotenv import load_dotenv

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()

# =========================
# ENV / CONFIG (Lite)
# =========================
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
if not TG_BOT_TOKEN:
    raise RuntimeError("❌ TG_BOT_TOKEN não definido.")

BASE_URL = os.getenv("COINGECKO_BASE_URL", "https://api.coingecko.com/api/v3").rstrip("/")
VS = os.getenv("VS_CURRENCY", "usd").strip().lower()

PER_PAGE = int(os.getenv("PER_PAGE", "250"))
TOP_SHOW = int(os.getenv("TOP_SHOW", "20"))
TOP_ENRICH = int(os.getenv("TOP_ENRICH", "40"))

MIN_MCAP = float(os.getenv("MIN_MCAP", "1000000"))
MAX_MCAP = float(os.getenv("MAX_MCAP", "400000000"))
MIN_VOL24 = float(os.getenv("MIN_VOL24", "500000"))

MIN_REQ_INTERVAL_SEC = float(os.getenv("MIN_REQ_INTERVAL_SEC", "0.45"))
CACHE_TTL_SEC = int(os.getenv("CACHE_TTL_SEC", "180"))
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "20"))
HTTP_RETRIES = int(os.getenv("HTTP_RETRIES", "3"))
CONCURRENCY = int(os.getenv("CONCURRENCY", "4"))

IMBALANCE_ALERT = float(os.getenv("IMBALANCE_ALERT", "0.25"))  # 0.25 = 25%
TOP_EXCHANGE_MAX_SHARE = float(os.getenv("TOP_EXCHANGE_MAX_SHARE", "0.70"))  # 70%
MIN_EXCHANGES = int(os.getenv("MIN_EXCHANGES", "2"))

# Períodos por hora (derivados via market_chart hourly de 1 dia)
PERIOD_HOURS = [1, 2, 3, 4, 6, 8, 12, 18, 24]

# =========================
# CACHE / RATE LIMIT
# =========================
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
    x = float(x or 0.0)
    if x >= 1e12: return f"${x/1e12:.2f}T"
    if x >= 1e9:  return f"${x/1e9:.2f}B"
    if x >= 1e6:  return f"${x/1e6:.2f}M"
    if x >= 1e3:  return f"${x/1e3:.2f}K"
    return f"${x:.0f}"

async def http_get_json(client: httpx.AsyncClient, url: str, params: Dict[str, Any], cache_key: Optional[str] = None) -> Any:
    if cache_key:
        cached = CACHE.get(cache_key)
        if cached is not None:
            return cached

    last_exc: Optional[Exception] = None
    for attempt in range(HTTP_RETRIES + 1):
        try:
            await RL.wait()
            r = await client.get(url, params=params)

            if r.status_code == 429:
                await asyncio.sleep(0.8 * (2 ** attempt))
                continue

            r.raise_for_status()
            data = r.json()
            if cache_key:
                CACHE.set(cache_key, data)
            return data
        except Exception as e:
            last_exc = e
            await asyncio.sleep(min(6.0, 0.7 * (2 ** attempt)))

    raise last_exc or RuntimeError("Erro HTTP desconhecido")

# =========================
# DATA MODEL
# =========================
@dataclass
class Coin:
    cg_id: str
    symbol: str
    name: str
    price: float
    mcap: float
    vol24: float
    ratio_vm: float
    chg_1h: float
    chg_24h: float
    chg_7d: float
    ret: Dict[int, float] = field(default_factory=dict)

    # microestrutura / tickers
    exch_count: int = 0
    top_exch_share: float = 0.0
    conv_vol_usd_sum: float = 0.0
    cost_up_usd: float = 0.0
    cost_down_usd: float = 0.0
    spread_med: float = 0.0

    # scores
    score_mom: float = 0.0
    score_sm: float = 0.0
    score_micro: float = 0.0
    score_hyb: float = 0.0
    flags: str = ""

# =========================
# COINGECKO ENDPOINTS (Lite)
# =========================
async def cg_markets(client: httpx.AsyncClient) -> List[Dict[str, Any]]:
    url = f"{BASE_URL}/coins/markets"
    params = {
        "vs_currency": VS,
        "order": "volume_desc",
        "per_page": min(max(PER_PAGE, 50), 250),
        "page": 1,
        "sparkline": "false",
        "price_change_percentage": "1h,24h,7d",
    }
    data = await http_get_json(client, url, params, cache_key=f"markets:{VS}:{params['per_page']}")
    return data if isinstance(data, list) else []

async def cg_market_chart_hourly_1d(client: httpx.AsyncClient, coin_id: str) -> Optional[List[List[float]]]:
    url = f"{BASE_URL}/coins/{coin_id}/market_chart"
    params = {"vs_currency": VS, "days": 1, "interval": "hourly"}
    data = await http_get_json(client, url, params, cache_key=f"chart1d:{VS}:{coin_id}")
    prices = (data or {}).get("prices")
    if not isinstance(prices, list) or len(prices) < 5:
        return None
    return prices

async def cg_coin_tickers(client: httpx.AsyncClient, coin_id: str, page: int = 1) -> Dict[str, Any]:
    url = f"{BASE_URL}/coins/{coin_id}/tickers"
    params = {"page": page}
    return await http_get_json(client, url, params, cache_key=f"tickers:{coin_id}:p{page}")

async def cg_exchange_data(client: httpx.AsyncClient, exch_id: str) -> Dict[str, Any]:
    url = f"{BASE_URL}/exchanges/{exch_id}"
    params = {}
    return await http_get_json(client, url, params, cache_key=f"exch:{exch_id}")

# =========================
# RETURNS
# =========================
def compute_period_returns_from_hourly(prices: List[List[float]], hours_list: List[int]) -> Dict[int, float]:
    out: Dict[int, float] = {}
    if not prices or len(prices) < 2:
        return out
    last = float(prices[-1][1] or 0.0)
    for h in hours_list:
        if len(prices) >= (h + 1):
            base = float(prices[-(h + 1)][1] or 0.0)
            out[h] = ((last - base) / base) * 100.0 if base else 0.0
    return out

# =========================
# REGIME (BTC)
# =========================
async def market_regime(client: httpx.AsyncClient) -> Tuple[str, Dict[str, float]]:
    mk = await cg_markets(client)
    btc = None
    for c in mk:
        if (c.get("id") or "") == "bitcoin":
            btc = c
            break
    if not btc:
        return ("UNKNOWN", {})

    b24 = safe_float(btc.get("price_change_percentage_24h_in_currency"))
    b7d = safe_float(btc.get("price_change_percentage_7d_in_currency"))

    regime = "RISK_ON" if (b24 >= 0 and b7d >= 0) else "RISK_OFF"
    return (regime, {"btc_24h": b24, "btc_7d": b7d})

# =========================
# FILTERS
# =========================
def pass_filters(mcap: float, vol24: float) -> bool:
    if mcap <= 0 or vol24 <= 0:
        return False
    if mcap < MIN_MCAP or mcap > MAX_MCAP:
        return False
    if vol24 < MIN_VOL24:
        return False
    return True

# =========================
# SCORING (sem trust_score)
# =========================
def norm_pct(x: float, scale: float) -> float:
    return clamp(x / scale, -1.5, 1.8)

def liquidity_norm(ratio_vm: float) -> float:
    return clamp(ratio_vm / 3.0, 0.0, 2.0)

def accel_feature(chg_1h: float, chg_24h: float) -> float:
    accel = chg_1h - (chg_24h / 24.0)
    return clamp(accel / 2.5, -1.5, 2.0)

def overheat_penalty(chg_24h: float, chg_12h: float) -> float:
    pen = 0.0
    if chg_24h > 45: pen += 0.35
    if chg_12h > 30: pen += 0.25
    if chg_24h > 90: pen += 0.35
    return clamp(pen, 0.0, 0.9)

def score_momentum(c: Coin, regime: str) -> float:
    r12 = c.ret.get(12, 0.0)
    pen = overheat_penalty(c.chg_24h, r12)
    if regime == "RISK_OFF":
        w1, w12, w24, w7d, wliq = 0.25, 0.30, 0.25, 0.15, 0.10
        extra_pen = 0.10
    else:
        w1, w12, w24, w7d, wliq = 0.35, 0.30, 0.20, 0.10, 0.15
        extra_pen = 0.00

    raw = (
        w1  * norm_pct(c.chg_1h, 10.0) +
        w12 * norm_pct(r12, 20.0) +
        w24 * norm_pct(c.chg_24h, 40.0) +
        w7d * norm_pct(c.chg_7d, 80.0) +
        wliq* liquidity_norm(c.ratio_vm)
    )
    raw -= (pen + extra_pen)
    return clamp(raw * 100.0, 0.0, 100.0)

def score_smartmoney(c: Coin, regime: str) -> float:
    r12 = c.ret.get(12, 0.0)
    accel = accel_feature(c.chg_1h, c.chg_24h)
    pen = overheat_penalty(c.chg_24h, r12)

    base = (
        0.45 * liquidity_norm(c.ratio_vm) +
        0.30 * accel +
        0.15 * norm_pct(r12, 25.0) +
        0.10 * norm_pct(c.chg_1h, 8.0)
    )
    if regime == "RISK_OFF":
        base -= (pen + 0.10)
    else:
        base -= pen

    return clamp(base * 100.0, 0.0, 100.0)

def micro_depth_imbalance(cost_up: float, cost_down: float) -> float:
    # positivo => "custa mais para derrubar do que para subir" (bullish)
    denom = cost_up + cost_down
    if denom <= 0:
        return 0.0
    return (cost_down - cost_up) / denom  # [-1..+1]

def score_microstructure(c: Coin) -> float:
    """
    Microestrutura: não usa trust_score (depreciado).
    Usa:
      - cost_to_move_up_usd / cost_to_move_down_usd
      - spread (mediana aproximada)
      - concentração de volume por exchange (top_exch_share)
      - número de exchanges
    """
    imb = micro_depth_imbalance(c.cost_up_usd, c.cost_down_usd)
    spread = c.spread_med  # % (quanto menor melhor)
    spread_n = clamp(1.0 - (spread / 1.2), 0.0, 1.0)  # 0..1 (1 = spread baixo)
    conc_pen = clamp((c.top_exch_share - TOP_EXCHANGE_MAX_SHARE) / 0.25, 0.0, 1.0)
    exch_n = clamp((c.exch_count - 1) / 6.0, 0.0, 1.0)

    # depth: se cost_down >> cost_up => imb positivo
    depth_n = clamp((imb + 1.0) / 2.0, 0.0, 1.0)

    raw = (
        0.45 * depth_n +
        0.25 * spread_n +
        0.20 * exch_n +
        0.10 * liquidity_norm(c.ratio_vm) / 2.0
    )
    raw -= 0.30 * conc_pen
    return clamp(raw * 100.0, 0.0, 100.0)

def explosion_flag(c: Coin) -> bool:
    r12 = c.ret.get(12, 0.0)
    accel = c.chg_1h - (c.chg_24h / 24.0)
    return (c.chg_1h >= 2.0 and accel >= 1.0 and c.ratio_vm >= 1.2 and r12 <= 35.0)

def institutional_flag(c: Coin, regime: str) -> bool:
    r12 = c.ret.get(12, 0.0)
    accel = c.chg_1h - (c.chg_24h / 24.0)
    if regime == "RISK_OFF":
        return (c.vol24 >= 2_000_000 and c.ratio_vm >= 1.0 and accel >= 0.6 and c.chg_24h <= 35 and r12 <= 25)
    return (c.vol24 >= 2_000_000 and c.ratio_vm >= 1.0 and accel >= 0.8 and c.chg_24h <= 55 and r12 <= 35)

def score_hybrid(c: Coin, regime: str) -> float:
    base = 0.40 * c.score_mom + 0.30 * c.score_sm + 0.30 * c.score_micro
    bonus = 6.0 if explosion_flag(c) else 0.0
    pen = overheat_penalty(c.chg_24h, c.ret.get(12, 0.0)) * 15.0
    if regime == "RISK_OFF":
        pen += 4.0
    return clamp(base + bonus - pen, 0.0, 100.0)

# =========================
# TICKERS / EXCHANGE QUALITY (sem trust_score ticker)
# =========================
def median(vals: List[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    mid = len(s) // 2
    if len(s) % 2 == 1:
        return s[mid]
    return 0.5 * (s[mid - 1] + s[mid])

async def enrich_tickers_and_exchanges(client: httpx.AsyncClient, c: Coin) -> None:
    """
    Coin tickers by ID:
      - soma de converted_volume.usd
      - share do maior exchange
      - custo para mover (up/down)
      - spread (bid_ask_spread_percentage) mediana
    Exchange data by ID:
      - usamos como “quality proxy” só para o TOP exchange (cacheado)
    """
    try:
        data = await cg_coin_tickers(client, c.cg_id, page=1)
        tickers = (data or {}).get("tickers") or []
        if not isinstance(tickers, list) or not tickers:
            return

        vol_by_exch: Dict[str, float] = {}
        spreads: List[float] = []

        cost_up_vals: List[float] = []
        cost_down_vals: List[float] = []

        vol_sum = 0.0
        exch_ids: set = set()

        for t in tickers[:100]:  # limita
            market = (t.get("market") or {})
            exch_id = (market.get("identifier") or "").strip()
            if exch_id:
                exch_ids.add(exch_id)

            conv = (t.get("converted_volume") or {})
            v_usd = safe_float(conv.get("usd"))
            if v_usd > 0:
                vol_sum += v_usd
                if exch_id:
                    vol_by_exch[exch_id] = vol_by_exch.get(exch_id, 0.0) + v_usd

            sp = safe_float(t.get("bid_ask_spread_percentage"))
            if sp > 0:
                spreads.append(sp)

            # campos podem existir ou não dependendo do retorno
            cu = safe_float(t.get("cost_to_move_up_usd"))
            cd = safe_float(t.get("cost_to_move_down_usd"))
            if cu > 0: cost_up_vals.append(cu)
            if cd > 0: cost_down_vals.append(cd)

        c.conv_vol_usd_sum = vol_sum
        c.exch_count = len(exch_ids)
        c.spread_med = median(spreads)

        # depth/cost: usa mediana
        c.cost_up_usd = median(cost_up_vals)
        c.cost_down_usd = median(cost_down_vals)

        # concentração
        if vol_by_exch and vol_sum > 0:
            top_exch, top_vol = max(vol_by_exch.items(), key=lambda kv: kv[1])
            c.top_exch_share = top_vol / vol_sum if vol_sum else 0.0

            # Exchange quality proxy (não é trust_score de ticker)
            # Só puxa o /exchanges/{id} do top exchange (cacheado) para flag
            try:
                ex = await cg_exchange_data(client, top_exch)
                tv = safe_float(ex.get("trade_volume_24h_btc"))  # proxy simples
                if tv <= 0:
                    c.flags += " ⚠️EX_LOWVOL"
            except Exception:
                pass

        # flags estruturais
        if c.exch_count < MIN_EXCHANGES:
            c.flags += " ⚠️1EXCH"
        if c.top_exch_share >= TOP_EXCHANGE_MAX_SHARE:
            c.flags += " ⚠️CONC"

    except Exception:
        return

# =========================
# BUILD UNIVERSE
# =========================
async def build_universe(client: httpx.AsyncClient, require_vol_gt_mcap: bool) -> List[Coin]:
    mk = await cg_markets(client)
    coins: List[Coin] = []

    for c in mk:
        cg_id = (c.get("id") or "").strip()
        symbol = (c.get("symbol") or "").upper().strip()
        name = (c.get("name") or "").strip()

        mcap = safe_float(c.get("market_cap"))
        vol24 = safe_float(c.get("total_volume"))
        price = safe_float(c.get("current_price"))

        if not cg_id or not symbol:
            continue
        if not pass_filters(mcap, vol24):
            continue

        if require_vol_gt_mcap and not (vol24 > mcap):
            continue

        chg_1h = safe_float(c.get("price_change_percentage_1h_in_currency"))
        chg_24h = safe_float(c.get("price_change_percentage_24h_in_currency"))
        chg_7d = safe_float(c.get("price_change_percentage_7d_in_currency"))

        ratio_vm = safe_div(vol24, mcap)

        coins.append(
            Coin(
                cg_id=cg_id,
                symbol=symbol,
                name=name,
                price=price,
                mcap=mcap,
                vol24=vol24,
                ratio_vm=ratio_vm,
                chg_1h=chg_1h,
                chg_24h=chg_24h,
                chg_7d=chg_7d,
            )
        )

    # Ranking base para decidir quais enriquecer
    coins.sort(key=lambda x: x.ratio_vm, reverse=True)
    enrich_list = coins[:max(1, TOP_ENRICH)]

    sem = asyncio.Semaphore(max(1, CONCURRENCY))

    async def enrich_all(coin: Coin) -> None:
        async with sem:
            # returns
            prices = await cg_market_chart_hourly_1d(client, coin.cg_id)
            if prices:
                coin.ret = compute_period_returns_from_hourly(prices, PERIOD_HOURS)

            # tickers + exchange proxy
            await enrich_tickers_and_exchanges(client, coin)

    await asyncio.gather(*(enrich_all(c) for c in enrich_list))
    return coins

# =========================
# OUTPUT
# =========================
def stats_line(c: Coin) -> str:
    parts = []
    for h in PERIOD_HOURS:
        if h in c.ret:
            parts.append(f"{h}h {c.ret[h]:+,.2f}%".replace(",", "X").replace(".", ",").replace("X", "."))
    return " | ".join(parts) if parts else "sem stats(12h)"

def micro_line(c: Coin) -> str:
    imb = micro_depth_imbalance(c.cost_up_usd, c.cost_down_usd)
    return (
        f"• EX: {c.exch_count} | TopExchShare: {c.top_exch_share:.2f}\n"
        f"• CostUp: {fmt_money(c.cost_up_usd)} | CostDown: {fmt_money(c.cost_down_usd)} | Imb: {imb:+.2f}\n"
        f"• SpreadMed: {c.spread_med:.2f}% | ConvVolUSD(sum): {fmt_money(c.conv_vol_usd_sum)}"
    )

def base_info(c: Coin) -> str:
    return (
        f"• Vol/Mcap: <b>{c.ratio_vm:.2f}x</b> | Mcap: {fmt_money(c.mcap)} | Vol24: {fmt_money(c.vol24)}\n"
        f"• 1h: {c.chg_1h:+.2f}% | 24h: {c.chg_24h:+.2f}% | 7d: {c.chg_7d:+.2f}%\n"
        f"• Stats: {stats_line(c)}"
    )

def format_list(title: str, coins: List[Coin], extra: str = "", show_micro: bool = False, score_field: str = "") -> str:
    if not coins:
        return "⚠️ Sem resultados nos filtros atuais."

    lines = [f"🔥 <b>{title}</b> | base={VS.upper()}"]
    if extra:
        lines.append(f"<i>{extra}</i>")

    show = coins[:max(1, TOP_SHOW)]
    for i, c in enumerate(show, 1):
        badges = []
        if explosion_flag(c): badges.append("💥")
        if "INST" in c.flags: badges.append("🏦")
        if "⚠️" in c.flags: badges.append("⚠️")

        b = " ".join(badges)
        score_txt = ""
        if score_field:
            val = getattr(c, score_field, 0.0)
            score_txt = f"\n• Score: <b>{val:.1f}</b>"

        block = f"\n<b>{i}) {c.symbol}/{VS.upper()}</b> {b} {c.flags}\n{base_info(c)}"
        if show_micro:
            block += f"\n{micro_line(c)}"
        block += score_txt
        lines.append(block)

    lines.append("⚙️ Observação: trust_score de ticker foi removido/depreciado; usamos microestrutura + exchange proxy + concentração.")
    return "\n".join(lines)

# =========================
# MODOS / HEURÍSTICAS
# =========================
def select_imbalance_alert(coins: List[Coin]) -> List[Coin]:
    out = []
    for c in coins:
        imb = micro_depth_imbalance(c.cost_up_usd, c.cost_down_usd)
        if imb >= IMBALANCE_ALERT and c.ratio_vm >= 1.0 and (c.chg_1h - c.chg_24h/24.0) >= 0.6:
            out.append(c)
    out.sort(key=lambda x: micro_depth_imbalance(x.cost_up_usd, x.cost_down_usd), reverse=True)
    return out

def select_market_maker_like(coins: List[Coin]) -> List[Coin]:
    """
    Heurística simples “market maker presence”:
    - spread baixo (<= 0.35%)
    - depth presente (cost_up/down > 0)
    - volume bom
    - não concentrado demais em 1 exchange
    """
    out = []
    for c in coins:
        if c.spread_med <= 0.35 and c.cost_up_usd > 0 and c.cost_down_usd > 0 and c.vol24 >= 2_000_000 and c.top_exch_share <= 0.75:
            out.append(c)
    out.sort(key=lambda x: (x.spread_med, -x.vol24))
    return out

# =========================
# TELEGRAM COMMANDS
# =========================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    txt = (
        "✅ Bot Lite online.\n\n"
        "<b>Comandos</b>\n"
        "/rank        → Vol24 > Mcap (Vol/Mcap)\n"
        "/rank_all    → sem filtro Vol>Mcap\n"
        "/momentum    → momentum científico\n"
        "/smart       → smart money (sem trust_score)\n"
        "/micro       → microestrutura (depth/spread/concentração)\n"
        "/hybrid      → híbrido (mom + smart + micro + regime BTC)\n"
        "/explosao    → detector de aceleração\n"
        "/inst        → filtro institucional\n"
        "/imbalance   → alerta desequilíbrio de liquidez (depth)\n"
        "/mm          → heurística market maker\n"
        "/regime      → regime BTC\n"
        "/ping\n"
    )
    await update.message.reply_text(txt, parse_mode=ParseMode.HTML)

async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("pong ✅")

async def cmd_regime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client: httpx.AsyncClient = context.application.bot_data["http"]
    reg, info = await market_regime(client)
    await update.message.reply_text(
        f"📈 Regime: <b>{reg}</b>\nBTC 24h: {info.get('btc_24h',0.0):+.2f}% | BTC 7d: {info.get('btc_7d',0.0):+.2f}%",
        parse_mode=ParseMode.HTML
    )

async def cmd_rank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client: httpx.AsyncClient = context.application.bot_data["http"]
    reg, info = await market_regime(client)
    coins = await build_universe(client, require_vol_gt_mcap=True)
    coins.sort(key=lambda x: x.ratio_vm, reverse=True)
    await update.message.reply_text(
        format_list("RANK Vol>Mcap", coins, extra=f"Regime={reg} | BTC24={info.get('btc_24h',0):+.2f}% BTC7d={info.get('btc_7d',0):+.2f}%"),
        parse_mode=ParseMode.HTML
    )

async def cmd_rank_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client: httpx.AsyncClient = context.application.bot_data["http"]
    reg, info = await market_regime(client)
    coins = await build_universe(client, require_vol_gt_mcap=False)
    coins.sort(key=lambda x: x.ratio_vm, reverse=True)
    await update.message.reply_text(
        format_list("RANK ALL", coins, extra=f"Regime={reg} | BTC24={info.get('btc_24h',0):+.2f}% BTC7d={info.get('btc_7d',0):+.2f}%"),
        parse_mode=ParseMode.HTML
    )

async def cmd_momentum(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client: httpx.AsyncClient = context.application.bot_data["http"]
    reg, info = await market_regime(client)
    coins = await build_universe(client, require_vol_gt_mcap=False)

    for c in coins[:TOP_ENRICH]:
        c.score_mom = score_momentum(c, reg)

    coins.sort(key=lambda x: x.score_mom, reverse=True)
    await update.message.reply_text(
        format_list("RANK MOMENTUM", coins, extra=f"Regime={reg} | BTC24={info.get('btc_24h',0):+.2f}% BTC7d={info.get('btc_7d',0):+.2f}%", score_field="score_mom"),
        parse_mode=ParseMode.HTML
    )

async def cmd_smart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client: httpx.AsyncClient = context.application.bot_data["http"]
    reg, info = await market_regime(client)
    coins = await build_universe(client, require_vol_gt_mcap=False)

    for c in coins[:TOP_ENRICH]:
        c.score_sm = score_smartmoney(c, reg)

    coins.sort(key=lambda x: x.score_sm, reverse=True)
    await update.message.reply_text(
        format_list("RANK SMART", coins, extra=f"Regime={reg} | BTC24={info.get('btc_24h',0):+.2f}% BTC7d={info.get('btc_7d',0):+.2f}%", score_field="score_sm"),
        parse_mode=ParseMode.HTML
    )

async def cmd_micro(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client: httpx.AsyncClient = context.application.bot_data["http"]
    reg, info = await market_regime(client)
    coins = await build_universe(client, require_vol_gt_mcap=False)

    for c in coins[:TOP_ENRICH]:
        c.score_micro = score_microstructure(c)

    coins.sort(key=lambda x: x.score_micro, reverse=True)
    await update.message.reply_text(
        format_list("RANK MICRO", coins, extra=f"Regime={reg} | BTC24={info.get('btc_24h',0):+.2f}% BTC7d={info.get('btc_7d',0):+.2f}%", show_micro=True, score_field="score_micro"),
        parse_mode=ParseMode.HTML
    )

async def cmd_hybrid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client: httpx.AsyncClient = context.application.bot_data["http"]
    reg, info = await market_regime(client)
    coins = await build_universe(client, require_vol_gt_mcap=False)

    for c in coins[:TOP_ENRICH]:
        c.score_mom = score_momentum(c, reg)
        c.score_sm = score_smartmoney(c, reg)
        c.score_micro = score_microstructure(c)
        c.score_hyb = score_hybrid(c, reg)

    coins.sort(key=lambda x: x.score_hyb, reverse=True)
    await update.message.reply_text(
        format_list("RANK HYBRID", coins, extra=f"Regime={reg} | BTC24={info.get('btc_24h',0):+.2f}% BTC7d={info.get('btc_7d',0):+.2f}%", show_micro=True, score_field="score_hyb"),
        parse_mode=ParseMode.HTML
    )

async def cmd_explosao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client: httpx.AsyncClient = context.application.bot_data["http"]
    reg, info = await market_regime(client)
    coins = await build_universe(client, require_vol_gt_mcap=False)

    ex = [c for c in coins if explosion_flag(c)]
    ex.sort(key=lambda x: (x.chg_1h - x.chg_24h/24.0, x.ratio_vm), reverse=True)

    await update.message.reply_text(
        format_list("DETECTOR EXPLOSÃO", ex, extra=f"Regime={reg} | BTC24={info.get('btc_24h',0):+.2f}% BTC7d={info.get('btc_7d',0):+.2f}%", show_micro=True),
        parse_mode=ParseMode.HTML
    )

async def cmd_inst(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client: httpx.AsyncClient = context.application.bot_data["http"]
    reg, info = await market_regime(client)
    coins = await build_universe(client, require_vol_gt_mcap=False)

    inst = []
    for c in coins:
        if institutional_flag(c, reg):
            c.flags += " INST"
            c.score_mom = score_momentum(c, reg)
            c.score_sm = score_smartmoney(c, reg)
            c.score_micro = score_microstructure(c)
            c.score_hyb = score_hybrid(c, reg)
            inst.append(c)

    inst.sort(key=lambda x: x.score_hyb, reverse=True)
    await update.message.reply_text(
        format_list("FILTRO INSTITUCIONAL", inst, extra=f"Regime={reg} | BTC24={info.get('btc_24h',0):+.2f}% BTC7d={info.get('btc_7d',0):+.2f}%", show_micro=True, score_field="score_hyb"),
        parse_mode=ParseMode.HTML
    )

async def cmd_imbalance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client: httpx.AsyncClient = context.application.bot_data["http"]
    reg, info = await market_regime(client)
    coins = await build_universe(client, require_vol_gt_mcap=False)

    alerts = select_imbalance_alert(coins)
    await update.message.reply_text(
        format_list("ALERTA IMBALANCE", alerts, extra=f"threshold={IMBALANCE_ALERT:.2f} | Regime={reg} | BTC24={info.get('btc_24h',0):+.2f}%", show_micro=True),
        parse_mode=ParseMode.HTML
    )

async def cmd_mm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client: httpx.AsyncClient = context.application.bot_data["http"]
    reg, info = await market_regime(client)
    coins = await build_universe(client, require_vol_gt_mcap=False)

    mm = select_market_maker_like(coins)
    await update.message.reply_text(
        format_list("HEURÍSTICA MARKET MAKER", mm, extra=f"spread<=0.35% | Regime={reg} | BTC24={info.get('btc_24h',0):+.2f}%", show_micro=True),
        parse_mode=ParseMode.HTML
    )

# =========================
# APP LIFECYCLE
# =========================
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
    application.add_handler(CommandHandler("regime", cmd_regime))

    application.add_handler(CommandHandler("rank", cmd_rank))
    application.add_handler(CommandHandler("rank_all", cmd_rank_all))
    application.add_handler(CommandHandler("momentum", cmd_momentum))
    application.add_handler(CommandHandler("smart", cmd_smart))
    application.add_handler(CommandHandler("micro", cmd_micro))
    application.add_handler(CommandHandler("hybrid", cmd_hybrid))
    application.add_handler(CommandHandler("explosao", cmd_explosao))
    application.add_handler(CommandHandler("inst", cmd_inst))
    application.add_handler(CommandHandler("imbalance", cmd_imbalance))
    application.add_handler(CommandHandler("mm", cmd_mm))

    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
import os, re, json, math
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone, timedelta

import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "").strip()

TOP_N = int(os.getenv("TOP_N", "5"))
PAGES = int(os.getenv("PAGES", "4"))
TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "20"))

MIN_MCAP = float(os.getenv("MIN_MCAP", "5000000"))
MAX_MCAP = float(os.getenv("MAX_MCAP", "300000000"))
MIN_VOL_RATIO = float(os.getenv("MIN_VOL_RATIO", "0.30"))
MAX_24H_PUMP = float(os.getenv("MAX_24H_PUMP", "15"))
MAX_ABS_1H = float(os.getenv("MAX_ABS_1H", "3.0"))

WEIGHTS_PATH = os.getenv("WEIGHTS_PATH", "weights.json")

if not TG_BOT_TOKEN:
    raise RuntimeError("❌ TG_BOT_TOKEN não definido.")
if not COINGECKO_API_KEY:
    raise RuntimeError("❌ COINGECKO_API_KEY não definido.")

CG_BASE = "https://pro-api.coingecko.com/api/v3"

SYMBOL_RE = re.compile(r"^[a-z0-9]+$", re.I)
BLACKLIST_TICKERS = {"USDT","USDC","DAI","TUSD","USDE","FDUSD","USDP","USDD","EUR","GBP","JPY","TRY"}
BLACKLIST_NAME_HINTS = {"usd","stable","tether","usd coin","dai","trueusd","first digital","euro","yen","pound","peg"}

# ========= Narrativas (você pode expandir quando quiser)
NARRATIVE_QUERIES = {
    "ai": ["artificial-intelligence", "ai", "agent", "machine-learning"],
    "l2": ["layer-2", "layer 2", "scaling"],
    "rwa": ["real-world-assets", "rwa"],
    "depin": ["depin"],
    "meme": ["meme", "memes"],
    "gaming": ["gaming", "gamefi", "metaverse"],
    "defi": ["decentralized-finance", "defi"],
}

# ========= Cache simples (reduz chamadas e rate-limit)
CACHE: Dict[str, Tuple[float, Any]] = {}
CACHE_TTL_SEC = 60

LAST_SCAN_CACHE: Dict[str, Any] = {}  # symbol -> Candidate
COIN_ID_MAP: Dict[str, str] = {}      # SYMBOL -> coingecko coin id (best-effort)

@dataclass
class Candidate:
    id: str
    symbol: str
    name: str
    mcap: float
    vol24: float
    vol_ratio: float
    chg_1h: float
    chg_24h: float
    score: float
    reasons: List[str]
    ohlc_gate: str

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default

def now_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

def format_money(x: float) -> str:
    if x >= 1e9: return f"${x/1e9:.2f}B"
    if x >= 1e6: return f"${x/1e6:.2f}M"
    if x >= 1e3: return f"${x/1e3:.2f}K"
    return f"${x:.0f}"

def is_probably_stable(symbol: str, name: str) -> bool:
    sym = (symbol or "").upper().strip()
    nm = (name or "").lower().strip()
    if sym in BLACKLIST_TICKERS:
        return True
    for h in BLACKLIST_NAME_HINTS:
        if h in nm:
            return True
    if "USD" in sym and len(sym) <= 6:
        return True
    return False

def load_weights() -> Dict[str, float]:
    default = {"liquidity":1.0,"momentum_control":1.0,"accumulation":1.0,"risk":1.0,"ohlc_gate":1.0,"onchain":1.0}
    try:
        if os.path.exists(WEIGHTS_PATH):
            with open(WEIGHTS_PATH,"r",encoding="utf-8") as f:
                data = json.load(f)
            for k in default:
                if k in data:
                    default[k] = float(data[k])
    except Exception:
        pass
    return default

def save_weights(w: Dict[str,float]) -> None:
    try:
        with open(WEIGHTS_PATH,"w",encoding="utf-8") as f:
            json.dump(w,f,ensure_ascii=False,indent=2)
    except Exception:
        pass

# =========================
# HTTP / COINGECKO
# =========================
async def cg_get(path: str, params: Dict[str, Any] | None = None) -> Any:
    params = params or {}
    key = f"{path}?{json.dumps(params, sort_keys=True)}"
    now = datetime.now(timezone.utc).timestamp()

    if key in CACHE:
        ts, val = CACHE[key]
        if now - ts <= CACHE_TTL_SEC:
            return val

    headers = {"x-cg-pro-api-key": COINGECKO_API_KEY}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.get(f"{CG_BASE}{path}", params=params, headers=headers)
        r.raise_for_status()
        data = r.json()

    CACHE[key] = (now, data)
    return data

async def fetch_markets(pages: int = PAGES) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for page in range(1, pages + 1):
        data = await cg_get("/coins/markets", {
            "vs_currency":"usd",
            "order":"volume_desc",
            "per_page":250,
            "page":page,
            "sparkline":"true",
            "price_change_percentage":"1h,24h,7d",
        })
        if not isinstance(data, list) or not data:
            break
        out.extend(data)
    return out

async def fetch_categories_marketdata() -> List[Dict[str, Any]]:
    return await cg_get("/coins/categories", {})

async def fetch_categories_list() -> List[Dict[str, Any]]:
    return await cg_get("/coins/categories/list", {})

async def fetch_markets_by_category(category_id: str, pages: int = 2) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for page in range(1, pages + 1):
        data = await cg_get("/coins/markets", {
            "vs_currency":"usd",
            "order":"volume_desc",
            "per_page":250,
            "page":page,
            "sparkline":"true",
            "price_change_percentage":"1h,24h,7d",
            "category":category_id,
        })
        if not isinstance(data, list) or not data:
            break
        out.extend(data)
    return out

# Premium: Top gainers/losers
async def fetch_top_gainers_losers(duration: str = "24h") -> Dict[str, Any]:
    # doc: /coins/top_gainers_losers (duration depends on API; if duration not supported, we still show response)
    return await cg_get("/coins/top_gainers_losers", {"vs_currency":"usd", "duration":duration})

# Premium: Recently added
async def fetch_recently_added() -> List[Dict[str, Any]]:
    return await cg_get("/coins/list/new", {})

# Trending (discovery)
async def fetch_trending() -> Dict[str, Any]:
    return await cg_get("/search/trending", {})

# OHLC gate (coin id required)
async def fetch_ohlc(coin_id: str, vs_currency: str = "usd", days: int = 1) -> List[List[float]]:
    return await cg_get(f"/coins/{coin_id}/ohlc", {"vs_currency":vs_currency, "days":days})

# On-chain: trending pools
async def fetch_onchain_trending_pools() -> Dict[str, Any]:
    return await cg_get("/onchain/networks/trending_pools", {})

# On-chain: token by contract (requires network + address)
async def fetch_onchain_token(network: str, address: str, include: str = "top_pools") -> Dict[str, Any]:
    return await cg_get(f"/onchain/networks/{network}/tokens/{address}", {"include": include})

async def resolve_category_id(narrative: str) -> Optional[str]:
    narrative = narrative.lower().strip()
    keys = NARRATIVE_QUERIES.get(narrative)
    if not keys:
        return None
    cats = await fetch_categories_list()
    for c in cats:
        cid = str(c.get("category_id","")).lower()
        nm = str(c.get("name","")).lower()
        for k in keys:
            if k in cid or k in nm:
                return c.get("category_id")
    return None

# =========================
# FEATURES / SCORE
# =========================
def compute_spark_volatility(spark: Optional[Dict[str, Any]]) -> Tuple[float, float]:
    if not spark or "price" not in spark:
        return 0.0, 0.0
    prices = spark.get("price") or []
    if len(prices) < 30:
        return 0.0, 0.0

    rets = []
    for i in range(1, len(prices)):
        p0, p1 = prices[i-1], prices[i]
        if p0 and p1 and p0 > 0:
            rets.append((p1/p0)-1.0)
    if len(rets) < 10:
        return 0.0, 0.0

    mean = sum(rets)/len(rets)
    var = sum((x-mean)**2 for x in rets)/max(1, len(rets)-1)
    vol = math.sqrt(var)

    n = len(prices)
    a = prices[:n//4]
    b = prices[-n//4:]
    slope = 0.0
    if a and b:
        slope = (sum(b)/len(b))/(sum(a)/len(a)) - 1.0

    return float(vol), float(slope)

def ohlc_gate_from_1d(ohlc: List[List[float]]) -> Tuple[str, float]:
    """
    Gate simples (sem depender do Bybit):
    - pega candles recentes (1D de OHLC) e mede:
      * compressão: range médio dos últimos N candles
      * breakout: close acima da média dos highs recentes
    Retorna (status, score_0_25)
    """
    if not ohlc or len(ohlc) < 8:
        return ("sem dados OHLC", 10.0)

    # each: [timestamp, open, high, low, close]
    last = ohlc[-12:] if len(ohlc) >= 12 else ohlc[:]
    ranges = [(c[2]-c[3]) for c in last if len(c) == 5]
    if not ranges:
        return ("sem range", 10.0)

    avg_range = sum(ranges)/len(ranges)
    # compressão = ranges recentes menores que média
    recent = ranges[-4:] if len(ranges) >= 4 else ranges
    comp = 1.0 - clamp((sum(recent)/len(recent)) / (avg_range + 1e-9), 0.0, 2.0)/2.0

    highs = [c[2] for c in last if len(c) == 5]
    closes = [c[4] for c in last if len(c) == 5]
    if not highs or not closes:
        return ("sem highs/closes", 10.0)

    mean_high = sum(highs[:-2]) / max(1, len(highs[:-2]))
    last_close = closes[-1]

    breakout = 1.0 if last_close > mean_high else 0.0

    # score 0-25
    score = 25.0 * (0.65*comp + 0.35*breakout)

    if breakout and comp > 0.35:
        status = "✅ compressão + rompimento (bom timing)"
    elif comp > 0.45:
        status = "🟡 compressão (pré-rompimento)"
    elif breakout:
        status = "🟡 rompimento sem compressão (cuidado)"
    else:
        status = "⚠️ sem sinal claro no candle"

    return (status, round(clamp(score, 0.0, 25.0), 1))

def score_coin(row: Dict[str, Any], weights: Dict[str, float], ohlc_status: str, ohlc_score: float, onchain_bonus: float = 0.0) -> Optional[Candidate]:
    coin_id = str(row.get("id","")).strip()
    symbol = str(row.get("symbol","")).upper().strip()
    name = str(row.get("name","")).strip()

    if not coin_id or not symbol or not SYMBOL_RE.match(row.get("symbol","") or ""):
        return None
    if is_probably_stable(symbol, name):
        return None

    mcap = safe_float(row.get("market_cap"))
    vol24 = safe_float(row.get("total_volume"))
    if mcap <= 0 or vol24 <= 0:
        return None

    if not (MIN_MCAP <= mcap <= MAX_MCAP):
        return None

    vol_ratio = vol24 / mcap
    if vol_ratio < MIN_VOL_RATIO:
        return None

    chg_1h = safe_float(row.get("price_change_percentage_1h_in_currency"))
    chg_24h = safe_float(row.get("price_change_percentage_24h_in_currency"))

    # pré-pump gate
    if chg_24h > MAX_24H_PUMP:
        return None
    if abs(chg_1h) > MAX_ABS_1H:
        return None

    vol, slope = compute_spark_volatility(row.get("sparkline_in_7d"))

    reasons: List[str] = []

    # (0-25) Liquidez
    liq = clamp((vol_ratio - 0.30) / (1.20 - 0.30), 0.0, 1.0)
    liq_score = 25.0 * liq
    if liq_score > 16:
        reasons.append(f"Liquidez forte (Vol/Mcap {vol_ratio:.2f})")

    # (0-25) Momentum controlado
    m24 = clamp((chg_24h - 1.0) / (10.0 - 1.0), 0.0, 1.0)
    m1 = 1.0 - clamp(abs(chg_1h) / 3.0, 0.0, 1.0)
    mom_score = 25.0 * (0.65*m24 + 0.35*m1)
    reasons.append(f"Momentum (24h {chg_24h:+.2f}%, 1h {chg_1h:+.2f}%)")

    # (0-25) Acumulação (quiet trend)
    vol_good = 1.0 - clamp((vol - 0.01) / (0.06 - 0.01), 0.0, 1.0)
    slope_good = clamp((slope + 0.02) / (0.10 + 0.02), 0.0, 1.0)
    acc_score = 25.0 * (0.55*vol_good + 0.45*slope_good)
    if acc_score > 14:
        reasons.append("Acumulação provável (vol contida + tendência leve)")

    # (0-25) Risco (proxy)
    risk_score = 25.0 * clamp((vol_good*0.7 + (1.0 - clamp(max(0.0, -chg_24h)/10.0, 0.0, 1.0))*0.3), 0.0, 1.0)

    # (0-25) OHLC gate já vem pronto
    gate_score = ohlc_score
    if ohlc_status:
        reasons.append(ohlc_status)

    # (0-10) Onchain bonus (fica pequeno pra não dominar tudo)
    on_score = clamp(onchain_bonus, 0.0, 10.0)
    if on_score > 0:
        reasons.append(f"On-chain aquecendo (+{on_score:.1f})")

    w_liq = weights["liquidity"]
    w_mom = weights["momentum_control"]
    w_acc = weights["accumulation"]
    w_rsk = weights["risk"]
    w_gate = weights["ohlc_gate"]
    w_on = weights["onchain"]

    w_sum = max(0.0001, w_liq+w_mom+w_acc+w_rsk+w_gate+w_on)
    total = (liq_score*w_liq + mom_score*w_mom + acc_score*w_acc + risk_score*w_rsk + gate_score*w_gate + on_score*w_on) / w_sum
    total = round(clamp(total, 0.0, 100.0), 1)

    # store coin id map (helps /timing if you add it later)
    COIN_ID_MAP[symbol] = coin_id

    return Candidate(
        id=coin_id, symbol=symbol, name=name,
        mcap=mcap, vol24=vol24, vol_ratio=vol_ratio,
        chg_1h=chg_1h, chg_24h=chg_24h, score=total,
        reasons=reasons[:4],
        ohlc_gate=ohlc_status
    )

def format_report(title: str, cands: List[Candidate], top_n: int) -> str:
    lines = [f"🔥 <b>{title} (Top {top_n})</b>", f"<i>{now_utc_str()}</i>", ""]
    for i, c in enumerate(cands[:top_n], start=1):
        lines.append(f"<b>{i}) {c.symbol}/USDT</b> | Score <b>{c.score}</b>")
        lines.append(f"• Mcap: {format_money(c.mcap)} | Vol24: {format_money(c.vol24)} | Vol/Mcap: <b>{c.vol_ratio:.2f}</b>")
        lines.append(f"• 1h: {c.chg_1h:+.2f}% | 24h: {c.chg_24h:+.2f}%")
        if c.reasons:
            lines.append("• " + " | ".join(c.reasons))
        lines.append("")
    return "\n".join(lines).strip()

# =========================
# HANDLERS
# =========================
async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("pong ✅")

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "✅ <b>Bot Premium Ultra online.</b>\n\n"
        "<b>Comandos:</b>\n"
        "/radar  → painel premium (gainers/losers + new + trending + narrativas + onchain pools)\n"
        "/smartmoney ai|l2|rwa|depin|meme|defi|gaming\n"
        "/onchain_trending → pools em alta (DEX)\n"
        "/onchain_token &lt;network&gt; &lt;contract&gt; → token onchain\n"
        "/weights | /weights set liquidity=... momentum_control=...\n"
        "/result SYMBOL pnl_percent (tuning)\n"
        "/ping\n"
    )
    await update.message.reply_text(txt, parse_mode=ParseMode.HTML)

async def cmd_radar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🛰️ Montando RADAR Premium…")

    try:
        cats = await fetch_categories_marketdata()
        top = await fetch_top_gainers_losers("24h")
        new = await fetch_recently_added()
        trending = await fetch_trending()
        pools = await fetch_onchain_trending_pools()

        # categorias: top 6 por (mcap_change_24h, volume_24h)
        def cat_key(x):
            return (safe_float(x.get("market_cap_change_24h")), safe_float(x.get("volume_24h")))
        cats.sort(key=cat_key, reverse=True)

        lines = ["🛰️ <b>RADAR PREMIUM (CoinGecko Pro + On-chain)</b>\n"]

        lines.append("<b>📌 Narrativas (Categorias)</b>")
        for c in cats[:6]:
            lines.append(f"• {c.get('name')} | McapΔ24h: {safe_float(c.get('market_cap_change_24h')):+.2f}% | Vol24h: {format_money(safe_float(c.get('volume_24h')))}")

        # Top gainers/losers: tentamos achar listas comuns na resposta
        lines.append("\n<b>🚀 Top Gainers/Losers (24h)</b>")
        # resposta pode variar por chave; pegamos as mais prováveis
        for key in ["top_gainers", "top_losers", "data"]:
            if key in top:
                arr = top.get(key)
                if isinstance(arr, list) and arr:
                    lines.append(f"• {key}: {', '.join([(x.get('symbol','').upper()) for x in arr[:6] if isinstance(x, dict)])}")
        if len(lines) < 6:
            lines.append("• (ok) endpoint respondeu, formato pode variar por plano.")

        lines.append("\n<b>🆕 Recently Added (amostra)</b>")
        if isinstance(new, list) and new:
            lines.append("• " + ", ".join([f"{x.get('symbol','').upper()}" for x in new[:10] if isinstance(x, dict)]))

        lines.append("\n<b>🔥 Trending (amostra)</b>")
        coins = trending.get("coins") if isinstance(trending, dict) else None
        if isinstance(coins, list) and coins:
            syms = []
            for it in coins[:10]:
                item = it.get("item", {})
                syms.append(str(item.get("symbol","")).upper())
            lines.append("• " + ", ".join([s for s in syms if s]))

        lines.append("\n<b>⛓️ On-chain Trending Pools (amostra)</b>")
        data = pools.get("data") if isinstance(pools, dict) else None
        if isinstance(data, list) and data:
            # tenta mostrar token symbols do pool
            shown = 0
            for p in data[:6]:
                attrs = p.get("attributes", {})
                name = attrs.get("name") or attrs.get("address") or "pool"
                vol24 = attrs.get("volume_usd", {}).get("h24") if isinstance(attrs.get("volume_usd"), dict) else None
                liq = attrs.get("reserve_in_usd") or attrs.get("liquidity_usd") or None
                lines.append(f"• {name} | Vol24: {format_money(safe_float(vol24))} | Liq: {format_money(safe_float(liq))}")
                shown += 1
                if shown >= 6:
                    break

        lines.append("\nUse: <code>/smartmoney ai</code> | <code>/smartmoney l2</code> | <code>/smartmoney rwa</code> | <code>/smartmoney depin</code> | <code>/smartmoney meme</code>")
        await msg.edit_text("\n".join(lines), parse_mode=ParseMode.HTML)

    except Exception as e:
        await msg.edit_text(f"⚠️ Erro no /radar: {type(e).__name__}: {e}")

async def cmd_onchain_trending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⛓️ Buscando On-chain Trending Pools…")
    try:
        pools = await fetch_onchain_trending_pools()
        data = pools.get("data", [])
        if not isinstance(data, list) or not data:
            await msg.edit_text("⚠️ Sem pools no retorno agora.")
            return

        lines = ["⛓️ <b>ON-CHAIN TRENDING POOLS (Top 10)</b>\n"]
        for i, p in enumerate(data[:10], start=1):
            attrs = p.get("attributes", {})
            name = attrs.get("name") or attrs.get("address") or "pool"
            vol24 = attrs.get("volume_usd", {}).get("h24") if isinstance(attrs.get("volume_usd"), dict) else None
            liq = attrs.get("reserve_in_usd") or attrs.get("liquidity_usd") or None
            lines.append(f"<b>{i})</b> {name}")
            lines.append(f"• Vol24: {format_money(safe_float(vol24))} | Liq: {format_money(safe_float(liq))}\n")

        await msg.edit_text("\n".join(lines).strip(), parse_mode=ParseMode.HTML)
    except Exception as e:
        await msg.edit_text(f"⚠️ Erro /onchain_trending: {type(e).__name__}: {e}")

async def cmd_onchain_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Use: /onchain_token <network> <contract>\nEx: /onchain_token ethereum 0x....")
        return
    network = context.args[0].lower().strip()
    address = context.args[1].strip()

    msg = await update.message.reply_text("⛓️ Buscando token on-chain…")
    try:
        tok = await fetch_onchain_token(network, address, include="top_pools")
        data = tok.get("data", {})
        attrs = data.get("attributes", {})
        name = attrs.get("name") or "token"
        symbol = (attrs.get("symbol") or "").upper()
        price = attrs.get("price_usd")
        fdv = attrs.get("fdv_usd")
        lines = [f"⛓️ <b>{name}</b> ({symbol})", f"• Price: ${safe_float(price):.6f}", f"• FDV: {format_money(safe_float(fdv))}"]

        included = tok.get("included", [])
        if isinstance(included, list) and included:
            lines.append("\n<b>Top Pools (amostra)</b>")
            shown = 0
            for it in included:
                if it.get("type") != "pool":
                    continue
                a = it.get("attributes", {})
                pname = a.get("name") or a.get("address") or "pool"
                vol24 = a.get("volume_usd", {}).get("h24") if isinstance(a.get("volume_usd"), dict) else None
                liq = a.get("reserve_in_usd") or a.get("liquidity_usd") or None
                lines.append(f"• {pname} | Vol24: {format_money(safe_float(vol24))} | Liq: {format_money(safe_float(liq))}")
                shown += 1
                if shown >= 6:
                    break

        await msg.edit_text("\n".join(lines), parse_mode=ParseMode.HTML)
    except Exception as e:
        await msg.edit_text(f"⚠️ Erro /onchain_token: {type(e).__name__}: {e}")

async def cmd_smartmoney(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Use: /smartmoney ai | l2 | rwa | depin | meme | defi | gaming")
        return
    narrative = context.args[0].lower().strip()

    msg = await update.message.reply_text(f"🔎 Smart Money — <b>{narrative.upper()}</b> (Premium Ultra)…", parse_mode=ParseMode.HTML)

    try:
        category_id = await resolve_category_id(narrative)
        if not category_id:
            await msg.edit_text("⚠️ Narrativa não encontrada. Tente: ai, l2, rwa, depin, meme, defi, gaming.")
            return

        weights = load_weights()
        rows = await fetch_markets_by_category(category_id, pages=2)
        if not rows:
            await msg.edit_text("⚠️ Sem moedas retornadas nessa categoria.")
            return

        # on-chain trending pools: usamos como “bônus suave”
        pools = await fetch_onchain_trending_pools()
        pool_data = pools.get("data", []) if isinstance(pools, dict) else []
        hot_pool_tokens = set()
        # tenta extrair nomes/símbolos do nome do pool (heurística)
        for p in pool_data[:50]:
            nm = (p.get("attributes", {}).get("name") or "").upper()
            for token in nm.replace("-", " ").replace("/", " ").split():
                if 2 <= len(token) <= 8:
                    hot_pool_tokens.add(token)

        scored: List[Candidate] = []

        # Para OHLC gate: chamamos só para os melhores candidatos preliminares (economiza chamadas)
        prelim = []
        for r in rows:
            coin_id = str(r.get("id",""))
            sym = str(r.get("symbol","")).upper()
            name = str(r.get("name",""))
            if not coin_id or not sym or is_probably_stable(sym, name):
                continue
            prelim.append(r)

        # pega top ~40 por liquidez para aplicar OHLC gate
        prelim.sort(key=lambda x: safe_float(x.get("total_volume")), reverse=True)
        prelim = prelim[:40]

        ohlc_cache: Dict[str, Tuple[str, float]] = {}
        for r in prelim:
            coin_id = str(r.get("id",""))
            try:
                ohlc = await fetch_ohlc(coin_id, "usd", 1)
                ohlc_cache[coin_id] = ohlc_gate_from_1d(ohlc)
            except Exception:
                ohlc_cache[coin_id] = ("sem OHLC (rate/limite)", 10.0)

        for r in rows:
            coin_id = str(r.get("id",""))
            sym = str(r.get("symbol","")).upper()

            gate_status, gate_score = ohlc_cache.get(coin_id, ("sem OHLC", 10.0))

            # on-chain bonus (heurístico): se símbolo aparecer em pools quentes
            on_bonus = 6.0 if sym in hot_pool_tokens else 0.0

            c = score_coin(r, weights, gate_status, gate_score, onchain_bonus=on_bonus)
            if c:
                scored.append(c)

        scored.sort(key=lambda x: x.score, reverse=True)

        if not scored:
            await msg.edit_text("⚠️ Nada passou nos filtros agora (ou já pumpeou demais / pouca liquidez).")
            return

        LAST_SCAN_CACHE.clear()
        for c in scored[:max(TOP_N, 20)]:
            LAST_SCAN_CACHE[c.symbol] = c

        text = format_report(f"SMART MONEY PRÉ-PUMP — {narrative.upper()}", scored, TOP_N)
        await msg.edit_text(text, parse_mode=ParseMode.HTML)

    except Exception as e:
        await msg.edit_text(f"⚠️ Erro /smartmoney: {type(e).__name__}: {e}")

async def cmd_weights(update: Update, context: ContextTypes.DEFAULT_TYPE):
    w = load_weights()
    if context.args and context.args[0].lower() == "set":
        for kv in context.args[1:]:
            if "=" not in kv:
                continue
            k, v = kv.split("=", 1)
            k = k.strip()
            try:
                val = float(v.strip())
            except Exception:
                continue
            if k in w:
                w[k] = clamp(val, 0.3, 3.0)
        save_weights(w)
        await update.message.reply_text(f"✅ Pesos: <code>{json.dumps(w)}</code>", parse_mode=ParseMode.HTML)
        return
    await update.message.reply_text(f"⚙️ Pesos: <code>{json.dumps(w)}</code>", parse_mode=ParseMode.HTML)

def tune_weights(weights: Dict[str, float], pnl_pct: float) -> Dict[str, float]:
    lr = 0.03
    pnl = clamp(pnl_pct / 20.0, -1.0, 1.0)
    weights["accumulation"] = clamp(weights["accumulation"] * (1.0 + lr * pnl * 0.9), 0.3, 3.0)
    weights["liquidity"] = clamp(weights["liquidity"] * (1.0 + lr * pnl * 0.6), 0.3, 3.0)
    weights["momentum_control"] = clamp(weights["momentum_control"] * (1.0 + lr * pnl * 0.5), 0.3, 3.0)
    weights["ohlc_gate"] = clamp(weights["ohlc_gate"] * (1.0 + lr * pnl * 0.7), 0.3, 3.0)
    if pnl_pct < 0:
        weights["risk"] = clamp(weights["risk"] * (1.0 + lr * 0.8), 0.3, 3.0)
    else:
        weights["risk"] = clamp(weights["risk"] * (1.0 + lr * pnl * 0.2), 0.3, 3.0)
    # onchain é “bônus”: sobe pouco
    weights["onchain"] = clamp(weights["onchain"] * (1.0 + lr * pnl * 0.3), 0.3, 3.0)
    return weights

async def cmd_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Use: /result SYMBOL pnl_percent\nEx: /result TNSR 8.4")
        return
    sym = context.args[0].upper().replace("/USDT", "").strip()
    pnl = safe_float(context.args[1], 0.0)

    w = load_weights()
    before = dict(w)
    w = tune_weights(w, pnl)
    save_weights(w)

    await update.message.reply_text(
        "✅ Resultado registrado.\n"
        f"• {sym} pnl: {pnl:+.2f}%\n"
        f"• Pesos antes: <code>{json.dumps(before)}</code>\n"
        f"• Pesos agora: <code>{json.dumps(w)}</code>",
        parse_mode=ParseMode.HTML
    )

def main():
    app = Application.builder().token(TG_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("radar", cmd_radar))
    app.add_handler(CommandHandler("smartmoney", cmd_smartmoney))
    app.add_handler(CommandHandler("onchain_trending", cmd_onchain_trending))
    app.add_handler(CommandHandler("onchain_token", cmd_onchain_token))
    app.add_handler(CommandHandler("weights", cmd_weights))
    app.add_handler(CommandHandler("result", cmd_result))
    app.run_polling(allowed_updates=Update.ALL_TYPES, close_loop=False)

if __name__ == "__main__":
    main()
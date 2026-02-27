import os
import math
from typing import Any, Dict, List, Tuple

from providers import cg_markets, cg_market_chart_1d, gt_trending_pools, cg_pools_megafilter

TOP_N = int(os.getenv("TOP_N", "5"))
EXCLUDE_STABLES = os.getenv("EXCLUDE_STABLES", "1").strip() == "1"
MIN_MCAP = float(os.getenv("MIN_MCAP", "500000"))
MAX_MCAP = float(os.getenv("MAX_MCAP", "5000000000"))
MIN_VOL24 = float(os.getenv("MIN_VOL24", "100000"))

# VM rule (volume/mcap)
MIN_VM = float(os.getenv("MIN_VM", "0.8"))
REQUIRE_VOL_GT_MCAP = os.getenv("REQUIRE_VOL_GT_MCAP", "0").strip() == "1"
VM_OVERHEAT = float(os.getenv("VM_OVERHEAT", "2.5"))

# anti-fomo
MAX_24H_PCT = float(os.getenv("MAX_24H_PCT", "120"))

STABLES = {"USDT","USDC","DAI","TUSD","FDUSD","PYUSD","USDQ","BRL","EUR","GBP","JPY","TRY"}

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def safe_div(a: float, b: float) -> float:
    return a/b if b else 0.0

def is_stable(symbol: str) -> bool:
    s = (symbol or "").upper().strip()
    return s in STABLES or s.endswith("USD") or s.endswith("USDT") or s.endswith("USDC")

def vol_accel_from_chart(chart: Dict[str, Any]) -> float:
    vols = (chart or {}).get("total_volumes") or []
    if not isinstance(vols, list) or len(vols) < 8:
        return 0.0
    tail = vols[-8:]
    vals = []
    for p in tail:
        try:
            vals.append(float(p[1]))
        except Exception:
            vals.append(0.0)
    last = vals[-1]
    prev = vals[-7:-1]  # 6 horas anteriores
    avg_prev = sum(prev) / max(len(prev), 1)
    if avg_prev <= 0:
        return 0.0
    ratio = last / avg_prev
    # 1.0 -> 0.5, 2.0 -> 1.0, 3.0 -> 1.5 (cap 2.0)
    return clamp((ratio - 1.0) * 0.5 + 0.5, 0.0, 2.0)

def dex_boost_from_trending(trending: Dict[str, Any]) -> Dict[str, float]:
    boost: Dict[str, float] = {}
    items = (trending or {}).get("data", []) or []
    for it in items[:30]:
        attrs = (it or {}).get("attributes", {}) or {}
        base = attrs.get("base_token") or {}
        sym = (base.get("symbol") or "").upper().strip()
        if not sym:
            continue
        pc24 = float((attrs.get("price_change_percentage") or {}).get("h24", 0.0) or 0.0)
        vol24 = float((attrs.get("volume_usd") or {}).get("h24", 0.0) or 0.0)
        liq = float(attrs.get("reserve_in_usd", 0.0) or 0.0)

        b = 0.0
        if vol24 > 0:
            b += min(math.log10(vol24) / 6.0, 1.2)
        if liq > 0:
            b += min(math.log10(liq) / 7.0, 1.0)
        b += clamp(pc24 / 25.0, -0.3, 0.8)

        boost[sym] = max(boost.get(sym, 0.0), b)
    return boost

def pool_whitelist_from_megafilter(mf: Dict[str, Any]) -> Dict[str, float]:
    """
    Converte megafilter em um “ok de liquidez” por símbolo.
    Se o token tem pools fortes, ganha boost.
    """
    out: Dict[str, float] = {}
    items = (mf or {}).get("data", []) or []
    for it in items[:80]:
        attrs = (it or {}).get("attributes", {}) or {}
        base = attrs.get("base_token") or {}
        sym = (base.get("symbol") or "").upper().strip()
        if not sym:
            continue
        liq = float(attrs.get("reserve_in_usd", 0.0) or 0.0)
        vol = float((attrs.get("volume_usd") or {}).get("h24", 0.0) or 0.0)
        # boost simples se passou liquidez/volume
        b = clamp(math.log10(max(liq, 1.0)) / 8.0, 0.0, 1.2) + clamp(math.log10(max(vol, 1.0)) / 8.0, 0.0, 1.2)
        out[sym] = max(out.get(sym, 0.0), b)
    return out

def ultra_score(mcap: float, vol24: float, chg1: float, chg24: float, vm: float, va: float, dex: float, pool: float) -> Tuple[float, str]:
    # gates
    if chg24 > MAX_24H_PCT:
        return 0.0, "filtered(fomo24)"
    if REQUIRE_VOL_GT_MCAP and vm < 1.0:
        return 0.0, "filtered(vm<1)"

    # componentes
    vm_n = clamp(vm / 1.2, 0.0, 1.2)
    va_n = clamp(va, 0.0, 2.0)
    mom1 = clamp(chg1 / 8.0, -0.8, 1.2)

    # penaliza vm absurdo (suspeito)
    vm_pen = 0.0
    if vm > VM_OVERHEAT:
        vm_pen = clamp((vm - VM_OVERHEAT) / VM_OVERHEAT, 0.0, 1.0) * 18.0

    raw = (
        35.0 * vm_n +
        28.0 * va_n +
        18.0 * mom1 +
        12.0 * dex +
        12.0 * pool -
        vm_pen
    )
    score = clamp(raw, 0.0, 100.0)
    notes = f"vm={vm:.2f} va={va:.2f} dex={dex:.2f} pool={pool:.2f} pen={vm_pen:.1f}"
    return score, notes

async def run_ultra(http) -> List[Dict[str, Any]]:
    markets = await cg_markets(http, per_page=250)

    trending = await gt_trending_pools(http)
    dex_boost = dex_boost_from_trending(trending)

    # megafilter: você pode rodar por rede (solana/ethereum/base/etc)
    mf = await cg_pools_megafilter(http, network=os.getenv("ONCHAIN_NETWORK", "solana"))
    pool_boost = pool_whitelist_from_megafilter(mf)

    # shortlist (barata)
    pre: List[Dict[str, Any]] = []
    for c in markets:
        sym = (c.get("symbol") or "").upper().strip()
        cid = (c.get("id") or "").strip()
        if not sym or not cid:
            continue

        if EXCLUDE_STABLES and is_stable(sym):
            continue

        mcap = float(c.get("market_cap") or 0.0)
        vol24 = float(c.get("total_volume") or 0.0)
        if mcap < MIN_MCAP or mcap > MAX_MCAP:
            continue
        if vol24 < MIN_VOL24:
            continue

        chg1 = float((c.get("price_change_percentage_1h_in_currency") or 0.0) or 0.0)
        chg24 = float((c.get("price_change_percentage_24h_in_currency") or 0.0) or 0.0)

        vm = safe_div(vol24, mcap)
        if vm < MIN_VM:
            continue

        pre.append({
            "symbol": sym, "id": cid, "name": c.get("name",""),
            "price": float(c.get("current_price") or 0.0),
            "mcap": mcap, "vol24": vol24, "chg1": chg1, "chg24": chg24,
            "vm": vm,
        })

    # puxa market_chart só dos melhores 30 (custo)
    pre.sort(key=lambda x: (x["vm"] * 0.8) + (x["chg1"] / 10.0), reverse=True)
    pre = pre[:30]

    out: List[Dict[str, Any]] = []
    for it in pre:
        chart = await cg_market_chart_1d(http, it["id"])
        va = vol_accel_from_chart(chart)

        dex = float(dex_boost.get(it["symbol"], 0.0))
        pool = float(pool_boost.get(it["symbol"], 0.0))

        score, notes = ultra_score(it["mcap"], it["vol24"], it["chg1"], it["chg24"], it["vm"], va, dex, pool)
        if score <= 0.0 and notes.startswith("filtered("):
            continue

        it["va"] = va
        it["dex"] = dex
        it["pool"] = pool
        it["score"] = score
        it["notes"] = notes
        out.append(it)

    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:TOP_N]
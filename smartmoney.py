from typing import Dict, List

from config import (
    EXCLUDE_STABLES, STABLE_SYMBOLS,
    MIN_MCAP, MAX_MCAP, MIN_VOL24,
    MAX_1H_P, MAX_24H_P,
)
from providers import cg_markets, cg_top_gainers_losers
from scoring import compute_score, continuation_bonus

def is_stable_like(symbol: str) -> bool:
    s = (symbol or "").upper().strip()
    return s in STABLE_SYMBOLS or s.endswith("USD") or s.endswith("USDT") or s.endswith("USDC")

def extract_tgl_ids(tgl: Dict) -> set:
    ids = set()
    for k in ("top_gainers", "top_losers"):
        arr = (tgl or {}).get(k) or []
        for it in arr:
            cid = (it or {}).get("id")
            if cid:
                ids.add(str(cid))
    return ids

async def build_candidates(client) -> List[Dict]:
    markets = await cg_markets(client)
    tgl = await cg_top_gainers_losers(client)
    tgl_ids = extract_tgl_ids(tgl)

    out: List[Dict] = []

    for c in markets:
        symbol = (c.get("symbol") or "").upper().strip()
        name = (c.get("name") or "").strip()
        cid = (c.get("id") or "").strip()

        price = float(c.get("current_price") or 0.0)
        mcap = float(c.get("market_cap") or 0.0)
        vol24 = float(c.get("total_volume") or 0.0)

        chg_1h = float((c.get("price_change_percentage_1h_in_currency") or 0.0) or 0.0)
        chg_24h = float((c.get("price_change_percentage_24h_in_currency") or 0.0) or 0.0)

        high_24h = float(c.get("high_24h") or 0.0)
        low_24h = float(c.get("low_24h") or 0.0)

        if not symbol or not cid:
            continue

        # filtros duros (anti bag)
        if EXCLUDE_STABLES and is_stable_like(symbol):
            continue
        if mcap < MIN_MCAP or mcap > MAX_MCAP:
            continue
        if vol24 < MIN_VOL24:
            continue
        if chg_1h > MAX_1H_P:
            continue
        if chg_24h > MAX_24H_P:
            continue

        cont = continuation_bonus(price, high_24h, chg_1h, chg_24h)
        # Premium “boost”: se estiver no top_gainers_losers, dá um empurrão pequeno
        premium_boost = 0.6 if cid in tgl_ids else 0.0

        score, notes = compute_score(mcap, vol24, chg_1h, chg_24h, cont_bonus=(cont + premium_boost))

        out.append({
            "symbol": symbol,
            "name": name,
            "id": cid,
            "price": price,
            "mcap": mcap,
            "vol24": vol24,
            "chg_1h": chg_1h,
            "chg_24h": chg_24h,
            "high_24h": high_24h,
            "low_24h": low_24h,
            "premium_flag": (cid in tgl_ids),
            "score": score,
            "notes": notes,
        })

    out.sort(key=lambda x: x["score"], reverse=True)
    return out
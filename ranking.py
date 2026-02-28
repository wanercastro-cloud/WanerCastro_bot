import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from config import VS_CURRENCY, PER_PAGE, MIN_MCAP, MIN_VOL24, CONCURRENCY
from coingecko_client import CoinGeckoClient

CHANGE_PERIODS = ["1h", "24h", "7d", "14d", "30d", "200d", "1y"]

@dataclass
class CoinRow:
    id: str
    symbol: str
    name: str
    price: float
    mcap: float
    vol24: float
    ratio: float
    changes: Dict[str, Optional[float]]
    chg12h: Optional[float]

def _safe_num(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None

async def fetch_markets_page(cg: CoinGeckoClient, page: int) -> List[Dict[str, Any]]:
    params = {
        "vs_currency": VS_CURRENCY,
        "order": "volume_desc",
        "per_page": PER_PAGE,
        "page": page,
        "sparkline": "false",
        "price_change_percentage": ",".join(CHANGE_PERIODS),
    }
    r = await cg.get_json("/coins/markets", params=params)
    return r.data

async def calc_12h_change(cg: CoinGeckoClient, coin_id: str) -> Optional[float]:
    # last 1 day, compute 12h change from time series
    params = {
        "vs_currency": VS_CURRENCY,
        "days": "1",
        "interval": "hourly",
    }
    r = await cg.get_json(f"/coins/{coin_id}/market_chart", params=params)
    prices = r.data.get("prices") or []
    if len(prices) < 3:
        return None

    # prices: [[ms, price], ...]
    now_price = prices[-1][1]
    # find closest to 12h ago (12 points if hourly; but sometimes irregular)
    target_ms = prices[-1][0] - (12 * 60 * 60 * 1000)
    idx = min(range(len(prices)), key=lambda i: abs(prices[i][0] - target_ms))
    base_price = prices[idx][1]
    if not base_price:
        return None
    return (now_price / base_price - 1.0) * 100.0

async def build_rank(
    cg: CoinGeckoClient,
    pages: int = 1,
    top_n_calc12h: int = 20
) -> Tuple[List[CoinRow], bool]:
    # returns rows + used_fallback?
    used_fallback_any = False
    all_items: List[Dict[str, Any]] = []
    for p in range(1, pages + 1):
        data = await fetch_markets_page(cg, p)
        all_items.extend(data)

    # Filter + compute ratio
    rows: List[CoinRow] = []
    for it in all_items:
        mcap = _safe_num(it.get("market_cap")) or 0.0
        vol24 = _safe_num(it.get("total_volume")) or 0.0
        if mcap <= 0 or vol24 <= 0:
            continue
        if mcap < MIN_MCAP or vol24 < MIN_VOL24:
            continue
        if vol24 <= mcap:
            continue  # key rule: VOL24 > MCAP

        changes = {}
        for per in CHANGE_PERIODS:
            changes[per] = _safe_num(it.get(f"price_change_percentage_{per}_in_currency"))

        rows.append(
            CoinRow(
                id=str(it.get("id")),
                symbol=str(it.get("symbol", "")).upper(),
                name=str(it.get("name", "")),
                price=_safe_num(it.get("current_price")) or 0.0,
                mcap=mcap,
                vol24=vol24,
                ratio=(vol24 / mcap) if mcap else 0.0,
                changes=changes,
                chg12h=None,
            )
        )

    # Sort by ratio desc, then vol24 desc
    rows.sort(key=lambda r: (r.ratio, r.vol24), reverse=True)

    # Calculate 12h for top subset (Lite-friendly)
    sem = asyncio.Semaphore(CONCURRENCY)

    async def _calc_one(r: CoinRow) -> None:
        async with sem:
            try:
                r.chg12h = await calc_12h_change(cg, r.id)
            except Exception:
                r.chg12h = None

    await asyncio.gather(*[_calc_one(r) for r in rows[:top_n_calc12h]])
    return rows, used_fallback_any
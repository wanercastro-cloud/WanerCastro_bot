from dataclasses import dataclass
from typing import Any, Dict, List

from config import Settings
from scoring import compute_score, is_stable_like

@dataclass
class Candidate:
    symbol: str
    name: str
    cg_id: str
    price: float
    mcap: float
    vol24: float
    chg_1h: float
    chg_24h: float
    score: float
    notes: str

def _f(x: Any) -> float:
    try:
        return float(x or 0.0)
    except Exception:
        return 0.0

async def build_ranking(cg, settings: Settings) -> List[Candidate]:
    """
    Lite: usa /coins/markets (página 1) com per_page até 250.
    """
    per_page = min(max(settings.candidates, 50), 250)
    markets = await cg.coins_markets(settings.vs_currency, per_page=per_page, page=1)
    if not isinstance(markets, list):
        markets = []

    out: List[Candidate] = []

    for c in markets:
        symbol = (c.get("symbol") or "").upper().strip()
        name = (c.get("name") or "").strip()
        cg_id = (c.get("id") or "").strip()

        if not symbol or not cg_id:
            continue

        if settings.exclude_stables and is_stable_like(symbol):
            continue

        mcap = _f(c.get("market_cap"))
        vol24 = _f(c.get("total_volume"))
        price = _f(c.get("current_price"))

        chg_1h = _f(c.get("price_change_percentage_1h_in_currency"))
        chg_24h = _f(c.get("price_change_percentage_24h_in_currency"))

        # Filtros
        if mcap < settings.min_mcap or mcap > settings.max_mcap:
            continue
        if vol24 < settings.min_vol24:
            continue

        vm = (vol24 / mcap) if mcap else 0.0
        if vm < settings.min_vm:
            continue

        score, notes = compute_score(
            mcap=mcap,
            vol24=vol24,
            chg_1h=chg_1h,
            chg_24h=chg_24h,
            prefer_mcap_lt_vol=settings.prefer_mcap_lt_vol,
        )

        out.append(
            Candidate(
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

    out.sort(key=lambda x: x.score, reverse=True)
    return out[: max(settings.top_n, 1)]
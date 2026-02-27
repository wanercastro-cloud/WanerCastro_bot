from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from config import SETTINGS
from providers import CoinGeckoProvider, GeckoTerminalProvider
from scoring import compute_score, is_stable_like, safe_div

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

def fmt_money(x: float) -> str:
    if x >= 1e9:
        return f"${x/1e9:.2f}B"
    if x >= 1e6:
        return f"${x/1e6:.2f}M"
    if x >= 1e3:
        return f"${x/1e3:.2f}K"
    return f"${x:.0f}"

def _dex_boost_from_trending(data: Dict[str, Any]) -> Dict[str, float]:
    """
    Lê trending pools (GeckoTerminal) e cria boost por símbolo.
    """
    boost: Dict[str, float] = {}
    items = (data or {}).get("data", []) or []
    for it in items[:30]:
        attrs = (it or {}).get("attributes", {}) or {}
        base = (attrs.get("base_token") or {}) if isinstance(attrs.get("base_token"), dict) else {}
        symbol = (base.get("symbol") or "").upper().strip()
        if not symbol:
            continue

        pc24 = float((attrs.get("price_change_percentage") or {}).get("h24", 0.0) or 0.0)
        vol24 = float((attrs.get("volume_usd") or {}).get("h24", 0.0) or 0.0)
        liq = float(attrs.get("reserve_in_usd", 0.0) or 0.0)

        # boost simples: liquidez + volume + momentum
        b = 0.0
        if vol24 > 0:
            b += min(1.1, (vol24 ** 0.5) / 6000.0)
        if liq > 0:
            b += min(1.0, (liq ** 0.5) / 9000.0)
        b += max(-0.2, min(0.7, pc24 / 25.0))

        boost[symbol] = max(boost.get(symbol, 0.0), b)
    return boost

async def build_ranking(
    cg: CoinGeckoProvider,
    gt: Optional[GeckoTerminalProvider] = None,
    dex_network: str = "solana",
) -> List[CandidateScore]:
    markets = await cg.markets(SETTINGS.VS_CURRENCY, SETTINGS.CANDIDATES, page=1)

    dex_boost_map: Dict[str, float] = {}
    if SETTINGS.USE_DEX_SIGNAL and gt is not None:
        try:
            trending = await gt.trending_pools_by_network(dex_network, page=1)
            dex_boost_map = _dex_boost_from_trending(trending)
        except Exception:
            dex_boost_map = {}

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

            if SETTINGS.EXCLUDE_STABLES and is_stable_like(symbol):
                continue

            # filtros principais
            if mcap < SETTINGS.MIN_MCAP or mcap > SETTINGS.MAX_MCAP:
                # exceção: se mcap < vol24 e você quiser “caçar monstro”
                if not (SETTINGS.BOOST_IF_MCAP_LT_VOL and mcap > 0 and vol24 > mcap):
                    continue

            if vol24 < SETTINGS.MIN_VOL24:
                # exceção: mcap < vol24 (volume absurdo)
                if not (SETTINGS.BOOST_IF_MCAP_LT_VOL and mcap > 0 and vol24 > mcap):
                    continue

            vm = safe_div(vol24, mcap)
            if vm < SETTINGS.MIN_VM:
                if not (SETTINGS.BOOST_IF_MCAP_LT_VOL and mcap > 0 and vol24 > mcap):
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

    candidates.sort(key=lambda x: x.score, reverse=True)
    return candidates[:max(1, SETTINGS.TOP_N)]

def format_top_message(items: List[CandidateScore]) -> str:
    if not items:
        return "⚠️ Sem candidatos no filtro atual (ajuste MIN_MCAP / MAX_MCAP / MIN_VOL24 / MIN_VM)."

    lines = [f"🔥 <b>SMART MONEY PRÉ-PUMP</b> (Top {len(items)})"]
    for i, it in enumerate(items, 1):
        lines.append(
            f"\n<b>{i}) {it.symbol}/{SETTINGS.VS_CURRENCY.upper()}</b> | <b>Score {it.score:.1f}</b>\n"
            f"• Mcap: {fmt_money(it.mcap)} | Vol24: {fmt_money(it.vol24)}\n"
            f"• 1h: {it.chg_1h:+.2f}% | 24h: {it.chg_24h:+.2f}%"
        )
    return "\n".join(lines)
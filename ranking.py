import math
from typing import List

import httpx

from config import settings
from providers import (
    cg_markets,
    cg_top_gainers_losers,
    cg_trending_search,
    cg_market_chart_1d,
    is_stable_like,
)
from scoring import (
    RankedItem,
    clamp,
    safe_div,
    fmt_money,
)


# =========================
# CORE SCORING – PRÉ-PUMP
# =========================
def compute_prepump_score(
    mcap: float,
    vol24: float,
    chg_1h: float,
    chg_24h: float,
    boost: float,
) -> tuple[float, str]:
    """
    Score focado em:
    - atenção (volume relativo à mcap)
    - aceleração curta (1h vs 24h)
    - penalizar pump já esticado
    """

    vm = safe_div(vol24, mcap)
    vm_n = clamp(vm / 1.2, 0.0, 1.2)

    accel = chg_1h - (chg_24h / 24.0)
    accel_n = clamp(accel / 2.5, -0.6, 1.2)

    mom1 = clamp(chg_1h / 6.0, -0.8, 1.3)
    mom24 = clamp(chg_24h / 18.0, -0.8, 1.3)

    overheat = clamp((chg_24h - 35.0) / 30.0, 0.0, 1.0)

    raw = (
        45.0 * vm_n +
        20.0 * accel_n +
        20.0 * mom1 +
        15.0 * mom24 +
        boost
    )

    score = clamp(raw - 18.0 * overheat, 0.0, 100.0)

    notes = f"vm={vm:.2f} accel={accel:.2f} overheat={overheat:.2f}"
    return score, notes


# =========================
# BUILD PRE-PUMP RANKING
# =========================
async def build_prepump_ranking(client: httpx.AsyncClient) -> List[RankedItem]:
    markets = await cg_markets(client)

    gainers = await cg_top_gainers_losers(client)
    trending = await cg_trending_search(client)

    gainers_set = set()
    if gainers:
        for k in ("top_gainers", "top_losers"):
            for it in gainers.get(k, [])[:15]:
                gainers_set.add(it.get("symbol", "").upper())

    trending_set = set()
    if trending:
        for it in trending.get("coins", []):
            trending_set.add(it["item"]["symbol"].upper())

    ranked: List[RankedItem] = []

    for c in markets:
        symbol = (c.get("symbol") or "").upper()
        if not symbol:
            continue

        if settings.EXCLUDE_STABLES and is_stable_like(symbol):
            continue

        mcap = float(c.get("market_cap") or 0)
        vol24 = float(c.get("total_volume") or 0)

        if mcap < settings.MIN_MCAP or mcap > settings.MAX_MCAP:
            continue
        if vol24 < settings.MIN_VOL24:
            continue

        chg_1h = float(c.get("price_change_percentage_1h_in_currency") or 0)
        chg_24h = float(c.get("price_change_percentage_24h_in_currency") or 0)

        boost = 0.0
        boosts = []

        if symbol in gainers_set:
            boost += settings.BOOST_TOP_GAINERS
            boosts.append("gainers")

        if symbol in trending_set:
            boost += settings.BOOST_TRENDING_SEARCH
            boosts.append("trending")

        score, notes = compute_prepump_score(
            mcap, vol24, chg_1h, chg_24h, boost
        )

        ranked.append(
            RankedItem(
                symbol=symbol,
                name=c.get("name", ""),
                cg_id=c.get("id", ""),
                price=float(c.get("current_price") or 0),
                mcap=mcap,
                vol24=vol24,
                chg_1h=chg_1h,
                chg_24h=chg_24h,
                score=score,
                notes=notes,
                boosts=",".join(boosts) if boosts else "-",
                mcap_fmt=fmt_money(mcap),
                vol24_fmt=fmt_money(vol24),
            )
        )

    ranked.sort(key=lambda x: x.score, reverse=True)
    return ranked[:settings.TOP_N]


# =========================
# CONTINUAÇÃO (anti-bag)
# =========================
async def build_continuation_report(client: httpx.AsyncClient, symbol: str) -> str:
    markets = await cg_markets(client)
    coin = next((c for c in markets if c.get("symbol", "").upper() == symbol), None)

    if not coin:
        return f"❌ {symbol} não encontrado no CoinGecko."

    chg_1h = float(coin.get("price_change_percentage_1h_in_currency") or 0)
    chg_24h = float(coin.get("price_change_percentage_24h_in_currency") or 0)

    msg = [f"🌊 <b>CONTINUAÇÃO – {symbol}</b>"]

    if chg_1h > 0 and chg_24h < 30:
        msg.append("✅ Estrutura saudável (continuação possível)")
        msg.append("📌 Estratégia:")
        msg.append("• Comprar apenas pullback 15m/30m")
        msg.append("• Stop abaixo do fundo anterior")
        msg.append("• Parcial 1 em +10–15%")
    else:
        msg.append("⚠️ Risco elevado de exaustão")
        msg.append("📌 Melhor ação: esperar correção")

    msg.append(f"\n• 1h: {chg_1h:+.2f}% | 24h: {chg_24h:+.2f}%")
    return "\n".join(msg)


# =========================
# FOMO / OVERHEAT
# =========================
async def build_fomo_report(client: httpx.AsyncClient, symbol: str) -> str:
    markets = await cg_markets(client)
    coin = next((c for c in markets if c.get("symbol", "").upper() == symbol), None)

    if not coin:
        return f"❌ {symbol} não encontrado."

    chg_1h = float(coin.get("price_change_percentage_1h_in_currency") or 0)
    chg_24h = float(coin.get("price_change_percentage_24h_in_currency") or 0)

    msg = [f"🔥 <b>FOMO CHECK – {symbol}</b>"]

    if chg_24h > 40 and chg_1h < chg_24h / 6:
        msg.append("🚨 FORTE RISCO DE TOPO LOCAL")
        msg.append("• Não entrar market")
        msg.append("• Aguardar pullback 30–50% do último impulso")
    else:
        msg.append("🟢 FOMO ainda controlado")

    msg.append(f"\n• 1h: {chg_1h:+.2f}%")
    msg.append(f"• 24h: {chg_24h:+.2f}%")

    return "\n".join(msg)
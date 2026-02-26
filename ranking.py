from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import httpx

from config import Settings
from providers import cg_markets, cg_market_chart_1d, geckoterminal_trending_pools
from scoring import (
    CandidateScore,
    compute_smartmoney_score,
    compute_sniper_score,
    is_stable_like,
    fmt_money,
)

def _dex_boost_from_trending(data: Dict[str, Any]) -> Dict[str, float]:
    """
    Usa Trending Pools do GeckoTerminal como “boost”.
    (O PDF lista Trending Pools como endpoint popular).  [oai_citation:2‡Build faster, research smarter with these top endpoints.pdf](sediment://file_000000000f54720eb3844ef915980e02)
    """
    boost: Dict[str, float] = {}
    items = (data or {}).get("data", []) or []
    for it in items[:30]:
        attrs = (it or {}).get("attributes", {}) or {}
        base_token = attrs.get("base_token") or {}
        symbol = (base_token.get("symbol") or "").upper().strip()
        if not symbol:
            continue

        pc24 = float((attrs.get("price_change_percentage") or {}).get("h24", 0.0) or 0.0)
        vol24 = float((attrs.get("volume_usd") or {}).get("h24", 0.0) or 0.0)
        liq = float(attrs.get("reserve_in_usd", 0.0) or 0.0)

        b = 0.0
        # log scale para não “explodir”
        if vol24 > 0:
            b += min((__import__("math").log10(vol24) / 6.0), 1.2)
        if liq > 0:
            b += min((__import__("math").log10(liq) / 7.0), 1.0)
        b += max(min(pc24 / 25.0, 0.8), -0.3)

        boost[symbol] = max(boost.get(symbol, 0.0), float(b))
    return boost

def _passes_filters(settings: Settings, symbol: str, mcap: float, vol24: float) -> bool:
    if settings.exclude_stables and is_stable_like(symbol):
        return False
    if mcap < settings.min_mcap or mcap > settings.max_mcap:
        return False
    if vol24 < settings.min_vol24:
        return False
    return True

def format_report(title: str, vs: str, items: List[CandidateScore]) -> str:
    if not items:
        return "⚠️ Sem candidatos no filtro atual (ajuste MIN_MCAP / MAX_MCAP / MIN_VOL24)."

    lines = [f"🔥 <b>{title}</b> (Top {len(items)})"]
    for i, it in enumerate(items, 1):
        lines.append(
            f"\n<b>{i}) {it.symbol}/{vs.upper()}</b> | <b>Score {it.score:.1f}</b>\n"
            f"• Mcap: {fmt_money(it.mcap)} | Vol24: {fmt_money(it.vol24)}\n"
            f"• 1h: {it.chg_1h:+.2f}% | 24h: {it.chg_24h:+.2f}%"
        )
    return "\n".join(lines)

async def build_smartmoney_report(http: httpx.AsyncClient, settings: Settings) -> Tuple[str, List[CandidateScore]]:
    markets = await cg_markets(http, settings)

    dex_boost: Dict[str, float] = {}
    if settings.use_dex_signal:
        try:
            t = await geckoterminal_trending_pools(http, settings)
            dex_boost = _dex_boost_from_trending(t)
        except Exception:
            dex_boost = {}

    scored: List[CandidateScore] = []
    for c in markets:
        symbol = (c.get("symbol") or "").upper().strip()
        cg_id = (c.get("id") or "").strip()
        if not symbol or not cg_id:
            continue

        price = float(c.get("current_price") or 0.0)
        name = (c.get("name") or "").strip()
        mcap = float(c.get("market_cap") or 0.0)
        vol24 = float(c.get("total_volume") or 0.0)
        chg_1h = float(c.get("price_change_percentage_1h_in_currency") or 0.0)
        chg_24h = float(c.get("price_change_percentage_24h_in_currency") or 0.0)

        if not _passes_filters(settings, symbol, mcap, vol24):
            continue

        score, notes = compute_smartmoney_score(mcap, vol24, chg_1h, chg_24h, dex_boost=dex_boost.get(symbol, 0.0))
        scored.append(CandidateScore(symbol, name, cg_id, price, mcap, vol24, chg_1h, chg_24h, score, notes))

    scored.sort(key=lambda x: x.score, reverse=True)
    top = scored[: max(settings.top_n, 1)]
    msg = format_report("SMART MONEY PRÉ-PUMP", settings.vs_currency, top)
    return msg, top

def _vol_accel_from_chart(chart: Dict[str, Any]) -> float:
    """
    CoinGecko market_chart traz 'total_volumes' [ts, vol].
    Aceleração = last_hour / avg(prev_6_hours). Normaliza para 0..~2.
    """
    vols = (chart or {}).get("total_volumes") or []
    if not isinstance(vols, list) or len(vols) < 8:
        return 0.0

    # pega últimos 8 pontos (hourly): [-1] é a hora mais recente
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

    ratio = last / avg_prev  # ex: 1.8 = 80% acima da média
    # normaliza: 1.0 vira 0.5, 2.0 vira 1.0, 3.0 vira 1.5...
    return max(0.0, min((ratio - 1.0) * 0.5 + 0.5, 2.0))

async def build_sniper_report(http: httpx.AsyncClient, settings: Settings) -> Tuple[str, List[CandidateScore]]:
    markets = await cg_markets(http, settings)

    dex_boost: Dict[str, float] = {}
    if settings.use_dex_signal:
        try:
            t = await geckoterminal_trending_pools(http, settings)
            dex_boost = _dex_boost_from_trending(t)
        except Exception:
            dex_boost = {}

    # 1) pré-seleção barata (sem market_chart ainda)
    pre: List[CandidateScore] = []
    for c in markets:
        symbol = (c.get("symbol") or "").upper().strip()
        cg_id = (c.get("id") or "").strip()
        if not symbol or not cg_id:
            continue

        price = float(c.get("current_price") or 0.0)
        name = (c.get("name") or "").strip()
        mcap = float(c.get("market_cap") or 0.0)
        vol24 = float(c.get("total_volume") or 0.0)
        chg_1h = float(c.get("price_change_percentage_1h_in_currency") or 0.0)
        chg_24h = float(c.get("price_change_percentage_24h_in_currency") or 0.0)

        if not _passes_filters(settings, symbol, mcap, vol24):
            continue

        # filtro sniper: 1h positivo e 24h não muito esticado
        if chg_1h < 0.8 or chg_24h > 45.0:
            continue

        pre.append(CandidateScore(symbol, name, cg_id, price, mcap, vol24, chg_1h, chg_24h, 0.0, ""))

    # limita custo: só puxa chart dos melhores “candidatos” por proxy de vol/mcap e 1h
    pre.sort(key=lambda x: (x.vol24 / max(x.mcap, 1.0)) + (x.chg_1h / 10.0), reverse=True)
    pre = pre[: min(30, len(pre))]

    # 2) enriquece com market_chart e pontua
    out: List[CandidateScore] = []
    limits = {
        "max_1h": float(__import__("os").getenv("MAX_1H_PCT", "18")),
        "max_24h": float(__import__("os").getenv("MAX_24H_PCT", "35")),
    }

    for it in pre:
        try:
            chart = await cg_market_chart_1d(http, settings, it.cg_id)
            vol_acc = _vol_accel_from_chart(chart)
            score, notes = compute_sniper_score(
                it.mcap, it.vol24, it.chg_1h, it.chg_24h,
                vol_accel=vol_acc,
                dex_boost=dex_boost.get(it.symbol, 0.0),
                limits=limits,
            )
            it.score = score
            it.notes = notes
            out.append(it)
        except Exception:
            continue

    out.sort(key=lambda x: x.score, reverse=True)
    top = out[: max(settings.top_n, 1)]
    msg = format_report("SNIPER CONTINUAÇÃO (modo 5)", settings.vs_currency, top)
    return msg, top
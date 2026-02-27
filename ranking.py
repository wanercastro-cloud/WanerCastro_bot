from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import math
import time

from config import (
    VS_CURRENCY, PER_PAGE, TOP_N,
    MIN_MCAP, MAX_MCAP, MIN_VOL24,
    REQUIRE_VOL_GT_MCAP,
    CACHE_TTL_SEC,
    W_RATIO, W_MOM_1H, W_MOM_12H, W_MOM_24H, W_MOM_7D
)
from providers import CoinGeckoClient

@dataclass
class Item:
    symbol: str
    name: str
    mcap: float
    vol24: float
    ratio: float
    chg_1h: Optional[float]
    chg_12h: Optional[float]
    chg_24h: Optional[float]
    chg_7d: Optional[float]
    chg_14d: Optional[float]
    chg_30d: Optional[float]
    chg_200d: Optional[float]
    chg_1y: Optional[float]
    score: float

_cache: Dict[str, Any] = {"ts": 0.0, "items": None}

def _safe_pct(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None

def _compute_12h_from_sparkline(spark: Any) -> Optional[float]:
    """
    CoinGecko markets sparkline (7d) costuma vir com uma série de preços.
    Não garantimos frequência exata, mas normalmente é denso o suficiente.
    Estratégia robusta:
      - pega último preço (p0)
      - pega preço ~12h atrás aproximando por fração do total (12h / 168h = 0.0714)
    """
    try:
        prices = spark.get("price") if isinstance(spark, dict) else None
        if not prices or len(prices) < 20:
            return None
        p0 = float(prices[-1])
        if p0 <= 0:
            return None
        idx = max(0, len(prices) - int(len(prices) * 0.0714) - 1)
        p12 = float(prices[idx])
        if p12 <= 0:
            return None
        return (p0 / p12 - 1.0) * 100.0
    except Exception:
        return None

def _momentum_score(item: Item) -> float:
    # score “científico-lite”: combinação ponderada e limitada
    def clip(v: Optional[float], lo=-50, hi=300) -> float:
        if v is None:
            return 0.0
        return max(lo, min(hi, v))

    ratio_term = math.log10(max(1.0, item.ratio))  # ratio 10 => 1, ratio 100 => 2
    mom_1h = clip(item.chg_1h)
    mom_12h = clip(item.chg_12h)
    mom_24h = clip(item.chg_24h)
    mom_7d = clip(item.chg_7d)

    return (
        W_RATIO * ratio_term * 100.0 +
        W_MOM_1H * mom_1h +
        W_MOM_12H * mom_12h +
        W_MOM_24H * mom_24h +
        W_MOM_7D * mom_7d
    )

async def fetch_rank(client: CoinGeckoClient) -> List[Item]:
    now = time.time()
    if _cache["items"] is not None and (now - _cache["ts"]) < CACHE_TTL_SEC:
        return _cache["items"]

    params = {
        "vs_currency": VS_CURRENCY,
        "order": "volume_desc",
        "per_page": PER_PAGE,
        "page": 1,
        "sparkline": "true",
        "price_change_percentage": "1h,24h,7d,14d,30d,200d,1y",
    }
    data = await client.get_json("/coins/markets", params=params)

    out: List[Item] = []
    for row in data:
        mcap = float(row.get("market_cap") or 0)
        vol24 = float(row.get("total_volume") or 0)

        if mcap <= 0 or vol24 <= 0:
            continue
        if mcap < MIN_MCAP or mcap > MAX_MCAP:
            continue
        if vol24 < MIN_VOL24:
            continue
        if REQUIRE_VOL_GT_MCAP and not (vol24 > mcap):
            continue

        ratio = vol24 / mcap

        item = Item(
            symbol=str(row.get("symbol") or "").upper(),
            name=str(row.get("name") or ""),
            mcap=mcap,
            vol24=vol24,
            ratio=ratio,
            chg_1h=_safe_pct(row.get("price_change_percentage_1h_in_currency")),
            chg_12h=_compute_12h_from_sparkline(row.get("sparkline_in_7d")),
            chg_24h=_safe_pct(row.get("price_change_percentage_24h_in_currency")),
            chg_7d=_safe_pct(row.get("price_change_percentage_7d_in_currency")),
            chg_14d=_safe_pct(row.get("price_change_percentage_14d_in_currency")),
            chg_30d=_safe_pct(row.get("price_change_percentage_30d_in_currency")),
            chg_200d=_safe_pct(row.get("price_change_percentage_200d_in_currency")),
            chg_1y=_safe_pct(row.get("price_change_percentage_1y_in_currency")),
            score=0.0,
        )
        item.score = _momentum_score(item)
        out.append(item)

    # ranking principal: ratio, depois score
    out.sort(key=lambda x: (x.ratio, x.score), reverse=True)

    _cache["ts"] = now
    _cache["items"] = out
    return out

def fmt_money(n: float) -> str:
    # compacto
    for unit, div in [("B", 1e9), ("M", 1e6), ("K", 1e3)]:
        if n >= div:
            return f"{n/div:.2f}{unit}"
    return f"{n:.0f}"

def format_table(items: List[Item], top_n: int) -> str:
    show = items[:top_n]
    lines = []
    lines.append("🔥 *VOL24 > MCAP* (Lite-safe) | rank por *Vol/Mcap*")
    lines.append("")
    for i, it in enumerate(show, 1):
        lines.append(
            f"{i}) *{it.symbol}* | ratio {it.ratio:.2f} | score {it.score:.1f}\n"
            f"   Mcap ${fmt_money(it.mcap)} | Vol24 ${fmt_money(it.vol24)}\n"
            f"   1h {it.chg_1h if it.chg_1h is not None else 'n/a'}% | "
            f"12h {it.chg_12h if it.chg_12h is not None else 'n/a'}% | "
            f"24h {it.chg_24h if it.chg_24h is not None else 'n/a'}%\n"
            f"   7d {it.chg_7d if it.chg_7d is not None else 'n/a'}% | "
            f"14d {it.chg_14d if it.chg_14d is not None else 'n/a'}% | "
            f"30d {it.chg_30d if it.chg_30d is not None else 'n/a'}% | "
            f"200d {it.chg_200d if it.chg_200d is not None else 'n/a'}% | "
            f"1y {it.chg_1y if it.chg_1y is not None else 'n/a'}%"
        )
    lines.append("")
    lines.append("📌 Comandos: /rank | /method | /ping")
    return "\n".join(lines)

def method_text() -> str:
    return (
        "🧪 *Fluxo científico (momentum ranking)*\n"
        "1) *Coleta* (CoinGecko markets)\n"
        "2) *Filtro* (Mcap/Vol mínimos + Vol24>MCAP)\n"
        "3) *Features*:\n"
        "   - Ratio = Vol24/Mcap (pressão de giro)\n"
        "   - Momentum: 1h, 12h (sparkline), 24h, 7d\n"
        "4) *Score* = pesos (W_RATIO, W_MOM_1H, W_MOM_12H, W_MOM_24H, W_MOM_7D)\n"
        "5) *Ranking* (ratio desc, score desc)\n"
        "6) *Validação* (no Bybit: Fluxo de Fundos 12H+1H + suporte 1H)\n"
        "7) *Gestão de risco* (sem virar bag): entrada fracionada + stop técnico + trailing\n"
    )
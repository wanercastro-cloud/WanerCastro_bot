from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from adaptive_weights import get_weights
from config import SETTINGS


STABLE_KEYWORDS = ["usd", "usdt", "usdc", "dai", "busd", "tusd", "fdusd", "usde"]


@dataclass
class Pick:
    coin_id: str
    symbol: str
    name: str
    score: float
    probability: str
    expected_upside: tuple[float, float]
    label: str
    thesis: str
    indicators: Dict
    current_price: float
    market_cap: float
    volume_24h: float


def _clip(x: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, x))


def is_valid_market_row(row: Dict) -> bool:
    symbol = str(row.get("symbol", "")).lower()
    if SETTINGS.exclude_stables and any(k in symbol for k in STABLE_KEYWORDS):
        return False
    mc = float(row.get("market_cap") or 0)
    v = float(row.get("total_volume") or 0)
    return SETTINGS.min_mcap <= mc <= SETTINGS.max_mcap and v >= SETTINGS.min_vol24


def trend_score(ind: Dict) -> float:
    p, e20, e50 = ind["price"], ind["ema20"], ind["ema50"]
    if None in (p, e20, e50):
        return 0.15
    if p > e20 > e50:
        return 1.0
    if p > e20 and p > e50:
        return 0.78
    if p > e50:
        return 0.45
    return 0.15


def macd_score(ind: Dict) -> float:
    now, prev = ind["macd_hist_now"], ind["macd_hist_prev"]
    if now is None or prev is None:
        return 0.15
    if now > 0 and now > prev:
        return 1.0
    if now > 0:
        return 0.75
    if now > prev:
        return 0.50
    return 0.15


def rsi_score(ind: Dict) -> float:
    r = ind["rsi14"]
    if r is None:
        return 0.15
    if 45 <= r <= 62:
        return 1.0
    if 40 <= r < 45 or 62 < r <= 68:
        return 0.72
    if 35 <= r < 40 or 68 < r <= 72:
        return 0.45
    return 0.18


def adx_score(ind: Dict) -> float:
    adx = ind["adx14"]
    plus_di = ind["plus_di"]
    minus_di = ind["minus_di"]
    if None in (adx, plus_di, minus_di):
        return 0.15
    if adx >= 25 and plus_di > minus_di:
        return 1.0
    if adx >= 20 and plus_di > minus_di:
        return 0.78
    if adx >= 18:
        return 0.50
    return 0.15


def mfi_score(ind: Dict) -> float:
    x = ind["mfi14"]
    if x is None:
        return 0.15
    if 45 <= x <= 70:
        return 1.0
    if 35 <= x < 45 or 70 < x <= 76:
        return 0.72
    if 25 <= x < 35:
        return 0.45
    return 0.18


def atr_score(ind: Dict) -> float:
    atr = ind["atr14"]
    price = ind["price"]
    high_20 = ind["high_20"]
    if None in (atr, price, high_20) or price == 0:
        return 0.15
    atr_pct = atr / price
    room = (high_20 - price) / price
    if 0.02 <= atr_pct <= 0.06 and room >= 0.05:
        return 1.0
    if atr_pct <= 0.08 and room >= 0.03:
        return 0.70
    if room >= 0.02:
        return 0.45
    return 0.15


def bollinger_score(ind: Dict) -> float:
    pos = ind["bb_position"]
    if pos is None:
        return 0.15
    if 0.45 <= pos <= 0.85:
        return 1.0
    if 0.30 <= pos < 0.45 or 0.85 < pos <= 0.95:
        return 0.65
    return 0.18


def roc_score(ind: Dict) -> float:
    x = ind["roc9"]
    if x is None:
        return 0.15
    if 1.5 <= x <= 8.0:
        return 1.0
    if 0.3 <= x < 1.5:
        return 0.72
    if 8.0 < x <= 12.0:
        return 0.50
    return 0.18


def exhaustion_score(ind: Dict) -> float:
    rsi = ind["rsi14"] or 0
    bb_pos = ind["bb_position"] or 0
    price = ind["price"] or 0
    ema20 = ind["ema20"] or 0
    now = ind["macd_hist_now"] or 0
    prev = ind["macd_hist_prev"] or 0
    ext = ((price - ema20) / ema20) if ema20 else 0
    hot = 0.0
    if rsi >= 78:
        hot += 0.35
    elif rsi >= 72:
        hot += 0.24
    elif rsi >= 66:
        hot += 0.15
    if bb_pos >= 1.05:
        hot += 0.25
    elif bb_pos >= 0.95:
        hot += 0.17
    if ext >= 0.18:
        hot += 0.20
    elif ext >= 0.12:
        hot += 0.13
    if now > 0 and now < prev:
        hot += 0.20
    return round(_clip(hot) * 100, 2)


def probability_band(score: float) -> str:
    if score >= 82:
        return "68%–76%"
    if score >= 75:
        return "60%–67%"
    if score >= 68:
        return "53%–59%"
    if score >= 60:
        return "46%–52%"
    return "<46%"


def expected_upside(score: float, ex: float) -> tuple[float, float]:
    low = 1.8 + score * 0.04 - ex * 0.01
    high = 3.6 + score * 0.08 - ex * 0.02
    low = max(1.0, low)
    high = max(low + 1.5, high)
    return round(low, 1), round(high, 1)


def classify(score: float, ex: float) -> str:
    if ex >= SETTINGS.risk_freeze_exhaustion:
        return "⛔ EXAUSTO"
    if score >= 74:
        return "🌙 OVERNIGHT PREMIUM"
    if score >= 66:
        return "📈 CONTINUAÇÃO VÁLIDA"
    return "🟡 OBSERVAR"


def build_thesis(ind: Dict, label: str) -> str:
    parts: List[str] = []
    if ind.get("price") and ind.get("ema20") and ind.get("ema50") and ind["price"] > ind["ema20"] > ind["ema50"]:
        parts.append("EMA20/EMA50 alinhadas")
    if (ind.get("macd_hist_now") or -999) > 0:
        parts.append("MACD positivo")
    if (ind.get("adx14") or 0) >= 20:
        parts.append("tendência com tração")
    if 45 <= (ind.get("rsi14") or 0) <= 65:
        parts.append("RSI saudável")
    if 40 <= (ind.get("mfi14") or 0) <= 72:
        parts.append("fluxo ainda vivo")
    if label == "⛔ EXAUSTO":
        parts = ["está esticado demais para overnight"]
    return ", ".join(parts[:4]) or "sem vantagem técnica clara"


def overnight_score(ind: Dict) -> float:
    w = get_weights()
    score = (
        w["trend"] * trend_score(ind) +
        w["macd"] * macd_score(ind) +
        w["rsi"] * rsi_score(ind) +
        w["adx"] * adx_score(ind) +
        w["mfi"] * mfi_score(ind) +
        w["atr"] * atr_score(ind) +
        w["bollinger"] * bollinger_score(ind) +
        w["roc"] * roc_score(ind)
    ) * 100
    return round(score, 2)


def make_pick(row: Dict, ind: Dict) -> Pick:
    score = overnight_score(ind)
    ex = exhaustion_score(ind)
    label = classify(score, ex)
    return Pick(
        coin_id=row["id"],
        symbol=str(row["symbol"]).upper(),
        name=row.get("name", row["symbol"]),
        score=score,
        probability=probability_band(score if label != "⛔ EXAUSTO" else max(30, 100 - ex)),
        expected_upside=expected_upside(score, ex),
        label=label,
        thesis=build_thesis(ind, label),
        indicators=ind,
        current_price=float(row.get("current_price") or 0),
        market_cap=float(row.get("market_cap") or 0),
        volume_24h=float(row.get("total_volume") or 0),
    )

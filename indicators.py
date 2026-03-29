from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class Candle:
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float


def market_chart_to_hourly_candles(payload: Dict) -> List[Candle]:
    prices = payload.get("prices", [])
    vols = payload.get("total_volumes", [])
    if len(prices) < 3 or len(vols) < 3:
        return []

    candles: List[Candle] = []
    for i in range(1, min(len(prices), len(vols))):
        prev_ts, prev_close = prices[i - 1]
        ts, close = prices[i]
        _, vol = vols[i]
        open_price = prev_close
        high = max(open_price, close)
        low = min(open_price, close)
        candles.append(Candle(ts=int(ts), open=float(open_price), high=float(high), low=float(low), close=float(close), volume=float(vol)))
    return candles


def ema(values: List[float], period: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return out
    alpha = 2 / (period + 1)
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(values)):
        prev = (values[i] - prev) * alpha + prev
        out[i] = prev
    return out


def sma(values: List[float], period: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return out
    total = sum(values[:period])
    out[period - 1] = total / period
    for i in range(period, len(values)):
        total += values[i] - values[i - period]
        out[i] = total / period
    return out


def rsi(closes: List[float], period: int = 14) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(closes)
    if len(closes) <= period:
        return out
    gains, losses = [], []
    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    out[period] = 100.0 if avg_loss == 0 else 100 - (100 / (1 + (avg_gain / avg_loss)))
    for i in range(period + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
        out[i] = 100.0 if avg_loss == 0 else 100 - (100 / (1 + (avg_gain / avg_loss)))
    return out


def macd(closes: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, List[Optional[float]]]:
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    macd_line: List[Optional[float]] = [None] * len(closes)
    for i in range(len(closes)):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            macd_line[i] = ema_fast[i] - ema_slow[i]
    signal_line = ema([x if x is not None else 0.0 for x in macd_line], signal)
    hist: List[Optional[float]] = [None] * len(closes)
    for i in range(len(closes)):
        if macd_line[i] is not None and signal_line[i] is not None:
            hist[i] = macd_line[i] - signal_line[i]
    return {"macd_line": macd_line, "signal_line": signal_line, "histogram": hist}


def atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(closes)
    if len(closes) <= period:
        return out
    trs = [0.0]
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    first = sum(trs[1:period + 1]) / period
    out[period] = first
    prev = first
    for i in range(period + 1, len(closes)):
        prev = ((prev * (period - 1)) + trs[i]) / period
        out[i] = prev
    return out


def roc(closes: List[float], period: int = 9) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(closes)
    for i in range(period, len(closes)):
        base = closes[i - period]
        out[i] = None if base == 0 else ((closes[i] - base) / base) * 100.0
    return out


def bollinger(closes: List[float], period: int = 20, std_mult: float = 2.0) -> Dict[str, List[Optional[float]]]:
    mid = sma(closes, period)
    upper: List[Optional[float]] = [None] * len(closes)
    lower: List[Optional[float]] = [None] * len(closes)
    width: List[Optional[float]] = [None] * len(closes)
    position: List[Optional[float]] = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1:i + 1]
        mean = sum(window) / period
        var = sum((x - mean) ** 2 for x in window) / period
        sd = math.sqrt(var)
        upper[i] = mean + std_mult * sd
        lower[i] = mean - std_mult * sd
        if mean != 0:
            width[i] = (upper[i] - lower[i]) / mean
        band = upper[i] - lower[i]
        if band != 0:
            position[i] = (closes[i] - lower[i]) / band
    return {"mid": mid, "upper": upper, "lower": lower, "width": width, "position": position}


def mfi(highs: List[float], lows: List[float], closes: List[float], volumes: List[float], period: int = 14) -> List[Optional[float]]:
    tps = [(h + l + c) / 3.0 for h, l, c in zip(highs, lows, closes)]
    flows = [tp * v for tp, v in zip(tps, volumes)]
    pos = [0.0]
    neg = [0.0]
    for i in range(1, len(tps)):
        if tps[i] > tps[i - 1]:
            pos.append(flows[i]); neg.append(0.0)
        elif tps[i] < tps[i - 1]:
            pos.append(0.0); neg.append(flows[i])
        else:
            pos.append(0.0); neg.append(0.0)
    out: List[Optional[float]] = [None] * len(closes)
    for i in range(period, len(closes)):
        ps = sum(pos[i - period + 1:i + 1])
        ns = sum(neg[i - period + 1:i + 1])
        if ns == 0:
            out[i] = 100.0
        else:
            mr = ps / ns
            out[i] = 100 - (100 / (1 + mr))
    return out


def adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Dict[str, List[Optional[float]]]:
    n = len(closes)
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    tr = [0.0] * n
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm[i] = up if up > down and up > 0 else 0.0
        minus_dm[i] = down if down > up and down > 0 else 0.0
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    plus_s = [None] * n
    minus_s = [None] * n
    tr_s = [None] * n
    if n <= period:
        return {"adx": [None] * n, "plus_di": [None] * n, "minus_di": [None] * n}
    plus_s[period] = sum(plus_dm[1:period + 1])
    minus_s[period] = sum(minus_dm[1:period + 1])
    tr_s[period] = sum(tr[1:period + 1])
    for i in range(period + 1, n):
        plus_s[i] = plus_s[i - 1] - (plus_s[i - 1] / period) + plus_dm[i]
        minus_s[i] = minus_s[i - 1] - (minus_s[i - 1] / period) + minus_dm[i]
        tr_s[i] = tr_s[i - 1] - (tr_s[i - 1] / period) + tr[i]
    plus_di: List[Optional[float]] = [None] * n
    minus_di: List[Optional[float]] = [None] * n
    dx: List[Optional[float]] = [None] * n
    for i in range(period, n):
        if tr_s[i] and tr_s[i] != 0:
            plus_di[i] = 100 * (plus_s[i] / tr_s[i])
            minus_di[i] = 100 * (minus_s[i] / tr_s[i])
            denom = plus_di[i] + minus_di[i]
            if denom != 0:
                dx[i] = 100 * abs(plus_di[i] - minus_di[i]) / denom
    adx_vals: List[Optional[float]] = [None] * n
    first = [x for x in dx[period:period * 2] if x is not None]
    if len(first) == period:
        adx_vals[period * 2 - 1] = sum(first) / period
        for i in range(period * 2, n):
            if dx[i] is not None and adx_vals[i - 1] is not None:
                adx_vals[i] = ((adx_vals[i - 1] * (period - 1)) + dx[i]) / period
    return {"adx": adx_vals, "plus_di": plus_di, "minus_di": minus_di}


def indicator_pack(candles: List[Candle]) -> Dict[str, Optional[float]]:
    if len(candles) < 60:
        raise ValueError("Use pelo menos 60 candles horários.")
    closes = [c.close for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    vols = [c.volume for c in candles]
    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    rsi14 = rsi(closes, 14)
    macd_pack = macd(closes)
    atr14 = atr(highs, lows, closes)
    roc9 = roc(closes)
    bb = bollinger(closes)
    mfi14 = mfi(highs, lows, closes, vols)
    adx_pack = adx(highs, lows, closes)
    return {
        "price": closes[-1],
        "ema20": ema20[-1],
        "ema50": ema50[-1],
        "rsi14": rsi14[-1],
        "macd_line_now": macd_pack["macd_line"][-1],
        "macd_signal_now": macd_pack["signal_line"][-1],
        "macd_hist_now": macd_pack["histogram"][-1],
        "macd_hist_prev": macd_pack["histogram"][-2],
        "atr14": atr14[-1],
        "roc9": roc9[-1],
        "mfi14": mfi14[-1],
        "bb_width": bb["width"][-1],
        "bb_position": bb["position"][-1],
        "adx14": adx_pack["adx"][-1],
        "plus_di": adx_pack["plus_di"][-1],
        "minus_di": adx_pack["minus_di"][-1],
        "high_20": max(highs[-20:]),
        "low_20": min(lows[-20:]),
        "vol_now": vols[-1],
        "vol_ma": sum(vols[-20:]) / 20,
    }

from statistics import mean
import math


def ema(values, period):
    out = [None] * len(values)
    if len(values) < period:
        return out
    alpha = 2 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = (values[i] - prev) * alpha + prev
        out[i] = prev
    return out


def sma(values, period):
    out = [None] * len(values)
    if len(values) < period:
        return out
    for i in range(period - 1, len(values)):
        out[i] = sum(values[i - period + 1:i + 1]) / period
    return out


def rsi(closes, period=14):
    out = [None] * len(closes)
    if len(closes) <= period:
        return out
    gains, losses = [], []
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    rs = avg_gain / avg_loss if avg_loss else math.inf
    out[period] = 100 - 100 / (1 + rs)
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        gain = max(d, 0)
        loss = max(-d, 0)
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
        rs = avg_gain / avg_loss if avg_loss else math.inf
        out[i] = 100 - 100 / (1 + rs)
    return out


def macd(closes, fast=12, slow=26, signal=9):
    fast_ema = ema(closes, fast)
    slow_ema = ema(closes, slow)
    macd_line = [None] * len(closes)
    for i in range(len(closes)):
        if fast_ema[i] is not None and slow_ema[i] is not None:
            macd_line[i] = fast_ema[i] - slow_ema[i]
    sig = ema([x if x is not None else 0 for x in macd_line], signal)
    hist = [None] * len(closes)
    for i in range(len(closes)):
        if macd_line[i] is not None and sig[i] is not None:
            hist[i] = macd_line[i] - sig[i]
    return macd_line, sig, hist


def true_range(highs, lows, closes):
    out = [None]
    for i in range(1, len(closes)):
        out.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    return out


def atr(highs, lows, closes, period=14):
    tr = true_range(highs, lows, closes)
    out = [None] * len(closes)
    if len(closes) <= period:
        return out
    first = sum(x for x in tr[1:period + 1] if x is not None) / period
    out[period] = first
    prev = first
    for i in range(period + 1, len(closes)):
        prev = ((prev * (period - 1)) + tr[i]) / period
        out[i] = prev
    return out


def roc(closes, period=9):
    out = [None] * len(closes)
    for i in range(period, len(closes)):
        base = closes[i - period]
        out[i] = ((closes[i] - base) / base) * 100 if base else None
    return out


def mfi(highs, lows, closes, volumes, period=14):
    typical = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
    flow = [tp * v for tp, v in zip(typical, volumes)]
    pos = [0]
    neg = [0]
    for i in range(1, len(typical)):
        if typical[i] > typical[i - 1]:
            pos.append(flow[i]); neg.append(0)
        elif typical[i] < typical[i - 1]:
            pos.append(0); neg.append(flow[i])
        else:
            pos.append(0); neg.append(0)
    out = [None] * len(closes)
    for i in range(period, len(closes)):
        p = sum(pos[i - period + 1:i + 1]); n = sum(neg[i - period + 1:i + 1])
        if n == 0:
            out[i] = 100
        else:
            mr = p / n
            out[i] = 100 - (100 / (1 + mr))
    return out


def bollinger(closes, period=20, mult=2):
    mid = sma(closes, period)
    upper = [None] * len(closes)
    lower = [None] * len(closes)
    width = [None] * len(closes)
    pos = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        w = closes[i - period + 1:i + 1]
        m = sum(w) / period
        var = sum((x - m) ** 2 for x in w) / period
        sd = math.sqrt(var)
        upper[i] = m + mult * sd
        lower[i] = m - mult * sd
        width[i] = (upper[i] - lower[i]) / m if m else None
        rng = upper[i] - lower[i]
        pos[i] = (closes[i] - lower[i]) / rng if rng else None
    return mid, upper, lower, width, pos


def adx(highs, lows, closes, period=14):
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
    if n <= period * 2:
        return [None] * n, [None] * n, [None] * n
    plus_s[period] = sum(plus_dm[1:period + 1])
    minus_s[period] = sum(minus_dm[1:period + 1])
    tr_s[period] = sum(tr[1:period + 1])
    for i in range(period + 1, n):
        plus_s[i] = plus_s[i - 1] - plus_s[i - 1] / period + plus_dm[i]
        minus_s[i] = minus_s[i - 1] - minus_s[i - 1] / period + minus_dm[i]
        tr_s[i] = tr_s[i - 1] - tr_s[i - 1] / period + tr[i]
    plus_di = [None] * n
    minus_di = [None] * n
    dx = [None] * n
    for i in range(period, n):
        if tr_s[i]:
            plus_di[i] = 100 * plus_s[i] / tr_s[i]
            minus_di[i] = 100 * minus_s[i] / tr_s[i]
            denom = plus_di[i] + minus_di[i]
            dx[i] = (100 * abs(plus_di[i] - minus_di[i]) / denom) if denom else None
    adx_vals = [None] * n
    first = [x for x in dx[period:period * 2] if x is not None]
    if len(first) == period:
        adx_vals[period * 2 - 1] = sum(first) / period
        for i in range(period * 2, n):
            if dx[i] is not None and adx_vals[i - 1] is not None:
                adx_vals[i] = ((adx_vals[i - 1] * (period - 1)) + dx[i]) / period
    return adx_vals, plus_di, minus_di


def build_indicator_pack_from_market_chart(data):
    prices = data["prices"]
    vols = data["total_volumes"]

    closes = [float(x[1]) for x in prices]
    volumes = [float(x[1]) for x in vols]
    highs = closes[:]
    lows = closes[:]

    e20 = ema(closes, 20)
    e50 = ema(closes, 50)
    rs = rsi(closes, 14)
    macd_line, macd_signal, macd_hist = macd(closes)
    at = atr(highs, lows, closes, 14)
    rc = roc(closes, 9)
    mf = mfi(highs, lows, closes, volumes, 14)
    bb_mid, bb_up, bb_low, bb_width, bb_pos = bollinger(closes)
    adx_vals, plus_di, minus_di = adx(highs, lows, closes, 14)

    if len(closes) < 60:
        raise ValueError("Poucos candles horÃ¡rios para indicadores")

    return {
        "price": closes[-1],
        "ema20": e20[-1],
        "ema50": e50[-1],
        "rsi14": rs[-1],
        "macd_hist_now": macd_hist[-1],
        "macd_hist_prev": macd_hist[-2],
        "macd_line_now": macd_line[-1],
        "macd_signal_now": macd_signal[-1],
        "atr14": at[-1],
        "roc9": rc[-1],
        "mfi14": mf[-1],
        "bb_position": bb_pos[-1],
        "bb_width": bb_width[-1],
        "adx14": adx_vals[-1],
        "plus_di": plus_di[-1],
        "minus_di": minus_di[-1],
        "high_20": max(closes[-20:]),
        "vol_now": volumes[-1],
        "vol_ma": mean(volumes[-20:]),
    }

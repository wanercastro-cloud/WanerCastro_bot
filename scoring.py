# -*- coding: utf-8 -*-

def _safe(v, default=0.0):
    return default if v is None else v


def smart_money_score(coin, base_result):
    mcap = float(coin.get("market_cap") or 0)
    vol24 = float(coin.get("total_volume") or 0)
    chg_1h = float(coin.get("price_change_percentage_1h_in_currency") or 0)
    chg_24h = float(coin.get("price_change_percentage_24h_in_currency") or 0)

    if mcap <= 0:
        return 0.0

    vol_mcap = vol24 / mcap
    accel = chg_1h - (chg_24h / 24.0)

    if vol_mcap >= 1.5:
        vm_score = 1.0
    elif vol_mcap >= 0.8:
        vm_score = 0.75
    elif vol_mcap >= 0.35:
        vm_score = 0.45
    else:
        vm_score = 0.15

    if accel >= 1.2:
        accel_score = 1.0
    elif accel >= 0.5:
        accel_score = 0.75
    elif accel > 0:
        accel_score = 0.45
    else:
        accel_score = 0.15

    if 0 < chg_1h <= 4:
        mom_score = 1.0
    elif 4 < chg_1h <= 7:
        mom_score = 0.7
    elif chg_1h > 7:
        mom_score = 0.35
    else:
        mom_score = 0.2

    overheat = 0.0
    if chg_24h > 10:
        overheat += 0.25
    if chg_24h > 16:
        overheat += 0.35
    if chg_24h > 25:
        overheat += 0.40

    health = float(base_result["score"]) / 100.0

    score = (
        0.34 * vm_score +
        0.26 * accel_score +
        0.18 * mom_score +
        0.22 * health
    ) * 100.0

    score -= overheat * 100.0
    return round(max(score, 0.0), 1)


def score_coin(coin, ind):
    price = _safe(ind.get("price"))
    ema20 = _safe(ind.get("ema20"))
    ema50 = _safe(ind.get("ema50"))
    rsi = _safe(ind.get("rsi14"))
    hist = _safe(ind.get("macd_hist_now"))
    hist_prev = _safe(ind.get("macd_hist_prev"))
    adx = _safe(ind.get("adx14"))
    mfi = _safe(ind.get("mfi14"))
    atr = _safe(ind.get("atr14"))
    bb_pos = _safe(ind.get("bb_position"), 0.5)
    roc = _safe(ind.get("roc9"))
    vol_now = _safe(ind.get("vol_now"))
    vol_ma = _safe(ind.get("vol_ma"), 1.0)

    chg_24h = float(coin.get("price_change_percentage_24h_in_currency") or 0)

    # TREND
    if price > ema20 > ema50:
        trend = 1.0
    elif price > ema20:
        trend = 0.7
    elif price > ema50:
        trend = 0.4
    else:
        trend = 0.1

    # RSI saudÃ¡vel
    if 45 <= rsi <= 56:
        rsi_score = 1.0
    elif 40 <= rsi < 45:
        rsi_score = 0.75
    elif 56 < rsi <= 62:
        rsi_score = 0.55
    elif 62 < rsi <= 68:
        rsi_score = 0.25
    else:
        rsi_score = 0.1

    # MACD
    if hist > 0 and hist >= hist_prev:
        macd = 1.0
    elif hist > 0:
        macd = 0.7
    elif hist > hist_prev:
        macd = 0.5
    else:
        macd = 0.2

    # ADX
    if adx >= 30:
        adx_score = 1.0
    elif adx >= 25:
        adx_score = 0.75
    elif adx >= 20:
        adx_score = 0.45
    elif adx >= 15:
        adx_score = 0.2
    else:
        adx_score = 0.05

    # MFI
    if 45 <= mfi <= 70:
        mfi_score = 1.0
    elif 35 <= mfi < 45:
        mfi_score = 0.7
    else:
        mfi_score = 0.4

    # ATR
    atr_pct = (atr / price) if price and atr else 0
    if 0.02 <= atr_pct <= 0.06:
        atr_score = 1.0
    elif atr_pct <= 0.08:
        atr_score = 0.7
    else:
        atr_score = 0.3

    # Bollinger
    if bb_pos < 0.85:
        bb_score = 1.0
    elif bb_pos < 0.95:
        bb_score = 0.6
    else:
        bb_score = 0.2

    # ROC
    if 1 < roc <= 6:
        roc_score = 1.0
    elif 0 < roc <= 10:
        roc_score = 0.7
    else:
        roc_score = 0.3

    # Volume relativo
    if vol_now >= vol_ma * 1.2:
        vol_score = 1.0
    elif vol_now >= vol_ma:
        vol_score = 0.7
    else:
        vol_score = 0.4

    score = (
        0.22 * trend +
        0.18 * macd +
        0.16 * rsi_score +
        0.14 * adx_score +
        0.10 * mfi_score +
        0.08 * atr_score +
        0.05 * bb_score +
        0.04 * roc_score +
        0.03 * vol_score
    ) * 100

    # Penalidades leves
    if chg_24h > 10:
        score -= 6
    if chg_24h > 14:
        score -= 10
    if chg_24h > 18:
        score -= 14

    if chg_24h < -10:
        score -= 8
    if chg_24h < -15:
        score -= 12

    if rsi > 68:
        score -= 10
    if rsi < 30:
        score -= 8

    if adx < 15:
        score -= 10

    score = max(score, 0)

    if score >= 72:
        label = "FORTE"
    elif score >= 58:
        label = "NEUTRO"
    else:
        label = "FRACO"

    result = {
        "symbol": coin["symbol"].upper(),
        "score": round(score, 1),
        "label": label,
        "rsi": round(rsi, 1),
        "adx": round(adx, 1),
        "chg_24h": round(chg_24h, 2),
    }
    result["smart_score"] = smart_money_score(coin, result)
    return result


def build_ranking_text(results, top_n=5):
    ranked = sorted(results, key=lambda x: x["score"], reverse=True)[:top_n]

    lines = ["SMART MONEY RANKING (SAUDAVEL)\n"]

    for i, r in enumerate(ranked, 1):
        lines.append(
            f"{i:02d}. {r['symbol']} | {r['score']} | {r['label']}\n"
            f"RSI {r['rsi']} | ADX {r['adx']} | 24h {r['chg_24h']}%\n"
        )

    return "\n".join(lines)


def build_smartmoney_text(results, top_n=5):
    ranked = sorted(results, key=lambda x: x["smart_score"], reverse=True)[:top_n]

    lines = ["SMART MONEY RANKING (PRE-PUMP PROXY)\n"]

    for i, r in enumerate(ranked, 1):
        lines.append(
            f"{i:02d}. {r['symbol']} | smart {r['smart_score']} | base {r['score']} | {r['label']}\n"
            f"RSI {r['rsi']} | ADX {r['adx']} | 24h {r['chg_24h']}%\n"
        )

    return "\n".join(lines)
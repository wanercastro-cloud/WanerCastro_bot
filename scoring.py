# -*- coding: utf-8 -*-
def _safe(v, default=0.0):
    return default if v is None else v


def overnight_score(coin, ind):
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
    high_20 = _safe(ind.get("high_20"), price)
    vol_now = _safe(ind.get("vol_now"))
    vol_ma = _safe(ind.get("vol_ma"), 1.0)

    chg_1h = float(coin.get("price_change_percentage_1h_in_currency") or 0)
    chg_24h = float(coin.get("price_change_percentage_24h_in_currency") or 0)
    chg_7d = float(coin.get("price_change_percentage_7d_in_currency") or 0)

    # Tendência válida só se estrutura estiver saudável
    trend = 1.0 if (price > ema20 > ema50) else (0.35 if price > ema20 and ema20 >= ema50 else 0.0)

    # MACD
    if hist > 0 and hist >= hist_prev:
        macd_score = 1.0
    elif hist > 0 and hist < hist_prev:
        macd_score = 0.55
    elif hist <= 0 and hist > hist_prev:
        macd_score = 0.25
    else:
        macd_score = 0.0

    # RSI conservador
    if 46 <= rsi <= 58:
        rsi_score = 1.0
    elif 40 <= rsi < 46:
        rsi_score = 0.72
    elif 58 < rsi <= 64:
        rsi_score = 0.35
    else:
        rsi_score = 0.10

    # ADX só vale se não estiver mascarando queda
    if adx >= 28:
        adx_score = 1.0
    elif adx >= 23:
        adx_score = 0.75
    elif adx >= 20:
        adx_score = 0.45
    else:
        adx_score = 0.10

    # MFI
    if 45 <= mfi <= 68:
        mfi_score = 1.0
    elif 38 <= mfi < 45:
        mfi_score = 0.72
    elif 68 < mfi <= 75:
        mfi_score = 0.35
    else:
        mfi_score = 0.15

    # ATR
    atr_pct = (atr / price) if price and atr else 0.0
    if 0.018 <= atr_pct <= 0.055:
        atr_score = 1.0
    elif 0.010 <= atr_pct <= 0.075:
        atr_score = 0.72
    else:
        atr_score = 0.28

    # Bollinger
    if bb_pos < 0.78:
        bb_score = 1.0
    elif bb_pos < 0.88:
        bb_score = 0.65
    else:
        bb_score = 0.15

    # ROC
    if 0.5 < roc <= 6:
        roc_score = 1.0
    elif 0 < roc <= 10:
        roc_score = 0.65
    else:
        roc_score = 0.20

    # Volume relativo
    if vol_now >= vol_ma * 1.25:
        vol_score = 1.0
    elif vol_now >= vol_ma * 1.05:
        vol_score = 0.72
    else:
        vol_score = 0.25

    base_score = (
        0.24 * trend +
        0.18 * macd_score +
        0.16 * rsi_score +
        0.14 * adx_score +
        0.10 * mfi_score +
        0.08 * atr_score +
        0.05 * bb_score +
        0.03 * roc_score +
        0.02 * vol_score
    ) * 100

    room = max((high_20 - price) / price, 0) if price else 0
    penalty = 0

    # Exaustão / pump recente
    if rsi > 64:
        penalty += 12
    if rsi > 70:
        penalty += 18

    if bb_pos > 0.90:
        penalty += 12
    if bb_pos > 0.97:
        penalty += 10

    if hist < hist_prev:
        penalty += 10
    if hist <= 0:
        penalty += 12

    if chg_24h > 12:
        penalty += 14
    if chg_24h > 18:
        penalty += 12

    if chg_7d > 35:
        penalty += 14
    if chg_7d > 60:
        penalty += 12

    if room < 0.05:
        penalty += 10
    if room < 0.03:
        penalty += 10

    if mfi > 78:
        penalty += 10

    if chg_1h > 4.5:
        penalty += 8

    # Colapso / faca caindo
    if chg_24h <= -12:
        penalty += 18
    if chg_24h <= -20:
        penalty += 25
    if chg_24h <= -35:
        penalty += 35

    if rsi < 32:
        penalty += 16
    if rsi < 26:
        penalty += 24

    if price < ema20:
        penalty += 15
    if ema20 < ema50:
        penalty += 18
    if price < ema20 and ema20 < ema50:
        penalty += 25

    if adx < 20:
        penalty += 12

    score = max(base_score - penalty, 0.0)
    exhaustion = min(max(penalty * 1.6, 0.0), 100.0)

    # Trava dura para overnight ruim
    hard_reject = (
        chg_24h <= -15 or
        rsi < 30 or
        price < ema20 or
        ema20 < ema50
    )

    if hard_reject:
        grade = "D"
        label = "EVITAR"
    else:
        if score >= 82 and exhaustion < 28:
            grade = "A+"
            label = "OVERNIGHT PREMIUM"
        elif score >= 74 and exhaustion < 38:
            grade = "A"
            label = "FORTE"
        elif score >= 64 and exhaustion < 52:
            grade = "B"
            label = "CONTINUACAO VALIDA"
        elif score >= 54 and exhaustion < 65:
            grade = "C"
            label = "OBSERVAR"
        else:
            grade = "D"
            label = "EVITAR"

    if grade == "A+":
        low = round(3.5 + score * 0.025, 1)
        high = round(6.5 + score * 0.05, 1)
        prob = "68%-76%"
    elif grade == "A":
        low = round(3.0 + score * 0.022, 1)
        high = round(5.5 + score * 0.042, 1)
        prob = "60%-68%"
    elif grade == "B":
        low = round(2.2 + score * 0.020, 1)
        high = round(4.2 + score * 0.035, 1)
        prob = "52%-60%"
    elif grade == "C":
        low = round(1.2 + score * 0.015, 1)
        high = round(2.8 + score * 0.028, 1)
        prob = "45%-52%"
    else:
        low, high, prob = 0.5, 2.5, "<45%"

    return {
        "id": coin["id"],
        "symbol": coin["symbol"].upper(),
        "name": coin["name"],
        "price": float(coin.get("current_price") or 0),
        "chg_1h": chg_1h,
        "chg_24h": chg_24h,
        "chg_7d": chg_7d,
        "score": round(score, 1),
        "grade": grade,
        "label": label,
        "probability": prob,
        "expected_upside_pct": (low, high),
        "rsi14": round(rsi, 1),
        "adx14": round(adx, 1) if adx else 0.0,
        "exhaustion": round(exhaustion, 1),
    }


def score_coin(coin, ind):
    return overnight_score(coin, ind)


def build_overnight_ranking_text(results, top_n=3):
    picks = [r for r in results if r["grade"] in ("A+", "A", "B")]
    picks = sorted(picks, key=lambda x: x["score"], reverse=True)[:top_n]

    if not picks:
        return (
            "OVERNIGHT PICK PRO\n\n"
            "Nenhum setup overnight confiavel agora.\n"
            "Status: mercado sem ativo com qualidade minima para carregar."
        )

    lines = ["OVERNIGHT PICK PRO"]
    for i, r in enumerate(picks, 1):
        lo, hi = r["expected_upside_pct"]
        lines.append(
            f"{i:02d}. {r['symbol']} | {r['grade']} | score {r['score']}\n"
            f"Chance: {r['probability']} | Upside: +{lo}% a +{hi}%\n"
            f"RSI: {r['rsi14']} | ADX: {r['adx14']} | 24h: {r['chg_24h']:.2f}% | Exaustao: {r['exhaustion']:.1f}"
        )
    return "\n\n".join(lines)


def build_radar_text(results, top_n=5):
    aplus = sorted([r for r in results if r["grade"] == "A+"], key=lambda x: x["score"], reverse=True)[:top_n]
    strong = sorted([r for r in results if r["grade"] == "A"], key=lambda x: x["score"], reverse=True)[:top_n]
    continuation = sorted([r for r in results if r["grade"] == "B"], key=lambda x: x["score"], reverse=True)[:top_n]
    avoid = sorted([r for r in results if r["grade"] == "D"], key=lambda x: x["exhaustion"], reverse=True)[:top_n]

    def block(title, rows):
        if not rows:
            return title + "\n(nenhum)"
        out = [title]
        for i, r in enumerate(rows, 1):
            lo, hi = r["expected_upside_pct"]
            out.append(
                f"{i:02d}. {r['symbol']} | {r['grade']} | {r['score']} | {r['probability']} | +{lo}% a +{hi}%"
            )
        return "\n".join(out)

    return "\n\n".join([
        "SMART MONEY RADAR PRO V2",
        block("A+ PREMIUM", aplus),
        block("A FORTE", strong),
        block("B CONTINUACAO", continuation),
        block("D EVITAR", avoid),
    ])

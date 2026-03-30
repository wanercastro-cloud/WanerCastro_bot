def _safe(v, default=0.0):
    return default if v is None else v


def overnight_score(coin, ind):
    price = _safe(ind["price"])
    ema20 = _safe(ind["ema20"])
    ema50 = _safe(ind["ema50"])
    rsi = _safe(ind["rsi14"])
    hist = _safe(ind["macd_hist_now"])
    hist_prev = _safe(ind["macd_hist_prev"])
    adx = _safe(ind["adx14"])
    mfi = _safe(ind["mfi14"])
    atr = _safe(ind["atr14"])
    bb_pos = _safe(ind["bb_position"], 0.5)
    roc = _safe(ind["roc9"])
    high_20 = _safe(ind["high_20"], price)
    vol_now = _safe(ind["vol_now"])
    vol_ma = _safe(ind["vol_ma"], 1.0)

    trend = 1.0 if price > ema20 > ema50 else (0.7 if price > ema20 else 0.2)
    macd = 1.0 if hist > 0 and hist >= hist_prev else (0.7 if hist > 0 else (0.5 if hist > hist_prev else 0.2))
    rsi_score = 1.0 if 45 <= rsi <= 62 else (0.75 if 40 <= rsi < 45 else (0.6 if 62 < rsi <= 68 else 0.3))
    adx_score = 1.0 if adx >= 25 else (0.75 if adx >= 20 else (0.5 if adx >= 18 else 0.2))
    mfi_score = 1.0 if 45 <= mfi <= 70 else (0.75 if 35 <= mfi < 45 else (0.4 if mfi > 75 else 0.3))
    atr_pct = (atr / price) if price and atr else 0.0
    atr_score = 1.0 if 0.02 <= atr_pct <= 0.06 else (0.7 if atr_pct <= 0.08 else 0.3)
    bb_score = 1.0 if bb_pos < 0.85 else (0.7 if bb_pos < 0.95 else 0.2)
    roc_score = 1.0 if roc > 2 else (0.7 if roc > 0 else 0.3)
    vol_score = 1.0 if vol_now >= vol_ma * 1.15 else (0.7 if vol_now >= vol_ma else 0.35)

    score = (
        0.20 * trend +
        0.18 * macd +
        0.14 * rsi_score +
        0.12 * adx_score +
        0.10 * mfi_score +
        0.10 * atr_score +
        0.06 * bb_score +
        0.05 * roc_score +
        0.05 * vol_score
    ) * 100

    room = max((high_20 - price) / price, 0) if price else 0
    exhaustion = 0
    if rsi > 72:
        exhaustion += 30
    if bb_pos > 0.95:
        exhaustion += 25
    if hist < hist_prev:
        exhaustion += 20
    if room < 0.03:
        exhaustion += 15
    if mfi > 80:
        exhaustion += 10

    label = "ð OVERNIGHT PREMIUM" if score >= 70 and exhaustion < 50 else ("ð CONTINUAÃÃO VÃLIDA" if score >= 60 and exhaustion < 60 else ("â EXAUSTO" if exhaustion >= 60 else "ð¡ OBSERVAR"))

    if label == "ð OVERNIGHT PREMIUM":
        low = round(3 + score * 0.03, 1)
        high = round(6 + score * 0.06, 1)
        prob = "64%â71%" if score >= 78 else "56%â63%"
    elif label == "ð CONTINUAÃÃO VÃLIDA":
        low = round(2 + score * 0.025, 1)
        high = round(4 + score * 0.045, 1)
        prob = "56%â63%" if score >= 70 else "48%â55%"
    elif label == "â EXAUSTO":
        low, high, prob = 0.5, 3.0, "<48%"
    else:
        low = round(1.5 + score * 0.02, 1)
        high = round(3 + score * 0.03, 1)
        prob = "48%â55%"

    return {
        "id": coin["id"],
        "symbol": coin["symbol"].upper(),
        "name": coin["name"],
        "price": float(coin.get("current_price") or 0),
        "chg_1h": float(coin.get("price_change_percentage_1h_in_currency") or 0),
        "chg_24h": float(coin.get("price_change_percentage_24h_in_currency") or 0),
        "chg_7d": float(coin.get("price_change_percentage_7d_in_currency") or 0),
        "score": round(score, 1),
        "label": label,
        "probability": prob,
        "expected_upside_pct": (low, high),
        "rsi14": round(rsi, 1),
        "adx14": round(adx, 1) if adx else 0,
        "exhaustion": round(exhaustion, 1),
    }


def score_coin(coin, ind):
    return overnight_score(coin, ind)


def build_overnight_ranking_text(results, top_n=3):
    premium = [r for r in results if r["label"] == "ð OVERNIGHT PREMIUM"]
    premium.sort(key=lambda x: x["score"], reverse=True)
    if not premium:
        premium = sorted(results, key=lambda x: x["score"], reverse=True)
    premium = premium[:top_n]

    lines = ["ð OVERNIGHT PICK"]
    for i, r in enumerate(premium, 1):
        lo, hi = r["expected_upside_pct"]
        lines.append(
            f"{i:02d}. {r['symbol']} | score {r['score']}\n"
            f"Chance: {r['probability']} | Upside: +{lo}% a +{hi}%\n"
            f"RSI: {r['rsi14']} | ADX: {r['adx14']} | 24h: {r['chg_24h']:.2f}%"
        )
    return "\n\n".join(lines)


def build_radar_text(results, top_n=5):
    overnight = sorted([r for r in results if r["label"] == "ð OVERNIGHT PREMIUM"], key=lambda x: x["score"], reverse=True)[:top_n]
    continuation = sorted([r for r in results if r["label"] == "ð CONTINUAÃÃO VÃLIDA"], key=lambda x: x["score"], reverse=True)[:top_n]
    avoid = sorted([r for r in results if r["label"] == "â EXAUSTO"], key=lambda x: x["exhaustion"], reverse=True)[:top_n]

    def block(title, rows):
        if not rows:
            return title + "\n(nenhum)"
        out = [title]
        for i, r in enumerate(rows, 1):
            lo, hi = r["expected_upside_pct"]
            out.append(f"{i:02d}. {r['symbol']} | {r['score']} | {r['probability']} | +{lo}% a +{hi}%")
        return "\n".join(out)

    return "\n\n".join([
        "ð SMART MONEY RADAR",
        block("ð OVERNIGHT PREMIUM", overnight),
        block("ð CONTINUAÃÃO VÃLIDA", continuation),
        block("â EVITAR", avoid),
    ])

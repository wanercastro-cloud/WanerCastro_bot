# -*- coding: utf-8 -*-

def _safe(v, default=0.0):
    return default if v is None else v


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

    # =========================
    # TREND
    # =========================
    if price > ema20 > ema50:
        trend = 1.0
    elif price > ema20:
        trend = 0.7
    elif price > ema50:
        trend = 0.4
    else:
        trend = 0.1

    # =========================
    # RSI
    # =========================
    if 46 <= rsi <= 58:
        rsi_score = 1.0
    elif 40 <= rsi < 46:
        rsi_score = 0.75
    elif 58 < rsi <= 64:
        rsi_score = 0.6
    else:
        rsi_score = 0.3

    # =========================
    # MACD
    # =========================
    if hist > 0 and hist >= hist_prev:
        macd = 1.0
    elif hist > 0:
        macd = 0.7
    elif hist > hist_prev:
        macd = 0.5
    else:
        macd = 0.2

    # =========================
    # ADX
    # =========================
    if adx >= 25:
        adx_score = 1.0
    elif adx >= 20:
        adx_score = 0.7
    else:
        adx_score = 0.4

    # =========================
    # MFI
    # =========================
    if 45 <= mfi <= 70:
        mfi_score = 1.0
    elif 35 <= mfi < 45:
        mfi_score = 0.7
    else:
        mfi_score = 0.4

    # =========================
    # ATR (volatilidade saudável)
    # =========================
    atr_pct = (atr / price) if price and atr else 0
    if 0.02 <= atr_pct <= 0.06:
        atr_score = 1.0
    elif atr_pct <= 0.08:
        atr_score = 0.7
    else:
        atr_score = 0.3

    # =========================
    # BOLLINGER
    # =========================
    if bb_pos < 0.85:
        bb_score = 1.0
    elif bb_pos < 0.95:
        bb_score = 0.6
    else:
        bb_score = 0.2

    # =========================
    # ROC (impulso)
    # =========================
    if roc > 2:
        roc_score = 1.0
    elif roc > 0:
        roc_score = 0.7
    else:
        roc_score = 0.3

    # =========================
    # VOLUME
    # =========================
    if vol_now >= vol_ma * 1.2:
        vol_score = 1.0
    elif vol_now >= vol_ma:
        vol_score = 0.7
    else:
        vol_score = 0.4

    # =========================
    # SCORE FINAL
    # =========================
    score = (
        0.22 * trend +
        0.18 * macd +
        0.16 * rsi_score +
        0.12 * adx_score +
        0.10 * mfi_score +
        0.08 * atr_score +
        0.07 * bb_score +
        0.07 * roc_score +
        0.05 * vol_score
    ) * 100

    # =========================
    # PENALIDADES LEVES
    # =========================
    if chg_24h > 15:
        score -= 8  # pump
    if chg_24h < -15:
        score -= 10  # dump
    if rsi > 70:
        score -= 8
    if rsi < 30:
        score -= 6

    score = max(score, 0)

    # =========================
    # CLASSIFICAÇÃO SIMPLES
    # =========================
    if score >= 75:
        label = "FORTE"
    elif score >= 60:
        label = "NEUTRO"
    else:
        label = "FRACO"

    return {
        "symbol": coin["symbol"].upper(),
        "score": round(score, 1),
        "label": label,
        "rsi": round(rsi, 1),
        "adx": round(adx, 1),
        "chg_24h": round(chg_24h, 2)
    }


# =========================
# TEXTO DO TELEGRAM
# =========================
def build_ranking_text(results, top_n=5):
    ranked = sorted(results, key=lambda x: x["score"], reverse=True)[:top_n]

    lines = ["SMART MONEY RANKING\n"]

    for i, r in enumerate(ranked, 1):
        lines.append(
            f"{i:02d}. {r['symbol']} | {r['score']} | {r['label']}\n"
            f"RSI {r['rsi']} | ADX {r['adx']} | 24h {r['chg_24h']}%\n"
        )

    return "\n".join(lines)
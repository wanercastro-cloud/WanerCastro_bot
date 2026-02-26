from typing import Dict, List
from config import TRAIL_PCT
from scoring import fmt_money

def anti_bag_stop(price: float, low_24h: float) -> float:
    if price <= 0:
        return 0.0
    trail = price * (1.0 - TRAIL_PCT)
    if low_24h and low_24h > 0:
        return max(trail, low_24h)
    return trail

def build_fomo_report(cands: List[Dict], top_n: int = 5) -> str:
    if not cands:
        return "⚠️ Nenhum candidato passou nos filtros (ajuste MIN_MCAP/MAX_MCAP/MIN_VOL24/MAX_1H_P/MAX_24H_P)."

    lines = [f"🔥 SMART MONEY PRÉ-PUMP (Top {min(top_n, len(cands))})"]

    for i, c in enumerate(cands[:top_n], 1):
        stop = anti_bag_stop(float(c["price"]), float(c.get("low_24h") or 0.0))
        flag = "🟡" if c.get("premium_flag") else "⚪️"
        lines.append(
            f"\n<b>{i}) {c['symbol']}/USD</b> | <b>Score {c['score']:.1f}</b> {flag}\n"
            f"• Mcap: {fmt_money(c['mcap'])} | Vol24: {fmt_money(c['vol24'])}\n"
            f"• 1h: {c['chg_1h']:+.2f}% | 24h: {c['chg_24h']:+.2f}%\n"
            f"• 24h Low/High: {c.get('low_24h', 0):.6f} / {c.get('high_24h', 0):.6f}\n"
            f"• Anti-bag stop (trail): {stop:.6f}"
        )

    lines.append("\nLegenda: 🟡 = apareceu no endpoint premium (top_gainers_losers) quando disponível.")
    return "\n".join(lines)
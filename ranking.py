from typing import List, Dict
from scoring import compute_score, fmt_money


def build_fomo_report(candidates: List[Dict]) -> str:
    if not candidates:
        return "⚠️ Nenhum candidato encontrado."

    lines = ["🔥 SMART MONEY PRÉ-PUMP"]

    for i, c in enumerate(candidates, 1):
        lines.append(
            f"\n{i}) {c['symbol']}/USD | Score {c['score']:.1f}\n"
            f"• Mcap: {fmt_money(c['mcap'])} | Vol24: {fmt_money(c['vol24'])}\n"
            f"• 1h: {c['chg_1h']:+.2f}% | 24h: {c['chg_24h']:+.2f}%"
        )

    return "\n".join(lines)
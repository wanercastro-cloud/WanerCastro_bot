from typing import List
from telegram.constants import ParseMode

from config import Settings
from scoring import fmt_money
from ranking import Candidate

def format_radar(items: List[Candidate], settings: Settings) -> str:
    if not items:
        return (
            "⚠️ Sem candidatos no filtro atual.\n\n"
            "Dica rápida:\n"
            "• reduza MIN_MCAP / MIN_VOL24\n"
            "• aumente MAX_MCAP\n"
            "• diminua MIN_VM\n"
        )

    lines = [f"🔥 <b>SMART MONEY PRÉ-PUMP</b> (Top {len(items)})"]
    for i, it in enumerate(items, 1):
        lines.append(
            f"\n<b>{i}) {it.symbol}/{settings.vs_currency.upper()}</b> | <b>Score {it.score:.1f}</b>\n"
            f"• Mcap: {fmt_money(it.mcap)} | Vol24: {fmt_money(it.vol24)}\n"
            f"• 1h: {it.chg_1h:+.2f}% | 24h: {it.chg_24h:+.2f}%"
        )
    return "\n".join(lines)

PARSE_MODE = ParseMode.HTML
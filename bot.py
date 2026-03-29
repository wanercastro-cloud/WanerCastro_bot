import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from __future__ import annotations

import traceback
from typing import Dict, List

from telegram import Bot

from coingecko_client import CoinGeckoClient
from config import SETTINGS
from indicators import indicator_pack, market_chart_to_hourly_candles
from performance_tracker import adapt_from_recent_results, close_pick, due_reviews, performance_summary, record_pick
from scheduler import run_loop
from strategy import Pick, is_valid_market_row, make_pick
from utils import fmt_pct, now_tz


bot = Bot(token=SETTINGS.telegram_bot_token)
client = CoinGeckoClient()


def send(msg: str) -> None:
    bot.send_message(chat_id=SETTINGS.telegram_chat_id, text=msg)


def build_pick_payload(pick: Pick) -> Dict:
    return {
        "coin_id": pick.coin_id,
        "symbol": pick.symbol,
        "label": pick.label,
        "score": pick.score,
        "entry_price": pick.current_price,
        "picked_at": now_tz().isoformat(),
        "reviewed": False,
    }


def rank_candidates() -> List[Pick]:
    rows = client.get_markets()
    ranked: List[Pick] = []
    for row in rows:
        if not is_valid_market_row(row):
            continue
        try:
            chart = client.get_market_chart(row["id"], days=30)
            candles = market_chart_to_hourly_candles(chart)
            if len(candles) < 60:
                continue
            ind = indicator_pack(candles)
            pick = make_pick(row, ind)
            ranked.append(pick)
        except Exception:
            continue
    ranked.sort(key=lambda x: x.score, reverse=True)
    return ranked


def format_pick_line(i: int, p: Pick) -> str:
    low, high = p.expected_upside
    return (
        f"{i:02d}. {p.symbol} | {p.label}\n"
        f"   Score: {p.score} | Chance: {p.probability} | Upside: +{low}% a +{high}%\n"
        f"   Tese: {p.thesis}"
    )


def run_overnight() -> None:
    ranked = rank_candidates()
    best = [x for x in ranked if x.label in {"🌙 OVERNIGHT PREMIUM", "📈 CONTINUAÇÃO VÁLIDA"}][: SETTINGS.overnight_top_n]
    if not best:
        send("🌙 Overnight: nenhum setup forte hoje. Melhor não forçar entrada.")
        return
    lines = [f"🌙 PICKS OVERNIGHT | {now_tz().strftime('%d/%m %H:%M')} BRT", ""]
    for i, p in enumerate(best, 1):
        lines.append(format_pick_line(i, p))
        lines.append("")
        record_pick(build_pick_payload(p))
    send("\n".join(lines).strip())


def run_review() -> None:
    due = due_reviews()
    if not due:
        return
    current_markets = {row["id"]: row for row in client.get_markets()}
    reviewed_msgs = []
    for pick in due:
        row = current_markets.get(pick["coin_id"])
        if not row:
            continue
        result = close_pick(pick, float(row.get("current_price") or 0))
        reviewed_msgs.append(
            f"🧾 REVIEW {result['symbol']}\n"
            f"Entrada: {result['entry_price']:.6f}\n"
            f"Saída: {result['exit_price']:.6f}\n"
            f"Resultado: {fmt_pct(result['return_pct'])}"
        )
    if reviewed_msgs:
        send("\n\n".join(reviewed_msgs[:3]))
    if SETTINGS.adapt_weights:
        updated = adapt_from_recent_results()
        if updated:
            send(
                "🧠 Ajuste leve de pesos aplicado\n"
                f"trend={updated['trend']:.2f}, macd={updated['macd']:.2f}, adx={updated['adx']:.2f}, rsi={updated['rsi']:.2f}"
            )


def run_status() -> None:
    summary = performance_summary()
    if summary["count"] == 0:
        return
    send(
        f"📊 STATUS OVERNIGHT\n"
        f"Trades avaliados: {summary['count']}\n"
        f"Win rate: {summary['win_rate']}%\n"
        f"Retorno médio: {summary['avg_return']:+.2f}%"
    )


def main() -> None:
    if SETTINGS.send_startup_message:
        send("🤖 Overnight bot iniciado.")
    run_loop(run_overnight=run_overnight, run_review=run_review, run_status=run_status)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise

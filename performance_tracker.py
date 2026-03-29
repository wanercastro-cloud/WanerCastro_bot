from __future__ import annotations

from typing import Dict, List

from adaptive_weights import nudge_weights
from config import SETTINGS
from utils import load_json, now_tz, pct, save_json


PICKS_PATH = "data/picks.json"
RESULTS_PATH = "data/results.json"


def _load_picks() -> List[Dict]:
    return load_json(PICKS_PATH, [])


def _save_picks(rows: List[Dict]) -> None:
    save_json(PICKS_PATH, rows)


def _load_results() -> List[Dict]:
    return load_json(RESULTS_PATH, [])


def _save_results(rows: List[Dict]) -> None:
    save_json(RESULTS_PATH, rows)


def record_pick(pick: Dict) -> None:
    rows = _load_picks()
    rows.append(pick)
    _save_picks(rows)


def due_reviews() -> List[Dict]:
    rows = _load_picks()
    due = []
    now = now_tz()
    for row in rows:
        if row.get("reviewed"):
            continue
        picked_at = now.fromisoformat(row["picked_at"])
        hours = (now - picked_at).total_seconds() / 3600
        if hours >= SETTINGS.review_hours_after_pick:
            due.append(row)
    return due


def close_pick(pick: Dict, current_price: float) -> Dict:
    result = {
        "coin_id": pick["coin_id"],
        "symbol": pick["symbol"],
        "picked_at": pick["picked_at"],
        "reviewed_at": now_tz().isoformat(),
        "entry_price": pick["entry_price"],
        "exit_price": current_price,
        "return_pct": round(pct(current_price, pick["entry_price"]), 2),
        "label": pick["label"],
        "score": pick["score"],
    }
    results = _load_results()
    results.append(result)
    _save_results(results)
    rows = _load_picks()
    for row in rows:
        if row["coin_id"] == pick["coin_id"] and row["picked_at"] == pick["picked_at"]:
            row["reviewed"] = True
            row["reviewed_at"] = result["reviewed_at"]
            row["exit_price"] = current_price
            row["return_pct"] = result["return_pct"]
    _save_picks(rows)
    return result


def performance_summary(last_n: int = 30) -> Dict:
    rows = _load_results()[-last_n:]
    if not rows:
        return {"count": 0, "avg_return": 0.0, "win_rate": 0.0}
    wins = sum(1 for r in rows if r["return_pct"] > 0)
    avg_return = sum(r["return_pct"] for r in rows) / len(rows)
    return {
        "count": len(rows),
        "avg_return": round(avg_return, 2),
        "win_rate": round((wins / len(rows)) * 100.0, 1),
    }


def adapt_from_recent_results(last_n: int = 20) -> Dict[str, float] | None:
    rows = _load_results()[-last_n:]
    if len(rows) < 8:
        return None
    avg = sum(r["return_pct"] for r in rows) / len(rows)
    # intentionally simple: when returns are positive, favor trend+macd+adx; otherwise cool them a little.
    perf = {
        "trend": 0.6 if avg > 2 else -0.3 if avg < 0 else 0.0,
        "macd": 0.6 if avg > 2 else -0.2 if avg < 0 else 0.0,
        "adx": 0.5 if avg > 2 else -0.2 if avg < 0 else 0.0,
        "bollinger": -0.2 if avg > 4 else 0.1,
        "rsi": 0.1,
        "mfi": 0.1,
        "atr": 0.0,
        "roc": 0.0,
    }
    return nudge_weights(perf)

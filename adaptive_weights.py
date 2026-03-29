from __future__ import annotations

from typing import Dict

from utils import load_json, save_json


WEIGHTS_PATH = "data/weights.json"
DEFAULT_WEIGHTS = {
    "trend": 0.24,
    "macd": 0.18,
    "rsi": 0.13,
    "adx": 0.12,
    "mfi": 0.10,
    "atr": 0.09,
    "bollinger": 0.07,
    "roc": 0.07,
}


def get_weights() -> Dict[str, float]:
    data = load_json(WEIGHTS_PATH, DEFAULT_WEIGHTS)
    total = sum(data.values()) or 1.0
    return {k: v / total for k, v in data.items()}


def nudge_weights(perf: Dict[str, float]) -> Dict[str, float]:
    current = get_weights()
    # perf is expected in range -1..+1
    for key, delta in perf.items():
        if key in current:
            current[key] = max(0.03, current[key] + (delta * 0.015))
    total = sum(current.values()) or 1.0
    current = {k: v / total for k, v in current.items()}
    save_json(WEIGHTS_PATH, current)
    return current

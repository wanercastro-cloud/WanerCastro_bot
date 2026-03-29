from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

import pytz

from config import SETTINGS


TZ = pytz.timezone(SETTINGS.timezone)


def now_tz() -> datetime:
    return datetime.now(TZ)


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def load_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data: Any) -> None:
    ensure_dir(os.path.dirname(path) or ".")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def pct(a: float, b: float) -> float:
    if b == 0:
        return 0.0
    return ((a - b) / b) * 100.0


def fmt_pct(x: float) -> str:
    return f"{x:+.1f}%"

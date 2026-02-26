import math
from dataclasses import dataclass
from typing import List, Tuple


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def fmt_money(x: float) -> str
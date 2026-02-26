import math
from dataclasses import dataclass
from typing import Dict, Tuple

STABLE_SYMBOLS = {
    "USDT", "USDC", "DAI", "TUSD", "USDE", "USDQ", "FDUSD", "PYUSD",
    "EUR", "GBP", "JPY", "TRY", "BRL"
}

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0

def is_stable_like(symbol: str) -> bool:
    s = (symbol or "").upper().strip()
    return (s in STABLE_SYMBOLS) or s.endswith("USD") or s.endswith("USDT") or s.endswith("USDC")

def fmt_money(x: float) -> str:
    if x >= 1e9:
        return f"${x/1e9:.2f}B"
    if x >= 1e6:
        return f"${x/1e6:.2f}M"
    if x >= 1e3:
        return f"${x/1e3:.2f}K"
    return f"${x:.0f}"

@dataclass
class CandidateScore:
    symbol: str
    name: str
    cg_id: str
    price: float
    mcap: float
    vol24: float
    chg_1h: float
    chg_24h: float
    score: float
    notes: str = ""

def compute_smartmoney_score(mcap: float, vol24: float, chg_1h: float, chg_24h: float, dex_boost: float = 0.0) -> Tuple[float, str]:
    vm = safe_div(vol24, mcap)
    vm_n = clamp(vm / 1.2, 0.0, 1.2)

    accel = (chg_1h - (chg_24h / 24.0))
    accel_n = clamp(accel / 2.5, -0.6, 1.2)

    mom1 = clamp(chg_1h / 6.0, -0.8, 1.3)
    mom24 = clamp(chg_24h / 18.0, -0.8, 1.3)

    overheat = clamp((chg_24h - 35.0) / 30.0, 0.0, 1.0)

    raw = 45.0 * vm_n + 20.0 * accel_n + 20.0 * mom1 + 15.0 * mom24 + 10.0 * dex_boost
    score = clamp(raw - 18.0 * overheat, 0.0, 100.0)
    return score, f"vm={vm:.2f} accel={accel:.2f} dex={dex_boost:.2f} overheat={overheat:.2f}"

def compute_sniper_score(
    mcap: float,
    vol24: float,
    chg_1h: float,
    chg_24h: float,
    vol_accel: float,
    dex_boost: float = 0.0,
    limits: Dict[str, float] | None = None,
) -> Tuple[float, str]:
    """
    Sniper = continuação cedo:
    - 1h positivo, mas não absurdo
    - 24h ainda “aceitável” (não é o topo do topo já esticado)
    - aceleração de volume (última hora vs média 6h)
    """
    limits = limits or {}
    max_1h = float(limits.get("max_1h", 18.0))
    max_24h = float(limits.get("max_24h", 35.0))

    vm = safe_div(vol24, mcap)
    vm_n = clamp(vm / 1.0, 0.0, 1.3)

    # volume acceleration já vem normalizado (0..~2)
    va_n = clamp(vol_accel, 0.0, 2.0)

    # favorece 1h positivo mas evita “vela foguete” já tardia
    mom1 = clamp(chg_1h / 8.0, -0.8, 1.2)
    penalty_1h = clamp((chg_1h - max_1h) / 10.0, 0.0, 1.0)
    penalty_24 = clamp((chg_24h - max_24h) / 20.0, 0.0, 1.0)

    raw = 45.0 * vm_n + 30.0 * va_n + 20.0 * mom1 + 10.0 * dex_boost
    score = clamp(raw - 25.0 * penalty_1h - 20.0 * penalty_24, 0.0, 100.0)

    return score, f"vm={vm:.2f} volAccel={vol_accel:.2f} dex={dex_boost:.2f} p1h={penalty_1h:.2f} p24={penalty_24:.2f}"
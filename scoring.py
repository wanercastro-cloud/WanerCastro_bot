import math
from typing import Tuple

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
    return (not s) or (s in STABLE_SYMBOLS)

def fmt_money(x: float) -> str:
    if x >= 1e9:
        return f"${x/1e9:.2f}B"
    if x >= 1e6:
        return f"${x/1e6:.2f}M"
    if x >= 1e3:
        return f"${x/1e3:.2f}K"
    return f"${x:.0f}"

def compute_score(
    mcap: float,
    vol24: float,
    chg_1h: float,
    chg_24h: float,
    prefer_mcap_lt_vol: bool,
) -> Tuple[float, str]:
    """
    Heurística Lite:
    - vol/mcap (atenção) + aceleração + momentum
    - bônus se mcap < vol24 (se ativado)
    - penaliza overheat (24h absurdo)
    """
    vm = safe_div(vol24, mcap)
    vm_n = clamp(vm / 1.2, 0.0, 1.25)

    accel = (chg_1h - (chg_24h / 24.0))
    accel_n = clamp(accel / 2.5, -0.6, 1.2)

    mom1 = clamp(chg_1h / 6.0, -0.8, 1.3)
    mom24 = clamp(chg_24h / 18.0, -0.8, 1.3)

    overheat = clamp((chg_24h - 40.0) / 40.0, 0.0, 1.0)

    bonus = 0.0
    if prefer_mcap_lt_vol and (mcap > 0) and (vol24 > mcap):
        # quando o volume de 24h supera a mcap: atenção extrema
        bonus = clamp(math.log10(vol24 / max(mcap, 1.0)) * 8.0, 0.0, 18.0)

    raw = (
        46.0 * vm_n +
        18.0 * accel_n +
        18.0 * mom1 +
        14.0 * mom24 +
        bonus
    )
    score = clamp(raw - 22.0 * overheat, 0.0, 100.0)

    notes = f"vm={vm:.2f} accel={accel:.2f} bonus={bonus:.1f} overheat={overheat:.2f}"
    return score, notes
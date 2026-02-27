import math
from typing import Tuple

from config import SETTINGS

STABLE_SYMBOLS = {
    "USDT", "USDC", "DAI", "TUSD", "USDE", "USDQ", "FDUSD", "PYUSD",
    "EUR", "GBP", "JPY", "TRY", "BRL"
}

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0

def is_stable_like(symbol: str) -> bool:
    if not symbol:
        return False
    s = symbol.upper().strip()
    return (s in STABLE_SYMBOLS) or s.endswith("USD") or s.endswith("USDT") or s.endswith("USDC")

def compute_score(
    mcap: float,
    vol24: float,
    chg_1h: float,
    chg_24h: float,
    dex_boost: float = 0.0,
) -> Tuple[float, str]:
    """
    Score focado em:
      - atenção do “smart money”: vol/mcap
      - aceleração: 1h vs (24h/24)
      - momentum (1h e 24h)
      - penalização por “super aquecido” em 24h
      - boost opcional de DEX (GeckoTerminal)
      - boost se mcap < vol24 (pedido seu)
    """
    vm = safe_div(vol24, mcap)
    vm_n = clamp(vm / 1.2, 0.0, 1.35)

    accel = (chg_1h - (chg_24h / 24.0))
    accel_n = clamp(accel / 2.5, -0.6, 1.2)

    mom1 = clamp(chg_1h / 6.0, -0.8, 1.3)
    mom24 = clamp(chg_24h / 18.0, -0.8, 1.3)

    # overheat: começa penalizar acima do seu threshold
    overheat_penalty = clamp((chg_24h - SETTINGS.OVERHEAT_24H) / 30.0, 0.0, 1.0)

    # boost “mcap < vol”
    mv_boost = 0.0
    if SETTINGS.BOOST_IF_MCAP_LT_VOL and (mcap > 0) and (vol24 > mcap):
        # cresce logaritmicamente com o excesso
        ratio = vol24 / mcap  # > 1
        mv_boost = clamp(math.log10(max(ratio, 1.0)) * 0.35, 0.0, 0.55)

    raw = (
        45.0 * vm_n +
        20.0 * accel_n +
        18.0 * mom1 +
        12.0 * mom24 +
        10.0 * dex_boost +
        12.0 * mv_boost
    )
    score = clamp(raw - 18.0 * overheat_penalty, 0.0, 100.0)

    notes = f"vm={vm:.2f} accel={accel:.2f} dex={dex_boost:.2f} mv_boost={mv_boost:.2f} overheat={overheat_penalty:.2f}"
    return score, notes
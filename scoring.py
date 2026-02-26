from typing import Tuple


def fmt_money(x: float) -> str:
    x = float(x or 0.0)
    if x >= 1e12:
        return f"${x/1e12:.2f}T"
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
    dex_boost: float = 0.0,
    overheat_24h: float = 35.0,
) -> Tuple[float, str]:
    # Volume / Mcap
    vm = vol24 / mcap if mcap else 0.0
    vm_n = min(vm / 1.2, 1.2)

    # Aceleração
    accel = chg_1h - (chg_24h / 24.0)
    accel_n = max(min(accel / 2.5, 1.2), -0.6)

    # Momentum
    mom1 = max(min(chg_1h / 6.0, 1.3), -0.8)
    mom24 = max(min(chg_24h / 18.0, 1.3), -0.8)

    # Penalização de overheat
    overheat_penalty = max((chg_24h - overheat_24h) / 30.0, 0.0)

    raw = (
        45 * vm_n +
        20 * accel_n +
        20 * mom1 +
        15 * mom24 +
        10 * dex_boost
    )

    score = max(min(raw - 18 * overheat_penalty, 100.0), 0.0)
    notes = f"vm={vm:.2f} accel={accel:.2f} dex={dex_boost:.2f}"

    return score, notes
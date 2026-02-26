from typing import Tuple
from config import OVERHEAT_24H

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
    cont_bonus: float = 0.0,
) -> Tuple[float, str]:
    vm = vol24 / mcap if mcap else 0.0
    vm_n = min(vm / 1.2, 1.2)

    accel = chg_1h - (chg_24h / 24.0)
    accel_n = max(min(accel / 2.5, 1.2), -0.6)

    mom1 = max(min(chg_1h / 6.0, 1.3), -0.8)
    mom24 = max(min(chg_24h / 18.0, 1.3), -0.8)

    overheat_penalty = max((chg_24h - OVERHEAT_24H) / 30.0, 0.0)

    raw = (
        45 * vm_n +
        20 * accel_n +
        20 * mom1 +
        15 * mom24 +
        10 * cont_bonus
    )

    score = max(min(raw - 18 * overheat_penalty, 100.0), 0.0)
    notes = f"vm={vm:.2f} accel={accel:.2f} cont={cont_bonus:.2f}"
    return score, notes

def continuation_bonus(price: float, high_24h: float, chg_1h: float, chg_24h: float) -> float:
    """
    “Surf continuação”: premia se:
    - 1h positivo (impulso recente)
    - 24h ainda não absurdamente esticado (evita topo)
    - preço relativamente perto da máxima 24h (pressionando resistência)
    """
    if price <= 0 or high_24h <= 0:
        return 0.0

    near_high = 1.0 - ((high_24h - price) / price)  # ~1 quando está colado na máxima
    near_high = max(min(near_high, 1.2), 0.0)

    if chg_1h < 0.5:
        return 0.0
    if chg_24h > 120:
        return 0.0

    # bônus suave (não deixa dominar o score)
    return max(min((near_high - 0.98) * 10.0, 1.2), 0.0)
from typing import List, Optional
from ranking import CoinRow, CHANGE_PERIODS

def _fmt_money(x: float) -> str:
    # compact
    absx = abs(x)
    if absx >= 1e12:
        return f"{x/1e12:.2f}T"
    if absx >= 1e9:
        return f"{x/1e9:.2f}B"
    if absx >= 1e6:
        return f"{x/1e6:.2f}M"
    if absx >= 1e3:
        return f"{x/1e3:.2f}K"
    return f"{x:.2f}"

def _fmt_pct(x: Optional[float]) -> str:
    if x is None:
        return "—"
    sign = "+" if x >= 0 else ""
    return f"{sign}{x:.2f}%"

def render_rank(rows: List[CoinRow], page: int, per_page: int) -> str:
    start = (page - 1) * per_page
    end = start + per_page
    chunk = rows[start:end]

    lines = []
    lines.append("📊 *RANK (VOL24 > MCAP)*  | ordenado por *(VOL24/MCAP)* desc")
    lines.append(f"Mostrando {start+1}-{min(end, len(rows))} de {len(rows)}\n")

    for i, r in enumerate(chunk, start=start + 1):
        lines.append(
            f"*{i:02d}) {r.symbol}* ({r.name})  | preço: `{r.price:.6g}`"
        )
        lines.append(
            f"• MCAP: `{_fmt_money(r.mcap)}` | VOL24: `{_fmt_money(r.vol24)}` | VOL/MCAP: `{r.ratio:.2f}x`"
        )
        # periods
        per_line = " | ".join([f"{p}:{_fmt_pct(r.changes.get(p))}" for p in ["1h","24h","7d","30d","200d","1y"]])
        lines.append(f"• Δ: {per_line}")
        lines.append(f"• 12h(calc): {_fmt_pct(r.chg12h)}")
        lines.append("")

    lines.append("Comandos: /rank 20 | /rank 50 2 | /detail bitcoin")
    return "\n".join(lines)

def render_detail(r: CoinRow) -> str:
    lines = []
    lines.append(f"🔎 *DETAIL* {r.symbol} ({r.name})")
    lines.append(f"• ID: `{r.id}`")
    lines.append(f"• Preço: `{r.price:.8g}`")
    lines.append(f"• MCAP: `{_fmt_money(r.mcap)}`")
    lines.append(f"• VOL24: `{_fmt_money(r.vol24)}`")
    lines.append(f"• VOL/MCAP: `{r.ratio:.2f}x`")
    lines.append("")
    lines.append("📈 *Variações (CoinGecko)*")
    for p in CHANGE_PERIODS:
        lines.append(f"• {p}: {_fmt_pct(r.changes.get(p))}")
    lines.append(f"• 12h(calc): {_fmt_pct(r.chg12h)}")
    return "\n".join(lines)
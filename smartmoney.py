from typing import Optional

from telegram.constants import ParseMode

from config import SETTINGS
from providers import CoinGeckoProvider
from ranking import format_top_message, build_ranking, fmt_money

def _pick_id_or_symbol(text: str) -> str:
    return (text or "").strip().lower()

async def cmd_coin(cg: CoinGeckoProvider, coin_id: str) -> str:
    data = await cg.coin_by_id(coin_id)
    if not data:
        return "⚠️ Não achei esse coin_id. Use o id do CoinGecko (ex: bitcoin, ethereum)."

    name = data.get("name") or coin_id
    symbol = (data.get("symbol") or "").upper()
    md = (data.get("market_data") or {}) if isinstance(data.get("market_data"), dict) else {}

    price = (md.get("current_price") or {}).get(SETTINGS.VS_CURRENCY)
    mcap = (md.get("market_cap") or {}).get(SETTINGS.VS_CURRENCY)
    vol = (md.get("total_volume") or {}).get(SETTINGS.VS_CURRENCY)

    chg_24h = md.get("price_change_percentage_24h") or 0.0
    chg_7d = md.get("price_change_percentage_7d") or 0.0

    parts = [
        f"🧠 <b>{name} ({symbol})</b>",
        f"• Price: <b>{price}</b> ({SETTINGS.VS_CURRENCY.upper()})",
        f"• Mcap: <b>{fmt_money(float(mcap or 0))}</b> | Vol24: <b>{fmt_money(float(vol or 0))}</b>",
        f"• Δ24h: <b>{float(chg_24h):+.2f}%</b> | Δ7d: <b>{float(chg_7d):+.2f}%</b>",
        f"• CoinGecko ID: <code>{coin_id}</code>",
    ]
    return "\n".join(parts)

async def cmd_chart(cg: CoinGeckoProvider, coin_id: str, days: int = 7) -> str:
    data = await cg.market_chart(coin_id, SETTINGS.VS_CURRENCY, days=days)
    prices = data.get("prices") or []
    if not prices:
        return "⚠️ Sem dados de chart agora."

    vals = [p[1] for p in prices if isinstance(p, list) and len(p) >= 2]
    if not vals:
        return "⚠️ Chart vazio."

    lo = min(vals)
    hi = max(vals)
    first = vals[0]
    last = vals[-1]
    pct = ((last - first) / first * 100.0) if first else 0.0

    return (
        f"📈 <b>Chart ({days}d)</b> <code>{coin_id}</code>\n"
        f"• Low: <b>{lo:.6g}</b> | High: <b>{hi:.6g}</b>\n"
        f"• Δ período: <b>{pct:+.2f}%</b>"
    )
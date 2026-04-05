import asyncio
import math
import os
import time
from typing import Any, Dict, List, Optional

import httpx

# =========================
# VARIÁVEIS RAILWAY
# =========================
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "").strip()
COINGECKO_BASE_URL = os.getenv("COINGECKO_BASE_URL", "https://pro-api.coingecko.com/api/v3").rstrip("/")
VS_CURRENCY = os.getenv("VS_CURRENCY", "usd").strip().lower()

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "").strip()

TOP_N = int(os.getenv("TOP_N", "10"))
CANDIDATES = int(os.getenv("CANDIDATES", "150"))

MIN_MCAP = float(os.getenv("MIN_MCAP", "2000000"))
MAX_MCAP = float(os.getenv("MAX_MCAP", "250000000"))
MIN_VOL24 = float(os.getenv("MIN_VOL24", "1500000"))
EXCLUDE_STABLES = os.getenv("EXCLUDE_STABLES", "true").lower() == "true"

# Subida
MIN_CHG_1H_UP = float(os.getenv("MIN_CHG_1H_UP", "1.2"))
MIN_ACCEL_UP = float(os.getenv("MIN_ACCEL_UP", "0.8"))
MIN_VM_UP = float(os.getenv("MIN_VM_UP", "0.35"))
MAX_CHG_24H_OVERHEAT = float(os.getenv("MAX_CHG_24H_OVERHEAT", "35"))

# Descida
MAX_CHG_1H_DOWN = float(os.getenv("MAX_CHG_1H_DOWN", "-1.8"))
MIN_VM_DOWN = float(os.getenv("MIN_VM_DOWN", "0.40"))
MIN_DUMP_24H = float(os.getenv("MIN_DUMP_24H", "-6"))

# Score
WEIGHT_VM = float(os.getenv("WEIGHT_VM", "45"))
WEIGHT_ACCEL = float(os.getenv("WEIGHT_ACCEL", "20"))
WEIGHT_CHG_1H = float(os.getenv("WEIGHT_CHG_1H", "20"))
WEIGHT_CHG_24H = float(os.getenv("WEIGHT_CHG_24H", "15"))
PENALTY_OVERHEAT = float(os.getenv("PENALTY_OVERHEAT", "18"))

# Alertas
MIN_SCORE_UP_ALERT = float(os.getenv("MIN_SCORE_UP_ALERT", "65"))
MIN_SCORE_DOWN_ALERT = float(os.getenv("MIN_SCORE_DOWN_ALERT", "60"))
ALERT_COOLDOWN_MIN = int(os.getenv("ALERT_COOLDOWN_MIN", "15"))

# Runtime
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "20"))
HTTP_RETRIES = int(os.getenv("HTTP_RETRIES", "3"))
SCAN_INTERVAL_MIN = int(os.getenv("SCAN_INTERVAL_MIN", "5"))
SEND_STARTUP_MESSAGE = os.getenv("SEND_STARTUP_MESSAGE", "true").lower() == "true"

STABLE_KEYWORDS = {
    "usdt", "usdc", "dai", "fdusd", "tusd", "usde", "usdd", "gusd",
    "susd", "lusd", "eurs", "eurc", "usdp", "pyusd", "rlusd", "usd"
}

LAST_ALERTS: Dict[str, float] = {}


def safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def clamp(v: float, low: float, high: float) -> float:
    return max(low, min(high, v))


def normalize(values: List[float]) -> List[float]:
    if not values:
        return []
    mn, mx = min(values), max(values)
    if math.isclose(mn, mx):
        return [0.5 for _ in values]
    return [(v - mn) / (mx - mn) for v in values]


def is_stable(symbol: str, name: str) -> bool:
    s = symbol.lower().strip()
    n = name.lower().strip()
    if s in STABLE_KEYWORDS:
        return True
    if s.endswith(("usd", "usdt", "usdc")):
        return True
    txt = f"{s} {n}"
    return any(k in txt.split() for k in STABLE_KEYWORDS)


def headers() -> Dict[str, str]:
    h = {"accept": "application/json"}
    if COINGECKO_API_KEY:
        h["x-cg-pro-api-key"] = COINGECKO_API_KEY
    return h


async def fetch_json(client: httpx.AsyncClient, path: str, params: Dict[str, Any]) -> Any:
    last_err: Optional[Exception] = None
    for attempt in range(1, HTTP_RETRIES + 1):
        try:
            r = await client.get(f"{COINGECKO_BASE_URL}{path}", params=params, headers=headers())
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            if attempt < HTTP_RETRIES:
                await asyncio.sleep(attempt)
    raise RuntimeError(f"Falha na API: {last_err}")


async def get_market() -> List[Dict[str, Any]]:
    params = {
        "vs_currency": VS_CURRENCY,
        "order": "volume_desc",
        "per_page": min(max(CANDIDATES, 50), 250),
        "page": 1,
        "sparkline": "false",
        "price_change_percentage": "1h,24h,7d"
    }
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        data = await fetch_json(client, "/coins/markets", params)
    if not isinstance(data, list):
        raise RuntimeError("Resposta inválida do CoinGecko")
    return data


def prepare_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        symbol = str(r.get("symbol", "")).upper()
        name = str(r.get("name", "")).strip()
        price = safe_float(r.get("current_price"))
        mcap = safe_float(r.get("market_cap"))
        vol24 = safe_float(r.get("total_volume"))
        chg_1h = safe_float(r.get("price_change_percentage_1h_in_currency"))
        chg_24h = safe_float(r.get("price_change_percentage_24h_in_currency"))
        chg_7d = safe_float(r.get("price_change_percentage_7d_in_currency"))

        if not symbol or mcap <= 0 or vol24 <= 0:
            continue
        if mcap < MIN_MCAP or mcap > MAX_MCAP:
            continue
        if vol24 < MIN_VOL24:
            continue
        if EXCLUDE_STABLES and is_stable(symbol, name):
            continue

        vm = vol24 / mcap
        accel = chg_1h - (chg_24h / 24.0)

        out.append({
            "symbol": symbol,
            "name": name,
            "price": price,
            "mcap": mcap,
            "vol24": vol24,
            "chg_1h": chg_1h,
            "chg_24h": chg_24h,
            "chg_7d": chg_7d,
            "vm": vm,
            "accel": accel
        })
    return out


def score_rows(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    if not rows:
        return {"up": [], "down": []}

    vm_n = normalize([r["vm"] for r in rows])
    accel_n = normalize([r["accel"] for r in rows])
    chg1_n = normalize([r["chg_1h"] for r in rows])
    chg24_n = normalize([r["chg_24h"] for r in rows])

    down_1h_base = normalize([abs(min(r["chg_1h"], 0)) for r in rows])
    down_24h_base = normalize([abs(min(r["chg_24h"], 0)) for r in rows])

    up_list = []
    down_list = []

    for i, r in enumerate(rows):
        overheat_penalty = clamp(max(0.0, r["chg_24h"] - MAX_CHG_24H_OVERHEAT) / 30.0, 0.0, 1.0)

        score_up = (
            WEIGHT_VM * vm_n[i] +
            WEIGHT_ACCEL * accel_n[i] +
            WEIGHT_CHG_1H * chg1_n[i] +
            WEIGHT_CHG_24H * chg24_n[i] -
            PENALTY_OVERHEAT * overheat_penalty
        )
        score_up = round(clamp(score_up, 0, 100), 1)

        up_signal = (
            r["chg_1h"] >= MIN_CHG_1H_UP and
            r["accel"] >= MIN_ACCEL_UP and
            r["vm"] >= MIN_VM_UP and
            r["chg_24h"] <= MAX_CHG_24H_OVERHEAT and
            score_up >= MIN_SCORE_UP_ALERT
        )

        if up_signal:
            up_list.append({**r, "score": score_up})

        score_down = (
            WEIGHT_VM * vm_n[i] +
            WEIGHT_CHG_1H * down_1h_base[i] +
            WEIGHT_CHG_24H * down_24h_base[i]
        )
        score_down = round(clamp(score_down, 0, 100), 1)

        down_signal = (
            r["chg_1h"] <= MAX_CHG_1H_DOWN and
            r["vm"] >= MIN_VM_DOWN and
            r["chg_24h"] <= MIN_DUMP_24H and
            score_down >= MIN_SCORE_DOWN_ALERT
        )

        if down_signal:
            down_list.append({**r, "score": score_down})

    up_list.sort(key=lambda x: x["score"], reverse=True)
    down_list.sort(key=lambda x: x["score"], reverse=True)

    return {"up": up_list[:TOP_N], "down": down_list[:TOP_N]}


def money(v: float) -> str:
    if v >= 1_000_000_000:
        return f"{v/1_000_000_000:.2f}B"
    if v >= 1_000_000:
        return f"{v/1_000_000:.2f}M"
    if v >= 1_000:
        return f"{v/1_000:.2f}K"
    return f"{v:.2f}"


def pct(v: float) -> str:
    return f"{'+' if v > 0 else ''}{v:.2f}%"


def cooldown_key(side: str, symbol: str) -> str:
    return f"{side}:{symbol}"


def can_send_alert(side: str, symbol: str) -> bool:
    key = cooldown_key(side, symbol)
    now = time.time()
    cooldown_sec = ALERT_COOLDOWN_MIN * 60
    last = LAST_ALERTS.get(key, 0)
    if now - last >= cooldown_sec:
        LAST_ALERTS[key] = now
        return True
    return False


def build_message(title: str, rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return f"{title}\n\nNenhum ativo passou no filtro."
    lines = [title, ""]
    for i, r in enumerate(rows, start=1):
        lines.append(
            f"{i:02d}. {r['symbol']} | score {r['score']} | "
            f"1h {pct(r['chg_1h'])} | 24h {pct(r['chg_24h'])} | 7d {pct(r['chg_7d'])}"
        )
        lines.append(
            f"vm {r['vm']:.2f}x | accel {pct(r['accel'])} | "
            f"preço ${r['price']:.6f} | mcap ${money(r['mcap'])} | vol ${money(r['vol24'])}"
        )
        lines.append("")
    return "\n".join(lines).strip()


def build_alert(side: str, r: Dict[str, Any]) -> str:
    emoji = "🚀" if side == "UP" else "📉"
    title = "ALERTA DE SUBIDA" if side == "UP" else "ALERTA DE DESCIDA"
    return (
        f"{emoji} {title}\n\n"
        f"{r['symbol']} ({r['name']})\n"
        f"score: {r['score']}\n"
        f"1h: {pct(r['chg_1h'])}\n"
        f"24h: {pct(r['chg_24h'])}\n"
        f"7d: {pct(r['chg_7d'])}\n"
        f"vm: {r['vm']:.2f}x\n"
        f"accel: {pct(r['accel'])}\n"
        f"preço: ${r['price']:.6f}\n"
        f"mcap: ${money(r['mcap'])}\n"
        f"vol24: ${money(r['vol24'])}"
    )


async def send_telegram(text: str) -> None:
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": text
    }
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()


async def run_once():
    rows = await get_market()
    prepared = prepare_rows(rows)
    ranked = score_rows(prepared)

    up_msg = build_message("🚀 SUBIDA - TOP VARIÁVEIS", ranked["up"])
    down_msg = build_message("📉 DESCIDA - TOP VARIÁVEIS", ranked["down"])

    print("\n" + up_msg + "\n")
    print("\n" + down_msg + "\n")

    await send_telegram(up_msg)
    await send_telegram(down_msg)

    for r in ranked["up"][:3]:
        if can_send_alert("UP", r["symbol"]):
            await send_telegram(build_alert("UP", r))

    for r in ranked["down"][:3]:
        if can_send_alert("DOWN", r["symbol"]):
            await send_telegram(build_alert("DOWN", r))


async def main():
    if not COINGECKO_API_KEY:
        raise RuntimeError("Defina COINGECKO_API_KEY no Railway.")

    if SEND_STARTUP_MESSAGE:
        try:
            await send_telegram("✅ Scanner de subida/descida iniciado no Railway.")
        except Exception:
            pass

    while True:
        try:
            await run_once()
        except Exception as e:
            err = f"⚠️ Erro no scanner: {str(e)[:300]}"
            print(err)
            try:
                await send_telegram(err)
            except Exception:
                pass
        await asyncio.sleep(SCAN_INTERVAL_MIN * 60)


if __name__ == "__main__":
    asyncio.run(main())
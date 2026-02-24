# smartmoney.py
from __future__ import annotations

import os
import math
import time
import requests
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

# =========================
# Config SAFE (ajuste fino)
# =========================
STABLE_KEYWORDS = {
    "usdt","usdc","usd","busd","dai","tusd","usdd","usdp","fdusd","eur","eurt","gbp","gbpt"
}
STABLE_SYMBOLS = {
    "u", "usdq", "fdusd", "usdc", "usdt", "dai", "tusd", "usdd", "usdp"
}

MIN_MCAP_USD = 20_000_000       # modo seguro: evita nano-cap
MIN_VOL24_USD = 3_000_000       # modo seguro: precisa rodar volume
MAX_MCAP_USD = 8_000_000_000    # opcional: evita gigantes "parados" (pode comentar)
MAX_PEG_DEVIATION = 0.012       # se preço ~1 e não varia, é peg/stable
MIN_ABS_PCT_24H = 0.15          # evita “travado”
MIN_ABS_PCT_1H  = 0.05          # evita “travado”
MAX_ABS_PCT_24H = 35.0          # modo seguro: se já estourou demais, vira chase
MAX_ABS_PCT_1H  = 12.0

TOP_N = 3
CURRENCY = "usd"


# =========================
# Helpers
# =========================
def _norm01(x: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.0
    if x <= lo:
        return 0.0
    if x >= hi:
        return 1.0
    return (x - lo) / (hi - lo)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _is_stable_like(symbol: str, name: str, price: float, p24: float, p1h: float) -> bool:
    s = (symbol or "").lower().strip()
    n = (name or "").lower().strip()

    if s in STABLE_SYMBOLS:
        return True
    if any(k in s for k in STABLE_KEYWORDS) or any(k in n for k in STABLE_KEYWORDS):
        return True

    # Peg heuristic: preço ~ 1 e mudanças muito pequenas
    if price and abs(price - 1.0) <= MAX_PEG_DEVIATION and abs(p24) < 0.25 and abs(p1h) < 0.15:
        return True

    return False


def _get_env(name: str, default: str = "") -> str:
    v = os.getenv(name, default)
    return v.strip() if isinstance(v, str) else default


# =========================
# CoinGecko Pro Markets
# =========================
def fetch_coingecko_markets(per_page: int = 250, pages: int = 4) -> List[Dict[str, Any]]:
    """
    Puxa dados do CoinGecko (Pro ou free).
    Requer:
      - COINGECKO_API_KEY (se Pro)
      - COINGECKO_BASE_URL (opcional)
        * Pro: https://pro-api.coingecko.com/api/v3
        * Free: https://api.coingecko.com/api/v3
    """
    api_key = _get_env("COINGECKO_API_KEY", "")
    base_url = _get_env("COINGECKO_BASE_URL", "https://pro-api.coingecko.com/api/v3")

    headers = {}
    # No Pro, a chave geralmente vai no header:
    if api_key:
        headers["x-cg-pro-api-key"] = api_key

    out: List[Dict[str, Any]] = []
    session = requests.Session()

    for page in range(1, pages + 1):
        url = f"{base_url}/coins/markets"
        params = {
            "vs_currency": CURRENCY,
            "order": "volume_desc",
            "per_page": per_page,
            "page": page,
            "sparkline": "false",
            "price_change_percentage": "1h,24h",
        }
        r = session.get(url, params=params, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list) or not data:
            break
        out.extend(data)
        time.sleep(0.25)  # gentil com rate limit

    return out


@dataclass
class Candidate:
    symbol: str
    name: str
    mcap: float
    vol24: float
    p1h: float
    p24: float
    score: float


def rank_smartmoney_safe(markets: List[Dict[str, Any]], top_n: int = TOP_N) -> List[Candidate]:
    cands: List[Candidate] = []

    for m in markets:
        symbol = str(m.get("symbol", "")).upper()
        name = str(m.get("name", ""))
        price = float(m.get("current_price") or 0.0)
        mcap = float(m.get("market_cap") or 0.0)
        vol24 = float(m.get("total_volume") or 0.0)

        # CoinGecko pode retornar None
        p1h = float(m.get("price_change_percentage_1h_in_currency") or 0.0)
        p24 = float(m.get("price_change_percentage_24h_in_currency") or 0.0)

        # ===== filtros SAFE =====
        if _is_stable_like(symbol, name, price, p24, p1h):
            continue
        if mcap < MIN_MCAP_USD:
            continue
        if vol24 < MIN_VOL24_USD:
            continue
        if MAX_MCAP_USD and mcap > MAX_MCAP_USD:
            continue

        # evita “travado” e evita “já foi”
        if abs(p24) < MIN_ABS_PCT_24H and abs(p1h) < MIN_ABS_PCT_1H:
            continue
        if abs(p24) > MAX_ABS_PCT_24H or abs(p1h) > MAX_ABS_PCT_1H:
            continue

        # ===== score SAFE =====
        # 1) Liquidez: volume relativo ao mcap (turnover)
        turnover = (vol24 / mcap) if mcap > 0 else 0.0
        s_turnover = _norm01(turnover, 0.03, 0.40)  # 3% a 40%

        # 2) Pré-pump "saudável": leve alta no 1h sem estar frenético
        # - penaliza muito negativo e muito alto
        s_1h = _norm01(p1h, 0.05, 2.50)  # 0.05% a 2.5%
        if p1h < -0.8:
            s_1h *= 0.55

        # 3) 24h: de leve a moderado (evita chase)
        s_24h = _norm01(p24, 0.20, 10.0)
        if p24 < -4.0:
            s_24h *= 0.60

        # 4) “Qualidade” por tamanho: mid-caps tendem a ser menos scam
        # favorece 30M–1B (curva log)
        log_m = math.log10(max(mcap, 1.0))
        s_size = _clamp(_norm01(log_m, math.log10(3e7), math.log10(1e9)), 0.0, 1.0)

        # 5) Penalidade: micro-cap + volume alto demais pode ser wash
        wash_risk = 0.0
        if mcap < 80_000_000 and turnover > 0.60:
            wash_risk = 0.25

        # Combinação SAFE (pesos)
        raw = (
            0.38 * s_turnover +
            0.22 * s_1h +
            0.20 * s_24h +
            0.20 * s_size
        )
        raw = max(0.0, raw - wash_risk)

        # Escala 0–100
        score = round(raw * 100.0, 1)

        cands.append(Candidate(
            symbol=f"{symbol}/USDT",
            name=name,
            mcap=mcap,
            vol24=vol24,
            p1h=p1h,
            p24=p24,
            score=score
        ))

    cands.sort(key=lambda x: x.score, reverse=True)
    return cands[:top_n]


def format_top(cands: List[Candidate]) -> str:
    if not cands:
        return "⚠️ SMART MONEY PRÉ-PUMP (SAFE)\nNenhuma moeda passou nos filtros (liquidez/volatilidade)."

    lines = ["🔥 SMART MONEY PRÉ-PUMP (SAFE TOP 3)"]
    for i, c in enumerate(cands, 1):
        lines.append(f"{i}) {c.symbol} | Score {c.score}")
        lines.append(f"   Mcap ${c.mcap:,.0f} | Vol24 ${c.vol24:,.0f}")
        lines.append(f"   1h {c.p1h:+.2f}% | 24h {c.p24:+.2f}%")
    return "\n".join(lines)


def run_safe_top3() -> str:
    markets = fetch_coingecko_markets(per_page=250, pages=4)
    top = rank_smartmoney_safe(markets, top_n=TOP_N)
    return format_top(top)
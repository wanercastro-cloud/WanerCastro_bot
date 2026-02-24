import os
import math
import requests

BASE = os.getenv("COINGECKO_BASE_URL", "https://pro-api.coingecko.com/api/v3").strip()
KEY = os.getenv("COINGECKO_API_KEY", "").strip()

if not KEY:
    raise RuntimeError("COINGECKO_API_KEY não definido nas variáveis de ambiente do Railway.")

# Excluir stablecoins óbvias (IDs do CoinGecko)
STABLE_IDS = {
    "tether", "usd-coin", "dai", "true-usd", "frax", "usdd", "first-digital-usd", "ethena-usde"
}


def _cg_get(path: str, params: dict | None = None):
    headers = {"x-cg-pro-api-key": KEY}
    r = requests.get(f"{BASE}{path}", params=params or {}, headers=headers, timeout=25)
    r.raise_for_status()
    return r.json()


def scan_prepump_top3() -> list[dict]:
    """
    Pré-pump smart money (6–24h):
    Filtros:
      - MCAP 5M–500M
      - Vol24 >= 30% MCAP
      - 24h <= +8%
      - 1h  <= +1.5%
    Score (0–100+) com pesos similares ao prompt:
      A (volume relativo) alto, mas sem pump
      B (silêncio: vol alto com preço baixo)
      C (p24 flat/levemente negativo)
      D (volume agressivo p/ tamanho)
      E (sem euforia: p24 < 5 e 1h baixo)
    Retorna TOP 3.
    """

    data = _cg_get("/coins/markets", {
        "vs_currency": "usd",
        "order": "volume_desc",
        "per_page": 250,
        "page": 1,
        "sparkline": "false",
        "price_change_percentage": "1h,24h"
    })

    candidates: list[dict] = []

    for c in data:
        cid = (c.get("id") or "").strip()
        if not cid or cid in STABLE_IDS:
            continue

        mcap = c.get("market_cap") or 0
        vol = c.get("total_volume") or 0
        p1h = c.get("price_change_percentage_1h_in_currency") or 0
        p24 = c.get("price_change_percentage_24h_in_currency") or 0

        # HARD FILTERS
        if not (5_000_000 <= mcap <= 500_000_000):
            continue
        if mcap <= 0 or vol <= 0:
            continue
        if vol < 0.30 * mcap:
            continue
        if p24 > 8:
            continue
        if p1h > 1.5:
            continue

        rel_vol = vol / mcap  # 0..∞

        # A: volume relativo (quanto maior, melhor)
        A = min(10.0, rel_vol * 15.0)

        # B: “silêncio”: volume alto com preço ainda contido
        # penaliza se 1h ou 24h já estiverem “quentes”
        silence = max(0.0, 1.0 - (abs(p1h) / 2.0 + max(p24, 0.0) / 10.0))
        B = min(10.0, silence * 10.0)

        # C: estrutura “acumulação”: 24h flat/negativo leve favorece
        if -6.0 <= p24 <= 3.0:
            C = 10.0
        elif -10.0 <= p24 <= 8.0:
            C = 6.0
        else:
            C = 0.0

        # D: volume agressivo p/ tamanho (proxy log)
        D = min(10.0, math.log10(max(vol, 1.0)) / 2.0)

        # E: ausência de euforia (proxy)
        E = 10.0 if (p24 < 5.0 and abs(p1h) < 0.8) else 6.0

        score = (A * 3.0) + (B * 2.0) + (C * 2.0) + (D * 2.0) + (E * 1.0)

        symbol = (c.get("symbol") or "").upper()
        candidates.append({
            "symbol": f"{symbol}/USDT",
            "name": c.get("name") or "",
            "mcap": int(mcap),
            "vol24": int(vol),
            "p1h": float(p1h),
            "p24": float(p24),
            "score": float(score),
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:3]
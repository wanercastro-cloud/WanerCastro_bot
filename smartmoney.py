import os, requests, math

BASE = os.getenv("COINGECKO_BASE_URL", "https://pro-api.coingecko.com/api/v3")
KEY  = os.getenv("COINGECKO_API_KEY", "")

STABLES = {"tether", "usd-coin", "dai", "true-usd", "frax", "usdd", "usde"}

def _cg_get(path, params=None):
    headers = {"x-cg-pro-api-key": KEY} if KEY else {}
    r = requests.get(f"{BASE}{path}", params=params or {}, headers=headers, timeout=25)
    r.raise_for_status()
    return r.json()

def scan_prepump_top3():
    """
    Implementa o seu prompt:
    - Filtra (mcap 5M–500M; vol24 >= 30% mcap; 24h<=+8%; 1h<=+1.5%)
    - Score: A,B,C,D,E (proxy via volume/price/ratios)
    Retorna TOP 3 (lista de dicts).
    """
    # Markets: retorna mcap, volume, variações
    data = _cg_get("/coins/markets", {
        "vs_currency": "usd",
        "order": "volume_desc",
        "per_page": 250,
        "page": 1,
        "sparkline": "false",
        "price_change_percentage": "1h,24h"
    })

    candidates = []
    for c in data:
        cid = c.get("id","")
        if cid in STABLES: 
            continue
        mcap = c.get("market_cap") or 0
        vol  = c.get("total_volume") or 0
        p1h  = c.get("price_change_percentage_1h_in_currency") or 0
        p24  = c.get("price_change_percentage_24h_in_currency") or 0

        # HARD FILTERS
        if not (5_000_000 <= mcap <= 500_000_000): 
            continue
        if vol < 0.30 * mcap:
            continue
        if p24 > 8:
            continue
        if p1h > 1.5:
            continue

        # Sinais (proxies práticos com dados disponíveis)
        # A: volume relativo (quanto maior vol/mcap, melhor, mas sem pump)
        rel_vol = vol / mcap if mcap else 0
        A = min(10, rel_vol * 15)  # ajustável

        # B: assimetria vol x preço (volume alto com preço baixo/flat)
        # quanto menor o p1h e p24, mais "silencioso"
        silence = max(0, 1 - (abs(p1h)/2 + max(p24,0)/10))
        B = min(10, silence * 10)

        # C: “estrutura de acumulação” proxy (p24 levemente negativo/flat é ok)
        C = 10 if (-6 <= p24 <= 3) else 6 if (-10 <= p24 <= 8) else 0

        # D: volume agressivo p/ tamanho
        D = min(10, math.log10(max(vol,1)) / 2)  # proxy

        # E: ausência de euforia (proxy: p24 não muito alto + p1h baixo)
        E = 10 if (p24 < 5 and abs(p1h) < 0.8) else 6

        score = (A*3) + (B*2) + (C*2) + (D*2) + (E*1)

        candidates.append({
            "symbol": (c.get("symbol","").upper() + "/USDT"),
            "name": c.get("name",""),
            "mcap": mcap,
            "vol24": vol,
            "p1h": p1h,
            "p24": p24,
            "score": score
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:3]
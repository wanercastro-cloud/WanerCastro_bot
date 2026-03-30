import os
import requests

from indicators import build_indicator_pack_from_market_chart

BASE_URL = os.environ["COINGECKO_BASE_URL"].rstrip("/")
API_KEY = os.environ["COINGECKO_API_KEY"]

VS_CURRENCY = os.getenv("VS_CURRENCY", "usd")
PER_PAGE = int(os.getenv("PER_PAGE", "250"))
PAGES = int(os.getenv("PAGES", "1"))
CANDIDATES = int(os.getenv("CANDIDATES", "35"))
MIN_MCAP = float(os.getenv("MIN_MCAP", "2000000"))
MAX_MCAP = float(os.getenv("MAX_MCAP", "300000000"))
MIN_VOL24 = float(os.getenv("MIN_VOL24", "1500000"))
EXCLUDE_STABLES = os.getenv("EXCLUDE_STABLES", "true").lower() == "true"

HEADERS = {"x-cg-pro-api-key": API_KEY}
STABLES = {"usdt","usdc","dai","busd","tusd","usde","fdusd","usdd","pyusd","gusd"}


def _get(url: str, params: dict):
    r = requests.get(url, headers=HEADERS, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def get_candidate_markets():
    rows = []
    for page in range(1, PAGES + 1):
        data = _get(
            f"{BASE_URL}/coins/markets",
            {
                "vs_currency": VS_CURRENCY,
                "order": "volume_desc",
                "per_page": PER_PAGE,
                "page": page,
                "sparkline": "false",
                "price_change_percentage": "1h,24h,7d",
            },
        )
        rows.extend(data)

    out = []
    for c in rows:
        symbol = (c.get("symbol") or "").lower()
        if EXCLUDE_STABLES and symbol in STABLES:
            continue
        mcap = float(c.get("market_cap") or 0)
        vol = float(c.get("total_volume") or 0)
        if mcap < MIN_MCAP or mcap > MAX_MCAP:
            continue
        if vol < MIN_VOL24:
            continue
        out.append(c)

    out.sort(key=lambda x: float(x.get("total_volume") or 0), reverse=True)
    return out[:CANDIDATES]


def get_indicator_pack_for_coin(coin_id: str):
    data = _get(
        f"{BASE_URL}/coins/{coin_id}/market_chart",
        {
            "vs_currency": VS_CURRENCY,
            "days": "30",
            "interval": "hourly",
        },
    )
    return build_indicator_pack_from_market_chart(data)

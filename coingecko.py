import os
import requests
import pandas as pd
import logging
from indicators import build_indicator_pack_from_market_chart
import config

logger = logging.getLogger(__name__)

HEADERS = {}
if config.COINGECKO_API_KEY:
    HEADERS["x-cg-pro-api-key"] = config.COINGECKO_API_KEY

BASE_URL = config.COINGECKO_BASE_URL.rstrip("/")

def _get(url: str, params: dict):
    """Requisição com tratamento de rate limit."""
    try:
        r = requests.get(url, headers=HEADERS, params=params, timeout=30)
        if r.status_code == 429:
            logger.warning("Rate limit atingido, aguardando 60s...")
            time.sleep(60)
            return _get(url, params)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"Erro na requisição {url}: {e}")
        return None

def is_stable_like(symbol: str, name: str) -> bool:
    s = (symbol or "").lower()
    n = (name or "").lower()
    stable_terms = [
        "usd", "usdt", "usdc", "dai", "busd", "fdusd",
        "tusd", "usde", "usdd", "pyusd", "gusd", "stable",
        "dollar", "synthetic usd"
    ]
    return any(term in s for term in stable_terms) or any(term in n for term in stable_terms)

def get_candidate_markets():
    """Retorna lista de moedas filtradas por volume, market cap, excluindo stablecoins."""
    rows = []
    for page in range(1, config.PAGES + 1):
        data = _get(
            f"{BASE_URL}/coins/markets",
            {
                "vs_currency": config.VS_CURRENCY,
                "order": "volume_desc",
                "per_page": config.PER_PAGE,
                "page": page,
                "sparkline": "false",
                "price_change_percentage": "1h,24h,7d",
            },
        )
        if data is None:
            continue
        rows.extend(data)

    out = []
    for c in rows:
        symbol = c.get("symbol") or ""
        name = c.get("name") or ""

        if config.EXCLUDE_STABLES and is_stable_like(symbol, name):
            continue

        mcap = float(c.get("market_cap") or 0)
        vol = float(c.get("total_volume") or 0)

        if mcap < config.MIN_MCAP or mcap > config.MAX_MCAP:
            continue
        if vol < config.MIN_VOL24:
            continue

        out.append(c)

    out.sort(key=lambda x: float(x.get("total_volume") or 0), reverse=True)
    return out[:config.CANDIDATES]

def get_indicator_pack_for_coin(coin_id: str):
    """Obtém dados de mercado (30 dias, horário) e calcula os indicadores."""
    data = _get(
        f"{BASE_URL}/coins/{coin_id}/market_chart",
        {
            "vs_currency": config.VS_CURRENCY,
            "days": "30",
            "interval": "hourly",
        },
    )
    if data is None:
        return None
    return build_indicator_pack_from_market_chart(data)
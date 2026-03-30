import os
import time
import requests
import logging
from datetime import datetime, timedelta
from indicators import build_indicator_pack_from_market_chart
import config

logger = logging.getLogger(__name__)

HEADERS = {}
if config.COINGECKO_API_KEY:
    HEADERS["x-cg-pro-api-key"] = config.COINGECKO_API_KEY

BASE_URL = config.COINGECKO_BASE_URL.rstrip("/")

# Cache simples em memória para os dados de market chart
_cache = {}
_cache_ttl = timedelta(minutes=config.SNAPSHOT_TTL_MINUTES)

def _get(url: str, params: dict, retries=3):
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=30)
            if r.status_code == 429:
                wait = 60 * (attempt + 1)
                logger.warning(f"Rate limit atingido. Aguardando {wait}s...")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Erro na requisição {url}: {e}")
            if attempt == retries - 1:
                return None
            time.sleep(2 ** attempt)
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

        out.append({
            'id': c['id'],
            'symbol': c['symbol'],
            'name': c['name'],
            'current_price': c.get('current_price', 0),
            'price_change_24h': c.get('price_change_percentage_24h', 0),
            'volume': vol,
            'market_cap': mcap
        })

    out.sort(key=lambda x: x['volume'], reverse=True)
    return out[:config.CANDIDATES]

def get_indicator_pack_for_coin(coin_id: str):
    # Verifica cache
    now = datetime.now()
    if coin_id in _cache and (now - _cache[coin_id]['timestamp']) < _cache_ttl:
        logger.debug(f"Usando cache para {coin_id}")
        return _cache[coin_id]['data']

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
    try:
        result = build_indicator_pack_from_market_chart(data)
        # Armazena em cache
        if result:
            _cache[coin_id] = {'data': result, 'timestamp': now}
        return result
    except Exception as e:
        logger.error(f"Erro ao processar indicadores para {coin_id}: {e}")
        return None
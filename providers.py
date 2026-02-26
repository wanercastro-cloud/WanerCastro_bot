import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from config import (
    COINGECKO_API_KEY,
    COINGECKO_BASE_URL,
    VS_CURRENCY,
    CANDIDATES,
    HTTP_RETRIES,
    HTTP_TIMEOUT,
)

# cache TTL simples
class TTLCache:
    def __init__(self, ttl_sec: int = 60):
        self.ttl = ttl_sec
        self._data: Dict[str, Tuple[float, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        v = self._data.get(key)
        if not v:
            return None
        ts, data = v
        if time.time() - ts > self.ttl:
            self._data.pop(key, None)
            return None
        return data

    def set(self, key: str, value: Any) -> None:
        self._data[key] = (time.time(), value)

CACHE = TTLCache(ttl_sec=60)

def cg_headers() -> Dict[str, str]:
    h = {"accept": "application/json"}
    if COINGECKO_API_KEY:
        h["x-cg-pro-api-key"] = COINGECKO_API_KEY
    return h

async def http_get_json(client: httpx.AsyncClient, url: str, params: Dict[str, Any]) -> Any:
    last: Optional[Exception] = None
    for _ in range(HTTP_RETRIES + 1):
        try:
            r = await client.get(url, params=params)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last = e
            await asyncio.sleep(0.4)
    raise last or RuntimeError("http_get_json falhou")

async def cg_markets(client: httpx.AsyncClient) -> List[Dict[str, Any]]:
    cache_key = f"cg_markets:{VS_CURRENCY}:{CANDIDATES}"
    cached = CACHE.get(cache_key)
    if cached is not None:
        return cached

    url = f"{COINGECKO_BASE_URL}/coins/markets"
    params = {
        "vs_currency": VS_CURRENCY,
        "order": "volume_desc",
        "per_page": min(max(CANDIDATES, 50), 250),
        "page": 1,
        "sparkline": "false",
        "price_change_percentage": "1h,24h",
    }
    data = await http_get_json(client, url, params)
    if not isinstance(data, list):
        data = []
    CACHE.set(cache_key, data)
    return data

async def cg_top_gainers_losers(client: httpx.AsyncClient) -> Dict[str, Any]:
    # premium: pode falhar em alguns planos, então a gente não derruba o bot
    cache_key = f"cg_tgl:{VS_CURRENCY}"
    cached = CACHE.get(cache_key)
    if cached is not None:
        return cached

    url = f"{COINGECKO_BASE_URL}/coins/top_gainers_losers"
    params = {"vs_currency": VS_CURRENCY, "duration": "24h"}
    try:
        data = await http_get_json(client, url, params)
    except Exception:
        data = {}
    CACHE.set(cache_key, data)
    return data

async def build_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(HTTP_TIMEOUT),
        headers=cg_headers(),
    )
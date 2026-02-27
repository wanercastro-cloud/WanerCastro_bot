import asyncio
import time
from typing import Any, Dict, Optional

import httpx

from config import SETTINGS

class TTLCache:
    def __init__(self, ttl_sec: int = 60):
        self.ttl = ttl_sec
        self._data: Dict[str, tuple[float, Any]] = {}

    def get(self, key: str):
        item = self._data.get(key)
        if not item:
            return None
        ts, val = item
        if time.time() - ts > self.ttl:
            self._data.pop(key, None)
            return None
        return val

    def set(self, key: str, value: Any):
        self._data[key] = (time.time(), value)

CACHE = TTLCache(ttl_sec=60)

def cg_headers() -> Dict[str, str]:
    headers = {"accept": "application/json"}
    if SETTINGS.COINGECKO_API_KEY:
        headers["x-cg-pro-api-key"] = SETTINGS.COINGECKO_API_KEY
    return headers

async def http_get_json(client: httpx.AsyncClient, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
    last_exc: Optional[Exception] = None
    for _ in range(SETTINGS.HTTP_RETRIES + 1):
        try:
            r = await client.get(url, params=params or {})
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_exc = e
            await asyncio.sleep(0.45)
    raise last_exc or RuntimeError("Erro desconhecido no http_get_json")

class CoinGeckoProvider:
    """
    LITE (CoinGecko Pro):
      - /coins/markets
      - /coins/{id}
      - /coins/{id}/market_chart
    """
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def markets(self, vs_currency: str, per_page: int, page: int = 1) -> list[dict]:
        cache_key = f"cg:markets:{vs_currency}:{per_page}:{page}"
        cached = CACHE.get(cache_key)
        if cached is not None:
            return cached

        url = f"{SETTINGS.COINGECKO_BASE_URL}/coins/markets"
        params = {
            "vs_currency": vs_currency,
            "order": "volume_desc",
            "per_page": max(50, min(per_page, 250)),
            "page": page,
            "sparkline": "false",
            "price_change_percentage": "1h,24h",
        }
        data = await http_get_json(self.client, url, params)
        if not isinstance(data, list):
            data = []
        CACHE.set(cache_key, data)
        return data

    async def coin_by_id(self, coin_id: str) -> dict:
        cache_key = f"cg:coin:{coin_id}"
        cached = CACHE.get(cache_key)
        if cached is not None:
            return cached

        url = f"{SETTINGS.COINGECKO_BASE_URL}/coins/{coin_id}"
        params = {
            "localization": "false",
            "tickers": "false",
            "market_data": "true",
            "community_data": "false",
            "developer_data": "false",
            "sparkline": "false",
        }
        data = await http_get_json(self.client, url, params)
        if not isinstance(data, dict):
            data = {}
        CACHE.set(cache_key, data)
        return data

    async def market_chart(self, coin_id: str, vs_currency: str, days: int = 7) -> dict:
        cache_key = f"cg:chart:{coin_id}:{vs_currency}:{days}"
        cached = CACHE.get(cache_key)
        if cached is not None:
            return cached

        url = f"{SETTINGS.COINGECKO_BASE_URL}/coins/{coin_id}/market_chart"
        params = {"vs_currency": vs_currency, "days": days}
        data = await http_get_json(self.client, url, params)
        if not isinstance(data, dict):
            data = {}
        CACHE.set(cache_key, data)
        return data

class GeckoTerminalProvider:
    """
    Endpoints do PDF (4 e 5):
      - Trending pools by network
      - Pools Megafilter (filtrando pools)
    """
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def trending_pools_by_network(self, network: str = "solana", page: int = 1) -> dict:
        cache_key = f"gt:trending:{network}:{page}"
        cached = CACHE.get(cache_key)
        if cached is not None:
            return cached

        url = f"{SETTINGS.GECKOTERMINAL_BASE_URL}/networks/{network}/trending_pools"
        data = await http_get_json(self.client, url, {"page": page})
        if not isinstance(data, dict):
            data = {}
        CACHE.set(cache_key, data)
        return data

    async def pools_megafilter(
        self,
        network: str = "solana",
        page: int = 1,
        min_liquidity_usd: int = 20000,
        min_volume_usd_h24: int = 20000,
    ) -> dict:
        """
        GeckoTerminal não chama isso literalmente de “megafilter” na URL,
        mas o conceito é o mesmo: filtrar pools por liquidez/volume.
        """
        cache_key = f"gt:pools:{network}:{page}:{min_liquidity_usd}:{min_volume_usd_h24}"
        cached = CACHE.get(cache_key)
        if cached is not None:
            return cached

        # Lista/filtra pools do network
        url = f"{SETTINGS.GECKOTERMINAL_BASE_URL}/networks/{network}/pools"
        params = {
            "page": page,
            "min_liquidity": min_liquidity_usd,
            "min_volume": min_volume_usd_h24,
        }
        data = await http_get_json(self.client, url, params)
        if not isinstance(data, dict):
            data = {}
        CACHE.set(cache_key, data)
        return data
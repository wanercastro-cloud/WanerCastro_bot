import asyncio
from typing import Any, Dict, List, Optional

import httpx

from config import Settings

def cg_headers(settings: Settings) -> Dict[str, str]:
    headers = {"accept": "application/json"}
    # CoinGecko Pro usa esse header:
    if settings.coingecko_api_key:
        headers["x-cg-pro-api-key"] = settings.coingecko_api_key
    return headers

async def http_get_json(client: httpx.AsyncClient, url: str, params: Dict[str, Any], retries: int = 2) -> Any:
    last_exc: Optional[Exception] = None
    for _ in range(retries + 1):
        try:
            r = await client.get(url, params=params)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_exc = e
            await asyncio.sleep(0.4)
    raise last_exc or RuntimeError("Erro desconhecido no http_get_json")

async def cg_markets(client: httpx.AsyncClient, settings: Settings) -> List[Dict[str, Any]]:
    url = f"{settings.coingecko_base_url}/coins/markets"
    params = {
        "vs_currency": settings.vs_currency,
        "order": "volume_desc",
        "per_page": min(max(settings.candidates, 50), 250),
        "page": 1,
        "sparkline": "false",
        "price_change_percentage": "1h,24h",
    }
    data = await http_get_json(client, url, params, retries=settings.http_retries)
    return data if isinstance(data, list) else []

async def cg_market_chart_1d(client: httpx.AsyncClient, settings: Settings, cg_id: str) -> Dict[str, Any]:
    # Endpoint “Coin Historical Chart Data by ID” (market_chart) é um dos mais usados.  [oai_citation:0‡Build faster, research smarter with these top endpoints.pdf](sediment://file_000000000f54720eb3844ef915980e02)
    url = f"{settings.coingecko_base_url}/coins/{cg_id}/market_chart"
    params = {
        "vs_currency": settings.vs_currency,
        "days": "1",
        "interval": "hourly",
    }
    data = await http_get_json(client, url, params, retries=settings.http_retries)
    return data if isinstance(data, dict) else {}

async def geckoterminal_trending_pools(client: httpx.AsyncClient, settings: Settings) -> Dict[str, Any]:
    # “Trending Pools by Network” é um endpoint popular do GeckoTerminal.  [oai_citation:1‡Build faster, research smarter with these top endpoints.pdf](sediment://file_000000000f54720eb3844ef915980e02)
    url = f"{settings.geckoterminal_base_url}/networks/trending_pools"
    params = {"page": 1}
    data = await http_get_json(client, url, params, retries=settings.http_retries)
    return data if isinstance(data, dict) else {}
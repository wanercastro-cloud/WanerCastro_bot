import asyncio
from typing import Any, Dict, List, Optional

import httpx

from config import settings


STABLE_SYMBOLS = {
    "USDT", "USDC", "DAI", "TUSD", "USDE", "USDQ", "FDUSD", "PYUSD",
    "EUR", "GBP", "JPY", "TRY", "BRL"
}


def is_stable_like(symbol: str) -> bool:
    s = (symbol or "").upper().strip()
    return s in STABLE_SYMBOLS or s.endswith("USD") or s.endswith("USDT") or s.endswith("USDC")


async def http_get_json(client: httpx.AsyncClient, url: str, params: Dict[str, Any]) -> Any:
    last_exc: Optional[Exception] = None
    for _ in range(settings.HTTP_RETRIES + 1):
        try:
            r = await client.get(url, params=params)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_exc = e
            await asyncio.sleep(0.35)
    raise last_exc or RuntimeError("Erro desconhecido no http_get_json")


async def cg_markets(client: httpx.AsyncClient) -> List[Dict[str, Any]]:
    url = f"{settings.COINGECKO_BASE_URL}/coins/markets"
    params = {
        "vs_currency": settings.VS_CURRENCY,
        "order": "volume_desc",
        "per_page": min(max(settings.CANDIDATES, 50), 250),
        "page": 1,
        "sparkline": "false",
        "price_change_percentage": "1h,24h",
    }
    data = await http_get_json(client, url, params)
    return data if isinstance(data, list) else []


async def cg_top_gainers_losers(client: httpx.AsyncClient) -> Optional[Dict[str, Any]]:
    # Premium: pode dar 401/403 dependendo do plano/endpoint liberado
    url = f"{settings.COINGECKO_BASE_URL}/coins/top_gainers_losers"
    params = {"vs_currency": settings.VS_CURRENCY, "duration": "24h"}
    try:
        return await http_get_json(client, url, params)
    except Exception:
        return None


async def cg_trending_search(client: httpx.AsyncClient) -> Optional[Dict[str, Any]]:
    # Público em muitos planos; se falhar, ignora
    url = f"{settings.COINGECKO_BASE_URL}/search/trending"
    try:
        return await http_get_json(client, url, {})
    except Exception:
        return None


async def cg_market_chart_1d(client: httpx.AsyncClient, cg_id: str) -> Optional[Dict[str, Any]]:
    # Para /continuacao e /fomo: séries de preço/volume (1 dia)
    url = f"{settings.COINGECKO_BASE_URL}/coins/{cg_id}/market_chart"
    params = {"vs_currency": settings.VS_CURRENCY, "days": 1}
    try:
        return await http_get_json(client, url, params)
    except Exception:
        return None
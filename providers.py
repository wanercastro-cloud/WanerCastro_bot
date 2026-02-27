import asyncio
from typing import Any, Dict, List, Optional
import httpx
import os

COINGECKO_BASE_URL = os.getenv("COINGECKO_BASE_URL", "https://pro-api.coingecko.com/api/v3").rstrip("/")
COINGECKO_API_KEY = os.getenv("COINGECKO_PRO_API_KEY", "").strip()
VS = os.getenv("VS_CURRENCY", "usd").strip().lower()
HTTP_RETRIES = int(os.getenv("HTTP_RETRIES", "2"))
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "20"))

# GeckoTerminal (on-chain/dex)
GECKOTERMINAL_BASE_URL = os.getenv("GECKOTERMINAL_BASE_URL", "https://api.geckoterminal.com/api/v2").rstrip("/")

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
            await asyncio.sleep(0.35)
    raise last or RuntimeError("http_get_json failed")

async def cg_markets(client: httpx.AsyncClient, per_page: int = 250) -> List[Dict[str, Any]]:
    url = f"{COINGECKO_BASE_URL}/coins/markets"
    params = {
        "vs_currency": VS,
        "order": "volume_desc",
        "per_page": min(max(per_page, 50), 250),
        "page": 1,
        "sparkline": "false",
        "price_change_percentage": "1h,24h",
    }
    data = await http_get_json(client, url, params)
    return data if isinstance(data, list) else []

async def cg_market_chart_1d(client: httpx.AsyncClient, cg_id: str) -> Dict[str, Any]:
    url = f"{COINGECKO_BASE_URL}/coins/{cg_id}/market_chart"
    params = {"vs_currency": VS, "days": "1", "interval": "hourly"}
    data = await http_get_json(client, url, params)
    return data if isinstance(data, dict) else {}

async def gt_trending_pools(client: httpx.AsyncClient) -> Dict[str, Any]:
    url = f"{GECKOTERMINAL_BASE_URL}/networks/trending_pools"
    params = {"page": 1}
    data = await http_get_json(client, url, params)
    return data if isinstance(data, dict) else {}

# Pools Megafilter (CoinGecko Onchain)
# Obs: endpoint costuma viver no domínio/api “onchain”. Mantive base configurável via env:
ONCHAIN_BASE_URL = os.getenv("COINGECKO_ONCHAIN_BASE_URL", "https://pro-api.coingecko.com/api/v3").rstrip("/")

async def cg_pools_megafilter(client: httpx.AsyncClient, network: str = "solana") -> Dict[str, Any]:
    url = f"{ONCHAIN_BASE_URL}/onchain/pools/megafilter"
    params = {
        "network": network,
        # filtros que você pode tunar via env depois:
        "min_liquidity_usd": os.getenv("MIN_LIQ_USD", "200000"),
        "min_volume_usd_24h": os.getenv("MIN_POOL_VOL24", "150000"),
        "page": 1,
    }
    data = await http_get_json(client, url, params)
    return data if isinstance(data, dict) else {}
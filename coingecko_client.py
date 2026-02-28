import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import httpx
from cachetools import TTLCache

from config import (
    COINGECKO_API_KEY,
    COINGECKO_BASE_URL,
    COINGECKO_FALLBACK_URL,
    COINGECKO_KEY_HEADER,
    CACHE_TTL_SEC,
    HTTP_TIMEOUT_SEC,
    HTTP_RETRIES,
)

@dataclass
class CGResponse:
    data: Any
    used_fallback: bool

class CoinGeckoClient:
    """
    Lite-friendly client:
    - TTL cache
    - retry/backoff for 429/5xx
    - automatic fallback if PRO returns 401/403
    """

    def __init__(self) -> None:
        self.cache = TTLCache(maxsize=2048, ttl=CACHE_TTL_SEC)
        self._client = httpx.AsyncClient(timeout=HTTP_TIMEOUT_SEC)

    async def aclose(self) -> None:
        await self._client.aclose()

    def _headers(self, base_url: str) -> Dict[str, str]:
        # For pro-api: x-cg-pro-api-key (docs)
        # For fallback public api: some keys also work, but if not, it still tries without breaking.
        headers = {"accept": "application/json"}
        if COINGECKO_API_KEY:
            headers[COINGECKO_KEY_HEADER] = COINGECKO_API_KEY
        return headers

    def _cache_key(self, url: str, params: Optional[Dict[str, Any]]) -> str:
        if not params:
            return url
        items = "&".join(f"{k}={params[k]}" for k in sorted(params.keys()))
        return f"{url}?{items}"

    async def get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> CGResponse:
        # Try PRO first, fallback if unauthorized
        url_pro = f"{COINGECKO_BASE_URL.rstrip('/')}/{path.lstrip('/')}"
        url_fb = f"{COINGECKO_FALLBACK_URL.rstrip('/')}/{path.lstrip('/')}"

        # cache per URL+params (separately)
        key_pro = self._cache_key(url_pro, params)
        if key_pro in self.cache:
            return CGResponse(self.cache[key_pro], used_fallback=False)

        # attempt PRO
        r = await self._request_with_retries(url_pro, params=params)
        if r is not None:
            self.cache[key_pro] = r
            return CGResponse(r, used_fallback=False)

        # fallback
        key_fb = self._cache_key(url_fb, params)
        if key_fb in self.cache:
            return CGResponse(self.cache[key_fb], used_fallback=True)

        r2 = await self._request_with_retries(url_fb, params=params, allow_unauth_key=True)
        if r2 is None:
            raise RuntimeError("CoinGecko: falhou PRO e fallback.")
        self.cache[key_fb] = r2
        return CGResponse(r2, used_fallback=True)

    async def _request_with_retries(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        allow_unauth_key: bool = False,
    ) -> Optional[Any]:
        headers = self._headers(url)
        # Se cair no fallback e a chave não for aceita, tenta sem header (às vezes 401 vem disso)
        alt_headers = {"accept": "application/json"}

        backoff = 1.0
        for attempt in range(1, HTTP_RETRIES + 1):
            try:
                resp = await self._client.get(url, params=params, headers=headers)
                if resp.status_code in (401, 403):
                    if allow_unauth_key:
                        resp2 = await self._client.get(url, params=params, headers=alt_headers)
                        if resp2.status_code == 200:
                            return resp2.json()
                    return None  # trigger fallback in caller

                if resp.status_code == 429:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 1.7, 12)
                    continue

                resp.raise_for_status()
                return resp.json()

            except httpx.HTTPStatusError as e:
                code = e.response.status_code if e.response else 0
                if code in (500, 502, 503, 504):
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 1.7, 12)
                    continue
                # 400: geralmente param errado -> não adianta insistir
                raise
            except (httpx.ReadTimeout, httpx.ConnectError):
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.7, 12)
                continue

        return None
import time
import httpx
from typing import Any, Dict, Optional
from config import (
    COINGECKO_BASE_URL, COINGECKO_PRO_API_KEY,
    HTTP_TIMEOUT_SEC, HTTP_RETRIES, HTTP_BACKOFF_BASE
)

class CoinGeckoClient:
    def __init__(self) -> None:
        self.client = httpx.AsyncClient(
            base_url=COINGECKO_BASE_URL,
            timeout=HTTP_TIMEOUT_SEC,
            headers={
                "accept": "application/json",
                "x-cg-pro-api-key": COINGECKO_PRO_API_KEY,  # ESSENCIAL p/ Lite/Pro
            },
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        params = params or {}
        last_exc: Exception | None = None

        for attempt in range(1, HTTP_RETRIES + 1):
            try:
                r = await self.client.get(path, params=params)
                # 429: respeitar retry-after
                if r.status_code == 429:
                    ra = r.headers.get("retry-after")
                    wait = float(ra) if ra and ra.isdigit() else (HTTP_BACKOFF_BASE ** attempt)
                    await self._sleep(wait)
                    continue

                r.raise_for_status()
                return r.json()

            except httpx.HTTPStatusError as e:
                last_exc = e
                # 401/403: não adianta retry infinito, retorna logo
                if e.response.status_code in (401, 403):
                    raise
                # outros erros: backoff
                await self._sleep(HTTP_BACKOFF_BASE ** attempt)

            except Exception as e:
                last_exc = e
                await self._sleep(HTTP_BACKOFF_BASE ** attempt)

        if last_exc:
            raise last_exc
        raise RuntimeError("Unknown HTTP error")

    async def _sleep(self, seconds: float) -> None:
        # async-friendly
        import asyncio
        await asyncio.sleep(seconds)
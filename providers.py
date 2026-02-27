import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import httpx

@dataclass
class ProviderState:
    base_url: str
    last_error: str = ""
    last_status: int = 0
    last_ok_ts: float = 0.0

class TTLCache:
    def __init__(self, ttl_sec: int):
        self.ttl = ttl_sec
        self._data: Dict[str, Tuple[float, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        it = self._data.get(key)
        if not it:
            return None
        ts, val = it
        if time.time() - ts > self.ttl:
            self._data.pop(key, None)
            return None
        return val

    def set(self, key: str, val: Any) -> None:
        self._data[key] = (time.time(), val)

class CoinGeckoLite:
    """
    - Tenta pro-api primeiro (se tiver key).
    - Se tomar 401, alterna para free base (pode dar 429, então tem backoff/caching).
    - Header compatível: envia x-cg-pro-api-key E x-cg-demo-api-key (algumas chaves exigem variação).
    """
    def __init__(
        self,
        api_key: str,
        base_pro: str,
        base_free: str,
        timeout_sec: float,
        retries: int,
        cache_ttl_sec: int,
    ):
        self.api_key = (api_key or "").strip()
        self.base_pro = base_pro.rstrip("/")
        self.base_free = base_free.rstrip("/")
        self.timeout = timeout_sec
        self.retries = retries
        self.cache = TTLCache(cache_ttl_sec)

        # Começa tentando pro se tiver key, senão free
        start_base = self.base_pro if self.api_key else self.base_free
        self.state = ProviderState(base_url=start_base)

        headers = {"accept": "application/json"}
        if self.api_key:
            headers["x-cg-pro-api-key"] = self.api_key
            headers["x-cg-demo-api-key"] = self.api_key  # compat
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout), headers=headers)

    async def aclose(self) -> None:
        await self.client.aclose()

    def _make_url(self, path: str) -> str:
        return f"{self.state.base_url}{path}"

    async def _sleep_backoff(self, attempt: int, retry_after: Optional[str]) -> None:
        if retry_after:
            try:
                sec = int(float(retry_after))
                await asyncio.sleep(min(max(sec, 1), 60))
                return
            except Exception:
                pass
        # backoff exponencial com teto
        await asyncio.sleep(min(0.8 * (2 ** attempt), 12.0))

    async def get_json(self, path: str, params: Dict[str, Any], cache_key: Optional[str] = None) -> Any:
        key = cache_key or f"{path}:{sorted(params.items())}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        last_exc: Optional[Exception] = None

        for attempt in range(self.retries + 1):
            try:
                url = self._make_url(path)
                r = await self.client.get(url, params=params)

                # 429: rate limit (com Retry-After)
                if r.status_code == 429:
                    self.state.last_error = "HTTP 429 (rate limit)"
                    self.state.last_status = 429
                    await self._sleep_backoff(attempt, r.headers.get("Retry-After"))
                    continue

                # 401: key/base inválida para o endpoint
                if r.status_code == 401:
                    self.state.last_error = "HTTP 401 (unauthorized)"
                    self.state.last_status = 401

                    # se está no pro, tenta free; se está no free, tenta pro
                    if self.state.base_url == self.base_pro:
                        self.state.base_url = self.base_free
                    else:
                        # só vale tentar pro se tiver key
                        if self.api_key:
                            self.state.base_url = self.base_pro

                    await self._sleep_backoff(attempt, None)
                    continue

                r.raise_for_status()
                data = r.json()

                self.state.last_error = ""
                self.state.last_status = r.status_code
                self.state.last_ok_ts = time.time()

                self.cache.set(key, data)
                return data

            except Exception as e:
                last_exc = e
                self.state.last_error = f"{type(e).__name__}: {e}"
                self.state.last_status = getattr(getattr(e, "response", None), "status_code", 0) or 0
                await self._sleep_backoff(attempt, None)

        raise last_exc or RuntimeError("Falha desconhecida no get_json")

    # ===== Lite endpoints usados =====

    async def coins_markets(self, vs_currency: str, per_page: int, page: int) -> Any:
        # docs: /coins/markets
        return await self.get_json(
            "/coins/markets",
            params={
                "vs_currency": vs_currency,
                "order": "volume_desc",
                "per_page": per_page,
                "page": page,
                "sparkline": "false",
                "price_change_percentage": "1h,24h",
            },
            cache_key=f"markets:{vs_currency}:{per_page}:{page}",
        )

    async def coin_by_id(self, coin_id: str) -> Any:
        return await self.get_json(
            f"/coins/{coin_id}",
            params={
                "localization": "false",
                "tickers": "false",
                "market_data": "true",
                "community_data": "false",
                "developer_data": "false",
                "sparkline": "false",
            },
            cache_key=f"coin:{coin_id}",
        )

    async def market_chart(self, coin_id: str, vs_currency: str, days: int) -> Any:
        return await self.get_json(
            f"/coins/{coin_id}/market_chart",
            params={"vs_currency": vs_currency, "days": str(days)},
            cache_key=f"chart:{coin_id}:{vs_currency}:{days}",
        )
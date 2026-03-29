from __future__ import annotations

import time
from typing import Any, Dict, List

import requests

from config import SETTINGS


class CoinGeckoClient:
    def __init__(self) -> None:
        self.base_url = SETTINGS.coingecko_base_url.rstrip("/")
        self.headers = {"x-cg-pro-api-key": SETTINGS.coingecko_api_key}
        self.timeout = 30

    def _get(self, path: str, params: Dict[str, Any]) -> Any:
        url = f"{self.base_url}{path}"
        response = requests.get(url, headers=self.headers, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def get_markets(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for page in range(1, SETTINGS.pages + 1):
            params = {
                "vs_currency": SETTINGS.vs_currency,
                "order": "volume_desc",
                "per_page": SETTINGS.per_page,
                "page": page,
                "sparkline": "false",
                "price_change_percentage": "1h,24h,7d",
            }
            rows.extend(self._get("/coins/markets", params))
            time.sleep(0.15)
        return rows

    def get_market_chart(self, coin_id: str, days: int = 30) -> Dict[str, Any]:
        params = {
            "vs_currency": SETTINGS.vs_currency,
            "days": days,
            "interval": "hourly",
        }
        return self._get(f"/coins/{coin_id}/market_chart", params)

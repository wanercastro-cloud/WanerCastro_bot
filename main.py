import os
import math
import asyncio
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple

import httpx
from dotenv import load_dotenv

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes


# =========================
# ENV / CONFIG
# =========================
load_dotenv()

TG_BOT_TOKEN = (os.getenv("TG_BOT_TOKEN") or "").strip()

# CoinGecko PRO (obrigatório)
COINGECKO_API_KEY = (os.getenv("COINGECKO_PRO_API_KEY") or "").strip()
COINGECKO_BASE_URL = (os.getenv("COINGECKO_BASE_URL") or "https://pro-api.coingecko.com/api/v3").strip()

# Radar / scoring
TOP_N = int(os.getenv("TOP_N", "5"))
VS_CURRENCY = os.getenv("VS_CURRENCY", "usd").strip().lower()
CANDIDATES = int(os.getenv("CANDIDATES", "120"))  # universo inicial
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "20"))

MIN_MCAP_USD = float(os.getenv("MIN_MCAP_USD", "5000000"))     # 5M
MIN_VOL24_USD = float(os.getenv("MIN_VOL24_USD", "2000000"))   # 2M
MAX_MCAP_USD = float(os.getenv("MAX_MCAP_USD", "0"))           # 0 = sem teto

# filtros (evitar stable/pegs e lixo)
EXCLUDE_STABLES = os.getenv("EXCLUDE_STABLES", "1").strip() != "0"
STABLE_SYMBOLS = {
    "usdt", "usdc", "dai", "tusd", "usde", "usdp", "usdq",
    "fdusd", "pyusd", "frax", "lusd", "eurs", "eurs", "eurs",
}

# Tempo de análise de ganho/perda (para endpoint top_gainers_losers)
GAINERS_DURATION = os.getenv("GAINERS_DURATION", "24h").strip()  # 1h | 24h | 7d (depende do endpoint)
GAINERS_KIND = os.getenv("GAINERS_KIND", "gainers").strip().lower()  # gainers | losers

# Mensagens
ALERT_CHAT_ID = (os.getenv("ALERT_CHAT_ID") or "").strip()  # opcional


if not TG_BOT_TOKEN:
    raise RuntimeError("❌ Variável TG_BOT_TOKEN não configurada no Railway/ENV.")

if not COINGECKO_API_KEY:
    raise RuntimeError("❌ Variável COINGECKO_PRO_API_KEY não configurada (necessária para CoinGecko PRO).")


# =========================
# DATA MODEL
# =========================
@dataclass
class CandidateScore:
    symbol: str
    name: str
    cg_id: str
    score: float
    mcap: float
    vol24: float
    chg_1h: float
    chg_24h: float


# =========================
# COINGECKO CLIENT
# =========================
class CoinGeckoProClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {"x-cg-pro-api-key": api_key}
        self.timeout = timeout

    async def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}{path}"
        # Retentativa simples (rede / rate)
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers) as client:
                    r = await client.get(url, params=params)
                    r.raise_for_status()
                    return r.json()
            except httpx.HTTPStatusError as e:
                # Se for 429, dá uma respirada e tenta de novo
                status = e.response.status_code
                if status == 429 and attempt < 2:
                    await asyncio.sleep(1.2 * (attempt + 1))
                    continue
                raise
            except httpx.RequestError:
                if attempt < 2:
                    await asyncio.sleep(0.8 * (attempt + 1))
                    continue
                raise

        raise RuntimeError("Falha ao consultar CoinGecko após retentativas.")

    async def top_gainers_losers(self, vs_currency: str = "usd", duration: str = "24h") -> Any:
        # Endpoint PRO: /coins/top_gainers_losers
        return await self._get(
            "/coins/top_gainers_losers",
            params={"vs_currency": vs_currency, "duration": duration},
        )

    async def coins_markets(
        self,
        vs_currency: str = "usd",
        order: str = "volume_desc",
        per_page: int = 250,
        page: int = 1,
        price_change_percentage: str = "1h,24h",
        sparkline: bool = False,
    ) -> List[Dict[str, Any]]:
        return await self._get(
            "/coins/markets",
            params={
                "vs_currency": vs_currency,
                "order": order,
                "per_page": per_page,
                "page": page,
                "sparkline": str(sparkline).lower(),
                "price_change_percentage": price_change_percentage,
            },
        )


cg = CoinGeckoProClient(COINGECKO_BASE_URL, COINGECKO_API_KEY, timeout=HTTP_TIMEOUT)


# =========================
# SCORING (pré-pump)
# =========================
def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default

def score_candidate(mcap: float, vol24: float, chg1h: float, chg24h: float) -> float:
    """
    Heurística:
      - Preferir liquidez (vol24) alta relativo ao mcap (turnover)
      - Preferir aceleração (chg1h) sem já estar esticado demais (chg24h)
      - Penalizar mcap muito baixa (fácil manipular) ou volume baixo
    Retorna 0..100
    """

    # Turnover = vol24 / mcap (quanto do mcap girou em 24h)
    turnover = vol24 / max(mcap, 1.0)

    # Normalizações suaves (log para não explodir)
    turnover_n = clamp(math.log10(1 + turnover * 10), 0.0, 2.0) / 2.0  # 0..1
    vol_n = clamp(math.log10(1 + vol24 / 1_000_000), 0.0, 4.0) / 4.0  # 0..1
    mcap_n = clamp(math.log10(1 + mcap / 
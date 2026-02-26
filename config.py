import os
from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class Settings:
    TG_BOT_TOKEN: str

    COINGECKO_BASE_URL: str
    COINGECKO_API_KEY: str

    VS_CURRENCY: str
    TOP_N: int
    CANDIDATES: int

    MIN_MCAP: float
    MAX_MCAP: float
    MIN_VOL24: float
    EXCLUDE_STABLES: bool

    HTTP_TIMEOUT: float
    HTTP_RETRIES: int

    # Premium boosters weights
    BOOST_TOP_GAINERS: float
    BOOST_TRENDING_SEARCH: float

    def cg_headers(self) -> Dict[str, str]:
        h = {"accept": "application/json"}
        if self.COINGECKO_API_KEY:
            h["x-cg-pro-api-key"] = self.COINGECKO_API_KEY
        return h


def _get_key() -> str:
    return (
        os.getenv("COINGECKO_API_KEY", "").strip()
        or os.getenv("COINGECKO_PRO_API_KEY", "").strip()
        or os.getenv("COINGECKO_KEY", "").strip()
    )


settings = Settings(
    TG_BOT_TOKEN=os.getenv("TG_BOT_TOKEN", "").strip(),

    COINGECKO_BASE_URL=os.getenv("COINGECKO_BASE_URL", "https://pro-api.coingecko.com/api/v3").rstrip("/"),
    COINGECKO_API_KEY=_get_key(),

    VS_CURRENCY=os.getenv("VS_CURRENCY", "usd").strip().lower(),
    TOP_N=int(os.getenv("TOP_N", "5")),
    CANDIDATES=int(os.getenv("CANDIDATES", "120")),

    MIN_MCAP=float(os.getenv("MIN_MCAP", "2000000")),
    MAX_MCAP=float(os.getenv("MAX_MCAP", "250000000")),
    MIN_VOL24=float(os.getenv("MIN_VOL24", "1500000")),
    EXCLUDE_STABLES=os.getenv("EXCLUDE_STABLES", "1").strip() == "1",

    HTTP_TIMEOUT=float(os.getenv("HTTP_TIMEOUT", "20")),
    HTTP_RETRIES=int(os.getenv("HTTP_RETRIES", "2")),

    BOOST_TOP_GAINERS=float(os.getenv("BOOST_TOP_GAINERS", "8.0")),       # +score
    BOOST_TRENDING_SEARCH=float(os.getenv("BOOST_TRENDING_SEARCH", "6.0")),# +score
)

if not settings.TG_BOT_TOKEN:
    raise RuntimeError("❌ Variável TG_BOT_TOKEN não definida.")
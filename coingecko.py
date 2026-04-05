import requests
import pandas as pd
import logging
from config import COINGECKO_API_KEY, VS_CURRENCY

logger = logging.getLogger(__name__)

def fetch_ohlc(coin_id: str, days: int = 30) -> pd.DataFrame | None:
    """
    Busca dados OHLC (Open, High, Low, Close) da CoinGecko.
    
    Args:
        coin_id: ID da moeda (ex: 'siren', 'bitcoin')
        days: Número de dias (1, 7, 14, 30, 90, 365)
    
    Returns:
        DataFrame com índice timestamp e colunas open, high, low, close.
        Retorna None em caso de erro.
    """
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc"
    headers = {
        "accept": "application/json",
        "x-cg-demo-api-key": COINGECKO_API_KEY
    }
    params = {
        "vs_currency": VS_CURRENCY,
        "days": days
    }
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        if not data:
            logger.warning(f"Dados vazios para {coin_id} com days={days}")
            return None
        
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        df = df[::-1]  # ordem cronológica (mais antigo -> mais recente)
        
        logger.info(f"Obtidos {len(df)} candles para {coin_id}")
        return df
    
    except requests.exceptions.RequestException as e:
        logger.error(f"Erro na requisição CoinGecko: {e}")
        return None
    except Exception as e:
        logger.error(f"Erro inesperado em fetch_ohlc: {e}")
        return None
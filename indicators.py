import pandas as pd
import pandas_ta as ta
import logging
from config import RSI_PERIOD, SMA_PERIOD, BB_PERIOD, BB_STD

logger = logging.getLogger(__name__)

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adiciona indicadores técnicos ao DataFrame.
    
    Indicadores calculados:
        - SMA (Média Móvel Simples)
        - RSI
        - MACD (linha, sinal, histograma)
        - Bollinger Bands (superior, média, inferior)
    
    Args:
        df: DataFrame com colunas 'open', 'high', 'low', 'close'
    
    Returns:
        DataFrame com as colunas dos indicadores adicionadas.
    """
    if df is None or len(df) < max(RSI_PERIOD, SMA_PERIOD, BB_PERIOD):
        logger.warning("Dados insuficientes para calcular indicadores")
        return df
    
    # Cópia para não modificar o original
    df = df.copy()
    
    # SMA
    df['SMA_20'] = ta.sma(df['close'], length=SMA_PERIOD)
    
    # RSI
    df['RSI'] = ta.rsi(df['close'], length=RSI_PERIOD)
    
    # MACD
    macd = ta.macd(df['close'])
    if macd is not None:
        df = df.join(macd)
    
    # Bollinger Bands
    bbands = ta.bbands(df['close'], length=BB_PERIOD, std=BB_STD)
    if bbands is not None:
        df = df.join(bbands)
    
    logger.debug("Indicadores calculados com sucesso")
    return df
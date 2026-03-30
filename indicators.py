import pandas as pd
import numpy as np
import config

def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def compute_macd(series, fast=12, slow=26, signal=9):
    exp_fast = series.ewm(span=fast, adjust=False).mean()
    exp_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = exp_fast - exp_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def compute_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def compute_volume_spike(volume_series):
    """
    Retorna 1 se o último volume > média móvel * fator, senão 0.
    """
    if len(volume_series) < config.VOLUME_MA_PERIOD:
        return 0
    ma_vol = volume_series.rolling(window=config.VOLUME_MA_PERIOD).mean().iloc[-1]
    last_vol = volume_series.iloc[-1]
    if ma_vol == 0:
        return 0
    if last_vol > ma_vol * config.VOLUME_SPIKE_FACTOR:
        return 1
    return 0

def build_indicator_pack_from_market_chart(data):
    prices = data.get('prices', [])
    if not prices or len(prices) < 50:
        return None

    df = pd.DataFrame(prices, columns=['timestamp', 'close'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)

    volumes = data.get('total_volumes', [])
    if volumes:
        vol_df = pd.DataFrame(volumes, columns=['timestamp', 'volume'])
        vol_df['timestamp'] = pd.to_datetime(vol_df['timestamp'], unit='ms')
        vol_df.set_index('timestamp', inplace=True)
        df = pd.concat([df, vol_df], axis=1).dropna()
    else:
        # se não houver volume, criamos uma série de zeros
        df['volume'] = 0

    if len(df) < 50:
        return None

    close = df['close']
    volume = df['volume']

    # --- RSI com pontuação progressiva ---
    rsi = compute_rsi(close, config.RSI_PERIOD).iloc[-1]
    if pd.isna(rsi):
        return None

    # Pontuação RSI: de -1 a 1, baseado em zona e momentum
    if rsi < 30:
        rsi_score = 1.0          # oversold forte
    elif rsi < 40:
        rsi_score = 0.5          # oversold leve, pode reverter
    elif rsi > 70:
        rsi_score = -1.0
    elif rsi > 60:
        rsi_score = -0.5
    else:
        # na zona neutra, verifica tendência (se RSI está subindo)
        # precisamos de mais de 2 períodos para ver inclinação
        if len(close) >= 3:
            rsi_prev = compute_rsi(close, config.RSI_PERIOD).iloc[-2]
            if rsi > rsi_prev and rsi > 50:
                rsi_score = 0.3   # momentum positivo
            elif rsi < rsi_prev and rsi < 50:
                rsi_score = -0.3
            else:
                rsi_score = 0
        else:
            rsi_score = 0

    # --- MACD ---
    macd, signal, hist = compute_macd(close, config.MACD_FAST, config.MACD_SLOW, config.MACD_SIGNAL)
    if len(hist) < 2:
        return None
    macd_score = 0
    # Cruzamento de alta: histograma passa de negativo para positivo
    if hist.iloc[-1] > 0 and hist.iloc[-2] <= 0:
        macd_score = 1.0
    # Cruzamento de baixa
    elif hist.iloc[-1] < 0 and hist.iloc[-2] >= 0:
        macd_score = -1.0
    else:
        # se já está positivo, mantém momentum fraco
        if hist.iloc[-1] > 0:
            macd_score = 0.2
        elif hist.iloc[-1] < 0:
            macd_score = -0.2

    # --- EMAs ---
    if len(close) < max(config.EMA_SHORT, config.EMA_LONG) + 1:
        return None
    ema_short = compute_ema(close, config.EMA_SHORT).iloc[-1]
    ema_long = compute_ema(close, config.EMA_LONG).iloc[-1]
    # Pontuação contínua: quanto maior a diferença, maior o score
    diff = (ema_short - ema_long) / ema_long  # variação relativa
    # mapeia de -1 a 1 (clamp)
    ema_score = max(-1.0, min(1.0, diff * 10))

    # --- Volume spike ---
    volume_score = compute_volume_spike(volume)

    # Score final ponderado
    final_score = (rsi_score * config.WEIGHTS['rsi'] +
                   macd_score * config.WEIGHTS['macd'] +
                   ema_score * config.WEIGHTS['ema'] +
                   volume_score * config.WEIGHTS['volume'])

    # Classificação (ainda mantida para compatibilidade)
    if final_score > config.BUY_THRESHOLD:
        classification = "COMPRA"
    elif final_score < config.SELL_THRESHOLD:
        classification = "VENDA"
    else:
        classification = "NEUTRO"

    return {
        'rsi': round(rsi, 2),
        'rsi_score': round(rsi_score, 2),
        'macd_score': round(macd_score, 2),
        'ema_score': round(ema_score, 2),
        'volume_score': volume_score,
        'final_score': round(final_score, 2),
        'classification': classification,
        'price': round(close.iloc[-1], 2),
        'timestamp': df.index[-1].isoformat()
    }
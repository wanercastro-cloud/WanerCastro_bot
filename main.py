import time
import logging
from datetime import datetime
from config import (
    COIN_ID, CHECK_EVERY_SECONDS, DAYS_TO_FETCH,
    RSI_OVERSOLD, RSI_OVERBOUGHT
)
from coingecko import fetch_ohlc
from indicators import calculate_indicators
from bot import send_telegram

# Configuração do logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Cache simples para evitar repetição de alertas (mesma hora + tipo)
_last_alert_cache = {}

def check_alerts(df) -> list:
    """
    Avalia as condições de alerta com base nos indicadores.
    Retorna uma lista de strings com os alertas.
    """
    alerts = []
    if df is None or len(df) < 3:
        return alerts
    
    last = df.iloc[-1]      # candle mais recente
    prev = df.iloc[-2]      # anterior
    
    # ----- RSI -----
    if 'RSI' in last and not pd.isna(last['RSI']):
        rsi_val = last['RSI']
        if rsi_val < RSI_OVERSOLD:
            alerts.append(f"🔴 RSI oversold: {rsi_val:.2f} (abaixo de {RSI_OVERSOLD})")
        elif rsi_val > RSI_OVERBOUGHT:
            alerts.append(f"🟢 RSI overbought: {rsi_val:.2f} (acima de {RSI_OVERBOUGHT})")
    
    # ----- MACD (cruzamento) -----
    # As colunas geradas pelo pandas_ta são: 'MACD_12_26_9', 'MACDs_12_26_9', 'MACDh_12_26_9'
    macd_col = 'MACD_12_26_9'
    signal_col = 'MACDs_12_26_9'
    if macd_col in last and signal_col in last and macd_col in prev and signal_col in prev:
        macd_now = last[macd_col]
        signal_now = last[signal_col]
        macd_prev = prev[macd_col]
        signal_prev = prev[signal_col]
        
        if macd_prev <= signal_prev and macd_now > signal_now:
            alerts.append(f"📈 MACD bullish crossover (MACD: {macd_now:.2f} > sinal: {signal_now:.2f})")
        elif macd_prev >= signal_prev and macd_now < signal_now:
            alerts.append(f"📉 MACD bearish crossover (MACD: {macd_now:.2f} < sinal: {signal_now:.2f})")
    
    # ----- Bollinger Bands -----
    bb_upper_col = f'BBU_{BB_PERIOD}_{BB_STD}'
    bb_lower_col = f'BBL_{BB_PERIOD}_{BB_STD}'
    if bb_upper_col in last and bb_lower_col in last:
        if last['close'] > last[bb_upper_col]:
            alerts.append(f"🚀 Preço acima da banda superior ({last[bb_upper_col]:.6f})")
        elif last['close'] < last[bb_lower_col]:
            alerts.append(f"📉 Preço abaixo da banda inferior ({last[bb_lower_col]:.6f})")
    
    return alerts

def main_loop():
    """Loop infinito de monitoramento"""
    logger.info(f"Iniciando monitor para {COIN_ID.upper()}")
    send_telegram(f"🤖 Bot de alertas iniciado!\nMoeda: {COIN_ID.upper()}\nIntervalo: {CHECK_EVERY_SECONDS}s")
    
    while True:
        try:
            # 1. Buscar dados
            df = fetch_ohlc(COIN_ID, days=DAYS_TO_FETCH)
            if df is None or len(df) < 30:
                logger.warning("Dados insuficientes. Aguardando...")
                time.sleep(CHECK_EVERY_SECONDS)
                continue
            
            # 2. Calcular indicadores
            df = calculate_indicators(df)
            
            # 3. Verificar alertas
            alerts = check_alerts(df)
            
            # 4. Evitar spam: envia cada tipo de alerta no máximo uma vez por hora
            current_hour = datetime.now().strftime("%Y-%m-%d %H")
            for alert in alerts:
                cache_key = f"{current_hour}_{alert[:50]}"
                if cache_key not in _last_alert_cache:
                    _last_alert_cache[cache_key] = True
                    # Limpeza simples da cache (mantém últimas 200 chaves)
                    if len(_last_alert_cache) > 200:
                        _last_alert_cache.clear()
                    
                    # Preço atual
                    current_price = df['close'].iloc[-1]
                    msg = f"💰 {COIN_ID.upper()}/{VS_CURRENCY.upper()}: {current_price:.8f}\n{alert}"
                    send_telegram(msg)
                    logger.info(f"Alerta enviado: {alert}")
            
            # Log de saúde
            last_rsi = df['RSI'].iloc[-1] if 'RSI' in df else None
            logger.info(f"Status - Preço: {df['close'].iloc[-1]:.8f} | RSI: {last_rsi}")
            
        except Exception as e:
            logger.error(f"Erro no loop principal: {e}", exc_info=True)
            send_telegram(f"⚠️ Erro crítico no bot: {str(e)[:100]}")
        
        time.sleep(CHECK_EVERY_SECONDS)

if __name__ == "__main__":
    # Importar aqui para evitar circularidade
    import pandas as pd
    from config import BB_PERIOD, BB_STD
    main_loop()
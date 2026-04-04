import os
import time
import logging
import requests
import pandas as pd
import pandas_ta as ta
from datetime import datetime

# ================= CONFIGURAÇÕES =================
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

COIN_ID = "siren"          # nome no CoinGecko
VS_CURRENCY = "usd"
INTERVAL_MINUTES = 15      # granularidade desejada (aproximada)
CHECK_EVERY_SECONDS = 300  # a cada 5 minutos verifica novos dados

# Parâmetros dos indicadores
RSI_PERIOD = 14
SMA_PERIOD = 20
BB_PERIOD = 20
BB_STD = 2

# Limiares para alertas
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ================= FUNÇÕES =================
def send_telegram(message):
    """Envia mensagem para o Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            logger.error(f"Erro Telegram: {resp.text}")
    except Exception as e:
        logger.error(f"Falha ao enviar mensagem: {e}")

def fetch_ohlc(days=30):
    """Busca dados OHLC da CoinGecko (velas de 4h se days=30, ou menor se days menor)"""
    url = f"https://api.coingecko.com/api/v3/coins/{COIN_ID}/ohlc"
    headers = {"accept": "application/json", "x-cg-demo-api-key": COINGECKO_API_KEY}
    params = {"vs_currency": VS_CURRENCY, "days": days}
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        if not data:
            logger.warning("Dados vazios retornados pela CoinGecko")
            return None
        
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        df = df[::-1]  # ordem cronológica
        logger.info(f"Obtidos {len(df)} candles")
        return df
    except Exception as e:
        logger.error(f"Erro na requisição: {e}")
        return None

def calculate_indicators(df):
    """Adiciona indicadores ao DataFrame"""
    df['SMA_20'] = ta.sma(df['close'], length=SMA_PERIOD)
    df['RSI'] = ta.rsi(df['close'], length=RSI_PERIOD)
    
    # MACD
    macd = ta.macd(df['close'])
    df = df.join(macd)
    
    # Bollinger Bands
    bbands = ta.bbands(df['close'], length=BB_PERIOD, std=BB_STD)
    df = df.join(bbands)
    
    return df

def check_alerts(df):
    """Verifica condições e retorna lista de alertas"""
    alerts = []
    last = df.iloc[-1]      # candle mais recente
    prev = df.iloc[-2]      # anterior
    
    # Verificar RSI
    if not pd.isna(last['RSI']):
        if last['RSI'] < RSI_OVERSOLD:
            alerts.append(f"🔴 RSI oversold: {last['RSI']:.2f} (abaixo de {RSI_OVERSOLD})")
        elif last['RSI'] > RSI_OVERBOUGHT:
            alerts.append(f"🟢 RSI overbought: {last['RSI']:.2f} (acima de {RSI_OVERBOUGHT})")
    
    # Cruzamento MACD (linha MACD cruza acima do sinal)
    if 'MACD_12_26_9' in last and 'MACDs_12_26_9' in last:
        macd_now = last['MACD_12_26_9']
        signal_now = last['MACDs_12_26_9']
        macd_prev = prev['MACD_12_26_9']
        signal_prev = prev['MACDs_12_26_9']
        
        if macd_prev <= signal_prev and macd_now > signal_now:
            alerts.append(f"📈 MACD bullish crossover (MACD: {macd_now:.2f} > sinal: {signal_now:.2f})")
        elif macd_prev >= signal_prev and macd_now < signal_now:
            alerts.append(f"📉 MACD bearish crossover (MACD: {macd_now:.2f} < sinal: {signal_now:.2f})")
    
    # Preço acima/abaixo das Bandas de Bollinger
    bb_upper = f'BBU_{BB_PERIOD}_{BB_STD}'
    bb_lower = f'BBL_{BB_PERIOD}_{BB_STD}'
    if bb_upper in last and bb_lower in last:
        if last['close'] > last[bb_upper]:
            alerts.append(f"🚀 Preço acima da banda superior ({last[bb_upper]:.4f})")
        elif last['close'] < last[bb_lower]:
            alerts.append(f"📉 Preço abaixo da banda inferior ({last[bb_lower]:.4f})")
    
    return alerts

def main_loop():
    logger.info("Iniciando monitor de criptomoedas (CoinGecko + Telegram)")
    send_telegram("🤖 Bot de alertas iniciado! Monitorando SIREN/USD")
    
    # Armazenar último timestamp para não repetir alertas
    last_alert_cache = {}
    
    while True:
        try:
            # Buscar dados suficientes para indicadores (ex: últimos 100 dias)
            df = fetch_ohlc(days=100)
            if df is None or len(df) < 30:
                logger.warning("Dados insuficientes. Aguardando...")
                time.sleep(CHECK_EVERY_SECONDS)
                continue
            
            df = calculate_indicators(df)
            alerts = check_alerts(df)
            
            # Evita spam: envia cada tipo de alerta no máximo uma vez por hora
            current_hour = datetime.now().strftime("%Y-%m-%d %H")
            for alert in alerts:
                key = f"{current_hour}_{alert[:50]}"  # chave única
                if key not in last_alert_cache:
                    last_alert_cache[key] = True
                    # Limpeza da cache (manter só últimas 24h)
                    if len(last_alert_cache) > 100:
                        last_alert_cache.clear()
                    
                    # Prepara mensagem com preço atual
                    price = df['close'].iloc[-1]
                    msg = f"💰 {COIN_ID.upper()}/USD: {price:.6f}\n{alert}"
                    send_telegram(msg)
                    logger.info(f"Alerta enviado: {alert}")
            
            # Log periódico de status
            logger.info(f"Verificação concluída. Preço atual: {df['close'].iloc[-1]:.6f}, RSI: {df['RSI'].iloc[-1]:.2f}")
            
        except Exception as e:
            logger.error(f"Erro inesperado no loop: {e}", exc_info=True)
            send_telegram(f"⚠️ Erro no bot: {str(e)[:100]}")
        
        time.sleep(CHECK_EVERY_SECONDS)

if __name__ == "__main__":
    # Verificar se todas as variáveis de ambiente estão presentes
    required_vars = [COINGECKO_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]
    if not all(required_vars):
        logger.error("Faltam variáveis de ambiente! Defina: COINGECKO_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID")
        exit(1)
    
    main_loop()
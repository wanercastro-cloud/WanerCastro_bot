import os
import logging
import json
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dotenv import load_dotenv
import config  # importa as configurações do config.py

# Carrega variáveis de ambiente (apenas para testes locais)
load_dotenv()

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ========= CONFIGURAÇÕES DO TELEGRAM ==========
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")

# ========= CACHE PARA EVITAR SPAM ==========
CACHE_FILE = "last_alerts.json"
ALERT_COOLDOWN_HOURS = 1   # Só envia um alerta por moeda a cada X horas

def load_last_alert_times():
    """Lê o dicionário de últimos alertas do cache"""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                data = json.load(f)
                # Converte strings de volta para datetime
                for coin, ts_str in data.items():
                    data[coin] = datetime.fromisoformat(ts_str)
                return data
        except Exception as e:
            logger.warning(f"Erro ao ler cache: {e}")
    return {}

def save_last_alert_times(alert_times):
    """Salva o dicionário de últimos alertas no cache"""
    # Converte datetime para string para serialização
    serializable = {coin: ts.isoformat() for coin, ts in alert_times.items()}
    with open(CACHE_FILE, "w") as f:
        json.dump(serializable, f)

# ========= BUSCAR DADOS DA COINGECKO ==========
def fetch_ohlcv(coin_id, days=30):
    """
    Busca dados OHLCV (Open, High, Low, Close, Volume) dos últimos 'days' dias.
    Endpoint: /coins/{id}/ohlc?vs_currency=usd&days={days}
    """
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc"
    params = {
        "vs_currency": "usd",
        "days": days
    }
    headers = {
        "x-cg-demo-api-key": COINGECKO_API_KEY
    }
    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        # data é uma lista de listas: [timestamp, open, high, low, close]
        df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        # O CoinGecko OHLC não fornece volume diretamente; vamos adicionar uma coluna fictícia
        # para manter compatibilidade. Para volume real, seria necessário outro endpoint.
        df["volume"] = 0  # Placeholder
        return df
    except Exception as e:
        logger.error(f"Erro ao buscar dados para {coin_id}: {e}")
        return None

# ========= INDICADORES TÉCNICOS ==========
def calculate_ema(series, period):
    """Exponential Moving Average"""
    return series.ewm(span=period, adjust=False).mean()

def calculate_rsi(series, period=14):
    """Relative Strength Index"""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_macd(close, fast=12, slow=26, signal=9):
    """MACD: linha, sinal e histograma"""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    macd_signal = macd_line.ewm(span=signal, adjust=False).mean()
    macd_hist = macd_line - macd_signal
    return macd_line, macd_signal, macd_hist

# ========= LÓGICA DE SINAL ==========
def check_signal(coin_id, df):
    """
    Verifica se as condições de alerta foram atendidas para uma moeda.
    Retorna um dicionário com os detalhes do sinal ou None.
    """
    if df is None or len(df) < 50:
        return None

    close = df["close"]
    ema7 = calculate_ema(close, 7)
    ema14 = calculate_ema(close, 14)
    rsi = calculate_rsi(close, config.RSI_PERIOD)
    _, _, macd_hist = calculate_macd(close)

    # Condições de entrada (configuráveis)
    # Exemplo: Preço abaixo da EMA7 (perda de força), RSI sobrecomprado, MACD histograma caindo
    perdeu_forca = close.iloc[-1] < ema7.iloc[-1]
    sobrecomprado = rsi.iloc[-1] > config.RSI_OVERBOUGHT
    momentum_virando = macd_hist.iloc[-1] < macd_hist.iloc[-2]

    if perdeu_forca and sobrecomprado and momentum_virando:
        return {
            "coin_id": coin_id,
            "preco": round(close.iloc[-1], 6),
            "rsi": round(rsi.iloc[-1], 2),
            "ema7": round(ema7.iloc[-1], 4),
            "ema14": round(ema14.iloc[-1], 4),
            "macd_hist": round(macd_hist.iloc[-1], 6),
            "timestamp": datetime.now().isoformat()
        }
    return None

# ========= ENVIO DE MENSAGENS PARA O TELEGRAM ==========
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(url, json=payload, timeout=5)
        if r.status_code != 200:
            logger.error(f"Erro Telegram: {r.text}")
        else:
            logger.info("Mensagem enviada com sucesso.")
    except Exception as e:
        logger.error(f"Falha ao enviar Telegram: {e}")

def format_alert_message(alert):
    return (
        f"🔻 <b>ALERTA - QUEDA IMINENTE (FILTRADO)</b>\n"
        f"📌 {alert['coin_id'].upper()}\n"
        f"💰 Preço: ${alert['preco']:.6f}\n"
        f"📈 RSI: {alert['rsi']} (limite {config.RSI_OVERBOUGHT})\n"
        f"📊 EMA7: {alert['ema7']} | EMA14: {alert['ema14']}\n"
        f"📉 MACD Hist: {alert['macd_hist']}\n"
        f"🕒 {alert['timestamp']}\n"
        f"✅ Alerta gerado APENAS quando a tendência forte acaba."
    )

# ========= MAIN (execução única) ==========
def main():
    logger.info("Iniciando verificação...")
    last_alerts = load_last_alert_times()
    now = datetime.now()
    any_alert = False

    for coin in config.COINS_TO_MONITOR:
        coin_id = coin["id"]
        coin_name = coin["name"]

        # Verifica cooldown
        last_alert_time = last_alerts.get(coin_id)
        if last_alert_time and (now - last_alert_time) < timedelta(hours=ALERT_COOLDOWN_HOURS):
            logger.info(f"Moeda {coin_name} em cooldown. Último alerta em {last_alert_time}")
            continue

        logger.info(f"Processando {coin_name}...")
        df = fetch_ohlcv(coin_id, days=config.LOOKBACK_DAYS)
        alert = check_signal(coin_id, df)
        if alert:
            msg = format_alert_message(alert)
            send_telegram(msg)
            last_alerts[coin_id] = now
            any_alert = True
        else:
            logger.info(f"Nenhum sinal para {coin_name}.")

    if any_alert:
        save_last_alert_times(last_alerts)
    else:
        logger.info("Nenhum alerta gerado nesta execução.")

if __name__ == "__main__":
    main()
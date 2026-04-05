# bot.py
import os
import sys
import json
import logging
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dotenv import load_dotenv
import config

# Carrega .env apenas localmente (no Actions, usa secrets)
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ========= TELEGRAM ==========
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ========= CACHE PARA EVITAR SPAM ==========
CACHE_FILE = "last_alert.json"
ALERT_COOLDOWN_HOURS = 1   # Só envia um alerta por hora (evita repetição)

def load_last_alert_time():
    """Lê timestamp do último alerta salvo no cache do Actions"""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                data = json.load(f)
                return datetime.fromisoformat(data.get("last_alert", "2000-01-01T00:00:00"))
        except:
            return datetime.min
    return datetime.min

def save_last_alert_time(ts):
    with open(CACHE_FILE, "w") as f:
        json.dump({"last_alert": ts.isoformat()}, f)

# ========= INDICADORES (igual antes) ==========
def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_macd(close, fast, slow, signal):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    macd_signal = macd_line.ewm(span=signal, adjust=False).mean()
    macd_hist = macd_line - macd_signal
    return macd_line, macd_signal, macd_hist

# ========= BUSCAR DADOS ==========
def fetch_klines(symbol, interval, limit):
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }
    resp = requests.get(config.BINANCE_BASE_URL, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    df = pd.DataFrame(data, columns=[
        'time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'number_of_trades',
        'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
    ])
    df['close'] = df['close'].astype(float)
    df['time'] = pd.to_datetime(df['time'], unit='ms')
    return df

# ========= LÓGICA DO SINAL ==========
def check_signal(df):
    if df is None or len(df) < config.EMA_LONG + 10:
        return None

    close = df['close']
    ema7 = calculate_ema(close, config.EMA_SHORT)
    ema14 = calculate_ema(close, config.EMA_MEDIUM)
    ema28 = calculate_ema(close, config.EMA_LONG)
    rsi = calculate_rsi(close, config.RSI_PERIOD)
    _, _, macd_hist = calculate_macd(close, config.MACD_FAST, config.MACD_SLOW, config.MACD_SIGNAL)

    tendencia_muito_forte = (ema7.iloc[-1] > ema14.iloc[-1]) and (ema14.iloc[-1] > ema28.iloc[-1])

    if config.IGNORE_STRONG_TREND and tendencia_muito_forte:
        logger.info("Tendência explosiva – alerta suprimido.")
        return None

    perdeu_forca = close.iloc[-1] < ema7.iloc[-1]
    sobrecomprado = rsi.iloc[-1] > config.RSI_OVERBOUGHT
    momentum_virando = macd_hist.iloc[-1] < macd_hist.iloc[-2]

    if perdeu_forca and sobrecomprado and momentum_virando:
        return {
            "preco": close.iloc[-1],
            "rsi": round(rsi.iloc[-1], 2),
            "ema7": round(ema7.iloc[-1], 4),
            "ema14": round(ema14.iloc[-1], 4),
            "ema28": round(ema28.iloc[-1], 4),
            "macd_hist": round(macd_hist.iloc[-1], 6),
            "tendencia_forte": tendencia_muito_forte,
            "timestamp": datetime.now().isoformat()
        }
    return None

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    r = requests.post(url, json=payload, timeout=5)
    if r.status_code != 200:
        logger.error(f"Telegram erro: {r.text}")

def format_alert_message(alert):
    return (
        f"🔻 <b>ALERTA - QUEDA IMINENTE (FILTRADO)</b>\n"
        f"📌 {config.SYMBOL}\n"
        f"💰 Preço: {alert['preco']:.6f}\n"
        f"📈 RSI: {alert['rsi']} (limite {config.RSI_OVERBOUGHT})\n"
        f"📊 EMA7: {alert['ema7']} | EMA14: {alert['ema14']}\n"
        f"📉 MACD Hist: {alert['macd_hist']}\n"
        f"🕒 {alert['timestamp']}\n"
        f"✅ Alerta gerado APENAS quando a tendência forte acaba."
    )

# ========= MAIN (execução única) ==========
def main():
    logger.info("Iniciando verificação...")
    try:
        df = fetch_klines(config.SYMBOL, config.INTERVAL, config.LIMIT)
        alerta = check_signal(df)
        if alerta:
            last_alert = load_last_alert_time()
            now = datetime.now()
            if now - last_alert < timedelta(hours=ALERT_COOLDOWN_HOURS):
                logger.info(f"Alerta suprimido: último alerta em {last_alert}")
                return
            msg = format_alert_message(alerta)
            send_telegram(msg)
            save_last_alert_time(now)
            logger.info("Alerta enviado com sucesso!")
        else:
            logger.info("Nenhum sinal detectado.")
    except Exception as e:
        logger.error(f"Erro: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
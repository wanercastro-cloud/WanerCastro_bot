import os
import json
import logging
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dotenv import load_dotenv
import config

# Carrega .env apenas para testes locais (não usado no GitHub Actions)
load_dotenv()

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ========== CONFIGURAÇÕES DO TELEGRAM ==========
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")

# ========== CACHE PARA EVITAR SPAM ==========
CACHE_FILE = "last_alerts.json"
ALERT_COOLDOWN_HOURS = 1   # Só envia um alerta por moeda a cada X horas

def load_last_alert_times():
    """Lê o dicionário de últimos alertas do cache"""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                data = json.load(f)
                return {k: datetime.fromisoformat(v) for k, v in data.items()}
        except Exception as e:
            logger.warning(f"Erro ao ler cache: {e}")
    return {}

def save_last_alert_times(alert_times):
    """Salva o dicionário de últimos alertas no cache"""
    serializable = {k: v.isoformat() for k, v in alert_times.items()}
    with open(CACHE_FILE, "w") as f:
        json.dump(serializable, f)

# ========== BUSCAR DADOS DA COINGECKO ==========
def fetch_ohlcv(coin_id, days=30):
    """
    Busca dados OHLCV (Open, High, Low, Close) dos últimos 'days' dias.
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
        # O OHLC da CoinGecko não fornece volume; adicionamos uma coluna vazia para compatibilidade
        df["volume"] = 0
        return df
    except Exception as e:
        logger.error(f"Erro ao buscar dados para {coin_id}: {e}")
        return None

# ========== INDICADORES TÉCNICOS ==========
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

# ========== LÓGICA DE SINAIS (LONG / SHORT) ==========
def check_signals(coin_id, df):
    """
    Verifica se as condições de COMPRA (LONG) ou VENDA (SHORT) foram atendidas.
    Retorna (tipo_sinal, dados) ou (None, None).
    """
    if df is None or len(df) < 50:
        return None, None

    close = df["close"]
    ema7 = calculate_ema(close, 7)
    ema14 = calculate_ema(close, 14)
    rsi = calculate_rsi(close, config.RSI_PERIOD)
    _, _, macd_hist = calculate_macd(close)

    preco = close.iloc[-1]
    rsi_val = rsi.iloc[-1]
    macd_hist_val = macd_hist.iloc[-1]
    macd_hist_prev = macd_hist.iloc[-2]

    # --- SINAL DE COMPRA (LONG) ---
    # 1. Preço acima da EMA7 (tendência de curto prazo para cima)
    # 2. RSI saindo de sobrevenda (<30) OU (RSI > 50 e MACD crescente)
    # 3. MACD histograma aumentando (momentum positivo)
    cond1_long = preco > ema7.iloc[-1]
    cond2_long = (rsi_val < 30 and rsi_val > rsi.iloc[-2]) or (rsi_val > 50 and macd_hist_val > macd_hist_prev)
    cond3_long = macd_hist_val > macd_hist_prev

    long_signal = cond1_long and cond2_long and cond3_long

    # --- SINAL DE VENDA (SHORT) ---
    # 1. Preço abaixo da EMA7 (perda de força)
    # 2. RSI sobrecomprado (>70) e caindo
    # 3. MACD histograma diminuindo (momentum negativo)
    cond1_short = preco < ema7.iloc[-1]
    cond2_short = rsi_val > 70 and rsi_val < rsi.iloc[-2]
    cond3_short = macd_hist_val < macd_hist_prev

    short_signal = cond1_short and cond2_short and cond3_short

    signal_data = {
        "preco": round(preco, 6),
        "rsi": round(rsi_val, 2),
        "ema7": round(ema7.iloc[-1], 4),
        "ema14": round(ema14.iloc[-1], 4),
        "macd_hist": round(macd_hist_val, 6),
        "timestamp": datetime.now().isoformat()
    }

    if long_signal:
        return "LONG", signal_data
    elif short_signal:
        return "SHORT", signal_data
    else:
        return None, None

# ========== ENVIO DE MENSAGENS PARA O TELEGRAM ==========
def send_telegram(message):
    """Envia mensagem via bot do Telegram"""
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

def format_alert_message(coin_name, signal_type, data):
    """Formata a mensagem do alerta para Telegram"""
    emoji = "🟢" if signal_type == "LONG" else "🔴"
    acao = "COMPRAR (LONG)" if signal_type == "LONG" else "VENDER (SHORT)"
    return (
        f"{emoji} <b>SINAL DE {signal_type}</b> {emoji}\n"
        f"📌 {coin_name.upper()}\n"
        f"🎯 Ação: {acao}\n"
        f"💰 Preço: ${data['preco']:.6f}\n"
        f"📊 RSI: {data['rsi']}\n"
        f"📈 EMA7: {data['ema7']} | EMA14: {data['ema14']}\n"
        f"📉 MACD Hist: {data['macd_hist']}\n"
        f"⏰ {data['timestamp']}\n"
        f"⚠️ Bybit Futuros: use stop-loss!"
    )

# ========== MAIN ==========
def main():
    logger.info("Iniciando verificação de sinais LONG/SHORT...")
    last_alerts = load_last_alert_times()
    now = datetime.now()
    any_alert = False

    for coin in config.COINS_TO_MONITOR:
        coin_id = coin["id"]
        coin_name = coin["name"]

        # Cooldown: evita spam
        last_alert_time = last_alerts.get(coin_id)
        if last_alert_time and (now - last_alert_time) < timedelta(hours=ALERT_COOLDOWN_HOURS):
            logger.info(f"Moeda {coin_name} em cooldown. Último alerta em {last_alert_time}")
            continue

        logger.info(f"Processando {coin_name}...")
        df = fetch_ohlcv(coin_id, days=config.LOOKBACK_DAYS)
        signal_type, signal_data = check_signals(coin_id, df)
        if signal_type:
            msg = format_alert_message(coin_name, signal_type, signal_data)
            send_telegram(msg)
            last_alerts[coin_id] = now
            any_alert = True
            logger.info(f"Sinal {signal_type} enviado para {coin_name}")
        else:
            logger.info(f"Nenhum sinal para {coin_name}.")

    if any_alert:
        save_last_alert_times(last_alerts)
    else:
        logger.info("Nenhum alerta gerado nesta execução.")

if __name__ == "__main__":
    main()
import os
import json
import logging
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")

# ========== TESTE FORÇADO (REMOVER DEPOIS) ==========
def enviar_mensagem_teste():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Telegram não configurado")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": "🤖 Bot ativo! Este é um teste. Em breve você receberá sinais reais.", "parse_mode": "HTML"}
    try:
        r = requests.post(url, json=payload, timeout=5)
        if r.status_code == 200:
            logger.info("Mensagem de teste enviada com sucesso!")
        else:
            logger.error(f"Erro teste: {r.text}")
    except Exception as e:
        logger.error(f"Falha: {e}")

# ========== FUNÇÕES DE BUSCA TOP 30 ==========
def get_top_coins(limit=30):
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {"vs_currency": "usd", "order": "market_cap_desc", "per_page": limit, "page": 1}
    headers = {"x-cg-demo-api-key": COINGECKO_API_KEY}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        coins = [{"id": c["id"], "symbol": c["symbol"].upper(), "name": c["name"]} for c in data]
        logger.info(f"Carregadas {len(coins)} moedas")
        return coins
    except Exception as e:
        logger.error(f"Erro ao buscar moedas: {e}")
        return []

def fetch_ohlcv(coin_id, days=30):
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc"
    params = {"vs_currency": "usd", "days": days}
    headers = {"x-cg-demo-api-key": COINGECKO_API_KEY}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return df
    except Exception as e:
        logger.error(f"Erro OHLC {coin_id}: {e}")
        return None

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

def calculate_macd(close):
    ema_fast = close.ewm(span=12, adjust=False).mean()
    ema_slow = close.ewm(span=26, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    return macd, signal, hist

def check_signals(df):
    if df is None or len(df) < 50:
        return None, None
    close = df["close"]
    ema7 = calculate_ema(close, 7)
    rsi = calculate_rsi(close)
    _, _, hist = calculate_macd(close)
    preco = close.iloc[-1]
    rsi_val = rsi.iloc[-1]
    hist_val = hist.iloc[-1]
    hist_prev = hist.iloc[-2]
    # LONG
    if preco > ema7.iloc[-1] and rsi_val > 55 and hist_val > hist_prev and hist_val > 0:
        return "LONG", {"preco": preco, "rsi": rsi_val, "ema7": ema7.iloc[-1], "hist": hist_val}
    # SHORT
    if preco < ema7.iloc[-1] and rsi_val < 45 and hist_val < hist_prev and hist_val < 0:
        return "SHORT", {"preco": preco, "rsi": rsi_val, "ema7": ema7.iloc[-1], "hist": hist_val}
    return None, None

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        r = requests.post(url, json=payload, timeout=5)
        if r.status_code != 200:
            logger.error(f"Erro: {r.text}")
    except Exception as e:
        logger.error(f"Falha: {e}")

def format_message(coin, signal, data):
    emoji = "🟢" if signal == "LONG" else "🔴"
    acao = "COMPRAR (LONG)" if signal == "LONG" else "VENDER (SHORT)"
    return (f"{emoji} <b>{signal} - OPORTUNIDADE</b> {emoji}\n"
            f"📌 {coin['name']} ({coin['symbol']})\n"
            f"🎯 {acao}\n"
            f"💰 ${data['preco']:.6f}\n"
            f"📊 RSI: {data['rsi']:.1f}\n"
            f"📈 EMA7: {data['ema7']:.4f}\n"
            f"📉 MACD Hist: {data['hist']:.6f}\n"
            f"⚠️ Bybit Futuros: use stop-loss")

def main():
    logger.info("Iniciando...")
    enviar_mensagem_teste()  # <--- TESTE IMEDIATO

    coins = get_top_coins(limit=30)
    if not coins:
        return

    for coin in coins:
        logger.info(f"Analisando {coin['name']}...")
        df = fetch_ohlcv(coin['id'])
        signal, data = check_signals(df)
        if signal:
            msg = format_message(coin, signal, data)
            send_telegram(msg)
            logger.info(f"Sinal {signal} enviado para {coin['name']}")
        else:
            logger.info("Sem sinal")

if __name__ == "__main__":
    main()
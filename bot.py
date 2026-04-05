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

# ========== CONFIGURAÇÕES ==========
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")

CACHE_FILE = "last_alerts.json"
ALERT_COOLDOWN_HOURS = 4   # Não repetir alerta da mesma moeda por 4h

# Parâmetros dos indicadores
LOOKBACK_DAYS = 30
RSI_PERIOD = 14
EMA_SHORT = 7
VOLUME_MA_PERIOD = 20

# Limites para evitar moedas de baixa liquidez
MIN_VOLUME_USD = 10_000_000   # Volume mínimo de $10M nas últimas 24h (aproximado)

# ========== FUNÇÕES AUXILIARES ==========
def load_last_alert_times():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                data = json.load(f)
                return {k: datetime.fromisoformat(v) for k, v in data.items()}
        except:
            return {}
    return {}

def save_last_alert_times(alert_times):
    serializable = {k: v.isoformat() for k, v in alert_times.items()}
    with open(CACHE_FILE, "w") as f:
        json.dump(serializable, f)

# ========== BUSCAR TOP 100 MOEDAS ==========
def get_top_100_coins():
    """Retorna lista de dicionários com id, symbol, name, market_cap das top 100 moedas."""
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": 100,
        "page": 1,
        "sparkline": "false"
    }
    headers = {"x-cg-demo-api-key": COINGECKO_API_KEY}
    try:
        response = requests.get(url, headers=headers, params=params, timeout=20)
        response.raise_for_status()
        data = response.json()
        coins = []
        for item in data:
            # Filtra moedas com volume mínimo (opcional)
            if item.get("total_volume", 0) >= MIN_VOLUME_USD:
                coins.append({
                    "id": item["id"],
                    "symbol": item["symbol"].upper(),
                    "name": item["name"],
                    "market_cap": item["market_cap"]
                })
        logger.info(f"Carregadas {len(coins)} moedas com volume > ${MIN_VOLUME_USD:,.0f}")
        return coins
    except Exception as e:
        logger.error(f"Erro ao buscar top 100: {e}")
        return []

# ========== BUSCAR DADOS OHLC ==========
def fetch_ohlcv(coin_id, days=30):
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc"
    params = {"vs_currency": "usd", "days": days}
    headers = {"x-cg-demo-api-key": COINGECKO_API_KEY}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        # Para volume, infelizmente o OHLC não tem. Vamos usar um placeholder.
        # O volume real poderia ser obtido do endpoint /coins/{id}/market_chart, mas aumenta chamadas.
        # Como alternativa, usamos volume simulado (não usaremos volume nas condições por enquanto)
        df["volume"] = 0
        return df
    except Exception as e:
        logger.error(f"Erro ao buscar dados para {coin_id}: {e}")
        return None

# ========== INDICADORES ==========
def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_macd(close, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    macd_signal = macd_line.ewm(span=signal, adjust=False).mean()
    macd_hist = macd_line - macd_signal
    return macd_line, macd_signal, macd_hist

def calculate_volume_ma(volume, period=20):
    return volume.rolling(window=period).mean()

# ========== LÓGICA DE SINAIS (RIGOROSA) ==========
def check_signals(coin_id, df):
    """Retorna ('LONG', dados) ou ('SHORT', dados) ou (None, None)"""
    if df is None or len(df) < 50:
        return None, None

    close = df["close"]
    ema7 = calculate_ema(close, EMA_SHORT)
    rsi = calculate_rsi(close, RSI_PERIOD)
    macd_line, macd_signal, macd_hist = calculate_macd(close)
    # volume_ma = calculate_volume_ma(df["volume"], VOLUME_MA_PERIOD)

    preco = close.iloc[-1]
    rsi_val = rsi.iloc[-1]
    macd_hist_val = macd_hist.iloc[-1]
    macd_hist_prev = macd_hist.iloc[-2]
    macd_hist_prev2 = macd_hist.iloc[-3]

    # Condições LONG
    cond1_long = preco > ema7.iloc[-1]                     # preço acima da EMA7
    cond2_long = rsi_val > 50 and rsi_val > rsi.iloc[-2]   # RSI > 50 e subindo
    cond3_long = macd_hist_val > 0 and macd_hist_val > macd_hist_prev and macd_hist_prev > macd_hist_prev2  # histograma positivo e crescendo 2 velas

    # Condições SHORT
    cond1_short = preco < ema7.iloc[-1]
    cond2_short = rsi_val < 50 and rsi_val < rsi.iloc[-2]
    cond3_short = macd_hist_val < 0 and macd_hist_val < macd_hist_prev and macd_hist_prev < macd_hist_prev2

    # Opcional: volume acima da média (desativado por falta de dados)
    # volume_ok = df["volume"].iloc[-1] > volume_ma.iloc[-1]

    if cond1_long and cond2_long and cond3_long:
        signal_data = {
            "preco": round(preco, 6),
            "rsi": round(rsi_val, 2),
            "ema7": round(ema7.iloc[-1], 4),
            "macd_hist": round(macd_hist_val, 6),
            "timestamp": datetime.now().isoformat()
        }
        return "LONG", signal_data
    elif cond1_short and cond2_short and cond3_short:
        signal_data = {
            "preco": round(preco, 6),
            "rsi": round(rsi_val, 2),
            "ema7": round(ema7.iloc[-1], 4),
            "macd_hist": round(macd_hist_val, 6),
            "timestamp": datetime.now().isoformat()
        }
        return "SHORT", signal_data
    else:
        return None, None

# ========== TELEGRAM ==========
def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Credenciais do Telegram não configuradas")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        r = requests.post(url, json=payload, timeout=5)
        if r.status_code != 200:
            logger.error(f"Erro Telegram: {r.text}")
        else:
            logger.info("Mensagem enviada com sucesso")
    except Exception as e:
        logger.error(f"Falha no envio: {e}")

def format_alert_message(coin_name, symbol, signal_type, data):
    emoji = "🟢" if signal_type == "LONG" else "🔴"
    acao = "COMPRAR (LONG)" if signal_type == "LONG" else "VENDER (SHORT)"
    return (
        f"{emoji} <b>{signal_type} - OPORTUNIDADE REAL</b> {emoji}\n"
        f"📌 {coin_name} ({symbol})\n"
        f"🎯 Ação: {acao}\n"
        f"💰 Preço: ${data['preco']:.6f}\n"
        f"📊 RSI: {data['rsi']}\n"
        f"📈 EMA7: {data['ema7']}\n"
        f"📉 MACD Hist: {data['macd_hist']}\n"
        f"⏰ {data['timestamp']}\n"
        f"⚠️ Bybit Futuros: use stop-loss e gestão de risco!"
    )

# ========== MAIN ==========
def main():
    logger.info("Iniciando busca por oportunidades LONG/SHORT (top 100 moedas)...")
    
    # Verifica credenciais
    if not all([TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, COINGECKO_API_KEY]):
        logger.error("Faltam secrets do Telegram ou CoinGecko. Encerrando.")
        return

    # Obtém lista dinâmica das top 100 moedas
    coins = get_top_100_coins()
    if not coins:
        logger.error("Nenhuma moeda carregada. Verifique a API key ou conexão.")
        return

    last_alerts = load_last_alert_times()
    now = datetime.now()
    any_alert = False

    for coin in coins:
        coin_id = coin["id"]
        coin_name = coin["name"]
        symbol = coin["symbol"]

        # Cooldown
        last_time = last_alerts.get(coin_id)
        if last_time and (now - last_time) < timedelta(hours=ALERT_COOLDOWN_HOURS):
            logger.info(f"{coin_name} em cooldown (alerta em {last_time})")
            continue

        logger.info(f"Analisando {coin_name} ({symbol})...")
        df = fetch_ohlcv(coin_id, days=LOOKBACK_DAYS)
        signal_type, signal_data = check_signals(coin_id, df)
        if signal_type:
            msg = format_alert_message(coin_name, symbol, signal_type, signal_data)
            send_telegram(msg)
            last_alerts[coin_id] = now
            any_alert = True
            logger.info(f"Sinal {signal_type} enviado para {coin_name}")
        else:
            logger.info(f"Sem sinal para {coin_name}")

    if any_alert:
        save_last_alert_times(last_alerts)
    else:
        logger.info("Nenhuma oportunidade encontrada nesta execução.")

if __name__ == "__main__":
    main()
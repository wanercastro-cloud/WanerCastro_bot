import requests
import pandas as pd
import numpy as np
import time
import json
import logging
import os
from datetime import datetime
from dotenv import load_dotenv
import config

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CryptoClassifier:
    def __init__(self):
        self.coins = config.COINS
        self.timeframe = config.TIMEFRAME
        self.limit = config.LIMIT
        self.api_url = config.COINGECKO_API_URL
        self.api_key = config.COINGECKO_API_KEY
        self.headers = {}
        if self.api_key:
            self.headers['x-cg-pro-api-key'] = self.api_key

    def _make_request(self, endpoint, params=None):
        """Faz requisição à API da CoinGecko com tratamento de limite"""
        url = f"{self.api_url}{endpoint}"
        try:
            resp = requests.get(url, headers=self.headers, params=params, timeout=10)
            if resp.status_code == 429:
                # Rate limit, espera e tenta novamente
                logger.warning("Rate limit atingido, aguardando 60s...")
                time.sleep(60)
                return self._make_request(endpoint, params)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Erro na requisição {url}: {e}")
            return None

    def fetch_historical_data(self, coin_id):
        """
        Busca dados históricos de preços (e volumes) para um timeframe.
        Retorna um DataFrame com colunas: timestamp, open, high, low, close, volume.
        Nota: A CoinGecko não fornece OHLCV diretamente, apenas preços e volumes a cada intervalo.
        Vamos usar o endpoint /coins/{id}/market_chart?vs_currency=usd&days=...&interval=...
        Para timeframe 1h, podemos usar days=4 (96 horas) e obter dados horários.
        """
        # Mapear timeframe para parâmetros da API
        if self.timeframe == '1h':
            days = max(7, self.limit // 24)  # pelo menos 7 dias para ter 168 pontos
            interval = 'hourly'
        elif self.timeframe == '1d':
            days = self.limit
            interval = 'daily'
        else:
            days = 30
            interval = 'daily'

        params = {
            'vs_currency': 'usd',
            'days': days,
            'interval': interval
        }
        data = self._make_request(f"/coins/{coin_id}/market_chart", params)
        if not data:
            return None

        # Extrair preços e volumes
        prices = data.get('prices', [])
        volumes = data.get('total_volumes', [])

        if len(prices) < self.limit:
            logger.warning(f"Dados insuficientes para {coin_id}: {len(prices)} pontos")
            return None

        # Construir DataFrame
        df = pd.DataFrame(prices, columns=['timestamp', 'close'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        # Adicionar volume
        vol_df = pd.DataFrame(volumes, columns=['timestamp', 'volume'])
        df = df.merge(vol_df, on='timestamp', how='left')
        df.set_index('timestamp', inplace=True)

        # Para OHLC, a API só fornece preço de fechamento. Vamos aproximar open=close.shift(1), high=close, low=close.
        # Isso não é perfeito, mas para indicadores como RSI e EMAs o fechamento é suficiente.
        # MACD usa fechamento, então OK. Apenas a falta de alta/baixa não afeta esses indicadores.
        df['open'] = df['close'].shift(1)
        df['high'] = df['close']
        df['low'] = df['close']
        df = df.dropna().tail(self.limit)
        return df

    @staticmethod
    def compute_rsi(series, period=14):
        delta = series.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    @staticmethod
    def compute_macd(series, fast=12, slow=26, signal=9):
        exp_fast = series.ewm(span=fast, adjust=False).mean()
        exp_slow = series.ewm(span=slow, adjust=False).mean()
        macd_line = exp_fast - exp_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    @staticmethod
    def compute_ema(series, period):
        return series.ewm(span=period, adjust=False).mean()

    def classify(self, df):
        close = df['close']
        # RSI
        rsi = self.compute_rsi(close, config.RSI_PERIOD).iloc[-1]
        rsi_score = 0
        if rsi < 30:
            rsi_score = 1
        elif rsi > 70:
            rsi_score = -1

        # MACD
        macd, signal, hist = self.compute_macd(close, config.MACD_FAST, config.MACD_SLOW, config.MACD_SIGNAL)
        macd_score = 0
        if hist.iloc[-1] > 0 and hist.iloc[-2] <= 0:
            macd_score = 1
        elif hist.iloc[-1] < 0 and hist.iloc[-2] >= 0:
            macd_score = -1

        # EMAs
        ema_short = self.compute_ema(close, config.EMA_SHORT).iloc[-1]
        ema_long = self.compute_ema(close, config.EMA_LONG).iloc[-1]
        ema_score = 1 if ema_short > ema_long else -1

        final_score = (rsi_score * config.WEIGHTS['rsi'] +
                       macd_score * config.WEIGHTS['macd'] +
                       ema_score * config.WEIGHTS['ema'])

        if final_score > config.BUY_THRESHOLD:
            classification = "COMPRA"
        elif final_score < config.SELL_THRESHOLD:
            classification = "VENDA"
        else:
            classification = "NEUTRO"

        return {
            'rsi': round(rsi, 2),
            'rsi_score': rsi_score,
            'macd_score': macd_score,
            'ema_score': ema_score,
            'final_score': round(final_score, 2),
            'classification': classification,
            'price': round(close.iloc[-1], 2)
        }

    def run(self):
        results = []
        for coin in self.coins:
            logger.info(f"Analisando {coin}...")
            df = self.fetch_historical_data(coin)
            if df is not None and len(df) >= 50:  # mínimo para indicadores
                try:
                    analysis = self.classify(df)
                    results.append({
                        'coin': coin,
                        **analysis
                    })
                except Exception as e:
                    logger.error(f"Erro ao classificar {coin}: {e}")
            else:
                logger.warning(f"Dados insuficientes para {coin}")
            # Pausa para respeitar limite (plano Lite: 50 chamadas/minuto)
            time.sleep(1.2)  # ~0.83 chamadas/segundo, seguro
        return results

    def print_results(self, results):
        if not results:
            print("Nenhum resultado obtido.")
            return
        print("\n" + "="*90)
        print(f"{'Moeda':<15} {'Preço':<10} {'RSI':<8} {'RSI Sc':<6} {'MACD Sc':<7} {'EMA Sc':<6} {'Score':<8} {'Classificação'}")
        print("-"*90)
        for r in sorted(results, key=lambda x: x['final_score'], reverse=True):
            print(f"{r['coin']:<15} {r['price']:<10} {r['rsi']:<8} {r['rsi_score']:<6} {r['macd_score']:<7} {r['ema_score']:<6} {r['final_score']:<8} {r['classification']}")
        print("="*90)

class TelegramNotifier:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.sent_alerts = self.load_alerts()

    def load_alerts(self):
        if os.path.exists(config.ALERTS_FILE):
            with open(config.ALERTS_FILE, 'r') as f:
                return json.load(f)
        return {}

    def save_alerts(self):
        with open(config.ALERTS_FILE, 'w') as f:
            json.dump(self.sent_alerts, f)

    def send_message(self, text):
        try:
            payload = {
                'chat_id': self.chat_id,
                'text': text,
                'parse_mode': 'HTML'
            }
            resp = requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=10)
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem Telegram: {e}")
            return False

    def notify(self, coin, classification, score, price, rsi):
        """Envia alerta apenas se não tiver sido enviado nas últimas 24h (ou com sinal diferente)"""
        now = datetime.now().isoformat()
        key = f"{coin}_{classification}"

        # Se já enviamos esse sinal nas últimas 24h, não repetir
        if key in self.sent_alerts:
            last_time = datetime.fromisoformat(self.sent_alerts[key])
            if (datetime.now() - last_time).total_seconds() < 86400:
                logger.info(f"Alerta para {coin} ({classification}) já enviado nas últimas 24h. Ignorando.")
                return

        message = (
            f"🚨 <b>Alerta de {classification}</b> 🚨\n"
            f"Moeda: <code>{coin.upper()}</code>\n"
            f"Preço: ${price}\n"
            f"RSI: {rsi}\n"
            f"Score: {score}\n"
            f"Classificação: {classification}\n"
            f"📅 {now[:19]}"
        )
        if self.send_message(message):
            self.sent_alerts[key] = now
            self.save_alerts()

def main():
    # Obter credenciais do Telegram do ambiente
    telegram_token = os.getenv('TELEGRAM_TOKEN')
    telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')
    if not telegram_token or not telegram_chat_id:
        logger.error("Variáveis TELEGRAM_TOKEN e TELEGRAM_CHAT_ID não definidas. Encerrando.")
        return

    classifier = CryptoClassifier()
    notifier = TelegramNotifier(telegram_token, telegram_chat_id)

    logger.info("Bot iniciado. Pressione Ctrl+C para parar.")
    while True:
        try:
            results = classifier.run()
            classifier.print_results(results)

            # Enviar alertas para classificações COMPRA ou VENDA
            for r in results:
                if r['classification'] in ('COMPRA', 'VENDA'):
                    notifier.notify(
                        coin=r['coin'],
                        classification=r['classification'],
                        score=r['final_score'],
                        price=r['price'],
                        rsi=r['rsi']
                    )

            logger.info(f"Aguardando {config.SLEEP_INTERVAL} segundos...")
            time.sleep(config.SLEEP_INTERVAL)
        except KeyboardInterrupt:
            logger.info("Bot interrompido pelo usuário.")
            break
        except Exception as e:
            logger.error(f"Erro inesperado: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
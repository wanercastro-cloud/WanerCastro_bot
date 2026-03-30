import logging
import time
import os
import json
import requests
from datetime import datetime
import config
from coingecko import get_candidate_markets, get_indicator_pack_for_coin

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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
        now = datetime.now().isoformat()
        key = f"{coin}_{classification}"
        # Evita repetição nas últimas 24h
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
            f"📅 {now[:19]}"
        )
        if self.send_message(message):
            self.sent_alerts[key] = now
            self.save_alerts()

def main():
    # Inicializa notificador se as credenciais estiverem presentes
    if config.TELEGRAM_TOKEN and config.TELEGRAM_CHAT_ID:
        notifier = TelegramNotifier(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID)
    else:
        notifier = None
        logger.warning("Telegram não configurado. Alertas desabilitados.")

    logger.info("Bot iniciado. Pressione Ctrl+C para parar.")
    while True:
        try:
            # 1. Obter lista de moedas a analisar
            if config.USE_DYNAMIC_FILTER and not config.STATIC_COINS:
                candidates = get_candidate_markets()
                coins = [c['id'] for c in candidates]
                logger.info(f"Filtro dinâmico: {len(coins)} moedas selecionadas.")
            else:
                coins = config.STATIC_COINS
                logger.info(f"Lista estática: {coins}")

            if not coins:
                logger.warning("Nenhuma moeda para analisar. Aguardando...")
                time.sleep(config.SLEEP_INTERVAL)
                continue

            # 2. Para cada moeda, obter indicadores e classificar
            results = []
            for coin_id in coins:
                logger.info(f"Analisando {coin_id}...")
                indicator_pack = get_indicator_pack_for_coin(coin_id)
                if indicator_pack is None:
                    logger.warning(f"Dados insuficientes para {coin_id}")
                    continue
                results.append({
                    'coin': coin_id,
                    **indicator_pack
                })
                time.sleep(1.2)  # Respeita rate limit

            # 3. Exibir resultados (ordenados por score)
            if results:
                print("\n" + "="*90)
                print(f"{'Moeda':<15} {'Preço':<10} {'RSI':<8} {'RSI Sc':<6} {'MACD Sc':<7} {'EMA Sc':<6} {'Score':<8} {'Classificação'}")
                print("-"*90)
                for r in sorted(results, key=lambda x: x['final_score'], reverse=True):
                    print(f"{r['coin']:<15} {r['price']:<10} {r['rsi']:<8} {r['rsi_score']:<6} {r['macd_score']:<7} {r['ema_score']:<6} {r['final_score']:<8} {r['classification']}")
                print("="*90)
            else:
                print("Nenhum resultado obtido.")

            # 4. Enviar alertas para compra/venda
            if notifier:
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
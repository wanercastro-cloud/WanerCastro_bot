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
    """Gerencia envio de mensagens para o Telegram."""
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"

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

def send_buy_ranking(notifier, results, top_n=5):
    """
    Envia ranking das top N oportunidades de compra (score positivo mais alto).
    """
    # Filtrar apenas compras e ordenar por score decrescente
    buy_list = [r for r in results if r['classification'] == 'COMPRA']
    if not buy_list:
        notifier.send_message("📊 Nenhuma oportunidade de compra identificada neste momento.")
        return

    buy_list.sort(key=lambda x: x['final_score'], reverse=True)
    top_buy = buy_list[:top_n]

    msg = "<b>🚀 TOP OPORTUNIDADES DE COMPRA 🚀</b>\n\n"
    for i, item in enumerate(top_buy, 1):
        # Exibe o símbolo (ticker) em maiúsculas
        symbol_display = item.get('symbol', item.get('coin_id', '')).upper()
        msg += f"{i}. <code>{symbol_display}</code>\n"
        msg += f"   💰 Preço: ${item['price']}\n"
        msg += f"   📈 Score: {item['final_score']}\n"
        msg += f"   📉 RSI: {item['rsi']}\n"
        # Opcional: mostrar interpretação do MACD
        macd_text = 'Alta' if item['macd_score'] == 1 else 'Neutro' if item['macd_score'] == 0 else 'Baixa'
        msg += f"   🔄 MACD: {macd_text}\n"
        ema_text = 'Alta' if item['ema_score'] == 1 else 'Baixa'
        msg += f"   📊 EMA: {ema_text}\n\n"

    notifier.send_message(msg)

def main():
    # Inicializa notificador se as credenciais estiverem presentes
    if config.TELEGRAM_TOKEN and config.TELEGRAM_CHAT_ID:
        notifier = TelegramNotifier(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID)
        logger.info("Notificador Telegram ativado.")
    else:
        notifier = None
        logger.warning("Telegram não configurado. Envio de ranking desabilitado.")

    logger.info("Bot iniciado. Pressione Ctrl+C para parar.")
    while True:
        try:
            # 1. Obter lista de moedas a analisar (com símbolos)
            if config.USE_DYNAMIC_FILTER and not config.STATIC_COINS:
                candidates = get_candidate_markets()
                if not candidates:
                    logger.warning("Nenhuma moeda encontrada com os filtros atuais. Aguardando...")
                    time.sleep(config.SLEEP_INTERVAL)
                    continue
                # Guardar (id, symbol) para cada candidato
                coins_info = [(c['id'], c['symbol'].upper()) for c in candidates]
                logger.info(f"Filtro dinâmico: {len(coins_info)} moedas selecionadas.")
            else:
                # Lista estática: não temos símbolos, usar o próprio ID como símbolo (upper)
                coins_info = [(cid, cid.upper()) for cid in config.STATIC_COINS if cid]
                if not coins_info:
                    logger.warning("Lista estática vazia. Aguardando...")
                    time.sleep(config.SLEEP_INTERVAL)
                    continue
                logger.info(f"Lista estática: {[cid for cid, _ in coins_info]}")

            # 2. Para cada moeda, obter indicadores e classificar
            results = []
            for coin_id, symbol in coins_info:
                logger.info(f"Analisando {symbol} ({coin_id})...")
                try:
                    indicator_pack = get_indicator_pack_for_coin(coin_id)
                except Exception as e:
                    logger.error(f"Erro inesperado ao processar {symbol}: {e}")
                    continue

                if indicator_pack is None:
                    logger.warning(f"Dados insuficientes para {symbol}")
                    continue

                results.append({
                    'coin_id': coin_id,
                    'symbol': symbol,
                    **indicator_pack
                })
                # Pequena pausa para evitar sobrecarga da API
                time.sleep(1.2)

            # 3. Exibir resultados no log (ordenados por score)
            if results:
                print("\n" + "="*95)
                print(f"{'Símbolo':<12} {'Preço':<10} {'RSI':<8} {'RSI Sc':<6} {'MACD Sc':<7} {'EMA Sc':<6} {'Score':<8} {'Classificação'}")
                print("-"*95)
                for r in sorted(results, key=lambda x: x['final_score'], reverse=True):
                    # Exibe o símbolo no log
                    sym = r.get('symbol', r.get('coin_id', '')).upper()
                    print(f"{sym:<12} {r['price']:<10} {r['rsi']:<8} {r['rsi_score']:<6} {r['macd_score']:<7} {r['ema_score']:<6} {r['final_score']:<8} {r['classification']}")
                print("="*95)
            else:
                print("Nenhum resultado obtido.")

            # 4. Enviar ranking das melhores compras via Telegram
            if notifier and results:
                send_buy_ranking(notifier, results, top_n=config.TOP_BUY_COUNT)

            logger.info(f"Aguardando {config.SLEEP_INTERVAL} segundos...")
            time.sleep(config.SLEEP_INTERVAL)

        except KeyboardInterrupt:
            logger.info("Bot interrompido pelo usuário.")
            break
        except Exception as e:
            logger.error(f"Erro inesperado no loop principal: {e}", exc_info=True)
            time.sleep(60)

if __name__ == "__main__":
    main()
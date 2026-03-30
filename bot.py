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
        self.last_ranking_hash = None  # para evitar repetição

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

    def send_buy_ranking(self, results, top_n=5, min_score=0.6):
        """
        Envia ranking das top N oportunidades de compra com score >= min_score.
        Evita repetir o mesmo ranking se não houver mudança significativa.
        """
        # Filtrar compras fortes
        buy_list = [r for r in results if r['classification'] == 'COMPRA' and r['final_score'] >= min_score]
        if not buy_list:
            # Se não houver compras fortes, não envia nada (evita spam)
            return

        buy_list.sort(key=lambda x: x['final_score'], reverse=True)
        top_buy = buy_list[:top_n]

        # Criar um hash do ranking para comparar
        ranking_key = ",".join([f"{item['symbol']}:{item['final_score']}" for item in top_buy])
        if self.last_ranking_hash == ranking_key:
            logger.info("Ranking inalterado, não enviando repetição.")
            return
        self.last_ranking_hash = ranking_key

        msg = "<b>🚀 TOP OPORTUNIDADES DE COMPRA 🚀</b>\n\n"
        for i, item in enumerate(top_buy, 1):
            msg += f"{i}. <code>{item['symbol'].upper()}</code>\n"
            msg += f"   💰 Preço: ${item['price']}\n"
            msg += f"   📈 Score: {item['final_score']}\n"
            msg += f"   📉 RSI: {item['rsi']}\n"
            if item.get('price_change_24h') is not None:
                change = item['price_change_24h']
                emoji = "🟢" if change > 0 else "🔴" if change < 0 else "⚪"
                msg += f"   {emoji} Variação 24h: {change:+.2f}%\n"
            macd_text = 'Alta' if item['macd_score'] == 1 else 'Neutro' if item['macd_score'] == 0 else 'Baixa'
            msg += f"   🔄 MACD: {macd_text}\n"
            ema_text = 'Alta' if item['ema_score'] == 1 else 'Baixa'
            msg += f"   📊 EMA: {ema_text}\n\n"

        self.send_message(msg)

def main():
    if config.TELEGRAM_TOKEN and config.TELEGRAM_CHAT_ID:
        notifier = TelegramNotifier(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID)
        logger.info("Notificador Telegram ativado.")
    else:
        logger.error("Telegram não configurado. Encerrando.")
        return

    logger.info("Bot iniciado. Pressione Ctrl+C para parar.")
    while True:
        try:
            # 1. Obter lista de moedas (com símbolos e informações de mercado)
            if config.USE_DYNAMIC_FILTER and not config.STATIC_COINS:
                candidates = get_candidate_markets()
                if not candidates:
                    logger.warning("Nenhuma moeda encontrada com os filtros atuais. Aguardando...")
                    time.sleep(config.SLEEP_INTERVAL)
                    continue
                coins_info = [(c['id'], c['symbol'], c) for c in candidates]
                logger.info(f"Filtro dinâmico: {len(coins_info)} moedas selecionadas.")
            else:
                # Lista estática: sem informações adicionais, criar um placeholder
                coins_info = [(cid, cid.upper(), None) for cid in config.STATIC_COINS if cid]
                if not coins_info:
                    logger.warning("Lista estática vazia. Aguardando...")
                    time.sleep(config.SLEEP_INTERVAL)
                    continue
                logger.info(f"Lista estática: {[cid for cid, _, _ in coins_info]}")

            results = []
            for coin_id, symbol, market_info in coins_info:
                logger.info(f"Analisando {symbol} ({coin_id})...")
                try:
                    indicator_pack = get_indicator_pack_for_coin(coin_id)
                except Exception as e:
                    logger.error(f"Erro inesperado ao processar {symbol}: {e}")
                    continue

                if indicator_pack is None:
                    logger.warning(f"Dados insuficientes para {symbol}")
                    continue

                # Adicionar informações de mercado (preço atual, variação 24h)
                if market_info:
                    price = market_info.get('current_price', indicator_pack['price'])
                    price_change_24h = market_info.get('price_change_24h')
                else:
                    price = indicator_pack['price']
                    price_change_24h = None

                results.append({
                    'coin_id': coin_id,
                    'symbol': symbol,
                    'price': price,
                    'price_change_24h': price_change_24h,
                    **indicator_pack
                })
                time.sleep(1.2)

            # 2. Exibir resultados no log
            if results:
                print("\n" + "="*100)
                print(f"{'Símbolo':<12} {'Preço':<12} {'24h%':<8} {'RSI':<8} {'Score':<8} {'Classificação'}")
                print("-"*100)
                for r in sorted(results, key=lambda x: x['final_score'], reverse=True):
                    change = f"{r['price_change_24h']:+.2f}%" if r.get('price_change_24h') is not None else "N/A"
                    print(f"{r['symbol'].upper():<12} ${r['price']:<11} {change:<8} {r['rsi']:<8} {r['final_score']:<8} {r['classification']}")
                print("="*100)
            else:
                print("Nenhum resultado obtido.")

            # 3. Enviar ranking via Telegram (apenas compras fortes)
            notifier.send_buy_ranking(results, top_n=config.TOP_BUY_COUNT, min_score=config.MIN_SCORE_FOR_RANKING)

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
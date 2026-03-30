import logging
import time
import os
import json
import requests
from datetime import datetime, timedelta
import pytz
import config
from coingecko import get_candidate_markets, get_indicator_pack_for_coin

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class TelegramNotifier:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.last_ranking_hash = None
        self.risk_freeze = {}

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

    def is_frozen(self, symbol):
        if symbol not in self.risk_freeze:
            return False
        last_time = self.risk_freeze[symbol]
        if datetime.now() - last_time < timedelta(hours=config.RISK_FREEZE_EXHAUSTION):
            return True
        del self.risk_freeze[symbol]
        return False

    def freeze(self, symbol):
        self.risk_freeze[symbol] = datetime.now()

    def send_buy_ranking(self, results, top_n=5, min_score=0.4, title="🚀 TOP OPORTUNIDADES DE COMPRA"):
        # Filtra compras com score >= min_score e não congeladas
        buy_list = [
            r for r in results
            if r['classification'] == 'COMPRA' and r['final_score'] >= min_score and not self.is_frozen(r['symbol'])
        ]
        if not buy_list:
            return

        buy_list.sort(key=lambda x: x['final_score'], reverse=True)
        top_buy = buy_list[:top_n]

        ranking_key = ",".join([f"{item['symbol']}:{item['final_score']}" for item in top_buy])
        if self.last_ranking_hash == ranking_key:
            logger.info("Ranking inalterado, não enviando repetição.")
            return
        self.last_ranking_hash = ranking_key

        for item in top_buy:
            self.freeze(item['symbol'])

        msg = f"<b>{title}</b>\n\n"
        for i, item in enumerate(top_buy, 1):
            msg += f"{i}. <code>{item['symbol'].upper()}</code>\n"
            msg += f"   💰 Preço: ${item['price']}\n"
            msg += f"   📈 Score: {item['final_score']}\n"
            msg += f"   📉 RSI: {item['rsi']}\n"
            if item.get('price_change_24h') is not None:
                change = item['price_change_24h']
                emoji = "🟢" if change > 0 else "🔴" if change < 0 else "⚪"
                msg += f"   {emoji} Variação 24h: {change:+.2f}%\n"
            macd_text = 'Alta' if item['macd_score'] > 0 else ('Neutro' if item['macd_score'] == 0 else 'Baixa')
            msg += f"   🔄 MACD: {macd_text}\n"
            ema_text = 'Alta' if item['ema_score'] > 0 else 'Baixa'
            msg += f"   📊 EMA: {ema_text}\n"
            vol_text = '🚀' if item.get('volume_score', 0) == 1 else ''
            msg += f"   📊 Volume: {vol_text}\n\n"

        self.send_message(msg)

def should_send_overnight():
    tz = pytz.timezone(config.TIMEZONE)
    now = datetime.now(tz)
    target_hour, target_minute = map(int, config.OVERNIGHT_TIME.split(':'))
    return now.hour == target_hour and now.minute == target_minute

def main():
    if not config.TELEGRAM_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.error("Telegram não configurado. Encerrando.")
        return

    notifier = TelegramNotifier(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID)
    if config.SEND_STARTUP_MESSAGE:
        notifier.send_message("🤖 Bot iniciado. Monitorando oportunidades de compra (versão early signals)")

    logger.info("Bot iniciado. Pressione Ctrl+C para parar.")
    overnight_sent_today = False

    while True:
        try:
            if config.USE_DYNAMIC_FILTER and not config.STATIC_COINS:
                candidates = get_candidate_markets()
                if not candidates:
                    logger.warning("Nenhuma moeda encontrada com os filtros atuais. Aguardando...")
                    time.sleep(config.SLEEP_INTERVAL)
                    continue
                coins_info = [(c['id'], c['symbol'], c) for c in candidates]
                logger.info(f"Filtro dinâmico: {len(coins_info)} moedas selecionadas.")
            else:
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

            if results:
                print("\n" + "="*110)
                print(f"{'Símbolo':<12} {'Preço':<12} {'24h%':<8} {'RSI':<8} {'MACD':<6} {'EMA':<6} {'Vol':<4} {'Score':<6} {'Class'}")
                print("-"*110)
                for r in sorted(results, key=lambda x: x['final_score'], reverse=True):
                    change = f"{r['price_change_24h']:+.2f}%" if r.get('price_change_24h') is not None else "N/A"
                    macd_str = f"{r['macd_score']:+.2f}"
                    ema_str = f"{r['ema_score']:+.2f}"
                    vol_str = "🚀" if r.get('volume_score', 0) == 1 else "-"
                    print(f"{r['symbol'].upper():<12} ${r['price']:<11} {change:<8} {r['rsi']:<8} {macd_str:<6} {ema_str:<6} {vol_str:<4} {r['final_score']:<6} {r['classification']}")
                print("="*110)
            else:
                print("Nenhum resultado obtido.")

            notifier.send_buy_ranking(
                results,
                top_n=config.TOP_BUY_COUNT,
                min_score=config.MIN_SCORE_FOR_RANKING,
                title="🚀 OPORTUNIDADES PRECOCES DE COMPRA"
            )

            if should_send_overnight() and not overnight_sent_today:
                logger.info("Gerando picks overnight...")
                notifier.send_buy_ranking(
                    results,
                    top_n=config.OVERNIGHT_TOP_N,
                    min_score=config.MIN_SCORE_FOR_RANKING,
                    title="🌙 PICKS OVERNIGHT (entrada antecipada)"
                )
                overnight_sent_today = True
            elif not should_send_overnight():
                overnight_sent_today = False

            logger.info(f"Aguardando {config.SCAN_INTERVAL_MINUTES} minutos...")
            time.sleep(config.SLEEP_INTERVAL)

        except KeyboardInterrupt:
            logger.info("Bot interrompido pelo usuário.")
            break
        except Exception as e:
            logger.error(f"Erro inesperado no loop principal: {e}", exc_info=True)
            time.sleep(60)

if __name__ == "__main__":
    main()
import logging
import time
import os
import json
import requests
from datetime import datetime, timedelta
import pytz
import threading
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import config
from coingecko import get_candidate_markets, get_indicator_pack_for_coin

# Configuração de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Variáveis globais de controle
running = True
last_scan_results = []
scan_thread = None
remaining_seconds = config.SLEEP_INTERVAL

class TelegramNotifier:
    """Gerencia envio de mensagens para o Telegram (sem comandos)."""
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.last_ranking_hash = None
        self.last_sell_ranking_hash = None
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
        buy_list = [
            r for r in results
            if r['classification'] == 'COMPRA' and r['final_score'] >= min_score and not self.is_frozen(r['symbol'])
        ]
        if not buy_list:
            return False

        buy_list.sort(key=lambda x: x['final_score'], reverse=True)
        top_buy = buy_list[:top_n]

        ranking_key = ",".join([f"{item['symbol']}:{item['final_score']}" for item in top_buy])
        if self.last_ranking_hash == ranking_key:
            logger.info("Ranking de compras inalterado, não enviando repetição.")
            return False
        self.last_ranking_hash = ranking_key

        for item in top_buy:
            self.freeze(item['symbol'])

        msg = f"<b>{title}</b>\n\n"
        for i, item in enumerate(top_buy, 1):
            price = item['price']
            if price < 0.01:
                price_str = f"{price:.8f}".rstrip('0').rstrip('.')
            else:
                price_str = f"{price:.2f}"
            
            volume = item.get('volume_24h', 0)
            if volume >= 1_000_000:
                vol_str = f"{volume/1_000_000:.1f}M"
            elif volume >= 1_000:
                vol_str = f"{volume/1_000:.1f}K"
            else:
                vol_str = str(int(volume)) if volume > 0 else "N/A"
            spike_icon = "🚀" if item.get('volume_score', 0) == 1 else ""

            msg += f"{i}. <code>{item['symbol'].upper()}</code>\n"
            msg += f"   💰 Preço: ${price_str}\n"
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
            msg += f"   📊 Volume: ${vol_str} {spike_icon}\n\n"

        return self.send_message(msg)

    def send_sell_ranking(self, results, top_n=5, max_score=-0.4, title="🔻 OPORTUNIDADES DE QUEDA IMINENTE"):
        sell_list = [
            r for r in results
            if r['classification'] == 'VENDA' and r['final_score'] <= max_score and not self.is_frozen(r['symbol'])
        ]
        if not sell_list:
            return False

        sell_list.sort(key=lambda x: x['final_score'])
        top_sell = sell_list[:top_n]

        ranking_key = ",".join([f"{item['symbol']}:{item['final_score']}" for item in top_sell])
        if self.last_sell_ranking_hash == ranking_key:
            logger.info("Ranking de vendas inalterado, não enviando repetição.")
            return False
        self.last_sell_ranking_hash = ranking_key

        for item in top_sell:
            self.freeze(item['symbol'])

        msg = f"<b>{title}</b>\n\n"
        for i, item in enumerate(top_sell, 1):
            price = item['price']
            if price < 0.01:
                price_str = f"{price:.8f}".rstrip('0').rstrip('.')
            else:
                price_str = f"{price:.2f}"
            
            volume = item.get('volume_24h', 0)
            if volume >= 1_000_000:
                vol_str = f"{volume/1_000_000:.1f}M"
            elif volume >= 1_000:
                vol_str = f"{volume/1_000:.1f}K"
            else:
                vol_str = str(int(volume)) if volume > 0 else "N/A"
            spike_icon = "🚀" if item.get('volume_score', 0) == 1 else ""

            msg += f"{i}. <code>{item['symbol'].upper()}</code>\n"
            msg += f"   💰 Preço: ${price_str}\n"
            msg += f"   📉 Score (queda): {item['final_score']}\n"
            msg += f"   📈 RSI: {item['rsi']}\n"
            if item.get('price_change_24h') is not None:
                change = item['price_change_24h']
                emoji = "🟢" if change > 0 else "🔴" if change < 0 else "⚪"
                msg += f"   {emoji} Variação 24h: {change:+.2f}%\n"
            macd_text = 'Alta' if item['macd_score'] > 0 else ('Neutro' if item['macd_score'] == 0 else 'Baixa')
            msg += f"   🔄 MACD: {macd_text}\n"
            ema_text = 'Alta' if item['ema_score'] > 0 else 'Baixa'
            msg += f"   📊 EMA: {ema_text}\n"
            msg += f"   📊 Volume: ${vol_str} {spike_icon}\n\n"

        return self.send_message(msg)

# Funções auxiliares
def should_send_overnight():
    tz = pytz.timezone(config.TIMEZONE)
    now = datetime.now(tz)
    target_hour, target_minute = map(int, config.OVERNIGHT_TIME.split(':'))
    return now.hour == target_hour and now.minute == target_minute

def perform_scan():
    global last_scan_results
    logger.info("Iniciando varredura...")
    if config.USE_DYNAMIC_FILTER and not config.STATIC_COINS:
        candidates = get_candidate_markets()
        if not candidates:
            logger.warning("Nenhuma moeda encontrada com os filtros atuais.")
            return []
        coins_info = [(c['id'], c['symbol'], c) for c in candidates]
        logger.info(f"Filtro dinâmico: {len(coins_info)} moedas selecionadas.")
    else:
        coins_info = [(cid, cid.upper(), None) for cid in config.STATIC_COINS if cid]
        if not coins_info:
            logger.warning("Lista estática vazia.")
            return []
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
            volume_24h = market_info.get('volume', 0)
        else:
            price = indicator_pack['price']
            price_change_24h = None
            volume_24h = 0

        results.append({
            'coin_id': coin_id,
            'symbol': symbol,
            'price': price,
            'price_change_24h': price_change_24h,
            'volume_24h': volume_24h,
            **indicator_pack
        })
        time.sleep(1.2)

    last_scan_results = results
    return results

def scan_loop(notifier):
    global running, last_scan_results, remaining_seconds
    next_scan_time = time.time()
    overnight_sent_today = False

    while True:
        if running:
            now = time.time()
            if now >= next_scan_time:
                try:
                    results = perform_scan()
                    if results:
                        # Alerta automático de COMPRA
                        notifier.send_buy_ranking(
                            results,
                            top_n=config.TOP_BUY_COUNT,
                            min_score=config.MIN_SCORE_FOR_RANKING,
                            title="🚀 OPORTUNIDADES PRECOCES DE COMPRA"
                        )
                        # Alerta automático de VENDA (se configurado)
                        if config.AUTO_SELL_ALERTS:
                            notifier.send_sell_ranking(
                                results,
                                top_n=config.TOP_BUY_COUNT,
                                max_score=-config.MIN_SCORE_FOR_RANKING,
                                title="🔻 ALERTA AUTOMÁTICO - QUEDA IMINENTE"
                            )
                        # Overnight picks (compra)
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
                    next_scan_time = now + config.SLEEP_INTERVAL
                except Exception as e:
                    logger.error(f"Erro no scan: {e}", exc_info=True)
                    next_scan_time = now + 60
            remaining = max(0, next_scan_time - time.time())
            remaining_seconds = remaining
            sleep_time = min(remaining, 60) if remaining > 0 else 60
            time.sleep(sleep_time)
        else:
            time.sleep(5)

# Comandos do Telegram (mesmos de antes, incluindo sellranking e selltop)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Bot de oportunidades de compra e venda ativo.\nUse /help para ver os comandos.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📋 *Comandos disponíveis:*\n\n"
        "🟢 *COMPRA*:\n"
        "/ranking - Força o envio do ranking de compra\n"
        "/top N - Envia as top N oportunidades de compra (ex: /top 5)\n\n"
        "🔴 *VENDA*:\n"
        "/sellranking - Força o envio do ranking de venda (queda iminente)\n"
        "/selltop N - Envia as top N oportunidades de venda (ex: /selltop 5)\n\n"
        "⚙️ *GERAL*:\n"
        "/status - Mostra configurações e próximo scan\n"
        "/filtros - Exibe os filtros ativos\n"
        "/alertas - Mostra regras dos alertas\n"
        "/parar - Pausa o loop automático\n"
        "/iniciar - Retoma o loop automático\n"
        "/help - Lista este menu"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def ranking_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not last_scan_results:
        await update.message.reply_text("Ainda não há resultados de scan. Aguarde alguns minutos.")
        return
    notifier = context.bot_data['notifier']
    success = notifier.send_buy_ranking(
        last_scan_results,
        top_n=config.TOP_BUY_COUNT,
        min_score=config.MIN_SCORE_FOR_RANKING,
        title="🚀 OPORTUNIDADES PRECOCES DE COMPRA"
    )
    if not success:
        await update.message.reply_text("Nenhuma oportunidade de compra forte encontrada no momento.")

async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /top N (ex: /top 5)")
        return
    try:
        n = int(context.args[0])
        if n <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Por favor, informe um número positivo.")
        return
    if not last_scan_results:
        await update.message.reply_text("Ainda não há resultados de scan. Aguarde alguns minutos.")
        return
    notifier = context.bot_data['notifier']
    success = notifier.send_buy_ranking(
        last_scan_results,
        top_n=n,
        min_score=config.MIN_SCORE_FOR_RANKING,
        title=f"🚀 TOP {n} OPORTUNIDADES DE COMPRA"
    )
    if not success:
        await update.message.reply_text(f"Nenhuma oportunidade de compra forte encontrada com top {n}.")

async def sellranking_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not last_scan_results:
        await update.message.reply_text("Ainda não há resultados de scan. Aguarde alguns minutos.")
        return
    notifier = context.bot_data['notifier']
    success = notifier.send_sell_ranking(
        last_scan_results,
        top_n=config.TOP_BUY_COUNT,
        max_score=-config.MIN_SCORE_FOR_RANKING,
        title="🔻 OPORTUNIDADES DE QUEDA IMINENTE"
    )
    if not success:
        await update.message.reply_text("Nenhuma oportunidade de venda forte encontrada no momento.")

async def selltop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /selltop N (ex: /selltop 5)")
        return
    try:
        n = int(context.args[0])
        if n <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Por favor, informe um número positivo.")
        return
    if not last_scan_results:
        await update.message.reply_text("Ainda não há resultados de scan. Aguarde alguns minutos.")
        return
    notifier = context.bot_data['notifier']
    success = notifier.send_sell_ranking(
        last_scan_results,
        top_n=n,
        max_score=-config.MIN_SCORE_FOR_RANKING,
        title=f"🔻 TOP {n} OPORTUNIDADES DE QUEDA"
    )
    if not success:
        await update.message.reply_text(f"Nenhuma oportunidade de venda forte encontrada com top {n}.")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tz = pytz.timezone(config.TIMEZONE)
    next_scan_time = datetime.now(tz) + timedelta(seconds=remaining_seconds)
    msg = (
        f"⚙️ *Status do Bot*\n\n"
        f"🔁 Loop automático: {'Ativo' if running else 'Pausado'}\n"
        f"⏱️ Próximo scan: {next_scan_time.strftime('%H:%M:%S')}\n"
        f"📊 Score mínimo compra: {config.MIN_SCORE_FOR_RANKING}\n"
        f"📉 Score mínimo venda: { -config.MIN_SCORE_FOR_RANKING}\n"
        f"🔍 Moedas por scan: {config.CANDIDATES}\n"
        f"🚫 Congelamento: {config.RISK_FREEZE_EXHAUSTION}h\n"
        f"🔔 Alertas automáticos de venda: {'Ativo' if config.AUTO_SELL_ALERTS else 'Inativo'}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def filtros_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        f"🔎 *Filtros de triagem ativos*\n\n"
        f"💰 Market Cap: {config.MIN_MCAP/1e6:.0f}M - {config.MAX_MCAP/1e6:.0f}M USD\n"
        f"📈 Volume 24h mínimo: {config.MIN_VOL24/1e6:.1f}M USD\n"
        f"🚫 Excluir stablecoins: {'Sim' if config.EXCLUDE_STABLES else 'Não'}\n"
        f"🌎 Moeda: {config.VS_CURRENCY.upper()}\n"
        f"📄 Páginas: {config.PAGES} (limite {config.PER_PAGE} por página)"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def alertas_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        f"🔔 *Regras dos alertas*\n\n"
        f"📊 Score mínimo compra: {config.MIN_SCORE_FOR_RANKING}\n"
        f"📉 Score máximo venda: { -config.MIN_SCORE_FOR_RANKING}\n"
        f"🚫 Congelamento após alerta: {config.RISK_FREEZE_EXHAUSTION}h\n"
        f"⚖️ Pesos: RSI={config.WEIGHTS['rsi']}, MACD={config.WEIGHTS['macd']}, EMA={config.WEIGHTS['ema']}, Volume={config.WEIGHTS['volume']}\n"
        f"📈 Limiar de compra: {config.BUY_THRESHOLD}\n"
        f"📉 Limiar de venda: {config.SELL_THRESHOLD}\n"
        f"🌙 Overnight (compra): às {config.OVERNIGHT_TIME} (top {config.OVERNIGHT_TOP_N})\n"
        f"🔔 Alertas automáticos de venda: {'Sim' if config.AUTO_SELL_ALERTS else 'Não'}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def parar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global running
    if not running:
        await update.message.reply_text("Loop automático já está pausado.")
        return
    running = False
    await update.message.reply_text("⏸️ Loop automático pausado. Use /iniciar para retomar.")

async def iniciar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global running
    if running:
        await update.message.reply_text("Loop automático já está ativo.")
        return
    running = True
    await update.message.reply_text("▶️ Loop automático retomado.")

def main():
    if not config.TELEGRAM_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.error("Telegram não configurado. Encerrando.")
        return

    notifier = TelegramNotifier(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID)

    thread = threading.Thread(target=scan_loop, args=(notifier,), daemon=True)
    thread.start()

    app = Application.builder().token(config.TELEGRAM_TOKEN).build()
    app.bot_data['notifier'] = notifier

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ranking", ranking_command))
    app.add_handler(CommandHandler("top", top_command))
    app.add_handler(CommandHandler("sellranking", sellranking_command))
    app.add_handler(CommandHandler("selltop", selltop_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("filtros", filtros_command))
    app.add_handler(CommandHandler("alertas", alertas_command))
    app.add_handler(CommandHandler("parar", parar_command))
    app.add_handler(CommandHandler("iniciar", iniciar_command))

    logger.info("Bot iniciado com suporte a comandos e alertas automáticos de venda (configurável).")
    app.run_polling()

if __name__ == "__main__":
    main()
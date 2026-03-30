import logging
import os
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from coingecko import get_candidate_markets, get_indicator_pack_for_coin
from scoring import score_coin, build_overnight_ranking_text, build_radar_text

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("overnight_bot")

print("🚀 BOT INICIANDO...")

REQUIRED_VARS = [
    "TG_BOT_TOKEN",
    "TG_CHAT_ID",
    "COINGECKO_API_KEY",
    "COINGECKO_BASE_URL",
    "TIMEZONE",
    "OVERNIGHT_TIME",
]

missing = [var for var in REQUIRED_VARS if not os.getenv(var)]
if missing:
    print("❌ ERRO: Variáveis obrigatórias faltando:")
    for var in missing:
        print(f" - {var}")
    raise SystemExit(1)

TG_BOT_TOKEN = os.environ["TG_BOT_TOKEN"]
TG_CHAT_ID = int(os.environ["TG_CHAT_ID"])
TIMEZONE = os.environ["TIMEZONE"]
OVERNIGHT_TIME = os.environ["OVERNIGHT_TIME"]

TOP_N = int(os.getenv("TOP_N", "5"))
OVERNIGHT_TOP_N = int(os.getenv("OVERNIGHT_TOP_N", "3"))

tz = ZoneInfo(TIMEZONE)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Bot online.\n"
        "Comandos:\n"
        "/ping\n"
        "/overnight\n"
        "/radar\n"
        "/smartmoney"
    )


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    now = datetime.now(tz).strftime("%d/%m/%Y %H:%M:%S")
    await update.message.reply_text(f"pong 🟢\nHorário: {now}")


def build_rankings():
    markets = get_candidate_markets()
    scored = []
    for coin in markets:
        try:
            ind = get_indicator_pack_for_coin(coin["id"])
            result = score_coin(coin, ind)
            scored.append(result)
        except Exception as e:
            log.warning("Falha em %s: %s", coin.get("symbol"), e)
    return scored


async def overnight(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scored = build_rankings()
    text = build_overnight_ranking_text(scored, top_n=OVERNIGHT_TOP_N)
    await update.message.reply_text(text, disable_web_page_preview=True)


async def radar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scored = build_rankings()
    text = build_radar_text(scored, top_n=TOP_N)
    await update.message.reply_text(text, disable_web_page_preview=True)


async def smartmoney(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scored = build_rankings()
    text = build_radar_text(scored, top_n=TOP_N)
    await update.message.reply_text(text, disable_web_page_preview=True)


def scheduler_loop(application: Application) -> None:
    sent_date = None
    while True:
        try:
            now = datetime.now(tz)
            hhmm = now.strftime("%H:%M")
            if hhmm == OVERNIGHT_TIME and sent_date != now.date():
                scored = build_rankings()
                text = build_overnight_ranking_text(scored, top_n=OVERNIGHT_TOP_N)
                application.bot.send_message(chat_id=TG_CHAT_ID, text=text, disable_web_page_preview=True)
                sent_date = now.date()
                log.info("Overnight enviado para o chat.")
        except Exception as e:
            log.exception("Erro no scheduler: %s", e)
        time.sleep(20)


def main() -> None:
    application = Application.builder().token(TG_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("ping", ping))
    application.add_handler(CommandHandler("overnight", overnight))
    application.add_handler(CommandHandler("radar", radar))
    application.add_handler(CommandHandler("smartmoney", smartmoney))

    scheduler = threading.Thread(target=scheduler_loop, args=(application,), daemon=True)
    scheduler.start()

    print("✅ Todas as variáveis obrigatórias carregadas")
    print("🤖 Bot iniciado com sucesso")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

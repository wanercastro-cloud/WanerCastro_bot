import asyncio
from datetime import time as dtime
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from config import TG_BOT_TOKEN, ALERT_CHAT_ID
from providers import build_http_client
from smartmoney import build_candidates
from ranking import build_fomo_report


TZ = ZoneInfo("America/Sao_Paulo")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ Smart Money Bot online\n\n"
        "Comandos:\n"
        "/radar  → Top 5 pré-pump (CoinGecko Pro + anti-bag)\n"
        "/surf   → Top 5 “continuação” (mesma base, foco em continuação)\n"
        "/checklist → lembrete do checklist das 21h"
    )


async def cmd_checklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🧾 <b>Checklist 21h (Bybit Fluxo de Fundos)</b>\n"
        "1) Abrir Bybit → Fluxo de fundos\n"
        "2) Ver 12H e 1H\n"
        "3) Anotar: Net Flow, Large inflow/outflow e suporte do 1H\n"
        "4) Escolher 1–3 candidatas pra amanhã"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def _run_radar(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str):
    await update.message.reply_text("🔎 Escaneando CoinGecko Pro...")
    client = context.application.bot_data["http"]

    cands = await build_candidates(client)

    # mode “surf”: prioriza candidatos com 1h positivo e perto da high_24h (já entra como bonus no score)
    if mode == "surf":
        cands = [c for c in cands if c["chg_1h"] >= 0.8]

    msg = build_fomo_report(cands, top_n=5)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_radar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _run_radar(update, context, mode="radar")


async def cmd_surf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _run_radar(update, context, mode="surf")


async def daily_21h_job(context: ContextTypes.DEFAULT_TYPE):
    # se não tiver chat id, não tenta enviar
    if not ALERT_CHAT_ID:
        return
    msg = (
        "⏰ <b>21h! Checklist Bybit (12H + 1H Fluxo de Fundos)</b>\n"
        "Anote: Net Flow, Large inflow/outflow e suporte do 1H.\n"
        "Depois rode /radar e compare."
    )
    await context.bot.send_message(chat_id=ALERT_CHAT_ID, text=msg, parse_mode=ParseMode.HTML)


async def post_init(app: Application):
    app.bot_data["http"] = await build_http_client()

    # Agenda lembrete diário às 21:00 (BRT)
    app.job_queue.run_daily(daily_21h_job, time=dtime(hour=21, minute=0, tzinfo=TZ))


async def post_shutdown(app: Application):
    client = app.bot_data.get("http")
    if client:
        await client.aclose()


def main():
    app = (
        Application.builder()
        .token(TG_BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("radar", cmd_radar))
    app.add_handler(CommandHandler("surf", cmd_surf))
    app.add_handler(CommandHandler("checklist", cmd_checklist))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
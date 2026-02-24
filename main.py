import os
import asyncio
from datetime import time as dt_time
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

from smartmoney import scan_prepump_top3


# ========= CONFIG =========
BRT = ZoneInfo("America/Sao_Paulo")

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "").strip()  # opcional, mas necessário para envio automático

if not TG_BOT_TOKEN:
    raise RuntimeError("TG_BOT_TOKEN não definido nas variáveis de ambiente do Railway.")


# ========= HELPERS =========
def format_top3_message(top3: list[dict], header: str) -> str:
    if not top3:
        return "⚠️ Nada passou nos filtros de smart money agora."

    lines = [header]
    for i, c in enumerate(top3, 1):
        # Exibir números de forma clara
        lines.append(
            f"{i}) {c['symbol']} | Score {c['score']:.1f}\n"
            f"   Mcap ${c['mcap']:,} | Vol24 ${c['vol24']:,}\n"
            f"   1h {c['p1h']:+.2f}% | 24h {c['p24']:+.2f}%"
        )
    return "\n".join(lines)


# ========= TELEGRAM COMMANDS =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Bot online.\n\n"
        "Comandos:\n"
        "/chatid  → mostrar seu chat_id\n"
        "/prepump → Top 1–3 pré-pump (CoinGecko Pro)\n\n"
        "Envio automático às 21h (BRT) se TG_CHAT_ID estiver configurado."
    )


async def chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    await update.message.reply_text(f"📌 Seu chat_id é: {cid}")


async def prepump(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Rodando scan pré-pump (CoinGecko Pro)…")

    try:
        top3 = scan_prepump_top3()
        msg = format_top3_message(top3, "🔥 SMART MONEY PRÉ-PUMP (TOP 3)")
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"⚠️ Erro no scan: {e}")


# ========= DAILY JOB (21h BRT) =========
async def send_prepump_daily(context: ContextTypes.DEFAULT_TYPE):
    # Se TG_CHAT_ID não estiver setado, não envia automaticamente
    if not TG_CHAT_ID:
        return

    try:
        top3 = scan_prepump_top3()
        msg = format_top3_message(top3, "🕘 21h BRT — SMART MONEY PRÉ-PUMP (TOP 3)")
        await context.bot.send_message(chat_id=TG_CHAT_ID, text=msg)
    except Exception as e:
        await context.bot.send_message(
            chat_id=TG_CHAT_ID,
            text=f"⚠️ 21h BRT: erro no scan pré-pump: {e}"
        )


# ========= MAIN =========
async def main():
    app = ApplicationBuilder().token(TG_BOT_TOKEN).build()

    # Agenda 21h BRT (diário)
    app.job_queue.run_daily(
        send_prepump_daily,
        time=dt_time(hour=21, minute=0, tzinfo=BRT)
    )

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("chatid", chatid))
    app.add_handler(CommandHandler("prepump", prepump))

    print("🤖 Bot rodando (polling)…")
    await app.run_polling(close_loop=False)


if __name__ == "__main__":
    asyncio.run(main())
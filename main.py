import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from smartmoney import scan_prepump_top3

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()

if not TG_BOT_TOKEN:
    raise RuntimeError("TG_BOT_TOKEN não definido no Railway.")


def format_top3_message(top3: list[dict]) -> str:
    if not top3:
        return "⚠️ Nenhuma moeda passou nos filtros de smart money."

    lines = ["🔥 SMART MONEY PRÉ-PUMP (TOP 3)"]
    for i, c in enumerate(top3, 1):
        lines.append(
            f"{i}) {c['symbol']} | Score {c['score']:.1f}\n"
            f"   Mcap ${c['mcap']:,} | Vol24 ${c['vol24']:,}\n"
            f"   1h {c['p1h']:+.2f}% | 24h {c['p24']:+.2f}%"
        )
    return "\n".join(lines)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Bot Smart Money online.\n\n"
        "Comandos:\n"
        "/chatid → mostrar chat_id\n"
        "/prepump → scan pré-pump"
    )


async def chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"📌 chat_id: {update.effective_chat.id}")


async def prepump(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Escaneando smart money…")

    try:
        top3 = scan_prepump_top3()
        msg = format_top3_message(top3)
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"⚠️ Erro no scan:\n{e}")


def main():
    app = ApplicationBuilder().token(TG_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("chatid", chatid))
    app.add_handler(CommandHandler("prepump", prepump))

    print("🤖 Bot rodando (polling)")
    app.run_polling()


if __name__ == "__main__":
    main()
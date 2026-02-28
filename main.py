import os
import logging
import asyncio
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("bot")

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()

# ========= comandos =========
async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("pong ✅")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ Online.\n\nComandos:\n"
        "/ping\n"
        "/radar\n"
        "/subscribe\n"
        "/unsubscribe\n"
        "/alertnow"
    )

# Placeholder do seu radar (troque pelo seu)
async def radar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔎 Rodando scanner (Lite endpoints)...")

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Inscrito (placeholder).")

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Removido (placeholder).")

async def alertnow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📣 Disparando scan e enviando para todos inscritos (placeholder).")

# ========= handler global de erro (ESSENCIAL) =========
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.exception("🔥 Erro em update=%s", update, exc_info=context.error)

    # tenta avisar o usuário, sem derrubar o bot
    try:
        if isinstance(update, Update) and update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ Ops! Deu um erro interno no bot. Já registrei no log e vou continuar rodando.",
            )
    except Exception:
        pass

def build_app() -> Application:
    if not TG_BOT_TOKEN:
        raise RuntimeError("TG_BOT_TOKEN vazio. Configure no Railway Variables.")

    app = Application.builder().token(TG_BOT_TOKEN).build()

    # comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("radar", radar))
    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe))
    app.add_handler(CommandHandler("alertnow", alertnow))

    # IMPORTANTÍSSIMO:
    app.add_error_handler(on_error)

    return app

def main():
    app = build_app()

    # polling estável:
    app.run_polling(
        drop_pending_updates=True,   # evita fila antiga
        allowed_updates=Update.ALL_TYPES,
        close_loop=False,
    )

if __name__ == "__main__":
    main()
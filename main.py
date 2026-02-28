import asyncio
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from config import TG_BOT_TOKEN, TOP_N, TOP_SHOW, PER_PAGE
from coingecko_client import CoinGeckoClient
from ranking import build_rank, CoinRow
from formatting import render_rank, render_detail
from checklist import checklist_21h_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger("bot")

# Single shared client
cg = CoinGeckoClient()

async def _ensure_no_webhook(app: Application) -> None:
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
    except Exception:
        pass

def _parse_int(s: str, default: int) -> int:
    try:
        return int(s)
    except Exception:
        return default

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = (
        "✅ Online.\n\n"
        "Comandos:\n"
        "/ping\n"
        "/rank 20\n"
        "/rank 50 2\n"
        "/detail <coingecko_id>  (ex: /detail bitcoin)\n"
        "/checklist\n"
    )
    await update.message.reply_text(msg)

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("pong ✅")

async def checklist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(checklist_21h_text(), parse_mode=ParseMode.MARKDOWN)

async def rank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # /rank [show] [page]
    show = TOP_SHOW
    page = 1
    if context.args:
        show = _parse_int(context.args[0], TOP_SHOW)
        if len(context.args) >= 2:
            page = _parse_int(context.args[1], 1)
    show = max(5, min(show, 80))
    page = max(1, page)

    await update.message.reply_text("🔎 Buscando CoinGecko (Lite-friendly)…")

    # how many pages to fetch to reach TOP_N baseline
    pages = max(1, (TOP_N + PER_PAGE - 1) // PER_PAGE)

    try:
        rows, _ = await build_rank(cg, pages=pages, top_n_calc12h=min(30, TOP_N))
        if not rows:
            await update.message.reply_text(
                "⚠️ Nenhuma moeda passou no filtro *VOL24 > MCAP* (com os filtros atuais).",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        text = render_rank(rows, page=page, per_page=show)
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        await update.message.reply_text(f"⚠️ Erro no /rank: `{type(e).__name__}: {e}`", parse_mode=ParseMode.MARKDOWN)

async def detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Use: /detail <coingecko_id>  (ex: /detail bitcoin)")
        return
    coin_id = context.args[0].strip().lower()

    await update.message.reply_text(f"🔎 Carregando `{coin_id}`…", parse_mode=ParseMode.MARKDOWN)

    try:
        # Reaproveita build_rank: pega 1 página e acha o id
        rows, _ = await build_rank(cg, pages=1, top_n_calc12h=0)

        # se não achar na 1ª página, faz uma busca maior (lite-friendly)
        found = next((r for r in rows if r.id == coin_id), None)
        if not found:
            rows2, _ = await build_rank(cg, pages=3, top_n_calc12h=0)
            found = next((r for r in rows2 if r.id == coin_id), None)

        if not found:
            await update.message.reply_text("⚠️ Não encontrei esse ID nas páginas iniciais. Tente um ID válido do CoinGecko.")
            return

        # calcula 12h
        from ranking import calc_12h_change
        found.chg12h = await calc_12h_change(cg, found.id)

        await update.message.reply_text(render_detail(found), parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        await update.message.reply_text(f"⚠️ Erro no /detail: `{type(e).__name__}: {e}`", parse_mode=ParseMode.MARKDOWN)

async def on_shutdown(app: Application) -> None:
    await cg.aclose()

def main() -> None:
    if not TG_BOT_TOKEN:
        raise RuntimeError("TG_BOT_TOKEN não definido nas variáveis do Railway.")

    app = Application.builder().token(TG_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("rank", rank))
    app.add_handler(CommandHandler("detail", detail))
    app.add_handler(CommandHandler("checklist", checklist))

    app.post_init = _ensure_no_webhook
    app.post_shutdown = on_shutdown

    log.info("Starting bot (polling)…")
    app.run_polling(close_loop=False, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
import asyncio
import httpx

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from config import settings
from ranking import build_prepump_ranking, build_continuation_report, build_fomo_report


# =========================
# TELEGRAM HANDLERS
# =========================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    txt = (
        "✅ Bot online.\n\n"
        "Comandos:\n"
        "/ping\n"
        "/prepump   → Top pré-pump (CoinGecko Pro/Premium + boosts)\n"
        "/smartmoney → alias do /prepump\n"
        "/radar      → alias do /prepump\n"
        "/continuacao <SYMBOL> → plano para surfar continuação (sem virar bag)\n"
        "/fomo <SYMBOL> → detector de superaquecimento / risco de reversão\n\n"
        "Ex:\n"
        "/continuacao CFG\n"
        "/fomo PIRATE"
    )
    await update.message.reply_text(txt)


async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("pong ✅")


async def cmd_prepump(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔎 Rodando scanner CoinGecko (pré-pump)...")
    client: httpx.AsyncClient = context.application.bot_data["http"]

    try:
        items = await build_prepump_ranking(client)
        if not items:
            await update.message.reply_text(
                "⚠️ Sem candidatos no filtro atual.\n"
                "Dica: reduza MIN_MCAP / MIN_VOL24 ou aumente MAX_MCAP."
            )
            return

        lines = [f"🔥 <b>SMART MONEY PRÉ-PUMP</b> (Top {len(items)})"]
        for i, it in enumerate(items, 1):
            lines.append(
                f"\n<b>{i}) {it.symbol}/{settings.VS_CURRENCY.upper()}</b> | <b>Score {it.score:.1f}</b>\n"
                f"• Mcap: {it.mcap_fmt} | Vol24: {it.vol24_fmt}\n"
                f"• 1h: {it.chg_1h:+.2f}% | 24h: {it.chg_24h:+.2f}%\n"
                f"• Boosts: {it.boosts}\n"
                f"• Nota: <code>{it.notes}</code>"
            )
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    except httpx.HTTPStatusError as e:
        await update.message.reply_text(
            f"⚠️ Erro CoinGecko: {e.response.status_code} {e.response.reason_phrase}\n"
            f"URL: {str(e.request.url)}"
        )
    except Exception as e:
        await update.message.reply_text(f"⚠️ Erro no scanner: {type(e).__name__}: {e}")


async def cmd_continuacao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    symbol = (context.args[0] if context.args else "").upper().strip()
    if not symbol:
        await update.message.reply_text("Use: /continuacao <SYMBOL>\nEx: /continuacao CFG")
        return

    client: httpx.AsyncClient = context.application.bot_data["http"]
    try:
        msg = await build_continuation_report(client, symbol)
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"⚠️ Falha no /continuacao: {type(e).__name__}: {e}")


async def cmd_fomo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    symbol = (context.args[0] if context.args else "").upper().strip()
    if not symbol:
        await update.message.reply_text("Use: /fomo <SYMBOL>\nEx: /fomo PIRATE")
        return

    client: httpx.AsyncClient = context.application.bot_data["http"]
    try:
        msg = await build_fomo_report(client, symbol)
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"⚠️ Falha no /fomo: {type(e).__name__}: {e}")


async def on_startup(app: Application) -> None:
    app.bot_data["http"] = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.HTTP_TIMEOUT),
        headers=settings.cg_headers(),
    )


async def on_shutdown(app: Application) -> None:
    client: httpx.AsyncClient | None = app.bot_data.get("http")
    if client:
        await client.aclose()


def main() -> None:
    application = (
        Application.builder()
        .token(settings.TG_BOT_TOKEN)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("ping", cmd_ping))

    application.add_handler(CommandHandler("prepump", cmd_prepump))
    application.add_handler(CommandHandler("smartmoney", cmd_prepump))
    application.add_handler(CommandHandler("radar", cmd_prepump))

    application.add_handler(CommandHandler("continuacao", cmd_continuacao))
    application.add_handler(CommandHandler("fomo", cmd_fomo))

    # Dica: Conflict = tem outro processo rodando polling com o MESMO token
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
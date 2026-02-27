import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional, Set

import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from config import SETTINGS
from providers import cg_headers, CoinGeckoProvider, GeckoTerminalProvider
from ranking import build_ranking, format_top_message
from smartmoney import cmd_coin, cmd_chart

load_dotenv()

BRT = timezone(timedelta(hours=-3))

def _get_chatset(app: Application) -> Set[int]:
    s = app.bot_data.get("subscribers")
    if not isinstance(s, set):
        s = set()
        app.bot_data["subscribers"] = s
    return s

async def _broadcast(app: Application, text: str) -> None:
    subs = list(_get_chatset(app))
    if not subs:
        return
    for chat_id in subs:
        try:
            await app.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
            await asyncio.sleep(0.08)
        except Exception:
            continue

async def _daily_loop(app: Application) -> None:
    """
    Loop nativo (sem JobQueue) para:
      - 21:00 BRT: mandar lembrete + top scan para todos inscritos.
    """
    while True:
        now = datetime.now(BRT)
        target = now.replace(hour=SETTINGS.ALERT_HOUR_BRT, minute=SETTINGS.ALERT_MINUTE_BRT, second=0, microsecond=0)
        if target <= now:
            target = target + timedelta(days=1)
        sleep_s = max(5, (target - now).total_seconds())
        await asyncio.sleep(sleep_s)

        # lembrete + scan
        reminder = (
            "⏰ <b>Checklist das 21h</b>\n"
            "Abra a Bybit e rode: <b>12H + 1H (Fluxo de Fundos)</b>\n"
            "Anote: <b>Net Flow</b>, <b>Large inflow/outflow</b> e <b>suporte do 1H</b>."
        )
        await _broadcast(app, reminder)

        # manda top scan junto
        try:
            cg: CoinGeckoProvider = app.bot_data["cg"]
            gt: Optional[GeckoTerminalProvider] = app.bot_data.get("gt")
            top = await build_ranking(cg, gt=gt, dex_network="solana")
            await _broadcast(app, format_top_message(top))
        except Exception:
            # não derruba o bot se falhar
            pass

# ---------- Telegram handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    txt = (
        "✅ Bot online (Lite endpoints).\n\n"
        "<b>Comandos</b>\n"
        "/ping\n"
        "/radar  ou /smartmoney  → Top pré-pump\n"
        "/coin <code>coingecko_id</code>  → coin data by id\n"
        "/chart <code>coingecko_id</code> [dias] → histórico resumido\n"
        "/subscribe → entrar na lista (mandar para todos)\n"
        "/unsubscribe → sair\n"
        "/alertnow → dispara scan e envia para todos inscritos\n"
    )
    await update.message.reply_text(txt, parse_mode=ParseMode.HTML)

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("pong ✅")

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    subs = _get_chatset(context.application)
    subs.add(update.effective_chat.id)
    await update.message.reply_text("✅ Inscrito. Vou mandar os alertas aqui também.")

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    subs = _get_chatset(context.application)
    subs.discard(update.effective_chat.id)
    await update.message.reply_text("🧼 Removido da lista de alertas.")

async def smartmoney(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔎 Rodando scanner (Lite endpoints)...")
    cg: CoinGeckoProvider = context.application.bot_data["cg"]
    gt: Optional[GeckoTerminalProvider] = context.application.bot_data.get("gt")

    try:
        top = await build_ranking(cg, gt=gt, dex_network="solana")
        await update.message.reply_text(format_top_message(top), parse_mode=ParseMode.HTML)
    except httpx.HTTPStatusError as e:
        await update.message.reply_text(f"⚠️ CoinGecko/GT HTTP {e.response.status_code}\nURL: {str(e.request.url)}")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Erro: {type(e).__name__}: {e}")

async def radar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await smartmoney(update, context)

async def alertnow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("📣 Disparando scan e enviando para todos inscritos...")
    cg: CoinGeckoProvider = context.application.bot_data["cg"]
    gt: Optional[GeckoTerminalProvider] = context.application.bot_data.get("gt")
    top = await build_ranking(cg, gt=gt, dex_network="solana")
    await _broadcast(context.application, format_top_message(top))
    await update.message.reply_text("✅ Enviado.")

async def coin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Use: /coin <coingecko_id> (ex: /coin bitcoin)")
        return
    coin_id = (context.args[0] or "").strip().lower()
    cg: CoinGeckoProvider = context.application.bot_data["cg"]
    msg = await cmd_coin(cg, coin_id)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def chart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Use: /chart <coingecko_id> [dias] (ex: /chart bitcoin 7)")
        return
    coin_id = (context.args[0] or "").strip().lower()
    days = 7
    if len(context.args) >= 2:
        try:
            days = max(1, min(365, int(context.args[1])))
        except Exception:
            days = 7
    cg: CoinGeckoProvider = context.application.bot_data["cg"]
    msg = await cmd_chart(cg, coin_id, days=days)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

# ---------- lifecycle ----------
async def on_startup(app: Application) -> None:
    # 1) client CoinGecko (com header da key Lite)
    cg_client = httpx.AsyncClient(timeout=httpx.Timeout(SETTINGS.HTTP_TIMEOUT), headers=cg_headers())
    app.bot_data["cg_client"] = cg_client
    app.bot_data["cg"] = CoinGeckoProvider(cg_client)

    # 2) client GeckoTerminal (sem header especial)
    gt_client = httpx.AsyncClient(timeout=httpx.Timeout(SETTINGS.HTTP_TIMEOUT), headers={"accept": "application/json"})
    app.bot_data["gt_client"] = gt_client
    app.bot_data["gt"] = GeckoTerminalProvider(gt_client)

    # set de inscritos
    _get_chatset(app)

    # scheduler nativo
    app.bot_data["daily_task"] = asyncio.create_task(_daily_loop(app))

async def on_shutdown(app: Application) -> None:
    t = app.bot_data.get("daily_task")
    if t:
        try:
            t.cancel()
        except Exception:
            pass

    cg_client = app.bot_data.get("cg_client")
    if cg_client:
        await cg_client.aclose()

    gt_client = app.bot_data.get("gt_client")
    if gt_client:
        await gt_client.aclose()

def main() -> None:
    app = (
        Application.builder()
        .token(SETTINGS.TG_BOT_TOKEN)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("smartmoney", smartmoney))
    app.add_handler(CommandHandler("radar", radar))

    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe))
    app.add_handler(CommandHandler("alertnow", alertnow))

    app.add_handler(CommandHandler("coin", coin))
    app.add_handler(CommandHandler("chart", chart))

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
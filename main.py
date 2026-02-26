import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import Optional, Set

import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from config import load_settings
from providers import cg_headers
from ranking import build_smartmoney_report, build_sniper_report

load_dotenv()
SETTINGS = load_settings()

SUBSCRIBERS_FILE = os.getenv("SUBSCRIBERS_FILE", "subscribers.json")

def _load_subscribers() -> Set[int]:
    try:
        with open(SUBSCRIBERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return set(int(x) for x in data)
    except Exception:
        pass
    return set()

def _save_subscribers(ids: Set[int]) -> None:
    try:
        with open(SUBSCRIBERS_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(list(ids)), f)
    except Exception:
        pass

SUBSCRIBERS: Set[int] = _load_subscribers()

async def _broadcast(app: Application, text: str) -> None:
    if not SUBSCRIBERS:
        return
    for chat_id in list(SUBSCRIBERS):
        try:
            await app.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
        except Exception:
            # não derruba por causa de 1 chat
            continue

# =========================
# COMMANDS
# =========================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "✅ Bot online.\n\n"
        "Comandos:\n"
        "/smartmoney  → Top pré-pump\n"
        "/sniper     → modo 5 (continuação cedo)\n"
        "/subscribe  → receber às 21h (BRT)\n"
        "/unsubscribe\n"
        "/sendall    → manda o último relatório para todos\n"
    )

async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    SUBSCRIBERS.add(chat_id)
    _save_subscribers(SUBSCRIBERS)
    await update.message.reply_text("🔔 Inscrito! Vou te mandar relatório diário às 21h (BRT).")

async def cmd_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    SUBSCRIBERS.discard(chat_id)
    _save_subscribers(SUBSCRIBERS)
    await update.message.reply_text("🔕 Removido. Você não receberá mais o relatório diário.")

LAST_REPORT: Optional[str] = None

async def cmd_smartmoney(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global LAST_REPORT
    await update.message.reply_text("🔎 Rodando Smart Money (CoinGecko + DEX boost)...")
    http: httpx.AsyncClient = context.application.bot_data["http"]
    msg, _ = await build_smartmoney_report(http, SETTINGS)
    LAST_REPORT = msg
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def cmd_sniper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global LAST_REPORT
    await update.message.reply_text("🎯 Sniper (modo 5): procurando continuação cedo...")
    http: httpx.AsyncClient = context.application.bot_data["http"]
    msg, _ = await build_sniper_report(http, SETTINGS)
    LAST_REPORT = msg
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def cmd_sendall(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    “Mande para todos”
    """
    if not SUBSCRIBERS:
        await update.message.reply_text("⚠️ Ninguém inscrito ainda. Use /subscribe em cada chat/grupo.")
        return
    if not LAST_REPORT:
        await update.message.reply_text("⚠️ Ainda não tenho relatório. Rode /smartmoney ou /sniper primeiro.")
        return

    await update.message.reply_text(f"📣 Enviando para {len(SUBSCRIBERS)} inscritos...")
    await _broadcast(context.application, LAST_REPORT)
    await update.message.reply_text("✅ Enviado.")

# =========================
# SCHEDULER (21h BRT)
# =========================
def _next_run_dt(now: datetime) -> datetime:
    target = now.replace(hour=SETTINGS.daily_hour, minute=SETTINGS.daily_minute, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return target

async def _daily_loop(app: Application) -> None:
    """
    Fallback se job_queue não existir.
    """
    while True:
        now = datetime.now(tz=SETTINGS.tz)
        nxt = _next_run_dt(now)
        sleep_s = max(5.0, (nxt - now).total_seconds())
        await asyncio.sleep(sleep_s)

        # escolhe qual relatório mandar (padrão: sniper)
        http: httpx.AsyncClient = app.bot_data["http"]
        msg, _ = await build_sniper_report(http, SETTINGS)

        global LAST_REPORT
        LAST_REPORT = msg

        await _broadcast(app, msg)

async def job_daily(context: ContextTypes.DEFAULT_TYPE) -> None:
    app = context.application
    http: httpx.AsyncClient = app.bot_data["http"]

    msg, _ = await build_sniper_report(http, SETTINGS)
    global LAST_REPORT
    LAST_REPORT = msg
    await _broadcast(app, msg)

# =========================
# LIFECYCLE
# =========================
async def on_startup(app: Application) -> None:
    app.bot_data["http"] = httpx.AsyncClient(
        timeout=httpx.Timeout(SETTINGS.http_timeout),
        headers=cg_headers(SETTINGS),
    )

    # tenta job_queue (se requirements tiver [job-queue])
    jq = getattr(app, "job_queue", None)
    if jq:
        jq.run_daily(
            job_daily,
            time=datetime.now(tz=SETTINGS.tz).replace(hour=SETTINGS.daily_hour, minute=SETTINGS.daily_minute, second=0, microsecond=0).timetz(),
            name="daily_report_21h",
        )
    else:
        # fallback: loop async
        app.create_task(_daily_loop(app))

async def on_shutdown(app: Application) -> None:
    http: Optional[httpx.AsyncClient] = app.bot_data.get("http")
    if http:
        await http.aclose()

def main() -> None:
    app = (
        Application.builder()
        .token(SETTINGS.tg_bot_token)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("smartmoney", cmd_smartmoney))
    app.add_handler(CommandHandler("sniper", cmd_sniper))
    app.add_handler(CommandHandler("subscribe", cmd_subscribe))
    app.add_handler(CommandHandler("unsubscribe", cmd_unsubscribe))
    app.add_handler(CommandHandler("sendall", cmd_sendall))

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
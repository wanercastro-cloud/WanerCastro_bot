import asyncio
import json
import os
import time
from datetime import datetime, timedelta

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import load_settings, Settings
from providers import CoinGeckoLite
from ranking import build_ranking
from smartmoney import format_radar, PARSE_MODE

load_dotenv()

SUBS_FILE = "subscribers.json"

def _load_subs() -> set[int]:
    try:
        with open(SUBS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(int(x) for x in data.get("chat_ids", []))
    except Exception:
        return set()

def _save_subs(chat_ids: set[int]) -> None:
    try:
        with open(SUBS_FILE, "w", encoding="utf-8") as f:
            json.dump({"chat_ids": sorted(chat_ids)}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _now(settings: Settings) -> datetime:
    return datetime.now(tz=settings.tz)

async def _broadcast(app: Application, text: str, parse_mode=None, settings: Settings | None = None) -> None:
    subs: set[int] = app.bot_data.get("subs", set())
    targets = set(subs)

    # opcional: também manda num canal fixo
    if settings and settings.alert_channel_id:
        try:
            targets.add(int(settings.alert_channel_id))
        except Exception:
            pass

    # manda pra todos
    for chat_id in sorted(targets):
        try:
            await app.bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
            await asyncio.sleep(0.05)
        except Exception:
            continue

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    txt = (
        "✅ Bot online (Lite endpoints).\n\n"
        "Comandos:\n"
        "/ping\n"
        "/radar  → scanner pré-pump (CoinGecko Lite)\n"
        "/coin <coingecko_id>  → detalhes\n"
        "/chart <coingecko_id> [days] → histórico resumido\n"
        "/subscribe → entrar na lista\n"
        "/unsubscribe → sair\n"
        "/alertnow → dispara scan e manda para todos inscritos\n"
        "/status → saúde do provider\n"
    )
    await update.message.reply_text(txt)

async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("pong ✅")

async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    subs: set[int] = context.application.bot_data["subs"]
    subs.add(int(chat_id))
    _save_subs(subs)
    await update.message.reply_text("✅ Inscrito. Você vai receber os alertas do /alertnow (e do agendamento se ativado).")

async def cmd_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    subs: set[int] = context.application.bot_data["subs"]
    subs.discard(int(chat_id))
    _save_subs(subs)
    await update.message.reply_text("🧹 Removido da lista.")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cg: CoinGeckoLite = context.application.bot_data["cg"]
    st = cg.state
    ago = int(time.time() - st.last_ok_ts) if st.last_ok_ts else -1
    msg = (
        "🧪 <b>Status</b>\n"
        f"• Base: <code>{st.base_url}</code>\n"
        f"• Last status: <b>{st.last_status}</b>\n"
        f"• Last error: <code>{st.last_error or 'OK'}</code>\n"
        f"• Último OK: <b>{ago}s</b> atrás\n"
    )
    await update.message.reply_text(msg, parse_mode=PARSE_MODE)

async def cmd_radar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    cg: CoinGeckoLite = context.application.bot_data["cg"]

    await update.message.reply_text("🔎 Rodando scanner (Lite endpoints)...")

    try:
        top = await build_ranking(cg, settings)
        msg = format_radar(top, settings)
        await update.message.reply_text(msg, parse_mode=PARSE_MODE)
    except Exception as e:
        await update.message.reply_text(f"⚠️ Erro no radar: {type(e).__name__}: {e}")

async def cmd_alertnow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    cg: CoinGeckoLite = context.application.bot_data["cg"]

    await update.message.reply_text("📣 Disparando scan e enviando para todos inscritos...")

    try:
        top = await build_ranking(cg, settings)
        msg = format_radar(top, settings)
        await _broadcast(context.application, msg, parse_mode=PARSE_MODE, settings=settings)
    except Exception as e:
        await update.message.reply_text(f"⚠️ Erro no alertnow: {type(e).__name__}: {e}")

async def cmd_coin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    cg: CoinGeckoLite = context.application.bot_data["cg"]

    if not context.args:
        await update.message.reply_text("Use: /coin <coingecko_id>  (ex: /coin bitcoin)")
        return

    coin_id = context.args[0].strip().lower()
    await update.message.reply_text(f"🔎 Buscando coin: {coin_id}...")

    try:
        data = await cg.coin_by_id(coin_id)
        md = (data or {}).get("market_data", {}) or {}
        price = (md.get("current_price", {}) or {}).get(settings.vs_currency)
        mcap = (md.get("market_cap", {}) or {}).get(settings.vs_currency)
        vol = (md.get("total_volume", {}) or {}).get(settings.vs_currency)
        chg24 = md.get("price_change_percentage_24h", None)

        msg = (
            f"🪙 <b>{data.get('name','')}</b> (<code>{data.get('symbol','').upper()}</code>)\n"
            f"• Price: <b>{price}</b> {settings.vs_currency.upper()}\n"
            f"• Mcap: <b>{mcap}</b>\n"
            f"• Vol24: <b>{vol}</b>\n"
            f"• 24h: <b>{chg24:+.2f}%</b>" if isinstance(chg24, (int, float)) else ""
        )
        await update.message.reply_text(msg, parse_mode=PARSE_MODE)
    except Exception as e:
        await update.message.reply_text(f"⚠️ Erro no /coin: {type(e).__name__}: {e}")

async def cmd_chart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    cg: CoinGeckoLite = context.application.bot_data["cg"]

    if not context.args:
        await update.message.reply_text("Use: /chart <coingecko_id> [days]  (ex: /chart bitcoin 30)")
        return

    coin_id = context.args[0].strip().lower()
    days = 30
    if len(context.args) >= 2:
        try:
            days = int(context.args[1])
        except Exception:
            days = 30
    days = max(1, min(days, 365))

    await update.message.reply_text(f"📈 Carregando histórico: {coin_id} ({days}d)...")

    try:
        data = await cg.market_chart(coin_id, settings.vs_currency, days)
        prices = data.get("prices", []) if isinstance(data, dict) else []
        if not prices or len(prices) < 2:
            await update.message.reply_text("⚠️ Sem dados suficientes no histórico.")
            return

        first = float(prices[0][1])
        last = float(prices[-1][1])
        pct = ((last - first) / first) * 100 if first else 0.0

        msg = (
            f"📊 <b>{coin_id}</b> ({days}d)\n"
            f"• Primeiro: <b>{first:.6g}</b>\n"
            f"• Último: <b>{last:.6g}</b>\n"
            f"• Variação: <b>{pct:+.2f}%</b>\n"
        )
        await update.message.reply_text(msg, parse_mode=PARSE_MODE)
    except Exception as e:
        await update.message.reply_text(f"⚠️ Erro no /chart: {type(e).__name__}: {e}")

async def scheduler_loop(app: Application) -> None:
    """
    Scheduler interno (sem JobQueue).
    Se SCHEDULER_ENABLED=1, ele dispara um /alertnow todo dia às 21h BRT.
    """
    settings: Settings = app.bot_data["settings"]
    if not settings.scheduler_enabled:
        return

    while True:
        try:
            now = _now(settings)
            target = now.replace(hour=settings.scheduler_hour_brt, minute=0, second=5, microsecond=0)
            if target <= now:
                target = target + timedelta(days=1)
            sleep_sec = (target - now).total_seconds()

            await asyncio.sleep(max(5.0, sleep_sec))

            # dispara e manda para todos
            cg: CoinGeckoLite = app.bot_data["cg"]
            top = await build_ranking(cg, settings)
            msg = format_radar(top, settings)
            await _broadcast(app, msg, parse_mode=PARSE_MODE, settings=settings)
        except Exception:
            await asyncio.sleep(10.0)

async def on_startup(app: Application) -> None:
    settings = load_settings()
    app.bot_data["settings"] = settings

    subs = _load_subs()
    app.bot_data["subs"] = subs

    cg = CoinGeckoLite(
        api_key=settings.cg_api_key,
        base_pro=settings.cg_base_url_pro,
        base_free=settings.cg_base_url_free,
        timeout_sec=settings.http_timeout,
        retries=settings.http_retries,
        cache_ttl_sec=settings.cache_ttl_sec,
    )
    app.bot_data["cg"] = cg

    # inicia scheduler interno
    app.bot_data["scheduler_task"] = asyncio.create_task(scheduler_loop(app))

async def on_shutdown(app: Application) -> None:
    try:
        task: asyncio.Task | None = app.bot_data.get("scheduler_task")
        if task:
            task.cancel()
    except Exception:
        pass

    cg: CoinGeckoLite = app.bot_data.get("cg")
    if cg:
        await cg.aclose()

def main() -> None:
    settings = load_settings()
    app = (
        Application.builder()
        .token(settings.tg_bot_token)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("radar", cmd_radar))
    app.add_handler(CommandHandler("alertnow", cmd_alertnow))
    app.add_handler(CommandHandler("subscribe", cmd_subscribe))
    app.add_handler(CommandHandler("unsubscribe", cmd_unsubscribe))
    app.add_handler(CommandHandler("coin", cmd_coin))
    app.add_handler(CommandHandler("chart", cmd_chart))
    app.add_handler(CommandHandler("status", cmd_status))

    # polling seguro
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
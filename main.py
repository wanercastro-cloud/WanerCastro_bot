import os
import httpx
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from providers import cg_headers, HTTP_TIMEOUT
from ultra import run_ultra

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
VS = os.getenv("VS_CURRENCY", "usd").strip().lower()

def fmt_money(x: float) -> str:
    x = float(x or 0.0)
    if x >= 1e9: return f"${x/1e9:.2f}B"
    if x >= 1e6: return f"${x/1e6:.2f}M"
    if x >= 1e3: return f"${x/1e3:.2f}K"
    return f"${x:.0f}"

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot online.\n\nComando único:\n/ultra → ULTRA PREMIUM (CG Pro + Onchain/Dex)")

async def cmd_ultra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧠 Rodando ULTRA PREMIUM (markets + chart + trending pools + megafilter)...")
    http: httpx.AsyncClient = context.application.bot_data["http"]

    items = await run_ultra(http)
    if not items:
        await update.message.reply_text("⚠️ Sem candidatos. Baixe MIN_VM/MIN_VOL24 ou aumente MAX_MCAP/CANDIDATES.")
        return

    lines = [f"🔥 <b>ULTRA PREMIUM</b> (Top {len(items)})"]
    for i, it in enumerate(items, 1):
        lines.append(
            f"\n<b>{i}) {it['symbol']}/{VS.upper()}</b> | <b>Score {it['score']:.1f}</b>\n"
            f"• Mcap: {fmt_money(it['mcap'])} | Vol24: {fmt_money(it['vol24'])} | vm={it['vm']:.2f}\n"
            f"• 1h: {it['chg1']:+.2f}% | 24h: {it['chg24']:+.2f}% | volAccel={it['va']:.2f}\n"
            f"• DexBoost={it['dex']:.2f} | PoolBoost={it['pool']:.2f}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

async def on_startup(app: Application):
    app.bot_data["http"] = httpx.AsyncClient(
        timeout=httpx.Timeout(HTTP_TIMEOUT),
        headers=cg_headers(),
    )

async def on_shutdown(app: Application):
    http = app.bot_data.get("http")
    if http:
        await http.aclose()

def main():
    app = (
        Application.builder()
        .token(TG_BOT_TOKEN)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ultra", cmd_ultra))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
from smartmoney import scan_prepump_top3

async def prepump(update, context):
    await update.message.reply_text("⏳ Rodando scan pré-pump (CoinGecko Pro)…")
    try:
        top3 = scan_prepump_top3()
        if not top3:
            await update.message.reply_text("⚠️ Nada passou nos filtros agora.")
            return
        lines = ["🔥 SMART MONEY PRÉ-PUMP (TOP 3)"]
        for i,c in enumerate(top3, 1):
            lines.append(
                f"{i}) {c['symbol']} | Score {c['score']:.1f}\n"
                f"   Mcap ${c['mcap']:,} | Vol24 ${c['vol24']:,}\n"
                f"   1h {c['p1h']:+.2f}% | 24h {c['p24']:+.2f}%"
            )
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"⚠️ Erro no scan: {e}")
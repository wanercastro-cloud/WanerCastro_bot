import os
import math
import asyncio
from datetime import datetime, timedelta, time as dt_time
from zoneinfo import ZoneInfo

import httpx
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes


BRT = ZoneInfo("America/Sao_Paulo")
BYBIT_BASE = os.getenv("BYBIT_BASE", "https://api.bybit.com")

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "").strip()  # ex: "123456789"


def _now_brt() -> datetime:
    return datetime.now(tz=BRT)


def _next_run_at(hour: int, minute: int) -> datetime:
    """Próxima ocorrência de (hour:minute) em BRT."""
    now = _now_brt()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


async def bybit_spot_usdt_tickers(client: httpx.AsyncClient) -> list[dict]:
    """
    Pega tickers spot (Bybit v5). Retorna lista de dicts do 'result.list'.
    """
    url = f"{BYBIT_BASE}/v5/market/tickers"
    params = {"category": "spot"}
    r = await client.get(url, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    if data.get("retCode") != 0:
        raise RuntimeError(f"Bybit error: {data.get('retMsg')}")
    return data["result"]["list"]


async def bybit_kline_last_closes(
    client: httpx.AsyncClient,
    symbol: str,
    interval: str,
    limit: int = 20,
) -> list[float]:
    """
    Retorna lista de closes (float) do mais antigo -> mais novo.
    interval: "60" (1h) ou "240" (4h) etc, padrão Bybit.
    """
    url = f"{BYBIT_BASE}/v5/market/kline"
    params = {"category": "spot", "symbol": symbol, "interval": interval, "limit": str(limit)}
    r = await client.get(url, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    if data.get("retCode") != 0:
        raise RuntimeError(f"Kline error {symbol}: {data.get('retMsg')}")
    rows = data["result"]["list"]  # geralmente vem do mais novo -> mais velho
    # row = [startTime, open, high, low, close, volume, turnover]
    rows_rev = list(reversed(rows))
    closes = [float(x[4]) for x in rows_rev]
    return closes


def minmax_scale(values: list[float]) -> list[float]:
    if not values:
        return []
    mn, mx = min(values), max(values)
    if mx == mn:
        return [50.0 for _ in values]  # neutro
    return [100.0 * (v - mn) / (mx - mn) for v in values]


def safe_float(x, default=0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


async def compute_scores() -> dict:
    """
    Busca mercado spot Bybit e calcula score combinado.
    Retorna dict com:
      - top: lista ordenada de candidatos com score e métricas
      - meta: info geral
    """
    async with httpx.AsyncClient(headers={"User-Agent": "WanerCastro_bot/1.0"}) as client:
        tickers = await bybit_spot_usdt_tickers(client)

        # Filtra apenas pares USDT spot
        usdt = []
        for t in tickers:
            sym = t.get("symbol", "")
            if not sym.endswith("USDT"):
                continue
            # Alguns retornos úteis:
            last = safe_float(t.get("lastPrice"))
            turnover = safe_float(t.get("turnover24h"))  # valor negociado
            vol = safe_float(t.get("volume24h"))
            pct24 = safe_float(t.get("price24hPcnt"))  # ex: 0.0386 = 3.86%
            if last <= 0 or turnover <= 0:
                continue
            usdt.append(
                {
                    "symbol": sym,
                    "last": last,
                    "turnover24h": turnover,
                    "volume24h": vol,
                    "pct24": pct24,
                }
            )

        # Pré-seleção por liquidez (pra não explodir em chamadas)
        # Pegamos os TOP 60 por turnover24h, e só então pedimos kline 1h/4h
        usdt.sort(key=lambda x: x["turnover24h"], reverse=True)
        candidates = usdt[:60]

        sem = asyncio.Semaphore(10)

        async def enrich(symbol: str) -> tuple[float, float]:
            # retorna (ret1h, ret4h) em %
            async with sem:
                closes_1h = await bybit_kline_last_closes(client, symbol, "60", limit=10)
                closes_4h = await bybit_kline_last_closes(client, symbol, "240", limit=10)
            # retorno: último / (um candle atrás) - 1
            ret1h = 100.0 * (closes_1h[-1] / closes_1h[-2] - 1.0) if len(closes_1h) >= 2 else 0.0
            ret4h = 100.0 * (closes_4h[-1] / closes_4h[-2] - 1.0) if len(closes_4h) >= 2 else 0.0
            return (ret1h, ret4h)

        tasks = [enrich(c["symbol"]) for c in candidates]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        enriched = []
        for c, r in zip(candidates, results):
            if isinstance(r, Exception):
                # se falhar kline, ainda mantém, mas com momentum 0
                ret1h, ret4h = 0.0, 0.0
            else:
                ret1h, ret4h = r

            # Componentes do score
            # Liquidez: log(turnover)
            liq = math.log10(max(c["turnover24h"], 1.0))

            # Momento: pondera 1h e 4h
            mom = 0.6 * ret1h + 0.4 * ret4h

            # "Fluxo" (proxy): turnover * max(pct24,0)
            # (é uma aproximação do interesse comprador no dia; dá um bom ranking prático)
            flow = c["turnover24h"] * max(c["pct24"], 0.0)

            enriched.append(
                {
                    **c,
                    "ret1h": ret1h,
                    "ret4h": ret4h,
                    "liq_raw": liq,
                    "mom_raw": mom,
                    "flow_raw": flow,
                }
            )

        # Normaliza para 0..100 dentro do conjunto de candidatos
        liq_scaled = minmax_scale([e["liq_raw"] for e in enriched])
        mom_scaled = minmax_scale([e["mom_raw"] for e in enriched])
        flow_scaled = minmax_scale([e["flow_raw"] for e in enriched])

        for e, ls, ms, fs in zip(enriched, liq_scaled, mom_scaled, flow_scaled):
            # Score combinado (0..100)
            # 40% fluxo, 35% momento, 25% liquidez
            score = 0.40 * fs + 0.35 * ms + 0.25 * ls

            # Penalidades simples (anti “moeda ruim”):
            # - se momentum negativo forte, corta um pouco
            if e["mom_raw"] < -1.0:
                score *= 0.85
            # - se turnover baixo (mesmo no top 60), pequeno corte
            if e["turnover24h"] < 200_000:
                score *= 0.90

            e["liq_score"] = ls
            e["mom_score"] = ms
            e["flow_score"] = fs
            e["score"] = score

        enriched.sort(key=lambda x: x["score"], reverse=True)

        return {
            "top": enriched,
            "meta": {
                "count_total_usdt": len(usdt),
                "count_candidates": len(enriched),
                "generated_at_brt": _now_brt().strftime("%d/%m/%Y %H:%M:%S"),
            },
        }


def format_message(payload: dict, top_n: int = 10) -> str:
    top = payload["top"][:top_n]
    meta = payload["meta"]

    if not top:
        return "⚠️ Não consegui montar ranking agora (lista vazia). Tente novamente em alguns minutos."

    best = top[0]
    lines = []
    lines.append("📊 TOP SPOT BYBIT (USDT) – SCORE COMBINADO")
    lines.append(f"🕒 Gerado: {meta['generated_at_brt']} BRT")
    lines.append("")
    lines.append(f"🥇 #1 {best['symbol']} – Score {best['score']:.1f}")
    lines.append(
        f"   Fluxo {best['flow_score']:.0f} | Momento {best['mom_score']:.0f} | Liquidez {best['liq_score']:.0f}"
    )
    lines.append(
        f"   Retornos: 1h {best['ret1h']:+.2f}% | 4h {best['ret4h']:+.2f}% | 24h {best['pct24']*100:+.2f}%"
    )
    lines.append("")
    lines.append("🏆 TOP 10:")
    for i, c in enumerate(top, start=1):
        lines.append(f"{i:02d}) {c['symbol']} – {c['score']:.1f}  (1h {c['ret1h']:+.2f}%, 4h {c['ret4h']:+.2f}%)")

    lines.append("")
    lines.append("⚠️ Nota: 'Fluxo' aqui é proxy (turnover + força no dia). Se quiser, depois eu adiciono regras de candle/EMA/RSI.")
    return "\n".join(lines)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id if update.effective_chat else None
    await update.message.reply_text(
        "✅ Bot online!\n\n"
        f"Seu Chat ID é: {chat_id}\n\n"
        "➡️ Agora copie esse número e cole no Railway como variável TG_CHAT_ID.\n"
        "Depois reinicie o serviço no Railway."
    )


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("⏳ Calculando ranking Spot Bybit…")
    try:
        payload = await compute_scores()
        msg = format_message(payload, top_n=10)
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"⚠️ Erro ao calcular ranking: {e}")


async def daily_loop(app):
    """
    Loop que dispara todo dia às 21:00 BRT.
    """
    while True:
        next_run = _next_run_at(21, 0)
        sleep_s = (next_run - _now_brt()).total_seconds()
        await asyncio.sleep(max(1, int(sleep_s)))

        # Só envia automático se TG_CHAT_ID estiver definido
        if not TG_CHAT_ID:
            continue

        try:
            payload = await compute_scores()
            msg = format_message(payload, top_n=10)
            await app.bot.send_message(chat_id=TG_CHAT_ID, text=msg)
        except Exception as e:
            # Log simples (Railway Logs)
            print(f"[daily_loop] error: {e}")


async def on_startup(app):
    # dispara loop diário em background
    app.create_task(daily_loop(app))


def main():
    if not TG_BOT_TOKEN:
        raise RuntimeError("Defina TG_BOT_TOKEN nas variáveis do Railway.")

    app = (
        ApplicationBuilder()
        .token(TG_BOT_TOKEN)
        .post_init(on_startup)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("top", cmd_top))

    # roda polling (Railway)
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
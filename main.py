import os
import re
import math
import asyncio
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple

import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
BYBIT_BASE_URL = os.getenv("BYBIT_BASE_URL", "https://api.bybit.com").rstrip("/")
TOP_N = int(os.getenv("TOP_N", "5"))  # Top 5
CANDIDATES = int(os.getenv("CANDIDATES", "80"))  # pré-filtro por liquidez
TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "15"))

if not TG_BOT_TOKEN:
    raise RuntimeError("❌ Variável TG_BOT_TOKEN não encontrada no Railway (Variables).")


# --- Filtros (evitar stable/pegs e lixo óbvio) ---
STABLE_BASES = {
    "USDT", "USDC", "DAI", "TUSD", "USDE", "USDQ", "FDUSD", "PYUSD", "USDD", "BUSD",
    "EUR", "GBP", "JPY", "TRY"
}

SYMBOL_RE = re.compile(r"^[A-Z0-9]+USDT$")  # Bybit spot costuma vir assim (ex: BTCUSDT)


@dataclass
class CandidateScore:
    symbol: str
    score: float
    net_flow_12h: float
    large_in: float
    large_out: float
    support_1h: float
    price_last: float
    vol24_usdt: float


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _fmt_num(x: float) -> str:
    ax = abs(x)
    if ax >= 1_000_000_000:
        return f"{x/1_000_000_000:.2f}B"
    if ax >= 1_000_000:
        return f"{x/1_000_000:.2f}M"
    if ax >= 1_000:
        return f"{x/1_000:.2f}k"
    return f"{x:.2f}"


def _sigmoid(x: float) -> float:
    # comprime valores extremos (0..1)
    return 1.0 / (1.0 + math.exp(-x))


def _is_probably_stable(symbol: str) -> bool:
    # Remove bases que são stable/fiat (ex: USDQUSDT)
    base = symbol.replace("USDT", "")
    if base in STABLE_BASES:
        return True
    # se o nome já sugere stable
    if "USD" in base and base not in {"SUSD"}:
        return True
    return False


async def bybit_get(client: httpx.AsyncClient, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{BYBIT_BASE_URL}{path}"
    r = await client.get(url, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    # Bybit v5 geralmente: retCode 0 = OK
    if isinstance(data, dict) and data.get("retCode", 0) != 0:
        raise RuntimeError(f"Bybit API erro: retCode={data.get('retCode')} msg={data.get('retMsg')}")
    return data


async def fetch_spot_usdt_tickers(client: httpx.AsyncClient) -> List[Dict[str, Any]]:
    data = await bybit_get(client, "/v5/market/tickers", {"category": "spot"})
    items = (data.get("result") or {}).get("list") or []
    # filtra só USDT
    out = []
    for it in items:
        sym = str(it.get("symbol", "")).upper()
        if not sym.endswith("USDT"):
            continue
        if not SYMBOL_RE.match(sym):
            continue
        if _is_probably_stable(sym):
            continue
        out.append(it)
    return out


async def fetch_kline(client: httpx.AsyncClient, symbol: str, interval: str, limit: int) -> List[List[str]]:
    # Bybit v5 kline retorna list de candles (strings):
    # [startTime, open, high, low, close, volume, turnover]
    data = await bybit_get(
        client,
        "/v5/market/kline",
        {"category": "spot", "symbol": symbol, "interval": interval, "limit": limit},
    )
    candles = (data.get("result") or {}).get("list") or []
    # vem do mais recente pro mais antigo; vamos inverter pra ficar antigo->novo
    candles = list(reversed(candles))
    return candles


def compute_support_1h(candles_1h: List[List[str]], lookback: int = 24) -> float:
    if not candles_1h:
        return 0.0
    recent = candles_1h[-lookback:] if len(candles_1h) >= lookback else candles_1h
    lows = [_safe_float(c[3]) for c in recent]  # low
    return min(lows) if lows else 0.0


def compute_flow_proxy(candles: List[List[str]]) -> Tuple[float, float, float, float]:
    """
    Proxy "smart money" usando turnover (USDT) e direção do candle.
    - net_flow: soma de turnover com sinal (bull = +, bear = -)
    - large_in / large_out: aproximação usando último candle (turnover) e direção
    - price_last: último close
    - vol_sum: soma turnover (USDT)
    """
    if not candles:
        return 0.0, 0.0, 0.0, 0.0

    net = 0.0
    vol_sum = 0.0
    for c in candles:
        o = _safe_float(c[1])
        cl = _safe_float(c[4])
        turn = _safe_float(c[6])  # turnover (USDT)
        vol_sum += turn
        net += turn if cl >= o else -turn

    last = candles[-1]
    o = _safe_float(last[1])
    cl = _safe_float(last[4])
    last_turn = _safe_float(last[6])
    # "large" proxy = último candle (não é perfeito, mas funciona como radar)
    large_in = last_turn if cl >= o else 0.0
    large_out = last_turn if cl < o else 0.0
    price_last = _safe_float(last[4])
    return net, large_in, large_out, price_last, vol_sum


def score_symbol(
    turnover24: float,
    net12: float,
    last12_turn: float,
    prev12_turn: float,
    last1_turn: float,
    prev1_turn: float,
) -> float:
    """
    Score pré-pump (0..100) baseado em:
    - Liquidez (turnover24)
    - Aceleração de turnover (12h e 1h)
    - Net flow 12h (direcional)
    """
    # normalizações suaves (log)
    liq = math.log10(turnover24 + 1.0)  # 0..?
    acc12 = math.log10((last12_turn + 1.0) / (prev12_turn + 1.0))
    acc1 = math.log10((last1_turn + 1.0) / (prev1_turn + 1.0))
    dir12 = math.tanh(net12 / (turnover24 + 1.0) * 10.0)  # -1..1

    # pesos
    raw = (0.45 * liq) + (1.40 * acc12) + (1.60 * acc1) + (1.10 * dir12)

    # comprime p/ 0..100
    s = _sigmoid(raw - 1.2) * 100.0
    return float(max(0.0, min(100.0, s)))


async def smartmoney_top5() -> List[CandidateScore]:
    async with httpx.AsyncClient() as client:
        tickers = await fetch_spot_usdt_tickers(client)

        # pré-filtro por liquidez (turnover24h em USDT)
        parsed = []
        for t in tickers:
            sym = str(t.get("symbol", "")).upper()
            turnover24 = _safe_float(t.get("turnover24h"))
            last_price = _safe_float(t.get("lastPrice"))
            if turnover24 <= 0 or last_price <= 0:
                continue
            parsed.append((sym, turnover24, last_price))

        parsed.sort(key=lambda x: x[1], reverse=True)
        candidates = [x[0] for x in parsed[:CANDIDATES]]

        results: List[CandidateScore] = []

        # puxa kline em paralelo com limite de concorrência
        sem = asyncio.Semaphore(8)

        async def process_symbol(sym: str):
            async with sem:
                # 12h: precisamos de 3 candles pra comparar "último vs anterior"
                c12 = await fetch_kline(client, sym, "720", 3)
                # 1h: para suporte + aceleração 1h
                c1 = await fetch_kline(client, sym, "60", 50)

                if len(c12) < 2 or len(c1) < 2:
                    return

                # turnover (USDT) por candle
                last12_turn = _safe_float(c12[-1][6])
                prev12_turn = _safe_float(c12[-2][6])

                last1_turn = _safe_float(c1[-1][6])
                prev1_turn = _safe_float(c1[-2][6])

                net12, large_in, large_out, price_last, vol12_sum = compute_flow_proxy(c12[-2:])

                # turnover24 vem do ticker (vamos reusar do parsed)
                turnover24 = next((v for (s, v, _) in parsed if s == sym), 0.0)

                # filtro anti-stable “disfarçada”: se variação e direção forem quase nulas E liquidez baixa, ignora
                if turnover24 < 200_000 and abs(net12) < 50_000:
                    return

                support = compute_support_1h(c1, lookback=24)

                sc = score_symbol(
                    turnover24=turnover24,
                    net12=net12,
                    last12_turn=last12_turn,
                    prev12_turn=prev12_turn,
                    last1_turn=last1_turn,
                    prev1_turn=prev1_turn,
                )

                results.append(
                    CandidateScore(
                        symbol=sym.replace("USDT", "/USDT"),
                        score=sc,
                        net_flow_12h=net12,
                        large_in=large_in,
                        large_out=large_out,
                        support_1h=support,
                        price_last=price_last,
                        vol24_usdt=turnover24,
                    )
                )

        await asyncio.gather(*[process_symbol(s) for s in candidates], return_exceptions=True)

        results.sort(key=lambda x: x.score, reverse=True)
        return results[:TOP_N]


def format_top(scores: List[CandidateScore]) -> str:
    if not scores:
        return "⚠️ Não encontrei candidatos fortes agora (Bybit SPOT). Tenta de novo em 5–10 min."

    lines = [f"🔥 <b>SMART MONEY PRÉ-PUMP — BYBIT SPOT (TOP {len(scores)})</b>\n"]
    for i, it in enumerate(scores, 1):
        net = it.net_flow_12h
        li = it.large_in
        lo = it.large_out
        sup = it.support_1h

        lines.append(
            f"<b>{i}) {it.symbol}</b> | <b>Score {it.score:.1f}</b>\n"
            f"Vol24 (USDT): {_fmt_num(it.vol24_usdt)}\n"
            f"Net Flow 12H: {'+' if net >= 0 else ''}{_fmt_num(net)}\n"
            f"Large In (proxy): {_fmt_num(li)} | Large Out (proxy): {_fmt_num(lo)}\n"
            f"Suporte 1H (min 24 candles): {sup:.8f}\n"
        )

    lines.append("📌 Dica: se perder o suporte 1H com volume, corta rápido. Se segurar e acelerar 1H, vira candidato de liderança.")
    return "\n".join(lines)


# ---------------- Telegram handlers ----------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ Bot online.\n\nComandos:\n"
        "/ping\n"
        "/smartmoney  → Top 5 Bybit SPOT (pré-pump)\n",
    )


async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("pong ✅")


async def cmd_smartmoney(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔎 Rodando scanner Bybit SPOT (Top 5)...")
    try:
        top = await smartmoney_top5()
        text = format_top(top)
        await msg.edit_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e:
        await msg.edit_text(f"⚠️ Erro no scanner: {e}")


def main():
    app = Application.builder().token(TG_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("smartmoney", cmd_smartmoney))

    # Importante: apenas 1 instância do bot rodando (Railway 1 replica).
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
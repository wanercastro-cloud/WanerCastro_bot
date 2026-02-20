import os
import time
import json
import logging
from typing import Dict, Any, Tuple, List

import requests
from cachetools import TTLCache

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# =========================
# CONFIG
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

TG_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
CG_KEY = os.getenv("COINGECKO_API_KEY", "").strip()
ALERT_CHAT_ID_ENV = os.getenv("ALERT_CHAT_ID", "").strip()

if not TG_TOKEN:
    raise RuntimeError("TG_BOT_TOKEN não configurado no Railway (Variables).")

# CoinGecko PRO base URL (correção do erro 10010)
CG_BASE = "https://pro-api.coingecko.com/api/v3"
CG_MARKETS = f"{CG_BASE}/coins/markets"
CG_SIMPLE_PRICE = f"{CG_BASE}/simple/price"

# Cache para reduzir 429 e deixar rápido
http_cache = TTLCache(maxsize=512, ttl=60)  # 60s cache de respostas
snap_cache = TTLCache(maxsize=2000, ttl=3600)  # 1h de "histórico curto" pra aceleração

# Persistência simples (melhor que nada; Railway pode reiniciar)
STATE_FILE = "/tmp/bot_state.json"

# =========================
# STATE (por chat_id)
# =========================
alert_enabled: Dict[int, bool] = {}
watchlists: Dict[int, set] = {}
alert_min_score: Dict[int, int] = {}
alert_cooldown_s: Dict[int, int] = {}
last_alert_at: Dict[Tuple[int, str], float] = {}  # (chat_id, symbol) -> timestamp

# Defaults
DEFAULT_MIN_SCORE = 75
DEFAULT_COOLDOWN_S = 240  # 4 min

# =========================
# HTTP HELPERS
# =========================
def cg_headers() -> Dict[str, str]:
    # CoinGecko PRO header
    if not CG_KEY:
        raise RuntimeError("COINGECKO_API_KEY não configurado no Railway (Variables).")
    return {
        "Accept": "application/json",
        "User-Agent": "WanerCastro_bot/1.0",
        "x-cg-pro-api-key": CG_KEY,
    }


def http_get_json(url: str, params: Dict[str, Any] = None, cache_key: str = "") -> Any:
    """GET com cache + retry básico (429/5xx) + timeout."""
    params = params or {}
    key = cache_key or f"{url}?{json.dumps(params, sort_keys=True)}"

    if key in http_cache:
        return http_cache[key]

    backoff = 1.0
    for attempt in range(5):
        try:
            r = requests.get(url, params=params, headers=cg_headers(), timeout=15)
            if r.status_code == 429:
                # Rate limit: aguarda e tenta de novo
                time.sleep(backoff)
                backoff = min(backoff * 2, 12)
                continue
            r.raise_for_status()
            data = r.json()
            http_cache[key] = data
            return data
        except requests.HTTPError as e:
            # 400/403/404 etc: loga corpo pra debug e não fica loopando
            body = ""
            try:
                body = r.text[:500]
            except Exception:
                pass
            logging.exception(f"HTTPError {getattr(r,'status_code',None)} body={body}")
            raise
        except Exception:
            logging.exception("Falha ao chamar CoinGecko")
            time.sleep(backoff)
            backoff = min(backoff * 2, 12)

    raise RuntimeError("CoinGecko indisponível após retries.")


# =========================
# SCORING / SMART MONEY (heurístico pré-pump)
# =========================
def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def score_coin(m: Dict[str, Any]) -> Dict[str, Any]:
    """
    Score "pré-pump" (heurístico):
    - Volatilidade (abs % 24h)
    - Volume (24h)
    - "Aceleração" de volume e preço vs snapshot anterior (curto prazo)
    """
    coin_id = m.get("id")
    symbol = (m.get("symbol") or "").upper()
    price = float(m.get("current_price") or 0)
    chg24 = float(m.get("price_change_percentage_24h") or 0)
    vol = float(m.get("total_volume") or 0)
    mcap = float(m.get("market_cap") or 0)

    # Guardar snapshot curto para comparar "agora vs último"
    now = time.time()
    prev = snap_cache.get(coin_id)
    snap_cache[coin_id] = {
        "t": now,
        "price": price,
        "vol": vol,
        "chg24": chg24,
        "mcap": mcap,
        "symbol": symbol,
        "name": m.get("name"),
    }

    # Aceleração (se tiver snapshot anterior)
    vol_acc = 1.0
    price_acc = 1.0
    dt = 60.0
    if prev:
        dt = max(10.0, now - float(prev.get("t", now)))
        prev_vol = float(prev.get("vol", vol))
        prev_price = float(prev.get("price", price))
        # ratios
        vol_acc = (vol / prev_vol) if prev_vol > 0 else 1.0
        price_acc = (price / prev_price) if prev_price > 0 else 1.0

    # Normalizações suaves
    vol_norm = clamp((vol ** 0.5) / 5000.0, 0, 1)  # volume grande sobe o score, mas sem explodir
    vol_acc_norm = clamp((vol_acc - 1.0) * 2.5, 0, 1)  # aceleração de volume
    price_acc_norm = clamp((price_acc - 1.0) * 25.0, 0, 1)  # aceleração de preço (bem sensível)
    volat_norm = clamp(abs(chg24) / 25.0, 0, 1)  # 25%+ vira 1
    quality_norm = clamp((vol / (mcap + 1.0)) * 5.0, 0, 1) if mcap > 0 else 0.2  # giro/liq

    # “Pré-pump” quer:
    # - vol_acc alto
    # - price_acc começando a virar
    # - volatilidade presente (mas não precisa 100% já)
    raw = (
        40 * vol_acc_norm +
        25 * price_acc_norm +
        20 * volat_norm +
        10 * vol_norm +
        5 * quality_norm
    )

    # Penaliza stablecoins e assets pouco voláteis
    if symbol in {"USDT", "USDC", "DAI", "TUSD", "FDUSD", "USDE"}:
        raw *= 0.1

    # Bonus se 24h já está positivo (para “iminente subida”)
    if chg24 > 0:
        raw += 5

    # Score 0..100
    score = int(clamp(raw, 0, 100))

    return {
        "id": coin_id,
        "symbol": symbol,
        "name": m.get("name") or symbol,
        "price": price,
        "chg24": chg24,
        "vol": vol,
        "mcap": mcap,
        "vol_acc": vol_acc,
        "price_acc": price_acc,
        "score": score,
        "dt": dt,
    }


def fmt_money(x: float) -> str:
    if x >= 1_000_000_000:
        return f"{x/1_000_000_000:.2f}B"
    if x >= 1_000_000:
        return f"{x/1_000_000:.2f}M"
    if x >= 1_000:
        return f"{x/1_000:.2f}K"
    return f"{x:.0f}"


def get_markets(vs: str = "usd", per_page: int = 250, page: int = 1) -> List[Dict[str, Any]]:
    params = {
        "vs_currency": vs,
        "order": "volume_desc",  # pegamos alta liquidez e depois ranqueamos por score
        "per_page": per_page,
        "page": page,
        "sparkline": "false",
        "price_change_percentage": "24h",
    }
    return http_get_json(CG_MARKETS, params=params, cache_key=f"markets:{vs}:{per_page}:{page}")


def top_premium_volatility(limit: int = 10) -> List[Dict[str, Any]]:
    # 1 página já dá muito; se quiser mais agressivo, some páginas.
    markets = get_markets(per_page=250, page=1)
    scored = [score_coin(m) for m in markets]

    # Critério: só volatilidade (pediu) + pré-pump (aceleração)
    # Exclui muito pequeno/sem liquidez
    scored = [s for s in scored if s["vol"] and s["vol"] > 5_000_000 and s["price"] > 0]

    # Ordena pelo score “pré-pump”
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]


# =========================
# TELEGRAM COMMANDS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    await update.message.reply_text(
        "🤖 Bot online!\n\n"
        "Comandos:\n"
        "/price BTC  (ex: /price BTC)\n"
        "/topspot  (Top Premium por volatilidade + pré-pump)\n"
        "/smartmoney  (Radar pré-pump mais agressivo)\n\n"
        "Alertas:\n"
        "/watch AZTEC  (ou /watch BTC)\n"
        "/unwatch AZTEC\n"
        "/mywatch\n"
        "/alerts_on | /alerts_off\n"
        "/setscore 75\n"
        "/setcooldown 240\n"
    )

    # init defaults
    watchlists.setdefault(cid, set())
    alert_enabled.setdefault(cid, True)
    alert_min_score.setdefault(cid, DEFAULT_MIN_SCORE)
    alert_cooldown_s.setdefault(cid, DEFAULT_COOLDOWN_S)


def normalize_symbol(sym: str) -> str:
    sym = (sym or "").strip().upper()
    sym = sym.replace("/", "").replace("USDT", "").replace("USD", "")
    return sym


def find_coin_for_symbol(markets: List[Dict[str, Any]], symbol: str) -> Dict[str, Any] | None:
    symbol = symbol.upper()
    for m in markets:
        if (m.get("symbol") or "").upper() == symbol:
            return m
    return None


async def topspot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        tops = top_premium_volatility(limit=10)
        lines = ["🏆 Top Premium (volatilidade + pré-pump)"]
        for i, c in enumerate(tops, 1):
            lines.append(
                f"{i:02d}. {c['symbol']} | ${c['price']:.6g} | 24h {c['chg24']:+.2f}% | "
                f"vol {fmt_money(c['vol'])} | score {c['score']} | "
                f"Δvol x{c['vol_acc']:.2f} | Δp x{c['price_acc']:.4f}"
            )
        await update.message.reply_text("\n".join(lines))
    except requests.HTTPError as e:
        await update.message.reply_text(f"⚠️ CoinGecko falhou: HTTPError {str(e)}")
    except Exception as e:
        logging.exception("Erro topspot")
        await update.message.reply_text(f"⚠️ Erro ao montar o Top Premium Spot. Erro: {type(e).__name__}")


async def smartmoney(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Radar mais agressivo (pega antes):
    - Dá mais peso à aceleração de volume e começa a sinalizar mesmo com 24h ainda baixo.
    """
    try:
        markets = get_markets(per_page=250, page=1)
        scored = [score_coin(m) for m in markets]
        scored = [s for s in scored if s["vol"] > 8_000_000 and s["price"] > 0]
        # Mais agressivo: ordena e mostra 12
        scored.sort(key=lambda x: (x["score"], x["vol_acc"]), reverse=True)
        top = scored[:12]

        lines = ["🐳 Smart Money Radar (heurístico, pré-pump)"]
        lines.append("Sinal = aceleração de volume + aceleração de preço + volatilidade\n")
        for i, c in enumerate(top, 1):
            tag = "🔥" if c["score"] >= 85 else ("⚡" if c["score"] >= 75 else "👀")
            lines.append(
                f"{i:02d}. {tag} {c['symbol']} | ${c['price']:.6g} | 24h {c['chg24']:+.2f}% | "
                f"vol {fmt_money(c['vol'])} | score {c['score']} | "
                f"Δvol x{c['vol_acc']:.2f} | Δp x{c['price_acc']:.4f}"
            )

        await update.message.reply_text("\n".join(lines))
    except requests.HTTPError as e:
        await update.message.reply_text(f"⚠️ CoinGecko falhou: HTTPError {str(e)}")
    except Exception as e:
        logging.exception("Erro smartmoney")
        await update.message.reply_text(f"⚠️ Erro no /smartmoney: {type(e).__name__}")


async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text("Use: /price BTC  (ou /price ETH)")
            return
        sym = normalize_symbol(context.args[0])
        markets = get_markets(per_page=250, page=1)
        m = find_coin_for_symbol(markets, sym)
        if not m:
            await update.message.reply_text(f"Não encontrei {sym} nos top líquidos (page 1).")
            return
        c = score_coin(m)
        await update.message.reply_text(
            f"💰 {c['symbol']} | ${c['price']:.6g}\n"
            f"24h: {c['chg24']:+.2f}% | vol: {fmt_money(c['vol'])}\n"
            f"Score pré-pump: {c['score']} | Δvol x{c['vol_acc']:.2f} | Δp x{c['price_acc']:.4f}"
        )
    except Exception as e:
        logging.exception("Erro price")
        await update.message.reply_text(f"⚠️ Erro no /price: {type(e).__name__}")


async def watch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    watchlists.setdefault(cid, set())
    if not context.args:
        await update.message.reply_text("Use: /watch AZTEC  (ou /watch BTC)")
        return
    sym = normalize_symbol(context.args[0])
    watchlists[cid].add(sym)
    await update.message.reply_text(f"✅ Adicionado à watchlist: {sym}")


async def unwatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    watchlists.setdefault(cid, set())
    if not context.args:
        await update.message.reply_text("Use: /unwatch AZTEC")
        return
    sym = normalize_symbol(context.args[0])
    watchlists[cid].discard(sym)
    await update.message.reply_text(f"🗑️ Removido da watchlist: {sym}")


async def mywatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    wl = sorted(list(watchlists.get(cid, set())))
    if not wl:
        await update.message.reply_text("Sua watchlist está vazia. Use /watch AZTEC")
        return
    await update.message.reply_text("📌 Watchlist:\n" + "\n".join([f"- {x}" for x in wl]))


async def alerts_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    alert_enabled[cid] = True
    await update.message.reply_text("🔔 Alertas ligados.")


async def alerts_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    alert_enabled[cid] = False
    await update.message.reply_text("🔕 Alertas desligados.")


async def setscore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Use: /setscore 75")
        return
    try:
        v = int(context.args[0])
        v = max(0, min(100, v))
        alert_min_score[cid] = v
        await update.message.reply_text(f"✅ Score mínimo ajustado: {v}")
    except Exception:
        await update.message.reply_text("⚠️ Use: /setscore 75")


async def setcooldown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Use: /setcooldown 240  (segundos)")
        return
    try:
        v = int(context.args[0])
        v = max(30, min(3600, v))
        alert_cooldown_s[cid] = v
        await update.message.reply_text(f"✅ Cooldown ajustado: {v}s")
    except Exception:
        await update.message.reply_text("⚠️ Use: /setcooldown 240")


# =========================
# ALERT JOB (automático)
# =========================
async def alert_job(context: ContextTypes.DEFAULT_TYPE):
    """
    Roda a cada 60s:
    - para cada chat com alertas ON:
      - pega mercados (cache ajuda)
      - para cada símbolo da watchlist:
         - calcula score
         - se score >= min e respeita cooldown -> alerta
    """
    try:
        markets = get_markets(per_page=250, page=1)
        # index para achar rápido
        idx = {(m.get("symbol") or "").upper(): m for m in markets}

        for cid, enabled in list(alert_enabled.items()):
            if not enabled:
                continue
            wl = watchlists.get(cid, set())
            if not wl:
                continue

            min_sc = alert_min_score.get(cid, DEFAULT_MIN_SCORE)
            cd = alert_cooldown_s.get(cid, DEFAULT_COOLDOWN_S)

            for sym in wl:
                m = idx.get(sym.upper())
                if not m:
                    continue
                c = score_coin(m)

                if c["score"] < min_sc:
                    continue

                k = (cid, sym.upper())
                now = time.time()
                last = last_alert_at.get(k, 0)
                if now - last < cd:
                    continue

                last_alert_at[k] = now
                tag = "🚨" if c["score"] >= 90 else ("⚠️" if c["score"] >= 80 else "🔔")
                msg = (
                    f"{tag} ALERTA PRÉ-PUMP (heurístico)\n"
                    f"{c['symbol']} | ${c['price']:.6g} | 24h {c['chg24']:+.2f}%\n"
                    f"vol {fmt_money(c['vol'])} | score {c['score']}\n"
                    f"Δvol x{c['vol_acc']:.2f} | Δp x{c['price_acc']:.4f}"
                )
                await context.bot.send_message(chat_id=cid, text=msg)

    except requests.HTTPError as e:
        logging.exception(f"Alert job HTTPError: {e}")
    except Exception:
        logging.exception("Alert job falhou")


# =========================
# PERSIST (best-effort)
# =========================
def load_state():
    global alert_enabled, watchlists, alert_min_score, alert_cooldown_s
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            alert_enabled = {int(k): bool(v) for k, v in data.get("alert_enabled", {}).items()}
            watchlists = {int(k): set(v) for k, v in data.get("watchlists", {}).items()}
            alert_min_score = {int(k): int(v) for k, v in data.get("alert_min_score", {}).items()}
            alert_cooldown_s = {int(k): int(v) for k, v in data.get("alert_cooldown_s", {}).items()}
            logging.info("Estado carregado.")
    except Exception:
        logging.exception("Falha ao carregar estado.")


def save_state():
    try:
        data = {
            "alert_enabled": {str(k): v for k, v in alert_enabled.items()},
            "watchlists": {str(k): sorted(list(v)) for k, v in watchlists.items()},
            "alert_min_score": {str(k): v for k, v in alert_min_score.items()},
            "alert_cooldown_s": {str(k): v for k, v in alert_cooldown_s.items()},
        }
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        logging.exception("Falha ao salvar estado.")


async def autosave_job(context: ContextTypes.DEFAULT_TYPE):
    save_state()


# =========================
# MAIN
# =========================
def main():
    load_state()

    app = ApplicationBuilder().token(TG_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("topspot", topspot))
    app.add_handler(CommandHandler("smartmoney", smartmoney))

    app.add_handler(CommandHandler("watch", watch))
    app.add_handler(CommandHandler("unwatch", unwatch))
    app.add_handler(CommandHandler("mywatch", mywatch))

    app.add_handler(CommandHandler("alerts_on", alerts_on))
    app.add_handler(CommandHandler("alerts_off", alerts_off))
    app.add_handler(CommandHandler("setscore", setscore))
    app.add_handler(CommandHandler("setcooldown", setcooldown))

    # Pré-ativação opcional (se você setar ALERT_CHAT_ID no Railway)
    if ALERT_CHAT_ID_ENV.isdigit():
        cid = int(ALERT_CHAT_ID_ENV)
        alert_enabled[cid] = True
        watchlists.setdefault(cid, set())
        alert_min_score.setdefault(cid, DEFAULT_MIN_SCORE)
        alert_cooldown_s.setdefault(cid, DEFAULT_COOLDOWN_S)
        logging.info(f"Alertas pré-ativados para chat_id={cid}")

    # Jobs
    app.job_queue.run_repeating(alert_job, interval=60, first=15)      # alertas a cada 60s
    app.job_queue.run_repeating(autosave_job, interval=120, first=60)  # autosave a cada 2 min

    logging.info("✅ Bot iniciado (CoinGecko PRO).")
    app.run_polling()

if __name__ == "__main__":
    main()
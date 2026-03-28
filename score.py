"""
score.py — CoinGecko VOL/MCAP scorer + ranking + alertas sniper para scalp no Telegram.

Comandos disponíveis:
  /ranking         — Executa o ranking agora
  /top N           — Retorna o top N coins (ex: /top 5)
  /status          — Mostra configurações atuais e próximo ciclo
  /filtros         — Lista os filtros de triagem ativos
  /alertas         — Mostra regras dos alertas sniper
  /parar           — Pausa o loop automático
  /iniciar         — Retoma o loop automático
  /help            — Lista todos os comandos

Dependências:
  pip install python-telegram-bot>=21.0
"""

import sys
import json
import os
import math
import re
import time
import asyncio
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone

from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes


# ──────────────────────────────────────────────────────────────────────────────
# Config via variáveis de ambiente
# ──────────────────────────────────────────────────────────────────────────────

CG_API_KEY = os.getenv("CG_API_KEY", "").strip()
CG_API_TIER = os.getenv("CG_API_TIER", "demo").strip().lower()

FETCH_N = int(os.getenv("FETCH_N", "300"))
PER_PAGE = 250
INTERVAL_SECONDS = int(os.getenv("INTERVAL_SECONDS", "900"))

MIN_MCAP = float(os.getenv("MIN_MCAP", "5000000"))
MAX_MCAP = float(os.getenv("MAX_MCAP", "2000000000"))
MIN_VOL24 = float(os.getenv("MIN_VOL24", "6000000"))
MIN_RATIO_X = float(os.getenv("MIN_RATIO_X", "0.40"))

TOP_SHOW = int(os.getenv("TOP_SHOW", "10"))

W_RATIO = float(os.getenv("W_RATIO", "0.45"))
W_MOM_1H = float(os.getenv("W_MOM_1H", "0.35"))
W_MOM_24H = float(os.getenv("W_MOM_24H", "0.15"))
W_MOM_7D = float(os.getenv("W_MOM_7D", "0.05"))

MAX_24H_FOR_ENTRY = float(os.getenv("MAX_24H_FOR_ENTRY", "80"))

ALERT_MIN_RATIO_X = float(os.getenv("ALERT_MIN_RATIO_X", "1.00"))
ALERT_MIN_1H = float(os.getenv("ALERT_MIN_1H", "2.5"))
ALERT_MAX_1H = float(os.getenv("ALERT_MAX_1H", "14"))
ALERT_MAX_24H = float(os.getenv("ALERT_MAX_24H", "45"))
ALERT_MIN_SCORE = float(os.getenv("ALERT_MIN_SCORE", "0.52"))

WASH_24H_HARD_MAX = float(os.getenv("WASH_24H_HARD_MAX", "120"))
WASH_RATIO_HARD_MAX = float(os.getenv("WASH_RATIO_HARD_MAX", "3.8"))
WASH_REQUIRE_1H_IF_HIGH_RATIO = os.getenv(
    "WASH_REQUIRE_1H_IF_HIGH_RATIO", "true"
).strip().lower() == "true"

SEND_RANKING_EVERY_CYCLE = os.getenv(
    "SEND_RANKING_EVERY_CYCLE", "false"
).strip().lower() == "true"

SNIPER_ONLY = os.getenv("SNIPER_ONLY", "true").strip().lower() == "true"

ALERT_COOLDOWN_SECONDS = int(os.getenv("ALERT_COOLDOWN_SECONDS", "3600"))

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "").strip()


# ──────────────────────────────────────────────────────────────────────────────
# Estado global
# ──────────────────────────────────────────────────────────────────────────────

loop_ativo = True
proximo_ciclo: datetime | None = None
ultimo_ranking: list[dict] = []
last_alerts: dict[str, float] = {}


# ──────────────────────────────────────────────────────────────────────────────
# CoinGecko
# ──────────────────────────────────────────────────────────────────────────────

def base_url() -> str:
    if CG_API_TIER == "paid" and CG_API_KEY:
        return "https://pro-api.coingecko.com/api/v3"
    return "https://api.coingecko.com/api/v3"


def make_headers() -> dict:
    headers = {
        "Accept": "application/json",
        "User-Agent": "cg-scalp-scorer/4.0",
    }

    if CG_API_KEY:
        if CG_API_TIER == "paid":
            headers["x-cg-pro-api-key"] = CG_API_KEY
        else:
            headers["x-cg-demo-api-key"] = CG_API_KEY

    return headers


def fetch_markets(page: int) -> list[dict]:
    params = urllib.parse.urlencode({
        "vs_currency": "usd",
        "order": "volume_desc",
        "per_page": PER_PAGE,
        "page": page,
        "sparkline": "false",
        "price_change_percentage": "1h,7d",
    })
    url = f"{base_url()}/coins/markets?{params}"
    req = urllib.request.Request(url, headers=make_headers())

    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 30 * (attempt + 1)
                print(f"[WARN] Rate limit na página {page}. Esperando {wait}s...", file=sys.stderr)
                time.sleep(wait)
            else:
                print(f"[ERR] HTTP {e.code} na página {page}: {e.reason}", file=sys.stderr)
                raise
        except Exception as e:
            wait = 5 * (attempt + 1)
            print(f"[ERR] Falha na página {page}, tentativa {attempt+1}: {e}", file=sys.stderr)
            time.sleep(wait)

    raise RuntimeError(f"Falha ao buscar página {page} após 3 tentativas.")


def fetch_all_coins() -> list[dict]:
    pages = math.ceil(FETCH_N / PER_PAGE)
    coins: list[dict] = []

    for page in range(1, pages + 1):
        print(f"[INFO] Buscando página {page}/{pages}...", file=sys.stderr)
        batch = fetch_markets(page)
        if not batch:
            break
        coins.extend(batch)
        if len(coins) >= FETCH_N:
            break
        if page < pages:
            time.sleep(1.5)

    print(f"[INFO] Total bruto carregado: {len(coins)} coins", file=sys.stderr)
    return coins[:FETCH_N]


# ──────────────────────────────────────────────────────────────────────────────
# Blacklist / filtros básicos
# ──────────────────────────────────────────────────────────────────────────────

BLACKLIST = {
    "usdt","usdc","busd","dai","tusd","usdp","usdd","frax","lusd","gusd",
    "susd","fdusd","pyusd","usde","crvusd","mkusd","cusd","zusd","usdq",
    "usdr","usds","musd","husd","ousd","usda","usdb","u",
    "eurs","eurq","eurt","eure","steur","ageur","eurc",
    "eur","gbp","jpy","cny","krw","brl","try","cad","sgd","chf",
    "wbtc","weth","steth","cbeth","reth","wsteth","weeth","ezeth","rseth",
    "lseth","ankreth","sweth","oseth","meth","wbeth","sfrxeth",
    "paxg","xaut","cache","pmgt","dgld",
    "hoodx","amznx","aaplx","nvdax","tslax","msfx","metax","googx",
    "spyx","qqqx","coinx","arkx","mstrx","nflxx","amdx","intcx",
}

BLACKLIST_KW = [
    "leveraged", "2x long", "3x long", "bear token", "bull token",
    "xstock", "wrapped ", "staked "
]

XSTOCK_RE = re.compile(r"^[A-Z]{2,5}X$")


def safe_float(val, default=0.0) -> float:
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def is_stable(coin: dict) -> bool:
    price = safe_float(coin.get("current_price"))
    chg_24h = abs(safe_float(coin.get("price_change_percentage_24h")))
    return 0.90 <= price <= 1.15 and chg_24h < 0.5


def is_bad(coin: dict) -> bool:
    sym = coin.get("symbol", "").lower()
    name = coin.get("name", "").lower()

    if sym in BLACKLIST:
        return True

    for kw in BLACKLIST_KW:
        if kw in sym or kw in name:
            return True

    if XSTOCK_RE.match(sym.upper()):
        return True

    if is_stable(coin):
        return True

    return False


# ──────────────────────────────────────────────────────────────────────────────
# Scales fixas
# ──────────────────────────────────────────────────────────────────────────────

def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(v, hi))


def scale_ratio(vol_mcap_x: float) -> float:
    return clamp(vol_mcap_x / 3.0)


def scale_mom_1h(chg_1h: float) -> float:
    return clamp(max(chg_1h, 0.0) / 10.0)


def scale_mom_24h(chg_24h: float) -> float:
    return clamp(max(chg_24h, 0.0) / 50.0)


def scale_mom_7d(chg_7d: float) -> float:
    return clamp(max(chg_7d, 0.0) / 100.0)


# ──────────────────────────────────────────────────────────────────────────────
# Regras de wash / classificação / alerta
# ──────────────────────────────────────────────────────────────────────────────

def looks_washy(vol_mcap_x: float, chg_1h: float, chg_24h: float, mcap: float) -> bool:
    if vol_mcap_x > WASH_RATIO_HARD_MAX:
        return True

    if chg_24h > WASH_24H_HARD_MAX:
        return True

    if WASH_REQUIRE_1H_IF_HIGH_RATIO and vol_mcap_x > 2.0 and chg_1h < 3.0:
        return True

    if mcap < 8_000_000 and vol_mcap_x > 2.8 and chg_1h < 3.0:
        return True

    return False


def classify_coin(vol_mcap_x: float, chg_1h: float, chg_24h: float, score: float) -> str:
    if chg_1h < 0:
        return "🔴 DESCARTE"

    if chg_24h > 80:
        return "🔴 TOPO"

    if vol_mcap_x > 2.0 and 5.0 < chg_1h < 15.0 and chg_24h < 60.0 and score >= 0.60:
        return "🔥 FORTE"

    if vol_mcap_x > 1.2 and 3.0 < chg_1h < 12.0 and chg_24h < 60.0 and score >= 0.55:
        return "🟢 SCALP"

    if vol_mcap_x > 0.8 and chg_1h >= 1.0:
        return "🟡 OBSERVAR"

    return "⚪ FRACO"


def should_alert(coin: dict) -> bool:
    return (
        coin["score"] >= ALERT_MIN_SCORE
        and coin["vol_mcap_x"] >= ALERT_MIN_RATIO_X
        and ALERT_MIN_1H <= coin["chg_1h"] <= ALERT_MAX_1H
        and coin["chg_24h"] <= ALERT_MAX_24H
        and coin["label"] in ("🔥 FORTE", "🟢 SCALP")
    )


def can_send_alert(coin_id: str) -> bool:
    now = time.time()
    last = last_alerts.get(coin_id, 0.0)
    if now - last >= ALERT_COOLDOWN_SECONDS:
        last_alerts[coin_id] = now
        return True
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Score principal
# ──────────────────────────────────────────────────────────────────────────────

def score_coins(coins: list[dict], top_n: int | None = None) -> list[dict]:
    if top_n is None:
        top_n = TOP_SHOW

    filtered: list[dict] = []

    for c in coins:
        if is_bad(c):
            continue

        mcap = safe_float(c.get("market_cap"))
        vol = safe_float(c.get("total_volume"))
        chg_1h = safe_float(c.get("price_change_percentage_1h_in_currency"))
        chg_24h = safe_float(c.get("price_change_percentage_24h"))
        chg_7d = safe_float(c.get("price_change_percentage_7d_in_currency"))

        if not (MIN_MCAP <= mcap <= MAX_MCAP):
            continue

        if vol < MIN_VOL24:
            continue

        if mcap <= 0:
            continue

        vol_mcap_x = vol / mcap

        if vol_mcap_x < MIN_RATIO_X:
            continue

        if looks_washy(vol_mcap_x, chg_1h, chg_24h, mcap):
            continue

        r = scale_ratio(vol_mcap_x)
        m1 = scale_mom_1h(chg_1h)
        m24 = scale_mom_24h(chg_24h)
        m7 = scale_mom_7d(chg_7d)

        score = (
            W_RATIO * r +
            W_MOM_1H * m1 +
            W_MOM_24H * m24 +
            W_MOM_7D * m7
        )

        # penalização progressiva por exaustão
        if chg_24h > MAX_24H_FOR_ENTRY:
            score *= 0.70
        elif chg_24h > 60:
            score *= 0.85

        if chg_7d > 120:
            score *= 0.70
        elif chg_7d > 80:
            score *= 0.85

        label = classify_coin(vol_mcap_x, chg_1h, chg_24h, score)

        c["_score"] = score
        c["_vol_mcap_x"] = vol_mcap_x
        c["_chg_1h"] = chg_1h
        c["_chg_24h"] = chg_24h
        c["_chg_7d"] = chg_7d
        c["_label"] = label
        filtered.append(c)

    print(f"[INFO] Passaram nos filtros: {len(filtered)}", file=sys.stderr)

    ranked = sorted(filtered, key=lambda x: x["_score"], reverse=True)[:top_n]
    result: list[dict] = []

    for rank, c in enumerate(ranked, 1):
        result.append({
            "rank": rank,
            "symbol": c.get("symbol", "").upper(),
            "name": c.get("name", ""),
            "price_usd": round(safe_float(c.get("current_price")), 6),
            "mcap_m": round(safe_float(c.get("market_cap")) / 1e6, 1),
            "vol24_m": round(safe_float(c.get("total_volume")) / 1e6, 1),
            "vol_mcap_x": round(c["_vol_mcap_x"], 2),
            "chg_1h": round(c["_chg_1h"], 2),
            "chg_24h": round(c["_chg_24h"], 2),
            "chg_7d": round(c["_chg_7d"], 2),
            "score": round(c["_score"], 4),
            "label": c["_label"],
            "coingecko_id": c.get("id", ""),
        })

    return result


# ──────────────────────────────────────────────────────────────────────────────
# Formatação Telegram
# ──────────────────────────────────────────────────────────────────────────────

def format_tg(ranked: list[dict]) -> str:
    now = datetime.now(timezone.utc).strftime("%d/%m %H:%M UTC")
    lines = [f"📊 Ranking VOL/MCAP + MOM — {now}\n"]

    for c in ranked:
        lines.append(
            f"{c['rank']:02d}. {c['symbol']} — {c['label']} — score {c['score']:.3f}\n"
            f"   VOL/MCAP: {c['vol_mcap_x']:.2f}x | "
            f"1h:{c['chg_1h']:+.1f}% 24h:{c['chg_24h']:+.1f}% 7d:{c['chg_7d']:+.1f}%\n"
            f"   ${c['price_usd']} | MCAP ${c['mcap_m']}M | VOL ${c['vol24_m']}M"
        )

    return "\n\n".join(lines)


def build_alert_message(c: dict) -> str:
    now = datetime.now(timezone.utc).strftime("%d/%m %H:%M UTC")
    return (
        f"🎯 SCALP ALERTA — {now}\n\n"
        f"{c['symbol']} — {c['label']}\n\n"
        f"💰 Preço: ${c['price_usd']}\n"
        f"📊 VOL/MCAP: {c['vol_mcap_x']:.2f}x\n"
        f"⚡ 1h: {c['chg_1h']:+.1f}%\n"
        f"📈 24h: {c['chg_24h']:+.1f}%\n"
        f"📆 7d: {c['chg_7d']:+.1f}%\n"
        f"🧠 Score: {c['score']:.3f}\n\n"
        f"🎯 Leitura: fluxo recente com perfil de scalp\n"
        f"⚠️ Gestão: operação curta, sem casar com o trade"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Telegram raw HTTP
# ──────────────────────────────────────────────────────────────────────────────

def send_tg_raw(text: str) -> None:
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("[WARN] Telegram não configurado.", file=sys.stderr)
        return

    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": TG_CHAT_ID,
        "text": text,
    }).encode()

    req = urllib.request.Request(url, data=payload, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if result.get("ok"):
                print("[OK] Telegram enviado.", file=sys.stderr)
            else:
                print(f"[WARN] Telegram respondeu: {result.get('description', '')}", file=sys.stderr)
    except Exception as e:
        print(f"[ERR] Falha ao enviar Telegram: {e}", file=sys.stderr)


def send_alerts_if_needed(ranked: list[dict]) -> None:
    sent = 0
    for c in ranked:
        coin_id = c.get("coingecko_id", "")
        if not coin_id:
            continue
        if should_alert(c) and can_send_alert(coin_id):
            send_tg_raw(build_alert_message(c))
            sent += 1
            time.sleep(1)

    if sent:
        print(f"[INFO] Alertas enviados: {sent}", file=sys.stderr)
    else:
        print("[INFO] Nenhum alerta enviado neste ciclo.", file=sys.stderr)


# ──────────────────────────────────────────────────────────────────────────────
# Execução principal
# ──────────────────────────────────────────────────────────────────────────────

def run_once(top_n: int | None = None) -> list[dict]:
    global ultimo_ranking
    coins = fetch_all_coins()
    ranked = score_coins(coins, top_n=top_n)
    if ranked:
        ultimo_ranking = ranked
    return ranked


def loop_automatico() -> None:
    global loop_ativo, proximo_ciclo

    print(f"[INFO] Loop iniciado — intervalo {INTERVAL_SECONDS}s", file=sys.stderr)

    while True:
        if loop_ativo:
            try:
                ranked = run_once()
                if ranked:
                    if not SNIPER_ONLY and SEND_RANKING_EVERY_CYCLE:
                        send_tg_raw(format_tg(ranked))
                    send_alerts_if_needed(ranked)
                else:
                    print("[WARN] Nenhuma coin passou nos filtros.", file=sys.stderr)
            except Exception as e:
                print(f"[ERR] Erro no ciclo: {e}", file=sys.stderr)
        else:
            print("[INFO] Loop pausado.", file=sys.stderr)

        proximo_ciclo = datetime.fromtimestamp(time.time() + INTERVAL_SECONDS, tz=timezone.utc)
        time.sleep(INTERVAL_SECONDS)


# ──────────────────────────────────────────────────────────────────────────────
# Handlers Telegram
# ──────────────────────────────────────────────────────────────────────────────

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    texto = (
        "🤖 Comandos disponíveis:\n\n"
        "/ranking — Executa o ranking agora\n"
        "/top N   — Top N coins (ex: /top 5)\n"
        "/status  — Configurações e próximo ciclo\n"
        "/filtros — Filtros de triagem ativos\n"
        "/alertas — Regras dos alertas sniper\n"
        "/parar   — Pausa o loop automático\n"
        "/iniciar — Retoma o loop automático\n"
        "/help    — Esta mensagem"
    )
    await update.message.reply_text(texto)


async def cmd_ranking(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("⏳ Buscando dados... aguarde ~20–40s.")
    try:
        loop = asyncio.get_running_loop()
        ranked = await loop.run_in_executor(None, run_once, None)
        if ranked:
            await update.message.reply_text(format_tg(ranked))
        else:
            await update.message.reply_text("⚠️ Nenhuma coin passou nos filtros.")
    except Exception as e:
        await update.message.reply_text(f"❌ Erro: {e}")


async def cmd_top(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    args = ctx.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Uso: /top N  (ex: /top 5)")
        return

    n = max(1, min(int(args[0]), 50))
    await update.message.reply_text(f"⏳ Buscando top {n}... aguarde ~20–40s.")

    try:
        loop = asyncio.get_running_loop()
        ranked = await loop.run_in_executor(None, run_once, n)
        if ranked:
            await update.message.reply_text(format_tg(ranked))
        else:
            await update.message.reply_text("⚠️ Nenhuma coin passou nos filtros.")
    except Exception as e:
        await update.message.reply_text(f"❌ Erro: {e}")


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    estado = "▶️ Ativo" if loop_ativo else "⏸ Pausado"
    prox = proximo_ciclo.strftime("%d/%m %H:%M UTC") if proximo_ciclo else "—"
    ult_len = len(ultimo_ranking)

    texto = (
        f"⚙️ Status do bot\n\n"
        f"Loop automático: {estado}\n"
        f"Intervalo: {INTERVAL_SECONDS}s\n"
        f"Próximo ciclo: {prox}\n"
        f"Último ranking: {ult_len} coins\n\n"
        f"API tier: {CG_API_TIER.upper()}\n"
        f"FETCH_N: {FETCH_N}\n"
        f"TOP_SHOW: {TOP_SHOW}\n"
        f"SNIPER_ONLY: {'SIM' if SNIPER_ONLY else 'NÃO'}\n"
        f"SEND_RANKING_EVERY_CYCLE: {'SIM' if SEND_RANKING_EVERY_CYCLE else 'NÃO'}\n"
        f"Cooldown alerta: {ALERT_COOLDOWN_SECONDS}s"
    )
    await update.message.reply_text(texto)


async def cmd_filtros(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    def fmt_m(v: float) -> str:
        return f"${v/1e6:.0f}M" if v >= 1e6 else f"${v:,.0f}"

    texto = (
        f"🔍 Filtros ativos\n\n"
        f"MCAP mín:         {fmt_m(MIN_MCAP)}\n"
        f"MCAP máx:         {fmt_m(MAX_MCAP)}\n"
        f"VOL 24h mín:      {fmt_m(MIN_VOL24)}\n"
        f"VOL/MCAP mín:     {MIN_RATIO_X:.2f}x\n"
        f"Penaliza 24h >    {MAX_24H_FOR_ENTRY:.1f}%\n\n"
        f"Pesos do score:\n"
        f"  VOL/MCAP ratio: {W_RATIO:.0%}\n"
        f"  Momentum 1h:    {W_MOM_1H:.0%}\n"
        f"  Momentum 24h:   {W_MOM_24H:.0%}\n"
        f"  Momentum 7d:    {W_MOM_7D:.0%}\n\n"
        f"Blacklist: stablecoins, wrapped, xStock, alavancados"
    )
    await update.message.reply_text(texto)


async def cmd_alertas(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    texto = (
        f"🎯 Regras dos alertas sniper\n\n"
        f"SNIPER_ONLY: {'SIM' if SNIPER_ONLY else 'NÃO'}\n"
        f"Cooldown: {ALERT_COOLDOWN_SECONDS}s\n"
        f"Score mín: {ALERT_MIN_SCORE:.2f}\n"
        f"VOL/MCAP mín: {ALERT_MIN_RATIO_X:.2f}x\n"
        f"1h entre: {ALERT_MIN_1H:.1f}% e {ALERT_MAX_1H:.1f}%\n"
        f"24h máx para alerta: {ALERT_MAX_24H:.1f}%\n\n"
        f"Filtro anti-wash:\n"
        f"  Ratio hard max: {WASH_RATIO_HARD_MAX:.2f}x\n"
        f"  24h hard max: {WASH_24H_HARD_MAX:.1f}%\n"
        f"  Exigir 1h se ratio alto: {'SIM' if WASH_REQUIRE_1H_IF_HIGH_RATIO else 'NÃO'}"
    )
    await update.message.reply_text(texto)


async def cmd_parar(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    global loop_ativo
    loop_ativo = False
    await update.message.reply_text("⏸ Loop automático pausado. Use /iniciar para retomar.")


async def cmd_iniciar(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    global loop_ativo
    loop_ativo = True
    await update.message.reply_text("▶️ Loop automático retomado.")


# ──────────────────────────────────────────────────────────────────────────────
# Registro de comandos
# ──────────────────────────────────────────────────────────────────────────────

async def registrar_comandos(app: Application) -> None:
    await app.bot.set_my_commands([
        BotCommand("ranking", "Executa o ranking agora"),
        BotCommand("top", "Top N coins — ex: /top 5"),
        BotCommand("status", "Configurações e próximo ciclo"),
        BotCommand("filtros", "Filtros de triagem ativos"),
        BotCommand("alertas", "Mostra regras dos alertas sniper"),
        BotCommand("parar", "Pausa o loop automático"),
        BotCommand("iniciar", "Retoma o loop automático"),
        BotCommand("help", "Lista todos os comandos"),
    ])
    print("[OK] Comandos registrados.", file=sys.stderr)


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    if not TG_BOT_TOKEN:
        print("[ERR] TG_BOT_TOKEN não definido.", file=sys.stderr)
        sys.exit(1)

    import threading

    thread = threading.Thread(target=loop_automatico, daemon=True)
    thread.start()

    app = Application.builder().token(TG_BOT_TOKEN).build()

    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("ranking", cmd_ranking))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("filtros", cmd_filtros))
    app.add_handler(CommandHandler("alertas", cmd_alertas))
    app.add_handler(CommandHandler("parar", cmd_parar))
    app.add_handler(CommandHandler("iniciar", cmd_iniciar))

    app.post_init = registrar_comandos

    print("[INFO] Bot aguardando comandos (polling)...", file=sys.stderr)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

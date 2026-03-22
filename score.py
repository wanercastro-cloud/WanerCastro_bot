#!/usr/bin/env python3
"""
score.py — CoinGecko VOL/MCAP scorer com comandos interativos no Telegram.

Comandos disponíveis:
  /ranking         — Executa o ranking agora (aguarda processamento)
  /top N           — Retorna o top N coins (ex: /top 5)
  /status          — Mostra configurações atuais e próximo ciclo
  /filtros         — Lista os filtros de triagem ativos
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
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# ─── Configuração via variáveis de ambiente ───────────────────────────────────

CG_API_KEY      = os.getenv('CG_API_KEY', '')
CG_API_TIER     = os.getenv('CG_API_TIER', 'demo').lower()
MIN_MCAP        = float(os.getenv('MIN_MCAP',        '5000000'))
MAX_MCAP        = float(os.getenv('MAX_MCAP',        '2000000000'))
MIN_VOL24       = float(os.getenv('MIN_VOL24',       '3000000'))
TOP_SHOW        = int(os.getenv('TOP_SHOW',           '10'))
IMBALANCE_MAX   = float(os.getenv('IMBALANCE_MAX',   '500'))
FETCH_N         = int(os.getenv('FETCH_N',            '500'))
PER_PAGE        = 250
W_MOM_1H        = float(os.getenv('W_MOM_1H',        '0.10'))
W_MOM_24H       = float(os.getenv('W_MOM_24H',       '0.40'))
W_MOM_7D        = float(os.getenv('W_MOM_7D',        '0.15'))
W_RATIO         = float(os.getenv('W_RATIO',          '0.35'))
INTERVAL_SECONDS = int(os.getenv('INTERVAL_SECONDS', '14400'))
TG_BOT_TOKEN    = os.getenv('TG_BOT_TOKEN', '')
TG_CHAT_ID      = os.getenv('TG_CHAT_ID', '')

# ─── Estado global do loop automático ────────────────────────────────────────

loop_ativo = True
proximo_ciclo: datetime | None = None
ultimo_ranking: list = []

# ─── CoinGecko ───────────────────────────────────────────────────────────────

def base_url():
    if CG_API_TIER == 'paid' and CG_API_KEY:
        return 'https://pro-api.coingecko.com/api/v3'
    return 'https://api.coingecko.com/api/v3'

def make_headers():
    h = {'Accept': 'application/json', 'User-Agent': 'cg-scorer/2.1'}
    if CG_API_KEY:
        if CG_API_TIER == 'paid':
            h['x-cg-pro-api-key'] = CG_API_KEY
        else:
            h['x-cg-demo-api-key'] = CG_API_KEY
    return h

def fetch_markets(page):
    params = urllib.parse.urlencode({
        'vs_currency': 'usd',
        'order': 'volume_desc',
        'per_page': PER_PAGE,
        'page': page,
        'sparkline': 'false',
        'price_change_percentage': '1h,7d',
    })
    url = base_url() + '/coins/markets?' + params
    req = urllib.request.Request(url, headers=make_headers())
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 60 * (attempt + 1)
                print(f'[WARN] Rate limit - aguardando {wait}s...', file=sys.stderr)
                time.sleep(wait)
            else:
                print(f'[ERR] HTTP {e.code} pagina {page}: {e.reason}', file=sys.stderr)
                raise
        except Exception as e:
            print(f'[ERR] Tentativa {attempt+1} falhou: {e}', file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f'Falha pagina {page} apos 3 tentativas')

def fetch_all_coins():
    pages = math.ceil(FETCH_N / PER_PAGE)
    coins = []
    for page in range(1, pages + 1):
        print(f'[INFO] Pagina {page}/{pages}...', file=sys.stderr)
        batch = fetch_markets(page)
        if not batch:
            break
        coins.extend(batch)
        if len(coins) >= FETCH_N:
            break
        if page < pages:
            time.sleep(2)
    print(f'[INFO] Total: {len(coins)} coins', file=sys.stderr)
    return coins[:FETCH_N]

# ─── Blacklist / filtros ──────────────────────────────────────────────────────

BLACKLIST = {
    'usdt','usdc','busd','dai','tusd','usdp','usdd','frax','lusd','gusd',
    'susd','fdusd','pyusd','usde','crvusd','mkusd','cusd','zusd','usdq',
    'usdr','usds','musd','husd','ousd','usda','usdb','u',
    'eurs','eurq','eurt','eure','steur','ageur','eurc',
    'eur','gbp','jpy','cny','krw','brl','try','cad','sgd','chf',
    'wbtc','weth','steth','cbeth','reth','wsteth','weeth','ezeth','rseth',
    'lseth','ankreth','sweth','oseth','meth','wbeth','sfrxeth',
    'paxg','xaut','cache','pmgt','dgld',
    'hoodx','amznx','aaplx','nvdax','tslax','msfx','metax','googx',
    'spyx','qqqx','coinx','arkx','mstrx','nflxx','amdx','intcx',
}
BLACKLIST_KW = ['leveraged','2x long','3x long','bear token','bull token','xstock','wrapped ','staked ']
XSTOCK_RE    = re.compile(r'^[A-Z]{2,5}X$')

def safe_float(val, default=0.0):
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default

def is_stable(coin):
    price = safe_float(coin.get('current_price'))
    chg   = abs(safe_float(coin.get('price_change_percentage_24h')))
    return 0.90 <= price <= 1.15 and chg < 0.5

def is_bad(coin):
    sym  = coin.get('symbol', '').lower()
    name = coin.get('name', '').lower()
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

# ─── Scoring ──────────────────────────────────────────────────────────────────

def normalize(vals):
    clean = [v for v in vals if not math.isnan(v)]
    if not clean:
        return [0.0] * len(vals)
    lo, hi = min(clean), max(clean)
    if hi == lo:
        return [0.5] * len(vals)
    return [(v - lo) / (hi - lo) for v in vals]

def score_coins(coins, top_n=None):
    if top_n is None:
        top_n = TOP_SHOW
    filtered = []
    for c in coins:
        if is_bad(c):
            continue
        mcap = safe_float(c.get('market_cap'))
        vol  = safe_float(c.get('total_volume'))
        if not (MIN_MCAP <= mcap <= MAX_MCAP):
            continue
        if vol < MIN_VOL24:
            continue
        ratio = (vol / mcap * 100) if mcap > 0 else 0
        if ratio > IMBALANCE_MAX:
            continue
        c['_ratio'] = ratio
        filtered.append(c)

    print(f'[INFO] Passaram: {len(filtered)}', file=sys.stderr)
    if not filtered:
        return []

    nr  = normalize([c['_ratio'] for c in filtered])
    n1  = normalize([safe_float(c.get('price_change_percentage_1h_in_currency'))  for c in filtered])
    n24 = normalize([safe_float(c.get('price_change_percentage_24h'))              for c in filtered])
    n7  = normalize([safe_float(c.get('price_change_percentage_7d_in_currency'))   for c in filtered])

    for i, c in enumerate(filtered):
        c['_score'] = W_RATIO*nr[i] + W_MOM_1H*n1[i] + W_MOM_24H*n24[i] + W_MOM_7D*n7[i]

    ranked = sorted(filtered, key=lambda x: x['_score'], reverse=True)[:top_n]
    result = []
    for rank, c in enumerate(ranked, 1):
        result.append({
            'rank':         rank,
            'symbol':       c.get('symbol', '').upper(),
            'name':         c.get('name', ''),
            'price_usd':    round(safe_float(c.get('current_price')), 6),
            'mcap_m':       round(safe_float(c.get('market_cap'))    / 1e6, 1),
            'vol24_m':      round(safe_float(c.get('total_volume'))  / 1e6, 1),
            'vol_mcap_x':   round(c['_ratio'] / 100, 2),
            'chg_1h':       round(safe_float(c.get('price_change_percentage_1h_in_currency')), 2),
            'chg_24h':      round(safe_float(c.get('price_change_percentage_24h')), 2),
            'chg_7d':       round(safe_float(c.get('price_change_percentage_7d_in_currency')), 2),
            'score':        round(c['_score'], 4),
            'coingecko_id': c.get('id', ''),
        })
    return result

# ─── Formatação ───────────────────────────────────────────────────────────────

def format_tg(ranked):
    now = datetime.now(timezone.utc).strftime('%d/%m %H:%M UTC')
    lines = [f'📊 Ranking VOL/MCAP + MOM — {now}\n']
    for c in ranked:
        lines.append(
            f"{c['rank']:02d}. {c['symbol']} — score {c['score']:.3f}\n"
            f"   VOL/MCAP: {c['vol_mcap_x']:.2f}x | "
            f"1h:{c['chg_1h']:+.1f}% 24h:{c['chg_24h']:+.1f}% 7d:{c['chg_7d']:+.1f}%\n"
            f"   ${c['price_usd']} | MCAP ${c['mcap_m']}M | VOL ${c['vol24_m']}M"
        )
    return '\n\n'.join(lines)

# ─── Envio Telegram (raw HTTP, para uso no loop síncrono) ────────────────────

def send_tg_raw(text):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print('[WARN] Telegram nao configurado.', file=sys.stderr)
        return
    url  = f'https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage'
    data = urllib.parse.urlencode({'chat_id': TG_CHAT_ID, 'text': text}).encode()
    req  = urllib.request.Request(url, data=data, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            r = json.loads(resp.read())
            if r.get('ok'):
                print('[OK] Telegram enviado.', file=sys.stderr)
            else:
                print(f"[WARN] Telegram: {r.get('description', '')}", file=sys.stderr)
    except Exception as e:
        print(f'[ERR] Telegram: {e}', file=sys.stderr)

# ─── Loop automático (roda em thread separada) ────────────────────────────────

def run_once(top_n=None):
    """Busca dados, faz o ranking e retorna (ranked, texto_tg)."""
    global ultimo_ranking
    coins  = fetch_all_coins()
    ranked = score_coins(coins, top_n=top_n)
    if ranked:
        ultimo_ranking = ranked
    return ranked

def loop_automatico():
    """Loop síncrono que roda em thread paralela ao bot."""
    global loop_ativo, proximo_ciclo
    print(f'[INFO] Loop iniciado — intervalo {INTERVAL_SECONDS}s', file=sys.stderr)
    while True:
        if loop_ativo:
            try:
                ranked = run_once()
                if ranked:
                    send_tg_raw(format_tg(ranked))
                else:
                    print('[WARN] Nenhum coin passou.', file=sys.stderr)
            except Exception as e:
                print(f'[ERR] Ciclo: {e}', file=sys.stderr)
        else:
            print('[INFO] Loop pausado, aguardando...', file=sys.stderr)

        proximo_ciclo = datetime.fromtimestamp(
            time.time() + INTERVAL_SECONDS, tz=timezone.utc
        )
        time.sleep(INTERVAL_SECONDS)

# ─── Handlers de comandos Telegram ───────────────────────────────────────────

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    texto = (
        "🤖 Comandos disponíveis:\n\n"
        "/ranking — Executa o ranking agora\n"
        "/top N   — Top N coins (ex: /top 5)\n"
        "/status  — Configurações e próximo ciclo\n"
        "/filtros — Filtros de triagem ativos\n"
        "/parar   — Pausa o loop automático\n"
        "/iniciar — Retoma o loop automático\n"
        "/help    — Esta mensagem"
    )
    await update.message.reply_text(texto)

async def cmd_ranking(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Buscando dados... aguarde ~30s.")
    try:
        loop = asyncio.get_event_loop()
        ranked = await loop.run_in_executor(None, run_once, None)
        if ranked:
            await update.message.reply_text(format_tg(ranked))
        else:
            await update.message.reply_text("⚠️ Nenhum coin passou nos filtros.")
    except Exception as e:
        await update.message.reply_text(f"❌ Erro: {e}")

async def cmd_top(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Uso: /top N  (ex: /top 5)")
        return
    n = max(1, min(int(args[0]), 50))
    await update.message.reply_text(f"⏳ Buscando top {n}... aguarde ~30s.")
    try:
        loop = asyncio.get_event_loop()
        ranked = await loop.run_in_executor(None, run_once, n)
        if ranked:
            await update.message.reply_text(format_tg(ranked))
        else:
            await update.message.reply_text("⚠️ Nenhum coin passou nos filtros.")
    except Exception as e:
        await update.message.reply_text(f"❌ Erro: {e}")

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global loop_ativo, proximo_ciclo, ultimo_ranking
    estado  = "▶️ Ativo" if loop_ativo else "⏸ Pausado"
    prox    = proximo_ciclo.strftime('%d/%m %H:%M UTC') if proximo_ciclo else "—"
    ult_len = len(ultimo_ranking)
    texto = (
        f"⚙️ Status do bot\n\n"
        f"Loop automático: {estado}\n"
        f"Intervalo: {INTERVAL_SECONDS}s ({INTERVAL_SECONDS//3600}h)\n"
        f"Próximo ciclo: {prox}\n"
        f"Último ranking: {ult_len} coins\n\n"
        f"TOP_SHOW: {TOP_SHOW}\n"
        f"FETCH_N: {FETCH_N}\n"
        f"API tier: {CG_API_TIER.upper()}"
    )
    await update.message.reply_text(texto)

async def cmd_filtros(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    def fmt_m(v):
        return f"${v/1e6:.0f}M" if v >= 1e6 else f"${v:,.0f}"

    texto = (
        f"🔍 Filtros ativos\n\n"
        f"MCAP mín:     {fmt_m(MIN_MCAP)}\n"
        f"MCAP máx:     {fmt_m(MAX_MCAP)}\n"
        f"VOL 24h mín:  {fmt_m(MIN_VOL24)}\n"
        f"VOL/MCAP máx: {IMBALANCE_MAX:.0f}%\n\n"
        f"Pesos do score:\n"
        f"  VOL/MCAP ratio: {W_RATIO:.0%}\n"
        f"  Momentum 1h:    {W_MOM_1H:.0%}\n"
        f"  Momentum 24h:   {W_MOM_24H:.0%}\n"
        f"  Momentum 7d:    {W_MOM_7D:.0%}\n\n"
        f"Blacklist: stablecoins, wrapped, xStock, alavancados"
    )
    await update.message.reply_text(texto)

async def cmd_parar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global loop_ativo
    loop_ativo = False
    await update.message.reply_text("⏸ Loop automático pausado. Use /iniciar para retomar.")

async def cmd_iniciar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global loop_ativo
    loop_ativo = True
    await update.message.reply_text("▶️ Loop automático retomado.")

# ─── Registro dos comandos no BotFather ──────────────────────────────────────

async def registrar_comandos(app: Application):
    await app.bot.set_my_commands([
        BotCommand("ranking", "Executa o ranking agora"),
        BotCommand("top",     "Top N coins — ex: /top 5"),
        BotCommand("status",  "Configurações e próximo ciclo"),
        BotCommand("filtros", "Filtros de triagem ativos"),
        BotCommand("parar",   "Pausa o loop automático"),
        BotCommand("iniciar", "Retoma o loop automático"),
        BotCommand("help",    "Lista todos os comandos"),
    ])
    print('[OK] Comandos registrados no BotFather.', file=sys.stderr)

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    if not TG_BOT_TOKEN:
        print('[ERR] TG_BOT_TOKEN não definido.', file=sys.stderr)
        sys.exit(1)

    # Inicia o loop automático em thread separada
    import threading
    t = threading.Thread(target=loop_automatico, daemon=True)
    t.start()

    # Constrói e configura o bot
    app = Application.builder().token(TG_BOT_TOKEN).build()

    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("ranking", cmd_ranking))
    app.add_handler(CommandHandler("top",     cmd_top))
    app.add_handler(CommandHandler("status",  cmd_status))
    app.add_handler(CommandHandler("filtros", cmd_filtros))
    app.add_handler(CommandHandler("parar",   cmd_parar))
    app.add_handler(CommandHandler("iniciar", cmd_iniciar))

    # Registra comandos no BotFather ao iniciar
    app.post_init = registrar_comandos

    print('[INFO] Bot aguardando comandos (polling)...', file=sys.stderr)
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()

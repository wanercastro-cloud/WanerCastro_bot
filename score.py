#!/usr/bin/env python3
import sys
import json
import os
import math
import re
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone

CG_API_KEY = os.getenv('CG_API_KEY', '')
CG_API_TIER = os.getenv('CG_API_TIER', 'demo').lower()
MIN_MCAP = float(os.getenv('MIN_MCAP', '5000000'))
MAX_MCAP = float(os.getenv('MAX_MCAP', '2000000000'))
MIN_VOL24 = float(os.getenv('MIN_VOL24', '3000000'))
TOP_SHOW = int(os.getenv('TOP_SHOW', '10'))
IMBALANCE_MAX = float(os.getenv('IMBALANCE_MAX', '500'))
FETCH_N = int(os.getenv('FETCH_N', '500'))
PER_PAGE = 250
W_MOM_1H = float(os.getenv('W_MOM_1H', '0.10'))
W_MOM_24H = float(os.getenv('W_MOM_24H', '0.40'))
W_MOM_7D = float(os.getenv('W_MOM_7D', '0.15'))
W_RATIO = float(os.getenv('W_RATIO', '0.35'))
INTERVAL_SECONDS = int(os.getenv('INTERVAL_SECONDS', '14400'))
TG_BOT_TOKEN = os.getenv('TG_BOT_TOKEN', '')
TG_CHAT_ID = os.getenv('TG_CHAT_ID', '')

def base_url():
    if CG_API_TIER == 'paid' and CG_API_KEY:
        return 'https://pro-api.coingecko.com/api/v3'
    return 'https://api.coingecko.com/api/v3'

def make_headers():
    h = {'Accept': 'application/json', 'User-Agent': 'cg-scorer/2.0'}
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
                print('[WARN] Rate limit - aguardando {}s...'.format(wait), file=sys.stderr)
                time.sleep(wait)
            else:
                print('[ERR] HTTP {} pagina {}: {}'.format(e.code, page, e.reason), file=sys.stderr)
                raise
        except Exception as e:
            print('[ERR] Tentativa {} falhou: {}'.format(attempt + 1, e), file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError('Falha pagina {} apos 3 tentativas'.format(page))

def fetch_all_coins():
    pages = math.ceil(FETCH_N / PER_PAGE)
    coins = []
    for page in range(1, pages + 1):
        print('[INFO] Pagina {}/{}...'.format(page, pages), file=sys.stderr)
        batch = fetch_markets(page)
        if not batch:
            break
        coins.extend(batch)
        if len(coins) >= FETCH_N:
            break
        if page < pages:
            time.sleep(2)
    print('[INFO] Total: {} coins'.format(len(coins)), file=sys.stderr)
    return coins[:FETCH_N]

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
XSTOCK_RE = re.compile(r'^[A-Z]{2,5}X$')

def safe_float(val, default=0.0):
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default

def is_stable(coin):
    price = safe_float(coin.get('current_price'))
    chg = abs(safe_float(coin.get('price_change_percentage_24h')))
    return 0.90 <= price <= 1.15 and chg < 0.5

def is_bad(coin):
    sym = coin.get('symbol', '').lower()
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

def normalize(vals):
    clean = [v for v in vals if not math.isnan(v)]
    if not clean:
        return [0.0] * len(vals)
    lo, hi = min(clean), max(clean)
    if hi == lo:
        return [0.5] * len(vals)
    return [(v - lo) / (hi - lo) for v in vals]

def score_coins(coins):
    filtered = []
    for c in coins:
        if is_bad(c):
            continue
        mcap = safe_float(c.get('market_cap'))
        vol = safe_float(c.get('total_volume'))
        if not (MIN_MCAP <= mcap <= MAX_MCAP):
            continue
        if vol < MIN_VOL24:
            continue
        ratio = (vol / mcap * 100) if mcap > 0 else 0
        if ratio > IMBALANCE_MAX:
            continue
        c['_ratio'] = ratio
        filtered.append(c)

    print('[INFO] Passaram: {}'.format(len(filtered)), file=sys.stderr)
    if not filtered:
        return []

    nr = normalize([c['_ratio'] for c in filtered])
    n1 = normalize([safe_float(c.get('price_change_percentage_1h_in_currency')) for c in filtered])
    n24 = normalize([safe_float(c.get('price_change_percentage_24h')) for c in filtered])
    n7 = normalize([safe_float(c.get('price_change_percentage_7d_in_currency')) for c in filtered])

    for i, c in enumerate(filtered):
        c['_score'] = W_RATIO*nr[i] + W_MOM_1H*n1[i] + W_MOM_24H*n24[i] + W_MOM_7D*n7[i]

    ranked = sorted(filtered, key=lambda x: x['_score'], reverse=True)[:TOP_SHOW]
    result = []
    for rank, c in enumerate(ranked, 1):
        result.append({
            'rank': rank,
            'symbol': c.get('symbol', '').upper(),
            'name': c.get('name', ''),
            'price_usd': round(safe_float(c.get('current_price')), 6),
            'mcap_m': round(safe_float(c.get('market_cap')) / 1e6, 1),
            'vol24_m': round(safe_float(c.get('total_volume')) / 1e6, 1),
            'vol_mcap_x': round(c['_ratio'] / 100, 2),
            'chg_1h': round(safe_float(c.get('price_change_percentage_1h_in_currency')), 2),
            'chg_24h': round(safe_float(c.get('price_change_percentage_24h')), 2),
            'chg_7d': round(safe_float(c.get('price_change_percentage_7d_in_currency')), 2),
            'score': round(c['_score'], 4),
            'coingecko_id': c.get('id', ''),
        })
    return result

def format_tg(ranked):
    now = datetime.now(timezone.utc).strftime('%d/%m %H:%M UTC')
    lines = ['Ranking VOL/MCAP + MOM - ' + now + '\n']
    for c in ranked:
        lines.append(
            '{:02d}. {} - score {:.3f}\n'.format(c['rank'], c['symbol'], c['score']) +
            '   VOL/MCAP: {:.2f}x | 1h:{:+.1f}% 24h:{:+.1f}% 7d:{:+.1f}%\n'.format(
                c['vol_mcap_x'], c['chg_1h'], c['chg_24h'], c['chg_7d']) +
            '   ${} | MCAP ${}M | VOL ${}M\n'.format(c['price_usd'], c['mcap_m'], c['vol24_m'])
        )
    return '\n'.join(lines)

def send_tg(text):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print('[WARN] Telegram nao configurado.', file=sys.stderr)
        return
    url = 'https://api.telegram.org/bot' + TG_BOT_TOKEN + '/sendMessage'
    data = urllib.parse.urlencode({'chat_id': TG_CHAT_ID, 'text': text}).encode()
    req = urllib.request.Request(url, data=data, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            r = json.loads(resp.read())
            if r.get('ok'):
                print('[OK] Telegram enviado.', file=sys.stderr)
            else:
                print('[WARN] Telegram: {}'.format(r.get('description', '')), file=sys.stderr)
    except Exception as e:
        print('[ERR] Telegram: {}'.format(e), file=sys.stderr)

def run_once():
    coins = fetch_all_coins()
    ranked = score_coins(coins)
    if not ranked:
        print('[WARN] Nenhum coin passou.', file=sys.stderr)
        return
    print('[INFO] Top {} no ranking.'.format(len(ranked)), file=sys.stderr)
    print(json.dumps(ranked, indent=2, ensure_ascii=False))
    send_tg(format_tg(ranked))

def main():
    print('[INFO] Iniciando - intervalo {}s'.format(INTERVAL_SECONDS), file=sys.stderr)
    while True:
        try:
            run_once()
        except Exception as e:
            print('[ERR] Ciclo: {}'.format(e), file=sys.stderr)
        time.sleep(INTERVAL_SECONDS)

if __name__ == '__main__':
    main()

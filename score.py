#!/usr/bin/env python3
“””
CoinGecko Scorer — autossuficiente
Busca dados direto da API CoinGecko, aplica scoring VOL/MCAP + Momentum e envia ao Telegram.
Zero dependências externas — usa apenas stdlib Python 3.9+
“””

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

# ── Configuração via variáveis de ambiente ─────────────────────────────────────

CG_API_KEY    = os.getenv(“CG_API_KEY”, “”)
CG_API_TIER   = os.getenv(“CG_API_TIER”, “demo”).lower()  # demo | paid

MIN_MCAP      = float(os.getenv(“MIN_MCAP”,      “10000000”))
MAX_MCAP      = float(os.getenv(“MAX_MCAP”,      “2000000000”))
MIN_VOL24     = float(os.getenv(“MIN_VOL24”,     “3000000”))
TOP_SHOW      = int(os.getenv(“TOP_SHOW”,        “10”))
IMBALANCE_MAX = float(os.getenv(“IMBALANCE_MAX”, “300”))   # VOL/MCAP% máx (3x)
FETCH_N       = int(os.getenv(“FETCH_N”,         “500”))   # coins a buscar
PER_PAGE      = 250                                         # máx da API CoinGecko

W_MOM_1H  = float(os.getenv(“W_MOM_1H”,  “0.10”))
W_MOM_24H = float(os.getenv(“W_MOM_24H”, “0.40”))
W_MOM_7D  = float(os.getenv(“W_MOM_7D”,  “0.15”))
W_RATIO   = float(os.getenv(“W_RATIO”,   “0.35”))

TG_BOT_TOKEN = os.getenv(“TG_BOT_TOKEN”, “”)
TG_CHAT_ID   = os.getenv(“TG_CHAT_ID”,   “”)

# ── API CoinGecko ──────────────────────────────────────────────────────────────

def _base_url():
if CG_API_TIER == “paid” and CG_API_KEY:
return “https://pro-api.coingecko.com/api/v3”
return “https://api.coingecko.com/api/v3”

def _headers():
h = {“Accept”: “application/json”, “User-Agent”: “cg-scorer/2.0”}
if CG_API_KEY:
key_header = “x-cg-pro-api-key” if CG_API_TIER == “paid” else “x-cg-demo-api-key”
h[key_header] = CG_API_KEY
return h

def fetch_markets(page: int) -> list:
params = urllib.parse.urlencode({
“vs_currency”:              “usd”,
“order”:                    “volume_desc”,
“per_page”:                 PER_PAGE,
“page”:                     page,
“sparkline”:                “false”,
“price_change_percentage”:  “1h,7d”,  # 24h já vem por padrão
})
url = f”{_base_url()}/coins/markets?{params}”
req = urllib.request.Request(url, headers=_headers())

```
for attempt in range(3):
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 429:
            wait = 60 * (attempt + 1)
            print(f"[WARN] Rate limit (429) — aguardando {wait}s...", file=sys.stderr)
            time.sleep(wait)
        else:
            print(f"[ERR] HTTP {e.code} na página {page}: {e.reason}", file=sys.stderr)
            raise
    except Exception as e:
        print(f"[ERR] Tentativa {attempt+1} falhou: {e}", file=sys.stderr)
        time.sleep(5 * (attempt + 1))

raise RuntimeError(f"Falha ao buscar página {page} após 3 tentativas")
```

def fetch_all_coins() -> list:
pages  = math.ceil(FETCH_N / PER_PAGE)
coins  = []
for page in range(1, pages + 1):
print(f”[INFO] Buscando página {page}/{pages}…”, file=sys.stderr)
batch = fetch_markets(page)
if not batch:
break
coins.extend(batch)
if len(coins) >= FETCH_N:
break
if page < pages:
time.sleep(1.5)  # respeita rate limit Demo (30 req/min)
print(f”[INFO] Total recebido: {len(coins)} coins”, file=sys.stderr)
return coins[:FETCH_N]

# ── Blacklist ──────────────────────────────────────────────────────────────────

BLACKLIST_SYMBOLS = {
“usdt”,“usdc”,“busd”,“dai”,“tusd”,“usdp”,“usdd”,“frax”,“lusd”,“gusd”,
“susd”,“fdusd”,“pyusd”,“usde”,“crvusd”,“mkusd”,“cusd”,“zusd”,“usdq”,
“usdr”,“usds”,“musd”,“husd”,“ousd”,“usd+”,“usda”,“usdb”,
“u”,
“eurs”,“eurq”,“eurt”,“eure”,“steur”,“ageur”,“eurc”,
“eur”,“gbp”,“jpy”,“cny”,“krw”,“brl”,“try”,“cad”,“sgd”,“chf”,
“wbtc”,“weth”,“steth”,“cbeth”,“reth”,“wsteth”,“weeth”,“ezeth”,“rseth”,
“lseth”,“ankreth”,“sweth”,“oseth”,“meth”,“wbeth”,“sfrxeth”,
“apxeth”,“unieth”,“pufeth”,“ineth”,“amphreth”,
“paxg”,“xaut”,“cache”,“pmgt”,“dgld”,
“hoodx”,“amznx”,“aaplx”,“nvdax”,“tslax”,“msfx”,“metax”,“googx”,
“spyx”,“qqqx”,“coinx”,“arkx”,“mstrx”,“nflxx”,“amdx”,“intcx”,
}

BLACKLIST_CONTAINS = [
“leveraged”,“2x long”,“3x long”,“2x short”,“3x short”,
“bear token”,“bull token”,“xstock”,“x stock”,“wrapped “,“staked “,
]

_XSTOCK_RE = re.compile(r’^[A-Z]{2,5}X$’)

def is_stablecoin(coin: dict) -> bool:
price = safe_float(coin.get(“current_price”))
chg24 = abs(safe_float(coin.get(“price_change_percentage_24h”)))
if 0.90 <= price <= 1.15 and chg24 < 0.5:
return True
return False

def is_blacklisted(coin: dict) -> bool:
symbol = coin.get(“symbol”, “”).lower()
name   = coin.get(“name”,   “”).lower()
if symbol in BLACKLIST_SYMBOLS:
return True
for kw in BLACKLIST_CONTAINS:
if kw in symbol or kw in name:
return True
if _XSTOCK_RE.match(symbol.upper()):
return True
if is_stablecoin(coin):
return True
return False

# ── Scoring ────────────────────────────────────────────────────────────────────

def safe_float(val, default=0.0):
try:
return float(val) if val is not None else default
except (TypeError, ValueError):
return default

def normalize(values: list) -> list:
valid = [v for v in values if not math.isnan(v)]
if not valid:
return [0.0] * len(values)
lo, hi = min(valid), max(valid)
if hi == lo:
return [0.5] * len(values)
return [(v - lo) / (hi - lo) for v in values]

def score_coins(coins: list) -> list:
filtered = []
skipped  = {“stablecoin”: 0, “blacklist”: 0, “mcap”: 0, “vol”: 0, “imbalance”: 0}

```
for c in coins:
    if is_blacklisted(c):
        skipped["stablecoin" if is_stablecoin(c) else "blacklist"] += 1
        continue
    mcap  = safe_float(c.get("market_cap"))
    vol24 = safe_float(c.get("total_volume"))
    if not (MIN_MCAP <= mcap <= MAX_MCAP):
        skipped["mcap"] += 1
        continue
    if vol24 < MIN_VOL24:
        skipped["vol"] += 1
        continue
    ratio = (vol24 / mcap * 100) if mcap > 0 else 0
    if ratio > IMBALANCE_MAX:
        skipped["imbalance"] += 1
        continue
    c["_ratio"] = ratio
    filtered.append(c)

print(f"[INFO] Passaram: {len(filtered)} | Removidos — "
      f"stable:{skipped['stablecoin']} blacklist:{skipped['blacklist']} "
      f"mcap:{skipped['mcap']} vol:{skipped['vol']} imbalance:{skipped['imbalance']}",
      file=sys.stderr)

if not filtered:
    return []

ratios = [c["_ratio"] for c in filtered]
m1h    = [safe_float(c.get("price_change_percentage_1h_in_currency"))  for c in filtered]
m24h   = [safe_float(c.get("price_change_percentage_24h"))             for c in filtered]
m7d    = [safe_float(c.get("price_change_percentage_7d_in_currency"))  for c in filtered]

n_ratio = normalize(ratios)
n_1h    = normalize(m1h)
n_24h   = normalize(m24h)
n_7d    = normalize(m7d)

for i, c in enumerate(filtered):
    c["_score"] = (
        W_RATIO   * n_ratio[i] +
        W_MOM_1H  * n_1h[i]   +
        W_MOM_24H * n_24h[i]  +
        W_MOM_7D  * n_7d[i]
    )

ranked = sorted(filtered, key=lambda x: x["_score"], reverse=True)[:TOP_SHOW]

result = []
for rank, c in enumerate(ranked, 1):
    result.append({
        "rank":         rank,
        "symbol":       c.get("symbol", "").upper(),
        "name":         c.get("name", ""),
        "price_usd":    round(safe_float(c.get("current_price")), 6),
        "mcap_m":       round(safe_float(c.get("market_cap")) / 1e6, 1),
        "vol24_m":      round(safe_float(c.get("total_volume")) / 1e6, 1),
        "vol_mcap_x":   round(c["_ratio"] / 100, 2),
        "chg_1h":       round(safe_float(c.get("price_change_percentage_1h_in_currency")), 2),
        "chg_24h":      round(safe_float(c.get("price_change_percentage_24h")), 2),
        "chg_7d":       round(safe_float(c.get("price_change_percentage_7d_in_currency")), 2),
        "score":        round(c["_score"], 4),
        "coingecko_id": c.get("id", ""),
    })
return result
```

# ── Telegram ───────────────────────────────────────────────────────────────────

def format_telegram(ranked: list) -> str:
now = datetime.now(timezone.utc).strftime(”%d/%m %H:%M UTC”)
lines = [f”📊 *Ranking VOL/MCAP + MOM* — {now}\n”]
for c in ranked:
lines.append(
f”*{c[‘rank’]:02d}. {c[‘symbol’]}* — score `{c['score']:.3f}`\n”
f”   📈 VOL/MCAP: `{c['vol_mcap_x']:.2f}x` | “
f”1h:{c[‘chg_1h’]:+.1f}% 24h:{c[‘chg_24h’]:+.1f}% 7d:{c[‘chg_7d’]:+.1f}%\n”
f”   💰 ${c[‘price_usd’]} | MCAP ${c[‘mcap_m’]}M | VOL ${c[‘vol24_m’]}M\n”
)
lines.append(
f”*MCAP ${MIN_MCAP/1e6:.0f}M–${MAX_MCAP/1e6:.0f}M | “
f”VOL24 ≥${MIN_VOL24/1e6:.0f}M | “
f”W: ratio={W_RATIO} 1h={W_MOM_1H} 24h={W_MOM_24H} 7d={W_MOM_7D}*”
)
return “\n”.join(lines)

def send_telegram(text: str):
if not TG_BOT_TOKEN or not TG_CHAT_ID:
print(”[WARN] TG_BOT_TOKEN ou TG_CHAT_ID não configurados.”, file=sys.stderr)
return
url  = f”https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage”
data = urllib.parse.urlencode({
“chat_id”:    TG_CHAT_ID,
“text”:       text,
“parse_mode”: “Markdown”,
}).encode()
req = urllib.request.Request(url, data=data, method=“POST”)
try:
with urllib.request.urlopen(req, timeout=10) as resp:
result = json.loads(resp.read())
if result.get(“ok”):
print(”[OK] Ranking enviado ao Telegram.”, file=sys.stderr)
else:
print(f”[WARN] Telegram erro: {result.get(‘description’,’’)}”, file=sys.stderr)
except Exception as e:
print(f”[ERR] Falha Telegram: {e}”, file=sys.stderr)

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
if not CG_API_KEY:
print(”[WARN] CG_API_KEY não definida — usando API pública sem autenticação.”, file=sys.stderr)

```
coins  = fetch_all_coins()
ranked = score_coins(coins)

if not ranked:
    print("[WARN] Nenhum coin passou pelos filtros.", file=sys.stderr)
    sys.exit(0)

print(f"[INFO] Top {len(ranked)} coins no ranking final.", file=sys.stderr)
print(json.dumps(ranked, indent=2, ensure_ascii=False))
send_telegram(format_telegram(ranked))
```

if **name** == “**main**”:
main()
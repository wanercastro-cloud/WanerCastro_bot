#!/usr/bin/env python3
“””
CoinGecko CLI Scorer v2
Lê JSON do `cg markets` e aplica scoring VOL24/MCAP + Momentum ponderado.
Saída: JSON ranqueado + envio automático ao Telegram.
“””

import sys
import json
import os
import math
import re
import urllib.request
import urllib.parse
from datetime import datetime, timezone

# ── Configuração via variáveis de ambiente ─────────────────────────────────────

MIN_MCAP      = float(os.getenv(“MIN_MCAP”,      “10000000”))   # 10M USD
MAX_MCAP      = float(os.getenv(“MAX_MCAP”,      “2000000000”)) # 2B USD
MIN_VOL24     = float(os.getenv(“MIN_VOL24”,     “3000000”))    # 3M USD
TOP_SHOW      = int(os.getenv(“TOP_SHOW”,        “10”))         # coins no ranking final
IMBALANCE_MAX = float(os.getenv(“IMBALANCE_MAX”, “300”))        # VOL/MCAP% máx (3x)

# Pesos — soma = 1.0 — 24H recebe maior peso

W_MOM_1H  = float(os.getenv(“W_MOM_1H”,  “0.10”))
W_MOM_24H = float(os.getenv(“W_MOM_24H”, “0.40”))
W_MOM_7D  = float(os.getenv(“W_MOM_7D”,  “0.15”))
W_RATIO   = float(os.getenv(“W_RATIO”,   “0.35”))

# Telegram

TG_BOT_TOKEN = os.getenv(“TG_BOT_TOKEN”, “”)
TG_CHAT_ID   = os.getenv(“TG_CHAT_ID”,   “”)

# ── Blacklist ──────────────────────────────────────────────────────────────────

# 1. Símbolos exatos (lowercase)

BLACKLIST_SYMBOLS = {
# Stablecoins USD
“usdt”,“usdc”,“busd”,“dai”,“tusd”,“usdp”,“usdd”,“frax”,“lusd”,“gusd”,
“susd”,“fdusd”,“pyusd”,“usde”,“crvusd”,“mkusd”,“cusd”,“zusd”,“usdq”,
“usdr”,“usds”,“musd”,“husd”,“ousd”,“usd+”,“usda”,“usdb”,
“u”,  # United Stables — símbolo de 1 char
# Stablecoins EUR / outras fiat
“eurs”,“eurq”,“eurt”,“eure”,“steur”,“ageur”,“eurc”,
“eur”,“gbp”,“jpy”,“cny”,“krw”,“brl”,“try”,“cad”,“sgd”,“chf”,
# Wrapped / LST / LRT
“wbtc”,“weth”,“steth”,“cbeth”,“reth”,“wsteth”,“weeth”,“ezeth”,“rseth”,
“lseth”,“ankreth”,“sweth”,“oseth”,“meth”,“wbeth”,“sfrxeth”,
“apxeth”,“unieth”,“pufeth”,“ineth”,“amphreth”,
# Commodities tokenizadas
“paxg”,“xaut”,“cache”,“pmgt”,“dgld”,
# xStocks conhecidos
“hoodx”,“amznx”,“aaplx”,“nvdax”,“tslax”,“msfx”,“metax”,“googx”,
“spyx”,“qqqx”,“coinx”,“arkx”,“mstrx”,“nflxx”,“amdx”,“intcx”,
}

# 2. Substrings no símbolo ou nome (lowercase)

BLACKLIST_CONTAINS = [
“leveraged”, “2x long”, “3x long”, “2x short”, “3x short”,
“bear token”, “bull token”,
“xstock”, “x stock”,
“wrapped “,
“staked “,
“ turbo”, “ ultra”,
“usd coin”, “tether”,
]

# 3. Padrão regex: xStocks — símbolo terminando em X precedido de 2-5 letras maiúsculas

# Ex: HOODX, AMZNX, AAPLX, NVDAX, TSLAX, METAX

_XSTOCK_RE = re.compile(r’^[A-Z]{2,5}X$’)

# ── Funções auxiliares ─────────────────────────────────────────────────────────

def safe_float(val, default=0.0):
try:
return float(val) if val is not None else default
except (TypeError, ValueError):
return default

def is_xstock(symbol: str) -> bool:
“”“Detecta padrão xStock: 2-5 letras + X final (ex: HOODX, AMZNX).”””
return bool(_XSTOCK_RE.match(symbol.upper()))

def is_stablecoin(coin: dict) -> bool:
“”“Detecta stablecoins por volatilidade: se |chg_24h| < 0.5% e preço ~1 USD.”””
price = safe_float(coin.get(“current_price”))
chg24 = abs(safe_float(coin.get(“price_change_percentage_24h”)))
# Preço entre 0.95 e 1.10 com variação mínima = stablecoin USD
if 0.95 <= price <= 1.10 and chg24 < 0.5:
return True
# Preço entre 0.85 e 1.25 (stablecoins EUR ~1.08-1.15)
if 0.85 <= price <= 1.25 and chg24 < 0.3:
return True
return False

def is_blacklisted(coin: dict) -> bool:
symbol = coin.get(“symbol”, “”).lower()
name   = coin.get(“name”,   “”).lower()

```
if symbol in BLACKLIST_SYMBOLS:
    return True
for kw in BLACKLIST_CONTAINS:
    if kw in symbol or kw in name:
        return True
if is_xstock(symbol):
    return True
if is_stablecoin(coin):
    return True
return False
```

def normalize(values: list) -> list:
“”“Min-max normalização para [0, 1].”””
valid = [v for v in values if v is not None and not math.isnan(v)]
if not valid:
return [0.0] * len(values)
lo, hi = min(valid), max(valid)
if hi == lo:
return [0.5] * len(values)
return [(v - lo) / (hi - lo) if v is not None else 0.0 for v in values]

def score_coins(coins: list) -> list:
“”“Aplica filtros, calcula score e retorna ranking.”””

```
filtered = []
skipped  = {"stablecoin": 0, "blacklist": 0, "mcap": 0, "vol": 0, "imbalance": 0}

for c in coins:
    if is_blacklisted(c):
        if is_stablecoin(c):
            skipped["stablecoin"] += 1
        else:
            skipped["blacklist"] += 1
        continue

    mcap  = safe_float(c.get("market_cap"))
    vol24 = safe_float(c.get("total_volume"))

    if mcap < MIN_MCAP or mcap > MAX_MCAP:
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

print(f"[INFO] Filtrados: {len(filtered)} coins passaram | "
      f"Removidos — stablecoin:{skipped['stablecoin']} "
      f"blacklist:{skipped['blacklist']} mcap:{skipped['mcap']} "
      f"vol:{skipped['vol']} imbalance:{skipped['imbalance']}", file=sys.stderr)

if not filtered:
    return []

# Métricas brutas
ratios = [c["_ratio"] for c in filtered]
m1h    = [safe_float(c.get("price_change_percentage_1h_in_currency"))  for c in filtered]
m24h   = [safe_float(c.get("price_change_percentage_24h"))             for c in filtered]
m7d    = [safe_float(c.get("price_change_percentage_7d_in_currency"))  for c in filtered]

# Normalização min-max
n_ratio = normalize(ratios)
n_1h    = normalize(m1h)
n_24h   = normalize(m24h)
n_7d    = normalize(m7d)

# Score composto
for i, c in enumerate(filtered):
    c["_score"] = (
        W_RATIO   * n_ratio[i] +
        W_MOM_1H  * n_1h[i]   +
        W_MOM_24H * n_24h[i]  +
        W_MOM_7D  * n_7d[i]
    )

# Ordenar e cortar
ranked = sorted(filtered, key=lambda x: x["_score"], reverse=True)[:TOP_SHOW]

# Output limpo
result = []
for rank, c in enumerate(ranked, 1):
    result.append({
        "rank":         rank,
        "symbol":       c.get("symbol", "").upper(),
        "name":         c.get("name", ""),
        "price_usd":    round(safe_float(c.get("current_price")), 6),
        "mcap_m":       round(safe_float(c.get("market_cap")) / 1e6, 1),
        "vol24_m":      round(safe_float(c.get("total_volume")) / 1e6, 1),
        "vol_mcap_x":   round(c["_ratio"] / 100, 2),  # expresso em "x" (ex: 1.78x)
        "chg_1h":       round(safe_float(c.get("price_change_percentage_1h_in_currency")), 2),
        "chg_24h":      round(safe_float(c.get("price_change_percentage_24h")), 2),
        "chg_7d":       round(safe_float(c.get("price_change_percentage_7d_in_currency")), 2),
        "score":        round(c["_score"], 4),
        "coingecko_id": c.get("id", ""),
    })
return result
```

# ── Formatação Telegram ────────────────────────────────────────────────────────

def format_telegram(ranked: list) -> str:
now = datetime.now(timezone.utc).strftime(”%d/%m %H:%M UTC”)
lines = [f”📊 *Ranking VOL/MCAP + MOM* — {now}\n”]
for c in ranked:
chg1  = f”{c[‘chg_1h’]:+.1f}%”
chg24 = f”{c[‘chg_24h’]:+.1f}%”
chg7  = f”{c[‘chg_7d’]:+.1f}%”
ratio = f”{c[‘vol_mcap_x’]:.2f}x”
score = f”{c[‘score’]:.3f}”
lines.append(
f”*{c[‘rank’]:02d}. {c[‘symbol’]}* — score `{score}`\n”
f”   📈 VOL/MCAP: `{ratio}` | 1h:{chg1} 24h:{chg24} 7d:{chg7}\n”
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
print(”[WARN] TG_BOT_TOKEN ou TG_CHAT_ID não configurados — pulando envio.”, file=sys.stderr)
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
print(”[OK] Mensagem enviada ao Telegram.”, file=sys.stderr)
else:
print(f”[WARN] Telegram erro: {result.get(‘description’,’’)}”, file=sys.stderr)
except Exception as e:
print(f”[ERR] Falha ao enviar Telegram: {e}”, file=sys.stderr)

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
raw = sys.stdin.read().strip()
if not raw:
print(”[ERR] Nenhum dado no stdin. Execute: cg markets … -o json | python3 score.py”, file=sys.stderr)
sys.exit(1)

```
try:
    coins = json.loads(raw)
except json.JSONDecodeError as e:
    print(f"[ERR] JSON inválido: {e}", file=sys.stderr)
    sys.exit(1)

if not isinstance(coins, list):
    print("[ERR] Esperado array JSON do `cg markets`.", file=sys.stderr)
    sys.exit(1)

print(f"[INFO] {len(coins)} coins recebidos. Aplicando filtros...", file=sys.stderr)

ranked = score_coins(coins)

if not ranked:
    print("[WARN] Nenhum coin passou pelos filtros.", file=sys.stderr)
    sys.exit(0)

print(f"[INFO] Top {len(ranked)} coins no ranking final.", file=sys.stderr)

# JSON limpo no stdout
print(json.dumps(ranked, indent=2, ensure_ascii=False))

# Telegram
send_telegram(format_telegram(ranked))
```

if **name** == “**main**”:
main()
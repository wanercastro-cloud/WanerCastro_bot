#!/usr/bin/env python3
“””
CoinGecko CLI Scorer
Lê JSON do `cg markets` e aplica scoring VOL24/MCAP + Momentum ponderado.
Saída: JSON ranqueado + envio opcional ao Telegram.
“””

import sys
import json
import os
import math
import urllib.request
import urllib.parse
from datetime import datetime, timezone

# ── Configuração via variáveis de ambiente ─────────────────────────────────────

MIN_MCAP      = float(os.getenv(“MIN_MCAP”,   “10000000”))      # 10M USD
MAX_MCAP      = float(os.getenv(“MAX_MCAP”,   “2000000000”))    # 2B USD
MIN_VOL24     = float(os.getenv(“MIN_VOL24”,  “3000000”))       # 3M USD
MIN_EXCHANGES = int(os.getenv(“MIN_EXCH”,     “3”))
TOP_N         = int(os.getenv(“TOP_N”,        “20”))            # coins a processar no scoring
TOP_SHOW      = int(os.getenv(“TOP_SHOW”,     “10”))            # coins no output final
IMBALANCE_MAX = float(os.getenv(“IMBALANCE_MAX”, “30”))        # VOL/MCAP% máx p/ evitar manipulação

# Pesos — 24H recebe maior peso

W_MOM_1H  = float(os.getenv(“W_MOM_1H”,  “0.10”))
W_MOM_24H = float(os.getenv(“W_MOM_24H”, “0.40”))
W_MOM_7D  = float(os.getenv(“W_MOM_7D”,  “0.15”))
W_RATIO   = float(os.getenv(“W_RATIO”,   “0.35”))

# Nota: W_MOM_12H removido — API CoinGecko não retorna candle de 12h em /markets

# Telegram

TG_BOT_TOKEN = os.getenv(“TG_BOT_TOKEN”, “”)
TG_CHAT_ID   = os.getenv(“TG_CHAT_ID”,   “”)

# Tokens a ignorar (stablecoins, xStocks, problemáticos)

BLACKLIST_SYMBOLS = {
“usdt”,“usdc”,“busd”,“dai”,“tusd”,“usdp”,“usdd”,“frax”,“lusd”,“gusd”,
“susd”,“fdusd”,“pyusd”,“eurs”,“usde”,“crvusd”,“mkusd”,“cusd”,“zusd”,
“wbtc”,“weth”,“steth”,“cbeth”,“reth”,“wsteth”,“weeth”,“ezeth”,“rseth”,
“lseth”,“ankreth”,“sweth”,“oseth”,“meth”,“eth2x”,“btc2x”,
“paxg”,“xaut”,“cache”,
“spy”,“qqq”,“tsla”,“aapl”,“nvda”,“msft”,“amzn”,“meta”,“goog”,
“eur”,“gbp”,“jpy”,“cny”,“krw”,“brl”,“try”,
}
BLACKLIST_CONTAINS = [“leveraged”,“2x”,“3x”,“short”,“bear”,“bull”,“xstock”,“wrapped”]

# ── Funções auxiliares ─────────────────────────────────────────────────────────

def safe_float(val, default=0.0):
try:
return float(val) if val is not None else default
except (TypeError, ValueError):
return default

def is_blacklisted(coin: dict) -> bool:
symbol = coin.get(“symbol”, “”).lower()
name   = coin.get(“name”,   “”).lower()
if symbol in BLACKLIST_SYMBOLS:
return True
for kw in BLACKLIST_CONTAINS:
if kw in symbol or kw in name:
return True
return False

def normalize(values: list[float]) -> list[float]:
“”“Min-max normalização para [0, 1].”””
valid = [v for v in values if v is not None and not math.isnan(v)]
if not valid:
return [0.0] * len(values)
lo, hi = min(valid), max(valid)
if hi == lo:
return [0.5] * len(values)
return [(v - lo) / (hi - lo) if v is not None else 0.0 for v in values]

def score_coins(coins: list[dict]) -> list[dict]:
“”“Aplica filtros, calcula score e retorna ranking.”””

```
# 1. Filtro de qualidade
filtered = []
for c in coins:
    if is_blacklisted(c):
        continue
    mcap   = safe_float(c.get("market_cap"))
    vol24  = safe_float(c.get("total_volume"))
    if mcap  < MIN_MCAP  or mcap  > MAX_MCAP:
        continue
    if vol24 < MIN_VOL24:
        continue
    ratio = (vol24 / mcap * 100) if mcap > 0 else 0
    if ratio > IMBALANCE_MAX:
        continue  # evita tokens com pump artificial
    c["_ratio"] = ratio
    filtered.append(c)

if not filtered:
    return []

# 2. Extrair métricas brutas
ratios = [c["_ratio"]                                        for c in filtered]
m1h    = [safe_float(c.get("price_change_percentage_1h_in_currency"))  for c in filtered]
m24h   = [safe_float(c.get("price_change_percentage_24h"))             for c in filtered]
m7d    = [safe_float(c.get("price_change_percentage_7d_in_currency"))  for c in filtered]

# 3. Normalizar cada dimensão
n_ratio = normalize(ratios)
n_1h    = normalize(m1h)
n_24h   = normalize(m24h)
n_7d    = normalize(m7d)

# 4. Score composto
for i, c in enumerate(filtered):
    c["_score"] = (
        W_RATIO   * n_ratio[i] +
        W_MOM_1H  * n_1h[i]   +
        W_MOM_24H * n_24h[i]  +
        W_MOM_7D  * n_7d[i]
    )
    c["_n_ratio"] = round(n_ratio[i], 4)
    c["_n_1h"]    = round(n_1h[i], 4)
    c["_n_24h"]   = round(n_24h[i], 4)
    c["_n_7d"]    = round(n_7d[i], 4)

# 5. Ordenar e cortar
ranked = sorted(filtered, key=lambda x: x["_score"], reverse=True)[:TOP_SHOW]

# 6. Montar output limpo
result = []
for rank, c in enumerate(ranked, 1):
    result.append({
        "rank":        rank,
        "symbol":      c.get("symbol","").upper(),
        "name":        c.get("name",""),
        "price_usd":   round(safe_float(c.get("current_price")), 6),
        "mcap_m":      round(safe_float(c.get("market_cap")) / 1e6, 1),
        "vol24_m":     round(safe_float(c.get("total_volume")) / 1e6, 1),
        "vol_mcap_pct":round(c["_ratio"], 2),
        "chg_1h":      round(safe_float(c.get("price_change_percentage_1h_in_currency")), 2),
        "chg_24h":     round(safe_float(c.get("price_change_percentage_24h")), 2),
        "chg_7d":      round(safe_float(c.get("price_change_percentage_7d_in_currency")), 2),
        "score":       round(c["_score"], 4),
        "coingecko_id":c.get("id",""),
    })
return result
```

# ── Formatação Telegram ────────────────────────────────────────────────────────

def format_telegram(ranked: list[dict]) -> str:
now = datetime.now(timezone.utc).strftime(”%d/%m %H:%M UTC”)
lines = [f”📊 *CG Ranking VOL/MCAP+MOM* — {now}\n”]
for c in ranked:
chg1  = f”{c[‘chg_1h’]:+.1f}%”
chg24 = f”{c[‘chg_24h’]:+.1f}%”
chg7  = f”{c[‘chg_7d’]:+.1f}%”
ratio = f”{c[‘vol_mcap_pct’]:.1f}%”
score = f”{c[‘score’]:.3f}”
lines.append(
f”*{c[‘rank’]:02d}. {c[‘symbol’]}* — score `{score}`\n”
f”   💧 VOL/MCAP: `{ratio}` | 1h:{chg1} 24h:{chg24} 7d:{chg7}\n”
f”   💰 ${c[‘price_usd’]} | MCAP ${c[‘mcap_m’]}M | VOL ${c[‘vol24_m’]}M\n”
)
lines.append(f”*Filtros: MCAP ${MIN_MCAP/1e6:.0f}M–${MAX_MCAP/1e6:.0f}M | VOL24 ≥${MIN_VOL24/1e6:.0f}M*”)
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
print(f”[WARN] Telegram retornou erro: {result}”, file=sys.stderr)
except Exception as e:
print(f”[ERR] Falha ao enviar Telegram: {e}”, file=sys.stderr)

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
raw = sys.stdin.read().strip()
if not raw:
print(”[ERR] Nenhum dado recebido no stdin.”, file=sys.stderr)
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

print(f"[INFO] Top {len(ranked)} coins ranqueados.", file=sys.stderr)

# Output JSON limpo no stdout
print(json.dumps(ranked, indent=2, ensure_ascii=False))

# Telegram
msg = format_telegram(ranked)
send_telegram(msg)
```

if **name** == “**main**”:
main()
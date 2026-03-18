#!/usr/bin/env bash

# run.sh — Busca dados via CoinGecko CLI e aplica scoring customizado

# Uso: ./run.sh [–save]

# –save: salva o JSON de saída em ./output/ranking_<timestamp>.json

set -euo pipefail

SCRIPT_DIR=”$(cd “$(dirname “${BASH_SOURCE[0]}”)” && pwd)”
TOTAL=”${FETCH_N:-500}”         # quantos coins buscar (env ou 500 padrão)
PER_PAGE=”${PER_PAGE:-250}”     # tamanho de cada página CLI
OUTPUT_DIR=”${SCRIPT_DIR}/output”

echo “[INFO] Iniciando coleta — ${TOTAL} coins via CoinGecko CLI…” >&2

# Garante que CG_API_KEY está configurado

if [[ -z “${CG_API_KEY:-}” ]]; then
echo “[ERR] CG_API_KEY não definida. Configure no .env ou variáveis de ambiente.” >&2
exit 1
fi

# Coleta com CLI — price_change_percentage inclui 1h, 7d além do 24h padrão

RAW_JSON=$(cg markets   
–total “${TOTAL}”   
–per-page “${PER_PAGE}”   
–price-change-percentage “1h,24h,7d”   
-o json)

# Aplica scoring Python

echo “${RAW_JSON}” | python3 “${SCRIPT_DIR}/score.py”

# Opcional: salvar output

if [[ “${1:-}” == “–save” ]]; then
mkdir -p “${OUTPUT_DIR}”
TIMESTAMP=$(date +”%Y%m%d_%H%M%S”)
OUTFILE=”${OUTPUT_DIR}/ranking_${TIMESTAMP}.json”
echo “${RAW_JSON}” | python3 “${SCRIPT_DIR}/score.py” > “${OUTFILE}”
echo “[INFO] Salvo em ${OUTFILE}” >&2
fi
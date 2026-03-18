FROM python:3.11.9-slim

# Instala dependências mínimas
RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    bash \
    jq \
    tar \
    && rm -rf /var/lib/apt/lists/*

# Instala CoinGecko CLI buscando a versão mais recente via GitHub API
RUN set -eux; \
    # Busca a URL do asset linux/amd64 no release mais recente
    RELEASE_URL=$(curl -fsSL \
        -H "Accept: application/vnd.github+json" \
        "https://api.github.com/repos/coingecko/coingecko-cli/releases/latest" \
        | jq -r '.assets[] | select(.name | test("linux.*amd64|amd64.*linux"; "i")) | .browser_download_url' \
        | head -1); \
    echo ">>> Downloading: ${RELEASE_URL}"; \
    # Detecta se é .tar.gz ou binário direto e instala adequadamente
    if echo "${RELEASE_URL}" | grep -q "\.tar\.gz"; then \
        curl -fsSL "${RELEASE_URL}" | tar -xz -C /tmp; \
        mv /tmp/cg /usr/local/bin/cg 2>/dev/null || \
        find /tmp -name "cg" -type f -exec mv {} /usr/local/bin/cg \;; \
    else \
        curl -fsSL "${RELEASE_URL}" -o /usr/local/bin/cg; \
    fi; \
    chmod +x /usr/local/bin/cg; \
    # Verifica instalação
    cg --version

WORKDIR /app

COPY run.sh score.py ./
RUN chmod +x run.sh

# CG_API_KEY e CG_API_TIER devem ser definidos no Railway como variáveis de ambiente
ENV CG_API_TIER=demo

CMD ["bash", "run.sh"]

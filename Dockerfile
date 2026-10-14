# ── SkippALGO Terminal access proxy ────────────────────────────
FROM golang:1.26.5-bookworm AS access-proxy-builder

WORKDIR /src
COPY services/terminal_access_proxy/go.mod services/terminal_access_proxy/main.go ./
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /terminal-access-proxy .

# ── SkippALGO Terminal — production image ──────────────────────
FROM python:3.12-slim AS base

WORKDIR /app

# System deps for pandas/numpy wheels and SSL
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

# Copy app code (excluding dev artifacts via .dockerignore)
COPY . .
COPY --from=access-proxy-builder /terminal-access-proxy /usr/local/bin/terminal-access-proxy

RUN chmod 0755 /usr/local/bin/terminal-access-proxy /app/scripts/start_terminal_service.sh

# Streamlit config
ENV STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_ADDRESS=127.0.0.1 \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_FILE_WATCHER_TYPE=none \
    PORT=8080

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl --fail --silent --show-error http://localhost:${PORT:-8080}/health || exit 1

ENTRYPOINT ["/app/scripts/start_terminal_service.sh"]

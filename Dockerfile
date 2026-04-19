# ── SkippALGO Terminal — production image ──────────────────────
FROM python:3.13-slim AS base

WORKDIR /app

# System deps for pandas/numpy wheels and SSL
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code (excluding dev artifacts via .dockerignore)
COPY . .

# Streamlit config
ENV STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_FILE_WATCHER_TYPE=none

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["streamlit", "run", "streamlit_terminal.py", \
    "--server.port=8501", "--server.address=0.0.0.0"]

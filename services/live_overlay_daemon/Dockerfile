FROM python:3.12-slim

WORKDIR /app

# services/__init__.py so Python resolves services.live_overlay_daemon
RUN mkdir -p /app/services && touch /app/services/__init__.py

# Build context is repo root (Root Directory cleared in Railway)
# tzdata guarantees IANA timezone files exist even on minimal slim images;
# the PyPI tzdata fallback in requirements.txt covers non-Docker installs.
RUN apt-get update && apt-get install -y --no-install-recommends tzdata     && rm -rf /var/lib/apt/lists/*
COPY services/live_overlay_daemon/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY services/live_overlay_daemon/ /app/services/live_overlay_daemon/
COPY artifacts/smc_microstructure_exports/smc_live_news_snapshot.json /app/artifacts/smc_microstructure_exports/smc_live_news_snapshot.json

# Run as non-root user for security (D1)
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

# Documentary default; runtime port is resolved by config.port() from the
# PORT env var (Railway injects it dynamically, so the bind port may differ).
EXPOSE 8000

CMD ["python", "-m", "services.live_overlay_daemon.main"]

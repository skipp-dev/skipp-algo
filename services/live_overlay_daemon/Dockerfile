FROM python:3.12-slim

WORKDIR /app

# services/__init__.py so Python resolves services.live_overlay_daemon
RUN mkdir -p /app/services && touch /app/services/__init__.py

# Build context is repo root (Root Directory cleared in Railway)
COPY services/live_overlay_daemon/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY services/live_overlay_daemon/ /app/services/live_overlay_daemon/
# Seed the default NEWS_SNAPSHOT_PATH with the tracked seed file so the daemon
# has a valid cold-start snapshot without requiring a live producer write first.
RUN mkdir -p /app/artifacts/smc_microstructure_exports
COPY services/live_overlay_daemon/news_snapshot_seed.json /app/artifacts/smc_microstructure_exports/smc_live_news_snapshot.json

# Run as non-root user for security (D1)
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["sh", "-c", "uvicorn services.live_overlay_daemon.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --http h11 --loop asyncio"]

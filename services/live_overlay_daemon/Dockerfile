FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (cached layer)
COPY services/live_overlay_daemon/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Copy only the daemon service + the spec it references
COPY services/live_overlay_daemon/ ./services/live_overlay_daemon/
# News snapshot is mounted at runtime via Railway volume or set via NEWS_SNAPSHOT_PATH
# For local docker-compose, mount the artifacts dir as a read-only volume.

# Expose the HTTP port (Railway overrides PORT env var automatically)
EXPOSE 8000

# Run with uvicorn; Railway sets PORT; use 1 worker (state is in-process)
CMD ["sh", "-c", "uvicorn services.live_overlay_daemon.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --log-level ${LOG_LEVEL:-info}"]

FROM python:3.12-slim

WORKDIR /app

# services/__init__.py so Python resolves services.live_overlay_daemon
RUN mkdir -p /app/services && touch /app/services/__init__.py

# Build context is repo root (Root Directory cleared in Railway)
COPY services/live_overlay_daemon/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY services/live_overlay_daemon/ /app/services/live_overlay_daemon/

EXPOSE 8000

CMD ["sh", "-c", "uvicorn services.live_overlay_daemon.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --http h11"]

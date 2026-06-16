FROM python:3.12-slim

WORKDIR /app

# Create services package marker so Python resolves services.live_overlay_daemon
RUN mkdir -p /app/services && touch /app/services/__init__.py

# Build context root = services/live_overlay_daemon/ (Railway root dir setting)
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Copy daemon source into the correct package path
COPY . /app/services/live_overlay_daemon/

EXPOSE 8000

CMD ["sh", "-c", "uvicorn services.live_overlay_daemon.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --log-level ${LOG_LEVEL:-info} --http h11"]

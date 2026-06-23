FROM python:3.12-slim

WORKDIR /app

# Build context is the repo root (clear the Railway "Root Directory" setting).
COPY services/signals_producer/requirements.txt /tmp/requirements.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r /tmp/requirements.txt

# The worker imports open_prep.realtime_signals (pure-stdlib FMP client).
COPY open_prep/ /app/open_prep/

# Run as a non-root user for security (D1).
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

ENV PYTHONUNBUFFERED=1

EXPOSE 8099

# The realtime signal engine runs forever and serves /healthz + /signals.
# TELEMETRY_BIND_HOST (set as a Railway service variable to 0.0.0.0) makes
# the bind reachable over the private network.  Railway overrides this CMD
# with railway.toml:startCommand (which injects $PORT); this is the local /
# `docker run` fallback (no shell expansion, exec form, single source of truth).
CMD ["python", "-m", "open_prep.realtime_signals", "--telemetry-port", "8099"]

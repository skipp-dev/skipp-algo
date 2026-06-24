FROM python:3.12-slim

WORKDIR /app

# Build context is the repo root (clear the Railway "Root Directory" setting).
COPY services/signals_producer/requirements.txt /tmp/requirements.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata ca-certificates \
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
# TELEMETRY_BIND_HOST defaults to 0.0.0.0 so Railway's proxy can reach the
# process without a separate service variable.  The module reads PORT from the
# environment directly; this CMD is the local / `docker run` fallback (no shell
# expansion, exec form, single source of truth).
CMD ["python", "-m", "open_prep.realtime_signals"]

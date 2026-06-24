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

# newsstack_fmp — multi-source news pipeline consumed by AsyncNewsstackPoller.
# terminal_tradingview_news — free TradingView headlines (unofficial endpoint,
#   no API key required; uses urllib + Browser UA, already in stdlib).
# smc_core — local utilities used by newsstack_fmp._bz_http (resilient retry).
# databento_utils — local helper used by terminal_tradingview_news.
COPY newsstack_fmp/ /app/newsstack_fmp/
COPY terminal_tradingview_news.py /app/terminal_tradingview_news.py
COPY smc_core/ /app/smc_core/
COPY databento_utils.py /app/databento_utils.py
# scripts/smc_newsapi_ai.py — NewsAPI.ai / Event Registry client imported by
#   newsstack_fmp.pipeline._fetch_newsapi_provider_items.  Only this one script
#   module is needed; copying the whole scripts/ dir keeps the image lean and
#   avoids pulling in Streamlit/heavy dashboard deps from other scripts.
COPY scripts/smc_newsapi_ai.py /app/scripts/smc_newsapi_ai.py
RUN touch /app/scripts/__init__.py

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
CMD ["python", "-m", "open_prep.realtime_signals"]

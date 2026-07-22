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
# smc_core.resilient — the single local utility used by the news adapters.
# Keep the package initializer empty in this lean image: the repository's full
# smc_core/__init__.py eagerly imports the scoring stack, which is unrelated to
# the producer and pulls in modules that are intentionally absent here.
# databento_utils — local helper used by terminal_tradingview_news.
COPY newsstack_fmp/ /app/newsstack_fmp/
COPY terminal_tradingview_news.py /app/terminal_tradingview_news.py
COPY terminal_fmp_insights.py /app/terminal_fmp_insights.py
COPY cisco_ai_defense.py /app/cisco_ai_defense.py
COPY open_prep_boundary.py /app/open_prep_boundary.py
# terminal_technicals + terminal_fmp_technicals — the RealtimeEngine's
# TechnicalScorer chain (tradingview_ta primary, FMP fallback). Without these
# the deferred import in realtime_signals._get_fetch_fn silently degraded to
# _noop_fetch: every prod signal scored technical_score=0.5 NEUTRAL and the
# RSI A1->A0 upgrades / STRONG_SELL A0 blocks were inert (audit finding).
COPY terminal_technicals.py /app/terminal_technicals.py
COPY terminal_fmp_technicals.py /app/terminal_fmp_technicals.py
RUN mkdir -p /app/smc_core && touch /app/smc_core/__init__.py
COPY smc_core/resilient.py /app/smc_core/resilient.py
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
# Railway overrides this CMD with railway.toml:startCommand. The engine reads
# PORT as the telemetry-port default itself, so neither path relies on shell
# expansion for the local / `docker run` fallback.
CMD ["python", "-m", "open_prep.realtime_signals"]

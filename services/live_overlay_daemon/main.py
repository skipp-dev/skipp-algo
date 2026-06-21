"""
FastAPI app — SMC Live Overlay Daemon.

Endpoints:
    GET /health                          — liveness healthcheck (no auth)
    GET /ready                           — readiness diagnostics (no auth)
  GET /{token}/smc_live?symbol=NVDA    — overlay payload (token = OVERLAY_SECRET_TOKEN)
Security model:
    Pine's request.get() cannot send Authorization headers, so the secret
  token is embedded in the URL path. The Pine source is never released to
  users, so the URL is effectively obscure. Rotate monthly via library update.

Stale handling:
  If the overlay cache is older than OVERLAY_MAX_STALE_SECS, the response
  still returns 200 but with stale=true and asof_ts showing the last computation
  time, so Pine can degrade gracefully to the baked mp.* defaults.
"""
from __future__ import annotations

import datetime
import logging
import math
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Path, Query
from fastapi.responses import JSONResponse, PlainTextResponse

from . import cache, config, feed, metrics, observability
from .market_hours import (
    compute_daemon_health_status,
)
from .market_hours import (
    is_us_regular_session_open as _is_us_regular_session_open,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
# Suppress per-symbol INFO flood from Databento client (500+ msgs/sec on startup)
logging.getLogger("databento.live.client").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

_startup_ts: float = 0.0

_VALID_TFS: frozenset[str] = frozenset({"5m", "10m", "15m", "30m", "1H", "4H"})


def _json_safe(value: Any) -> Any:
    """Return a JSON-safe value tree by normalizing non-finite floats to None."""
    if isinstance(value, float) or value.__class__.__name__ == "Decimal":
        return _coerced if math.isfinite(_coerced := float(value)) else None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _lifespan(app: FastAPI):
    global _startup_ts
    logger.info("Starting SMC Live Overlay Daemon …")
    observability.metric_counter("live_overlay.daemon.start_attempt")

    # Validate required env vars fail-fast at startup
    with observability.trace_span("live_overlay.daemon_lifespan"):
        config.databento_api_key()
        config.overlay_secret_token()

        feed.start()
        _startup_ts = time.monotonic()
        logger.info(
            "Daemon started — refresh=%ds flow=%ds rolling=%d bars",
            config.refresh_secs(),
            config.flow_refresh_secs(),
            config.rolling_bars(),
        )
        observability.metric_counter("live_overlay.daemon.start_success")
        observability.audit_event("live_overlay_daemon_start", "ok")
    yield
    logger.info("Shutting down …")
    feed.stop()
    observability.metric_counter("live_overlay.daemon.stop_total")
    observability.audit_event("live_overlay_daemon_stop", "ok")
    logger.info("Daemon stopped.")


app = FastAPI(
    title="SMC Live Overlay",
    version="1.0.0",
    docs_url=None,  # disable swagger UI in production
    redoc_url=None,
    lifespan=_lifespan,
)


# ---------------------------------------------------------------------------
# /health — no auth, process liveness only (Railway/Uptime)
# ---------------------------------------------------------------------------

@app.api_route("/health", methods=["GET", "HEAD"], include_in_schema=False)
def health() -> JSONResponse:
    observability.metric_counter("live_overlay.health_requests.total")
    uptime = time.monotonic() - _startup_ts if _startup_ts else 0
    return JSONResponse(
        {
            "status": "alive",
            "service": "smc-live-overlay",
            "uptime_secs": round(uptime),
            "ts": datetime.datetime.now(datetime.UTC).isoformat(),
        }
    )


# ---------------------------------------------------------------------------
# /ready — no auth, dependency + worker readiness detail payload
# ---------------------------------------------------------------------------

@app.api_route("/ready", methods=["GET", "HEAD"], include_in_schema=False)
def ready() -> JSONResponse:
    observability.metric_counter("live_overlay.ready_requests.total")
    uptime = time.monotonic() - _startup_ts if _startup_ts else 0
    feed_healthy = feed.is_ready()
    bar_age = feed.last_bar_age_secs()
    workers = feed.worker_liveness()
    feed_metrics = feed.metrics_snapshot()
    workers_healthy = all(workers.values())
    market_open = _is_us_regular_session_open()
    overlay_age = cache.overlay_age_secs()
    max_stale = config.max_stale_secs()
    bar_symbols = cache.bar_symbol_count()
    bar_count = cache.total_bar_count()
    overlay_symbols = cache.overlay_symbol_count()
    overlay_fresh = (
        overlay_symbols > 0
        and overlay_age != float("inf")
        and overlay_age <= max_stale
    )
    status = compute_daemon_health_status(
        feed_healthy=feed_healthy,
        workers_healthy=workers_healthy,
        overlay_fresh=overlay_fresh,
        market_open=market_open,
        bar_count=bar_count,
    )
    observability.metric_gauge("live_overlay.health.status_ok", 1 if status == "ok" else 0)
    observability.audit_event(
        "live_overlay_ready",
        status,
        feed_healthy=feed_healthy,
        workers_healthy=workers_healthy,
        overlay_fresh=overlay_fresh,
    )
    return JSONResponse(
        {
            "status": status,
            "feed_healthy": feed_healthy,
            "workers_healthy": workers_healthy,
            "worker_liveness": workers,
            "feed_metrics": feed_metrics,
            "market_open": market_open,
            "overlay_fresh": overlay_fresh,
            "last_bar_age_secs": None if bar_age is None else round(bar_age, 1),
            "uptime_secs": round(uptime),
            "bar_symbols": bar_symbols,
            "bar_count": bar_count,
            "overlay_symbols": overlay_symbols,
            "overlay_age_secs": (
                None
                if overlay_age == float("inf")
                else round(overlay_age, 1)
            ),
            "ts": datetime.datetime.now(datetime.UTC).isoformat(),
        }
    )


# ---------------------------------------------------------------------------
# /{token}/metrics — Prometheus text exposition (token-protected)
# ---------------------------------------------------------------------------

@app.get("/{token}/metrics", include_in_schema=False)
def prometheus_metrics(token: str = Path(...)) -> PlainTextResponse:
    """Prometheus scrape endpoint, protected by the same bearer token as /smc_live."""
    expected = config.overlay_secret_token()
    if not _ct_eq(token, expected):
        raise HTTPException(status_code=404)

    body = metrics.render_metrics(_startup_ts)
    return PlainTextResponse(body, media_type="text/plain; version=0.0.4; charset=utf-8")


# ---------------------------------------------------------------------------
# /{token}/smc_live — overlay payload
# ---------------------------------------------------------------------------

@app.get("/{token}/smc_live")
def smc_live(
    token: str = Path(...),
    symbol: str = Query(..., min_length=1, max_length=10),
    tf: str = Query("5m", max_length=8),  # timeframe hint — stored in response
) -> JSONResponse:
    started_at = time.monotonic()
    observability.metric_counter("live_overlay.smc_live_requests.total")
    sym = symbol.upper().strip()
    try:
        # Constant-time token comparison to avoid timing attacks. _ct_eq hashes
        # both sides to a fixed-length digest before comparing, so neither the
        # comparison nor a Python len() short-circuit can leak the token length
        # as a timing side-channel (CWE-208).
        expected = config.overlay_secret_token()
        if not _ct_eq(token, expected):
            observability.metric_counter("live_overlay.smc_live_auth.denied")
            observability.audit_event("smc_live_auth", "denied", symbol=sym, tf=tf)
            raise HTTPException(status_code=404)  # 404 not 401 to avoid leaking route structure

        if tf not in _VALID_TFS:
            observability.metric_counter("live_overlay.smc_live_bad_tf.total")
            observability.audit_event("smc_live_tf_validation", "rejected", symbol=sym, tf=tf)
            raise HTTPException(
                status_code=400,
                detail=f"tf must be one of {sorted(_VALID_TFS)}",
            )
        payload = cache.get_overlay(sym)

        if payload is None:
            observability.metric_counter("live_overlay.smc_live_cache_miss.total")
            observability.metric_counter("live_overlay.smc_live_stale_served.total")
            observability.audit_event("smc_live_fetch", "cache_miss", symbol=sym, tf=tf)
            # Symbol not yet in cache — return minimal stale response
            return JSONResponse(
                {
                    "schema": "smc-live-overlay/1",
                    "symbol": sym,
                    "tf": tf,
                    "asof_ts": int(datetime.datetime.now(datetime.UTC).timestamp()),
                    "stale": True,
                    "news_strength": None,
                    "news_bias": None,
                    "flow_rel_vol": None,
                    "flow_delta_proxy_pct": None,
                    "squeeze_on": None,
                    "ats_state": None,
                    "ats_zscore": None,
                    "vix_level": None,
                    "tone": None,
                    "global_heat": None,
                    "event_window_state": None,
                    "event_risk_level": None,
                    "next_event_name": None,
                    "next_event_time": None,
                    "market_event_blocked": False,
                    "symbol_event_blocked": False,
                    "event_provider_status": "unavailable",
                }
            )

        # Re-evaluate stale based on current overlay age so a cached payload
        # does not serve a stale=false flag after the age window has elapsed.
        age = cache.overlay_age_secs()
        max_stale = config.max_stale_secs()
        payload = dict(payload)  # copy — do not mutate shared cache state
        payload["stale"] = (age > max_stale) if age != float("inf") else True
        # Inject tf into response
        payload["tf"] = tf
        if payload["stale"]:
            observability.metric_counter("live_overlay.smc_live_stale_served.total")
        observability.metric_counter("live_overlay.smc_live_success.total")
        observability.audit_event("smc_live_fetch", "ok", symbol=sym, tf=tf, stale=payload["stale"])
        return JSONResponse(_json_safe(payload))
    except Exception as exc:
        # Let FastAPI's own HTTPExceptions (auth denied, bad tf, etc.) propagate
        # unchanged; only unexpected failures (cache/config bugs, etc.) become
        # a deterministic 500 with observability signals for triage.
        if isinstance(exc, HTTPException):
            raise
        logger.exception("smc_live failed for %s tf=%s", sym, tf)
        observability.metric_counter("live_overlay.smc_live_errors.total")
        observability.audit_event(
            "smc_live_fetch", "error", symbol=sym, tf=tf, error=type(exc).__name__
        )
        raise HTTPException(status_code=500, detail="internal error") from exc
    finally:
        observability.metric_histogram_ms(
            "live_overlay.smc_live_latency",
            (time.monotonic() - started_at) * 1000.0,
        )


# ---------------------------------------------------------------------------
# Constant-time string comparison (avoid timing oracle on token)
# ---------------------------------------------------------------------------

def _ct_eq(a: str, b: str) -> bool:
    """Constant-time string equality with no length side-channel.

    Both inputs are reduced to fixed-length SHA-256 digests *before* the
    constant-time compare. ``hmac.compare_digest`` on two raw strings still
    leaks their length (it returns early when the lengths differ), so a naive
    ``compare_digest(token, expected)`` — or a Python ``len()`` pre-check —
    would expose the secret-token length as a timing oracle (CWE-208).
    Comparing fixed 32-byte digests makes the timing independent of the input
    length, while SHA-256's collision resistance preserves equality semantics.
    """
    import hashlib
    import hmac

    a_digest = hashlib.sha256(a.encode()).digest()
    b_digest = hashlib.sha256(b.encode()).digest()
    return hmac.compare_digest(a_digest, b_digest)

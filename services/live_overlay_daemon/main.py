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

import base64
import binascii
import datetime
import logging
import math
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from . import cache, compute, config, feed, metrics, observability
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

_VALID_TFS: frozenset[str] = frozenset(compute.supported_timeframes())


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
# /{token}/metrics — Prometheus text exposition (token-protected, legacy path)
# ---------------------------------------------------------------------------

@app.get("/{token}/metrics", include_in_schema=False)
def prometheus_metrics_legacy(token: str = Path(...)) -> PlainTextResponse:
    """Prometheus scrape endpoint, protected by the same path secret as /smc_live.

    Legacy path kept for backwards compatibility. New deployments should use
    /metrics with Basic auth so the secret token does not appear in Prometheus
    target labels or scrape logs.
    """
    expected = config.overlay_secret_token()
    if not _ct_eq(token, expected):
        raise HTTPException(status_code=404)

    body = metrics.render_metrics(_startup_ts)
    return PlainTextResponse(body, media_type="text/plain; version=0.0.4; charset=utf-8")


# ---------------------------------------------------------------------------
# /metrics — Prometheus text exposition (Basic auth, preferred)
# ---------------------------------------------------------------------------

def _basic_auth_password(request: Request) -> str | None:
    """Extract password from a Basic Authorization header, or None."""
    auth = request.headers.get("authorization")
    if not auth:
        return None
    scheme, sep, credentials = auth.partition(" ")
    if sep != " " or scheme.lower() != "basic":
        return None
    credentials = credentials.strip()
    if not credentials:
        return None
    try:
        decoded = base64.b64decode(credentials.encode(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    _user, sep2, password = decoded.partition(":")
    if sep2 != ":":
        return None
    # Allow any username; only the password matters for this shared secret.
    return password


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics(request: Request) -> PlainTextResponse:
    """Prometheus scrape endpoint protected by Basic auth.

    Uses the overlay secret token as the Basic auth password. This keeps the
    token out of Prometheus target labels, scrape logs, and remote-write
    metadata. Alloy config should set __metrics_path__ = "/metrics" and
    basic_auth { username = "metrics", password = sys.env("OVERLAY_SECRET_TOKEN") }.
    """
    password = _basic_auth_password(request)
    expected = config.overlay_secret_token()
    if password is None or not _ct_eq(password, expected):
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Basic"})

    body = metrics.render_metrics(_startup_ts)
    return PlainTextResponse(body, media_type="text/plain; version=0.0.4; charset=utf-8")


# ---------------------------------------------------------------------------
# Timeframe-aware payload lookup / on-demand compute
# ---------------------------------------------------------------------------

def _get_payload_for_timeframe(sym: str, tf: str) -> dict[str, Any] | None:
    """Return overlay payload for symbol and timeframe.

    The background refresh thread computes the default 5m timeframe and stores
    it in the overlay cache. For non-default timeframes we aggregate the cached
    1-minute bars on demand so callers still get timeframe-consistent fields.
    """
    if tf == "5m":
        return cache.get_overlay(sym)

    bars = cache.get_bars_snapshot(sym)
    if not bars:
        return None
    payload = compute.build_payload(
        sym,
        bars,
        compute.get_global_news_fields(),
        config.max_stale_secs(),
        tf=tf,
    )
    # On-demand payloads should be marked stale based on bar recency, not
    # overlay cache age (which tracks only the background 5m snapshot).
    valid_ts_events = [
        ts
        for bar in bars
        if isinstance((ts := bar.get("ts_event")), int)
        and not isinstance(ts, bool)
        and ts > 0
    ]
    if not valid_ts_events:
        payload["stale"] = True
        return payload

    latest_bar_age_secs = max(0.0, time.time() - (max(valid_ts_events) / 1_000_000_000))
    payload["stale"] = latest_bar_age_secs > config.max_stale_secs()
    return payload


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
        # Constant-time token comparison to avoid timing attacks. _ct_eq uses
        # fixed-length normalized buffers and guarded input caps so direct
        # user-input length mismatches do not create a timing oracle (CWE-208).
        expected = config.overlay_secret_token()
        if not _ct_eq(token, expected):
            observability.metric_counter("live_overlay.smc_live_auth.denied")
            observability.audit_event("smc_live_auth", "denied", symbol=sym, tf=tf)
            raise HTTPException(status_code=404)  # 404 not 401 to avoid leaking route structure

        if tf not in _VALID_TFS:
            observability.metric_counter("live_overlay.smc_live_bad_tf.total")
            observability.audit_event("live_overlay_tf_validation", "rejected", symbol=sym, tf=tf)
            raise HTTPException(
                status_code=400,
                detail=f"tf must be one of {sorted(_VALID_TFS)}",
            )
        payload = _get_payload_for_timeframe(sym, tf)

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

        payload = dict(payload)  # shallow-copy — do not mutate shared cache state
        if tf == "5m":
            # Re-evaluate stale for cached background snapshots.
            age = cache.overlay_age_secs()
            max_stale = config.max_stale_secs()
            payload["stale"] = (age > max_stale) if age != float("inf") else True
        if payload.get("stale"):
            observability.metric_counter("live_overlay.smc_live_stale_served.total")
        # Inject tf into response
        payload["tf"] = tf
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

    Both inputs are reduced to fixed-size SHA-256 digests before
    ``hmac.compare_digest``. This keeps the compare width constant (32 bytes)
    and avoids token-length-dependent compare work.
    """
    import hashlib
    import hmac

    # Keep a hard upper bound on attacker-controlled input processing.
    if len(a) > 4096:
        return False

    a_bytes = a.encode()
    if len(a_bytes) > 16_384:
        return False

    a_digest = hashlib.sha256(a_bytes).digest()
    b_digest = hashlib.sha256(b.encode()).digest()
    return hmac.compare_digest(a_digest, b_digest)

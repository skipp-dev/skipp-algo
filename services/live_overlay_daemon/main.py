"""
FastAPI app — SMC Live Overlay Daemon.

Endpoints:
  GET /health                          — healthcheck (no auth)
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
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Path, Query
from fastapi.responses import JSONResponse

from . import cache, config, feed

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
# Suppress per-symbol INFO flood from Databento client (500+ msgs/sec on startup)
logging.getLogger("databento.live.client").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

_startup_ts: float = 0.0

_VALID_TFS: frozenset[str] = frozenset({"5m", "15m", "1H", "4H", "1D"})


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _lifespan(app: FastAPI):
    global _startup_ts
    logger.info("Starting SMC Live Overlay Daemon …")

    # Validate required env vars fail-fast at startup
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
    yield
    logger.info("Shutting down …")
    feed.stop()
    logger.info("Daemon stopped.")


app = FastAPI(
    title="SMC Live Overlay",
    version="1.0.0",
    docs_url=None,  # disable swagger UI in production
    redoc_url=None,
    lifespan=_lifespan,
)


# ---------------------------------------------------------------------------
# /health — no auth, used by Railway healthcheck
# ---------------------------------------------------------------------------

@app.api_route("/health", methods=["GET", "HEAD"], include_in_schema=False)
def health() -> JSONResponse:
    uptime = time.monotonic() - _startup_ts if _startup_ts else 0
    feed_healthy = feed.is_ready()
    bar_age = feed.last_bar_age_secs()
    workers = feed.worker_liveness()
    workers_healthy = all(workers.values())
    overlay_age = cache.overlay_age_secs()
    max_stale = config.max_stale_secs()
    overlay_fresh = overlay_age != float("inf") and overlay_age <= max_stale
    status = "ok" if (feed_healthy and workers_healthy and overlay_fresh) else "starting"
    return JSONResponse(
        {
            "status": status,
            "feed_healthy": feed_healthy,
            "workers_healthy": workers_healthy,
            "worker_liveness": workers,
            "overlay_fresh": overlay_fresh,
            "last_bar_age_secs": None if bar_age is None else round(bar_age, 1),
            "uptime_secs": round(uptime),
            "bar_symbols": cache.bar_symbol_count(),
            "bar_count": cache.total_bar_count(),
            "overlay_symbols": cache.overlay_symbol_count(),
            "overlay_age_secs": (
                None
                if overlay_age == float("inf")
                else round(overlay_age, 1)
            ),
            "ts": datetime.datetime.now(datetime.UTC).isoformat(),
        }
    )


# ---------------------------------------------------------------------------
# /{token}/smc_live — overlay payload
# ---------------------------------------------------------------------------

@app.get("/{token}/smc_live")
def smc_live(
    token: str = Path(...),
    symbol: str = Query(..., min_length=1, max_length=10),
    tf: str = Query("5m", max_length=8),  # timeframe hint — stored in response
) -> JSONResponse:
    # Constant-time token comparison to avoid timing attacks. _ct_eq hashes
    # both sides to a fixed-length digest before comparing, so neither the
    # comparison nor a Python len() short-circuit can leak the token length
    # as a timing side-channel (CWE-208).
    expected = config.overlay_secret_token()
    if not _ct_eq(token, expected):
        raise HTTPException(status_code=404)  # 404 not 401 to avoid leaking route structure

    sym = symbol.upper().strip()
    if tf not in _VALID_TFS:
        raise HTTPException(
            status_code=400,
            detail=f"tf must be one of {sorted(_VALID_TFS)}",
        )
    payload = cache.get_overlay(sym)

    if payload is None:
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
    payload = dict(payload)  # shallow-copy — do not mutate shared cache state
    payload["stale"] = (age > max_stale) if age != float("inf") else True
    # Inject tf into response
    payload["tf"] = tf
    return JSONResponse(payload)


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

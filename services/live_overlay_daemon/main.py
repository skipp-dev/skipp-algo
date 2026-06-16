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
logger = logging.getLogger(__name__)

_startup_ts: float = 0.0


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
    return JSONResponse(
        {
            "status": "ok",
            "uptime_secs": round(uptime),
            "bar_symbols": cache.bar_symbol_count(),
            "bar_count": cache.total_bar_count(),
            "overlay_symbols": cache.overlay_symbol_count(),
            "overlay_age_secs": (
                None
                if cache.overlay_age_secs() == float("inf")
                else round(cache.overlay_age_secs(), 1)
            ),
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
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
    # Constant-time token comparison to avoid timing attacks
    expected = config.overlay_secret_token()
    # Compare using XOR approach (timing-safe manual comparison)
    if len(token) != len(expected) or not _ct_eq(token, expected):
        raise HTTPException(status_code=404)  # 404 not 401 to avoid leaking route structure

    sym = symbol.upper().strip()
    payload = cache.get_overlay(sym)

    if payload is None:
        # Symbol not yet in cache — return minimal stale response
        return JSONResponse(
            {
                "schema": "smc-live-overlay/1",
                "symbol": sym,
                "tf": tf,
                "asof_ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
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

    # Inject tf into response
    payload["tf"] = tf
    return JSONResponse(payload)


# ---------------------------------------------------------------------------
# Constant-time string comparison (avoid timing oracle on token)
# ---------------------------------------------------------------------------

def _ct_eq(a: str, b: str) -> bool:
    """Constant-time string equality (same as hmac.compare_digest for str)."""
    import hmac
    return hmac.compare_digest(a.encode(), b.encode())

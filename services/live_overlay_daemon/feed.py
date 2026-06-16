"""
Live feed consumer — runs in a daemon background thread.

Architecture:
  - One db.Live() connection subscribes to EQUS.MINI ohlcv-1m ALL_SYMBOLS.
  - Records are pushed to cache.push_bar() as they arrive.
  - A separate refresh thread runs compute.run_full_compute_cycle() on schedule.
  - A fast-refresh thread runs compute.run_flow_patch_cycle() more frequently.

Reconnect strategy:
  - On BentoError or connection drop, wait RECONNECT_DELAY_SECS and reconnect.
  - On consecutive failures > MAX_RECONNECT_ATTEMPTS, log and sleep longer
    (avoids hammering the API on persistent outage).

Thread safety:
  - All cache writes go through cache.py's locks (see concurrency-shared-mutables.md).
  - The reconnect loop and refresh loop are independent threads; they share
    no state directly except through cache.py's guarded structures.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

import databento as db

from . import cache, compute, config

logger = logging.getLogger(__name__)

_RECONNECT_DELAY_SECS = 10
_MAX_RECONNECT_ATTEMPTS = 5
_RECONNECT_BACKOFF_SECS = 120

# VIX symbol on EQUS.MINI
_VIX_SYMBOL = "VIX"

_feed_thread: threading.Thread | None = None
_refresh_thread: threading.Thread | None = None
_flow_refresh_thread: threading.Thread | None = None
_stop_event = threading.Event()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _record_to_bar(record: Any) -> dict[str, Any] | None:
    """Convert a DBN OhlcvMsg record to a plain bar dict."""
    try:
        return {
            "open": getattr(record, "open", 0) / 1e9,
            "high": getattr(record, "high", 0) / 1e9,
            "low": getattr(record, "low", 0) / 1e9,
            "close": getattr(record, "close", 0) / 1e9,
            "volume": getattr(record, "volume", 0),
            "ts_event": getattr(record.hd, "ts_event", 0),
        }
    except Exception:
        return None


def _symbol_from_record(record: Any, symmap: dict[int, str]) -> str | None:
    """Resolve instrument_id → ticker symbol via the session symmap."""
    try:
        iid = record.hd.instrument_id
        return symmap.get(iid)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Feed consumer loop
# ---------------------------------------------------------------------------

def _run_feed_loop(stop: threading.Event) -> None:
    """Persistent reconnect loop for the db.Live() consumer."""
    consecutive_failures = 0
    rolling = config.rolling_bars()
    cache.init_bar_cache(rolling)

    while not stop.is_set():
        symmap: dict[int, str] = {}
        client: db.Live | None = None
        try:
            key = config.databento_api_key()
            client = db.Live(key=key)
            client.subscribe(
                dataset="EQUS.MINI",
                schema="ohlcv-1m",
                symbols="ALL_SYMBOLS",
                stype_in="raw_symbol",
            )
            logger.info("db.Live() connected — subscribing EQUS.MINI ohlcv-1m ALL_SYMBOLS")
            consecutive_failures = 0

            for record in client:
                if stop.is_set():
                    break

                rec_type = type(record).__name__

                # Symbol mapping record — build instrument_id → ticker map
                if rec_type == "SymbolMappingMsg":
                    try:
                        raw = record.stype_in_symbol or ""
                        iid = record.hd.instrument_id
                        if raw:
                            symmap[iid] = raw.upper()
                    except Exception:
                        logger.debug("SymbolMappingMsg parse error", exc_info=True)
                    continue

                # Skip system records that aren't OHLCV data
                if "Ohlcv" not in rec_type and "Bar" not in rec_type:
                    continue

                sym = _symbol_from_record(record, symmap)
                if sym is None:
                    continue

                bar = _record_to_bar(record)
                if bar is None:
                    continue

                cache.push_bar(sym, bar)

                # Track VIX separately
                if sym == _VIX_SYMBOL and bar.get("close"):
                    cache.set_vix(bar["close"])

        except db.BentoError as exc:
            consecutive_failures += 1
            logger.warning(
                "db.Live() BentoError (attempt %d/%d): %s",
                consecutive_failures, _MAX_RECONNECT_ATTEMPTS, exc,
            )
        except Exception as exc:
            consecutive_failures += 1
            logger.warning("db.Live() unexpected error: %s", exc)
        finally:
            if client is not None:
                try:
                    client.stop()
                except Exception:
                    logger.debug("client.stop() error during cleanup", exc_info=True)

        if stop.is_set():
            break

        delay = (
            _RECONNECT_BACKOFF_SECS
            if consecutive_failures >= _MAX_RECONNECT_ATTEMPTS
            else _RECONNECT_DELAY_SECS
        )
        logger.info("Feed reconnecting in %ds …", delay)
        stop.wait(delay)

    logger.info("Feed thread stopped.")


# ---------------------------------------------------------------------------
# Refresh loop
# ---------------------------------------------------------------------------

def _run_refresh_loop(stop: threading.Event) -> None:
    """Full overlay recompute on the standard refresh cadence."""
    secs = config.refresh_secs()
    # Stagger first run: wait one cycle so bars have time to accumulate
    stop.wait(min(secs, 60))  # wait at most 60s on startup
    while not stop.is_set():
        t0 = time.monotonic()
        try:
            n = compute.run_full_compute_cycle()
            elapsed = time.monotonic() - t0
            logger.info("Full overlay computed: %d symbols in %.1fs", n, elapsed)
        except Exception as exc:
            logger.error("Full overlay compute error: %s", exc)
        stop.wait(secs)
    logger.info("Refresh thread stopped.")


def _run_flow_refresh_loop(stop: threading.Event) -> None:
    """Fast flow-field patch on the short cadence."""
    secs = config.flow_refresh_secs()
    stop.wait(secs)  # wait one full cycle before first run
    while not stop.is_set():
        t0 = time.monotonic()
        try:
            n = compute.run_flow_patch_cycle()
            elapsed = time.monotonic() - t0
            logger.debug("Flow patch: %d symbols in %.1fs", n, elapsed)
        except Exception as exc:
            logger.error("Flow patch error: %s", exc)
        stop.wait(secs)
    logger.info("Flow refresh thread stopped.")


# ---------------------------------------------------------------------------
# Public start / stop API (called from main.py lifespan)
# ---------------------------------------------------------------------------

def start() -> None:
    """Start the three background threads (feed + refresh + flow refresh)."""
    global _feed_thread, _refresh_thread, _flow_refresh_thread

    _stop_event.clear()

    _feed_thread = threading.Thread(
        target=_run_feed_loop, args=(_stop_event,), daemon=True, name="live-feed"
    )
    _refresh_thread = threading.Thread(
        target=_run_refresh_loop, args=(_stop_event,), daemon=True, name="overlay-refresh"
    )
    _flow_refresh_thread = threading.Thread(
        target=_run_flow_refresh_loop,
        args=(_stop_event,),
        daemon=True,
        name="flow-refresh",
    )

    _feed_thread.start()
    _refresh_thread.start()
    _flow_refresh_thread.start()
    logger.info("Live feed + overlay refresh threads started.")


def stop() -> None:
    """Signal all background threads to stop and wait for them."""
    _stop_event.set()
    for thread in (_feed_thread, _refresh_thread, _flow_refresh_thread):
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)
    logger.info("All feed threads stopped.")

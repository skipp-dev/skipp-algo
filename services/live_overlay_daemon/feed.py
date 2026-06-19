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

import asyncio
import atexit
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
_feed_ready = threading.Event()
_last_bar_at: float = 0.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _record_to_bar(record: Any) -> dict[str, Any] | None:
    """Convert a DBN OhlcvMsg record to a plain bar dict."""
    try:
        # Require at least one Databento OHLCV attribute to be present; plain
        # Python objects (e.g. object()) have none of these and must yield None.
        if not (hasattr(record, "open") or hasattr(record, "high") or hasattr(record, "low") or hasattr(record, "close")):
            return None

        def _price(name: str) -> float | None:
            val = getattr(record, name, None)
            return (val / 1e9) if val is not None else None

        return {
            "open": _price("open"),
            "high": _price("high"),
            "low": _price("low"),
            "close": _price("close"),
            "volume": getattr(record, "volume", 0),
            # ts_event is a top-level field on OHLCVMsg, not under .hd
            "ts_event": _ts if (_ts := getattr(record, "ts_event", None)) is not None else getattr(getattr(record, "hd", None), "ts_event", 0),
        }
    except Exception:
        return None


def _symbol_from_record(record: Any, symmap: dict[int, str]) -> str | None:
    """Resolve instrument_id → ticker symbol via the session symmap."""
    try:
        # instrument_id is available directly on the record (not only via .hd)
        iid = getattr(record, "instrument_id", None)
        if iid is None:
            iid = getattr(getattr(record, "hd", None), "instrument_id", None)
        if iid is None:
            return None
        sym = symmap.get(iid)
        return sym.upper() if sym else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Feed consumer loop
# ---------------------------------------------------------------------------

def _run_feed_loop(stop: threading.Event) -> None:
    """Persistent reconnect loop for the db.Live() consumer."""
    # databento.live uses asyncio internally. Background threads have no
    # event loop by default — set one explicitly to avoid uvloop transport errors.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        consecutive_failures = 0
        max_failures = config.max_feed_failures()
        rolling = config.rolling_bars()
        cache.init_bar_cache(rolling, max_symbols=config.max_symbols())

        while not stop.is_set():
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

                # Build symbology map from SymbolMappingMsg records
                # yielded by the iterator (no private-attr access).
                symmap: dict[int, str] = {}

                _rec_count = 0
                _ohlcv_count = 0
                _sym_none_count = 0
                _bar_none_count = 0
                _bars_pushed_count = 0
                for record in client:
                    if stop.is_set():
                        break

                    rec_type = type(record).__name__
                    _rec_count += 1
                    if _rec_count % 2000 == 0:
                        logger.debug(
                            "Feed stats: total=%d symmap=%d ohlcv=%d sym_none=%d bar_none=%d bars_pushed=%d",
                            _rec_count, len(symmap), _ohlcv_count, _sym_none_count,
                            _bar_none_count, _bars_pushed_count,
                        )

                    # Handle SymbolMappingMsg to build symbology map
                    if rec_type == "SymbolMappingMsg":
                        iid = getattr(record, "instrument_id", None)
                        raw = getattr(record, "stype_out_symbol", None) or getattr(record, "raw_symbol", None)
                        if iid is not None and raw:
                            symmap[iid] = raw
                        continue

                    # Skip system records that aren't OHLCV data
                    rec_type_upper = rec_type.upper()
                    if "OHLCV" not in rec_type_upper and "BAR" not in rec_type_upper:
                        continue

                    _ohlcv_count += 1
                    if _ohlcv_count == 1:
                        logger.info("First OHLCV record: type=%s symmap_size=%d", rec_type, len(symmap))

                    sym = _symbol_from_record(record, symmap)
                    if sym is None:
                        _sym_none_count += 1
                        if _sym_none_count <= 3:
                            logger.warning(
                                "sym=None for instrument_id=%s symmap_size=%d",
                                getattr(record, "instrument_id", "?"),
                                len(symmap),
                            )
                        continue

                    bar = _record_to_bar(record)
                    if bar is None:
                        _bar_none_count += 1
                        if _bar_none_count <= 3:
                            logger.warning("bar=None for sym=%s rec_type=%s", sym, rec_type)
                        continue

                    cache.push_bar(sym, bar)
                    _bars_pushed_count += 1

                    global _last_bar_at
                    _last_bar_at = time.monotonic()

                    if not _feed_ready.is_set():
                        _feed_ready.set()
                        logger.info("Feed ready — first bar pushed for %s", sym)

                    # Track VIX separately — use explicit None-check so that a
                    # zero close (corrupted tick) is still cached rather than
                    # silently dropped by a falsy test.
                    if sym == _VIX_SYMBOL and bar.get("close") is not None:
                        cache.set_vix(bar["close"])

            except db.BentoError as exc:
                consecutive_failures += 1
                _feed_ready.clear()
                logger.warning(
                    "db.Live() BentoError (attempt %d/%d): %s",
                    consecutive_failures, _MAX_RECONNECT_ATTEMPTS, exc,
                    exc_info=True,
                )
            except Exception as exc:
                consecutive_failures += 1
                _feed_ready.clear()
                logger.warning("db.Live() unexpected error: %s", exc, exc_info=True)
            finally:
                if client is not None:
                    try:
                        client.stop()
                    except Exception:
                        logger.debug("client.stop() error during cleanup", exc_info=True)

            if stop.is_set():
                break

            # Signal unhealthy during reconnect — /health must not report
            # "ok" while the feed is disconnected (F2.1).
            _feed_ready.clear()

            if consecutive_failures >= max_failures:
                logger.critical(
                    "Feed loop exceeded %d consecutive failures — "
                    "circuit-breaker triggered, thread stopping.",
                    max_failures,
                )
                _feed_ready.clear()
                break

            delay = (
                _RECONNECT_BACKOFF_SECS
                if consecutive_failures >= _MAX_RECONNECT_ATTEMPTS
                else _RECONNECT_DELAY_SECS
            )
            logger.info("Feed reconnecting in %ds …", delay)
            stop.wait(delay)

        logger.info("Feed thread stopped.")
    finally:
        loop.close()


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
            logger.error("Full overlay compute error: %s", exc, exc_info=True)
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
            logger.error("Flow patch error: %s", exc, exc_info=True)
        stop.wait(secs)
    logger.info("Flow refresh thread stopped.")


# ---------------------------------------------------------------------------
# Public start / stop API (called from main.py lifespan)
# ---------------------------------------------------------------------------

def start() -> None:
    """Start the three background threads (feed + refresh + flow refresh)."""
    global _feed_thread, _refresh_thread, _flow_refresh_thread

    if _feed_thread is not None and _feed_thread.is_alive():
        logger.warning("start() called while feed threads are already running — ignoring.")
        return

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

    # Safety-net shutdown hook: the three threads are daemon=True, so an exit
    # path that bypasses the FastAPI lifespan (e.g. an unhandled exception or a
    # bare process exit) would hard-kill them before client.stop() / loop.close()
    # run, leaking Databento sockets/FDs. atexit fires on normal interpreter
    # shutdown and blocks on stop() (bounded join), giving the loop a chance to
    # close cleanly. unregister-then-register keeps exactly one hook across
    # stop()/start() restart cycles; stop() is idempotent and join-bounded.
    atexit.unregister(stop)
    atexit.register(stop)
    logger.info("Live feed + overlay refresh threads started.")


def stop() -> None:
    """Signal all background threads to stop and wait for them."""
    _stop_event.set()
    _feed_ready.clear()
    for thread in (_feed_thread, _refresh_thread, _flow_refresh_thread):
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)
    logger.info("All feed threads stopped.")


def is_ready() -> bool:
    """Return True if the feed is connected and bars are not stale."""
    if not _feed_ready.is_set():
        return False
    if _last_bar_at <= 0:
        return False
    return (time.monotonic() - _last_bar_at) < config.max_stale_secs()


def last_bar_age_secs() -> float | None:
    """Return seconds since the last bar was pushed, or None if never."""
    if _last_bar_at <= 0:
        return None
    return time.monotonic() - _last_bar_at

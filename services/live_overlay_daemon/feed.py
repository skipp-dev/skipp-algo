"""
Live feed consumer — runs in a daemon background thread.

Architecture:
  - One db.Live() connection subscribes to EQUS.MINI ohlcv-1m ALL_SYMBOLS.
  - Records are enqueued and drained by a separate ingest thread into cache.push_bar().
  - A separate refresh thread runs compute.run_full_compute_cycle() on schedule.
  - A fast-refresh thread runs compute.run_flow_patch_cycle() more frequently.

Reconnect strategy:
  - On BentoError or connection drop, wait RECONNECT_DELAY_SECS and reconnect.
  - On consecutive failures >= MAX_RECONNECT_ATTEMPTS, log and sleep longer
    (avoids hammering the API on persistent outage).

Thread safety:
  - All cache writes go through cache.py's locks (see concurrency-shared-mutables.md).
  - The reconnect, ingest, refresh and supervisor loops are independent threads;
    they share feed-local mutables via feed.py's own locks + cache.py's guards.
"""
from __future__ import annotations

import asyncio
import atexit
import logging
import os
import queue
import threading
import time
from typing import Any

import databento as db

from . import cache, compute, config, market_hours
from .observability import metric_counter

logger = logging.getLogger(__name__)

_RECONNECT_DELAY_SECS = 10
_MAX_RECONNECT_ATTEMPTS = 5
_RECONNECT_BACKOFF_SECS = 120
_INGEST_STOP_SENTINEL = object()

# VIX index level — polled from FMP's ^VIX quote (the CBOE index does not trade
_VIX_FMP_SYMBOL = "^VIX"  # on EQUS.MINI; only ETFs like VIXY resolve there, so bars can't supply it

_feed_thread: threading.Thread | None = None
_refresh_thread: threading.Thread | None = None
_flow_refresh_thread: threading.Thread | None = None
_stop_event = threading.Event()
_feed_ready = threading.Event()
_last_bar_at: float = 0.0
_feed_connected_at: float = 0.0
_runtime: dict[str, Any] = {
    "ingest_thread": None,
    "ingest_queue": None,
    "ingest_queue_max": 0,
    # Supervisor self-heal (WP1): the active db.Live() client (so the
    # supervisor can break a blocked iterator) and the supervisor thread
    # handle. Kept in _runtime to avoid a new module-level `global` statement.
    "supervisor_thread": None,
    "active_client": None,
}
_metrics_lock = threading.Lock()
_metrics: dict[str, int] = {
    "reconnect_attempts": 0,
    "bento_errors": 0,
    "unexpected_errors": 0,
    "circuit_breakers": 0,
    "partial_restarts": 0,
    "supervisor_heals": 0,
}
_backpressure_lock = threading.Lock()
_backpressure: dict[str, float] = {
    "ingest_queue_depth_max": 0.0,
    "ingest_queue_dropped_total": 0.0,
    "ingest_queue_lag_ms_last": 0.0,
    "ingest_queue_lag_ms_max": 0.0,
}

# Guard all lifecycle mutations (start/stop/worker reads) against races.
_lifecycle_lock = threading.Lock()

# ── Supervisor self-heal (WP1) ──────────────────────────────────────────────
# Guards _runtime["active_client"] so the supervisor can break a blocked
# ``for record in client:`` iterator during a silent stall.
_active_client_lock = threading.Lock()
# Set on a non-retryable configuration error so the supervisor escalates to a
# process restart (operator attention) instead of futile self-heal attempts.
_fatal_config_error = threading.Event()

_SUPERVISOR_INTERVAL_SECS = 30.0
_STALL_MAX_BAR_AGE_SECS = 180.0   # 3 min without a bar during RTH = stall
_SELF_HEAL_MAX_ATTEMPTS = 3


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _price_from_record(record: Any, name: str) -> float | None:
    """Read a nanodollar price field from a Databento record and scale to float."""
    val = getattr(record, name, None)
    return (val / 1e9) if val is not None else None

def _record_to_bar(record: Any) -> dict[str, Any] | None:
    """Convert a DBN OhlcvMsg record to a plain bar dict."""
    try:
        # Require at least one Databento OHLCV attribute to be present; plain
        # Python objects (e.g. object()) have none of these and must yield None.
        if not (hasattr(record, "open") or hasattr(record, "high") or hasattr(record, "low") or hasattr(record, "close")):
            return None

        return {
            "open": _price_from_record(record, "open"),
            "high": _price_from_record(record, "high"),
            "low": _price_from_record(record, "low"),
            "close": _price_from_record(record, "close"),
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


def _poll_vix_from_fmp() -> None:
    """Refresh the cached VIX level from FMP's ^VIX quote.

    The CBOE volatility index is not on the EQUS.MINI bar feed (only ETFs like
    VIXY resolve there), so it is polled from FMP on the overlay refresh cadence
    instead. Fail-soft: a missing FMP key, HTTP error, or non-finite price leaves
    the last cached value untouched. The loader is built once and cached in
    ``_runtime`` (``None`` sentinel = construction failed, do not retry) to avoid
    adding a module-level ``global``.
    """
    if "vix_loader" not in _runtime:
        try:
            from .fmp_data_loader import FMPDataLoader

            _runtime["vix_loader"] = FMPDataLoader()
        except Exception as exc:
            _runtime["vix_loader"] = None
            logger.warning("VIX poll disabled — FMP loader unavailable: %s", exc)
    loader = _runtime.get("vix_loader")
    if loader is None:
        return
    level = loader.get_quote(_VIX_FMP_SYMBOL)
    if level is not None:
        cache.set_vix(level)


def _inc_metric(name: str, amount: int = 1) -> None:
    with _metrics_lock:
        _metrics[name] = _metrics.get(name, 0) + amount
    # Also emit as structured observability counter for log-drain/metrics pipeline
    metric_counter(f"live_overlay.feed.{name}", float(amount))


def _metrics_snapshot() -> dict[str, int]:
    with _metrics_lock:
        return dict(_metrics)


def _record_enqueue_backpressure() -> None:
    with _backpressure_lock:
        ingest_queue = _runtime.get("ingest_queue")
        depth = float(ingest_queue.qsize()) if ingest_queue is not None else 0.0
        _backpressure["ingest_queue_depth_max"] = max(
            _backpressure.get("ingest_queue_depth_max", 0.0),
            depth,
        )


def _record_queue_drop() -> float:
    with _backpressure_lock:
        _backpressure["ingest_queue_dropped_total"] = (
            _backpressure.get("ingest_queue_dropped_total", 0.0) + 1.0
        )
        return _backpressure["ingest_queue_dropped_total"]


def _should_log_queue_drop_warning(dropped_total: float) -> bool:
    """Emit warning on first drop, then every 100 dropped bars."""
    dropped_count = int(dropped_total)
    return dropped_count > 0 and (dropped_count == 1 or dropped_count % 100 == 0)


def _record_queue_lag_ms(lag_ms: float) -> None:
    with _backpressure_lock:
        _backpressure["ingest_queue_lag_ms_last"] = lag_ms
        _backpressure["ingest_queue_lag_ms_max"] = max(
            _backpressure.get("ingest_queue_lag_ms_max", 0.0),
            lag_ms,
        )


def backpressure_snapshot() -> dict[str, float]:
    with _backpressure_lock:
        snapshot = dict(_backpressure)
    ingest_queue = _runtime.get("ingest_queue")
    snapshot["ingest_queue_depth"] = float(ingest_queue.qsize()) if ingest_queue is not None else 0.0
    return snapshot


_last_bar_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Feed consumer loop
# ---------------------------------------------------------------------------

def _run_feed_loop(stop: threading.Event) -> None:
    """Persistent reconnect loop for the db.Live() consumer."""
    global _feed_connected_at
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
                try:
                    key = config.databento_api_key()
                except RuntimeError as exc:
                    # Non-retryable local configuration error (e.g. missing
                    # DATABENTO_API_KEY) — retrying only creates log noise
                    # and delays operator feedback.
                    _feed_ready.clear()
                    _fatal_config_error.set()
                    logger.critical("Non-retryable feed configuration error: %s", exc)
                    break

                client = db.Live(key=key)
                with _active_client_lock:
                    _runtime["active_client"] = client
                client.subscribe(
                    dataset="EQUS.MINI",
                    schema="ohlcv-1m",
                    symbols="ALL_SYMBOLS",
                    stype_in="raw_symbol",
                )
                _feed_connected_at = time.monotonic()
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

                    ingest_queue = _runtime.get("ingest_queue")
                    if ingest_queue is None:
                        continue
                    try:
                        ingest_queue.put_nowait((sym, bar, time.monotonic()))
                        _record_enqueue_backpressure()
                        _bars_pushed_count += 1
                    except queue.Full:
                        dropped_total = _record_queue_drop()
                        if _should_log_queue_drop_warning(dropped_total):
                            logger.warning(
                                "Ingest queue full — dropping newest bar (dropped_total=%d)",
                                int(dropped_total),
                            )

            except db.BentoError as exc:
                consecutive_failures += 1
                _inc_metric("bento_errors")
                _feed_ready.clear()
                logger.warning(
                    "db.Live() BentoError (failure %d/%d before circuit-break): %s",
                    consecutive_failures, max_failures, exc,
                    exc_info=True,
                )
            except Exception as exc:
                consecutive_failures += 1
                _inc_metric("unexpected_errors")
                _feed_ready.clear()
                logger.warning("db.Live() unexpected error: %s", exc, exc_info=True)
            finally:
                with _active_client_lock:
                    _runtime["active_client"] = None
                _feed_connected_at = 0.0
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
                _inc_metric("circuit_breakers")
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
            _inc_metric("reconnect_attempts")
            logger.info("Feed reconnecting in %ds …", delay)
            stop.wait(delay)

        logger.info("Feed thread stopped.")
    finally:
        loop.close()


def _run_ingest_loop(stop: threading.Event) -> None:
    """Drain feed queue into cache and compute backpressure telemetry."""
    while True:
        ingest_queue = _runtime.get("ingest_queue")
        if stop.is_set() and (ingest_queue is None or ingest_queue.empty()):
            break
        if ingest_queue is None:
            stop.wait(0.2)
            continue
        try:
            item = ingest_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        if item is _INGEST_STOP_SENTINEL:
            ingest_queue.task_done()
            if stop.is_set():
                break
            continue

        sym, bar, queued_at = item

        cache.push_bar(sym, bar)

        now = time.monotonic()
        _record_queue_lag_ms(max(0.0, (now - queued_at) * 1000.0))

        global _last_bar_at
        with _last_bar_lock:
            _last_bar_at = now
            if not stop.is_set() and not _feed_ready.is_set():
                _feed_ready.set()
                logger.info("Feed ready — first bar pushed for %s", sym)

        ingest_queue.task_done()
    logger.info("Ingest thread stopped.")


# ---------------------------------------------------------------------------
# Refresh loop
# ---------------------------------------------------------------------------

def _run_refresh_loop(stop: threading.Event) -> None:
    """Full overlay recompute on the standard refresh cadence."""
    secs = config.refresh_secs()
    # Stagger first run: wait up to 60s so bars have time to accumulate
    stop.wait(min(secs, 60))  # wait at most 60s on startup
    while not stop.is_set():
        t0 = time.monotonic()
        try:
            _poll_vix_from_fmp()  # refresh cache.get_vix() before compute reads it
            n = compute.run_full_compute_cycle()
            elapsed = time.monotonic() - t0
            logger.info("Full overlay computed: %d symbols in %.1fs", n, elapsed)
        except Exception as exc:
            metric_counter("live_overlay.full_compute_cycle.errors")
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
            metric_counter("live_overlay.flow_patch_cycle.errors")
            logger.error("Flow patch error: %s", exc, exc_info=True)
        stop.wait(secs)
    logger.info("Flow refresh thread stopped.")


# ---------------------------------------------------------------------------
# Supervisor — self-heal dead/stalled workers (WP1)
# ---------------------------------------------------------------------------

def _escalate_to_platform_restart(code: int = 1) -> None:
    """Terminate the process so the platform restart policy (Railway
    ``ON_FAILURE``) takes over.

    Isolated behind a module-level function so tests can monkeypatch it: a
    ``SystemExit`` raised in a non-main thread does NOT stop the process, so
    ``os._exit`` is the only reliable escalation from the supervisor thread.
    """
    os._exit(code)


def _supervisor_break_stalled_client() -> None:
    """Break a blocked ``for record in client:`` loop so the feed thread runs
    into its reconnect path. Safe no-op when no client is currently active."""
    with _active_client_lock:
        client = _runtime.get("active_client")
    if client is None:
        return
    try:
        client.stop()
    except Exception:
        logger.debug("supervisor client.stop() failed", exc_info=True)


def _run_supervisor_loop(stop: threading.Event) -> None:
    """Self-heal dead/stalled feed workers; escalate to a process restart so
    the platform ``ON_FAILURE`` policy takes over when healing keeps failing.

    Detection every ``_SUPERVISOR_INTERVAL_SECS``:
      * dead worker threads via ``worker_liveness()``;
      * silent feed stalls (no bar for > ``_STALL_MAX_BAR_AGE_SECS`` during a
        US regular session) via ``last_bar_age_secs()``.
    Remediation, in order:
      * a stall breaks the blocked iterator with ``client.stop()`` so the feed
        loop reconnects;
      * dead workers are re-armed via the idempotent ``start()`` partial restart;
      * a non-retryable config error, or ``_SELF_HEAL_MAX_ATTEMPTS`` exhausted,
        escalates to a process restart.
    """
    heal_attempts = 0
    while not stop.wait(_SUPERVISOR_INTERVAL_SECS):
        if _fatal_config_error.is_set():
            logger.critical(
                "Supervisor: non-retryable feed configuration error — "
                "escalating to process restart for operator attention."
            )
            _escalate_to_platform_restart()
            return

        workers = worker_liveness()
        stalled = False
        if market_hours.is_us_regular_session_open():
            age = last_bar_age_secs()
            if age is not None:
                stalled = age > _STALL_MAX_BAR_AGE_SECS
            elif _feed_connected_at > 0:
                # Connected but never delivered a single bar: entitlement or
                # empty-subscription wedges are operationally stale too.
                stalled = (time.monotonic() - _feed_connected_at) > _STALL_MAX_BAR_AGE_SECS

        if all(workers.values()) and not stalled:
            heal_attempts = 0
            continue

        heal_attempts += 1
        _inc_metric("supervisor_heals")
        logger.critical(
            "Supervisor: workers=%s stalled=%s — heal attempt %d/%d",
            workers, stalled, heal_attempts, _SELF_HEAL_MAX_ATTEMPTS,
        )
        if heal_attempts > _SELF_HEAL_MAX_ATTEMPTS:
            logger.critical(
                "Supervisor: self-heal exhausted (%d/%d) — escalating; "
                "platform ON_FAILURE policy restarts the process.",
                _SELF_HEAL_MAX_ATTEMPTS, _SELF_HEAL_MAX_ATTEMPTS,
            )
            _escalate_to_platform_restart()
            return

        if stalled:
            # Break the blocked iterator → feed loop enters its reconnect path.
            _supervisor_break_stalled_client()
        if not all(workers.values()):
            if stop.is_set():
                return
            # Idempotent partial restart under the lifecycle lock; re-arms only
            # dead threads. The supervisor itself stays alive, so _do_start's
            # supervisor branch is a no-op.
            try:
                start()
            except Exception:
                logger.error("Supervisor partial restart failed", exc_info=True)

    logger.info("Supervisor thread stopped.")


def start() -> None:
    """Start the five background threads (feed + ingest + refresh + flow refresh + supervisor)."""
    with _lifecycle_lock:
        _do_start()


def reset_lifecycle_for_restart() -> None:
    """Explicit opt-in for controlled stop() -> start() restart sequences."""
    with _lifecycle_lock:
        _stop_event.clear()


def _do_start() -> None:
    """Unsynchronized start implementation; callers must hold _lifecycle_lock."""
    global _feed_thread, _refresh_thread, _flow_refresh_thread

    desired_queue_max = config.ingest_queue_max()
    ingest_thread = _runtime.get("ingest_thread")
    workers_alive = (
        (_feed_thread is not None and _feed_thread.is_alive())
        or (ingest_thread is not None and ingest_thread.is_alive())
        or (_refresh_thread is not None and _refresh_thread.is_alive())
        or (_flow_refresh_thread is not None and _flow_refresh_thread.is_alive())
    )
    if _runtime.get("ingest_queue") is None or (_runtime.get("ingest_queue_max") != desired_queue_max and not workers_alive):
        _runtime["ingest_queue"] = queue.Queue(maxsize=desired_queue_max)
        _runtime["ingest_queue_max"] = desired_queue_max
    elif _runtime.get("ingest_queue_max") != desired_queue_max:
        logger.warning(
            "LIVE_OVERLAY_INGEST_QUEUE_MAX changed from %d to %d while workers are alive; "
            "queue resize ignored until next restart.",
            _runtime["ingest_queue_max"],
            desired_queue_max,
        )

    feed_alive = _feed_thread is not None and _feed_thread.is_alive()
    ingest_alive = ingest_thread is not None and ingest_thread.is_alive()
    refresh_alive = _refresh_thread is not None and _refresh_thread.is_alive()
    flow_alive = _flow_refresh_thread is not None and _flow_refresh_thread.is_alive()
    supervisor_thread = _runtime.get("supervisor_thread")
    supervisor_alive = supervisor_thread is not None and supervisor_thread.is_alive()

    # Idempotent no-op when every worker is already healthy.
    if feed_alive and ingest_alive and refresh_alive and flow_alive and supervisor_alive:
        logger.warning("start() called while all workers alive — ignoring")
        return

    if _stop_event.is_set():
        logger.warning("start() called while stop event is set — ignoring")
        return

    started: list[str] = []
    if not feed_alive:
        _feed_thread = threading.Thread(
            target=_run_feed_loop, args=(_stop_event,), daemon=True, name="live-feed"
        )
        _feed_thread.start()
        started.append("live-feed")

    if not ingest_alive:
        ingest_thread = threading.Thread(
            target=_run_ingest_loop, args=(_stop_event,), daemon=True, name="ingest-processor"
        )
        ingest_thread.start()
        _runtime["ingest_thread"] = ingest_thread
        started.append("ingest-processor")

    if not refresh_alive:
        _refresh_thread = threading.Thread(
            target=_run_refresh_loop, args=(_stop_event,), daemon=True, name="overlay-refresh"
        )
        _refresh_thread.start()
        started.append("overlay-refresh")

    if not flow_alive:
        _flow_refresh_thread = threading.Thread(
            target=_run_flow_refresh_loop,
            args=(_stop_event,),
            daemon=True,
            name="flow-refresh",
        )
        _flow_refresh_thread.start()
        started.append("flow-refresh")

    # Supervisor self-heal thread (WP1): tracked in _runtime so it can be
    # re-armed by an idempotent partial restart if it ever dies.
    if not supervisor_alive:
        supervisor_thread = threading.Thread(
            target=_run_supervisor_loop, args=(_stop_event,), daemon=True,
            name="live-overlay-supervisor",
        )
        supervisor_thread.start()
        _runtime["supervisor_thread"] = supervisor_thread
        started.append("live-overlay-supervisor")

    if started and (feed_alive or ingest_alive or refresh_alive or flow_alive):
        _inc_metric("partial_restarts")

    # Safety-net shutdown hook: the background threads are daemon=True, so an exit
    # path that bypasses the FastAPI lifespan (e.g. an unhandled exception or a
    # bare process exit) would hard-kill them before client.stop() / loop.close()
    # run, leaking Databento sockets/FDs. atexit fires on normal interpreter
    # shutdown and blocks on stop() (bounded join), giving the loop a chance to
    # close cleanly. unregister-then-register keeps exactly one hook across
    # stop()/start() restart cycles; stop() is idempotent and join-bounded.
    atexit.unregister(stop)

    atexit.register(stop)
    logger.info("Live feed workers started/recovered: %s", ", ".join(started) if started else "none")


def stop() -> None:
    """Signal all background threads to stop and wait for them."""
    global _feed_thread, _refresh_thread, _flow_refresh_thread
    with _lifecycle_lock:
        _stop_event.set()
        _feed_ready.clear()
        if _feed_thread is not None and _feed_thread.is_alive() and hasattr(_feed_thread, "join"):
            _feed_thread.join(timeout=5)
        ingest_thread = _runtime.get("ingest_thread")
        ingest_queue = _runtime.get("ingest_queue")
        if ingest_queue is not None and ingest_thread is not None and ingest_thread.is_alive():
            try:
                # Wake a potentially blocked queue.get(timeout=0.5) so stop()
                # does not need to wait for timeout jitter during teardown.
                ingest_queue.put_nowait(_INGEST_STOP_SENTINEL)
            except queue.Full:
                # If full, the ingest loop is already actively draining.
                pass
        if ingest_thread is not None and ingest_thread.is_alive() and hasattr(ingest_thread, "join"):
            ingest_thread.join(timeout=5)
        if _refresh_thread is not None and _refresh_thread.is_alive() and hasattr(_refresh_thread, "join"):
            _refresh_thread.join(timeout=5)
        if _flow_refresh_thread is not None and _flow_refresh_thread.is_alive() and hasattr(_flow_refresh_thread, "join"):
            _flow_refresh_thread.join(timeout=5)
        supervisor_thread = _runtime.get("supervisor_thread")
        if supervisor_thread is not None and supervisor_thread.is_alive() and hasattr(supervisor_thread, "join"):
            supervisor_thread.join(timeout=5)

        if _feed_thread is None or not _feed_thread.is_alive():
            _feed_thread = None
        if _refresh_thread is None or not _refresh_thread.is_alive():
            _refresh_thread = None
        if ingest_thread is None or not ingest_thread.is_alive():
            _runtime["ingest_thread"] = None
        if _flow_refresh_thread is None or not _flow_refresh_thread.is_alive():
            _flow_refresh_thread = None
        if supervisor_thread is None or not supervisor_thread.is_alive():
            _runtime["supervisor_thread"] = None
        # Defensive clear after joins: the feed thread can still race to set
        # readiness during shutdown; stop() must always end in not-ready state.
        _feed_ready.clear()
        still_alive = {
            "live_feed": _feed_thread is not None and _feed_thread.is_alive(),
            "ingest_processor": ingest_thread is not None and ingest_thread.is_alive(),
            "overlay_refresh": _refresh_thread is not None and _refresh_thread.is_alive(),
            "flow_refresh": _flow_refresh_thread is not None and _flow_refresh_thread.is_alive(),
        }
        # Late teardown: logging handlers may already have closed streams
        # (e.g. pytest capture or atexit ordering).  Guard against ValueError
        # so stop() never raises during interpreter shutdown.
        try:
            if any(still_alive.values()):
                logger.warning("Stop requested; bounded joins ended with workers still alive: %s", still_alive)
            else:
                logger.info("All feed threads stopped.")
        except (ValueError, OSError):
            pass


def is_ready() -> bool:
    """Return True if the feed is connected and bars are not stale."""
    if not _feed_ready.is_set():
        return False
    with _last_bar_lock:
        last_bar_at = _last_bar_at
    if last_bar_at <= 0:
        return False
    return (time.monotonic() - last_bar_at) < config.max_stale_secs()


def last_bar_age_secs() -> float | None:
    """Return seconds since the last bar was pushed, or None if never."""
    with _last_bar_lock:
        last_bar_at = _last_bar_at
    if last_bar_at <= 0:
        return None
    return time.monotonic() - last_bar_at


def worker_liveness() -> dict[str, bool]:
    """Return per-worker liveness flags for operational health reporting."""
    with _lifecycle_lock:
        ingest_thread = _runtime.get("ingest_thread")
        return {
            "live_feed": _feed_thread is not None and _feed_thread.is_alive(),
            "ingest_processor": ingest_thread is not None and ingest_thread.is_alive(),
            "overlay_refresh": _refresh_thread is not None and _refresh_thread.is_alive(),
            "flow_refresh": _flow_refresh_thread is not None and _flow_refresh_thread.is_alive(),
        }


def metrics_snapshot() -> dict[str, int]:
    """Return feed counters for /health observability payload."""
    return _metrics_snapshot()

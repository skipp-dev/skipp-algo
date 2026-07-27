"""Databento live-bar cache feed (Task 1.2 of the signal-migration plan).

Builds a process-internal ``db.Live`` consumer for ``EQUS.MINI`` /
``ohlcv-1s`` against an explicit symbol list, filling a thread-safe
per-symbol bar cache. This module is deliberately narrow — cache-filling
only, no compute/refresh threads — so a later task (1.3) can turn the cache
into FMP-compatible quote rows without touching signal-detection logic.

Ported patterns (see task-1.2-report.md for the full mapping):

- Reconnect loop (persistent retry, ``db.BentoError``/unexpected-error
  handling, backoff, circuit breaker, per-thread asyncio event loop, an
  ingest queue drained by a separate thread) — ported from
  ``services/live_overlay_daemon/feed.py``.
- Explicit-symbol ``ohlcv-1s`` subscription with ``stype_in="raw_symbol"``
  and intraday replay via ``start=`` — ported from
  ``services/a0_fast_detector/live_runtime.py``.
- Cumulative regular-session volume semantics, including the RTH gate
  (pre-market/post-market/non-trading-day bars cause no cache mutation at
  all, mirroring ``OUTSIDE_SESSION``) and the reset at the ET session-date
  boundary — ported from ``open_prep/a0_stream_state.py``.
- ``data_age_ms`` formula (``max(0, ts_recv - ts_event) * 1000``) — ported
  from ``open_prep/a0_contract.py::build_market_snapshot``.

New in this module (no existing anchor covers it): the ``END_OF_INTERVAL``
SystemMsg (code 4) is used as a "second complete" barrier. OHLCV records are
staged into a per-connection ``_pending`` dict (owned solely by the ingest
thread) as they arrive; only when ``END_OF_INTERVAL`` is observed does the
ingest thread atomically flush that batch into the shared cache under one
lock acquisition. This guarantees a reader never observes a torn update
where some symbols reflect the new second and others don't. A trailing
partial batch (stream/test ends without a closing barrier) is flushed on
shutdown so no data is silently dropped.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import queue
import threading
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import databento as db

from newsstack_fmp._market_cal import (
    is_us_equity_trading_day,
    regular_session_close_minutes,
)

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
_PRICE_SCALE = 1e-9
_OPEN_MINUTES = 9 * 60 + 30  # 09:30 ET, mirrors open_prep/a0_stream_state.py

# databento_dbn.SystemCode values (see SystemMsg.code).
_SYSTEM_CODE_END_OF_INTERVAL = 4
_SYSTEM_CODE_REPLAY_COMPLETED = 3

_STOP_SENTINEL = object()
_BARRIER_SENTINEL = object()


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BarState:
    """One normalized ``ohlcv-1s`` bar. ``ts_event`` is the bar OPEN time."""

    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    ts_event: float
    ts_recv: float


@dataclass(slots=True)
class _SymbolCacheEntry:
    session_date: str
    latest_bar: BarState
    cumulative_volume: int
    session_high: float
    session_low: float


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------


class DatabentoFeedTelemetry:
    """Thread-safe counters/gauges for the feed, in the repo's homegrown
    structured-text Prometheus style (see ``A0FastTelemetry`` /
    ``PreA0Telemetry`` — no external ``prometheus_client`` dependency)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._connected = False
        self._records_received = 0
        self._record_rejections: Counter[str] = Counter()
        self._reconnect_attempts = 0
        self._bento_errors = 0
        self._unexpected_errors = 0
        self._circuit_breakers = 0
        self._supervisor_restarts = 0
        self._queue_dropped = 0
        self._replay_completions = 0
        self._last_data_age_ms: float | None = None
        self._max_data_age_ms = 0.0

    def set_connected(self, connected: bool) -> None:
        with self._lock:
            self._connected = bool(connected)

    def record_received(self) -> None:
        with self._lock:
            self._records_received += 1

    def record_rejected(self, reason: str) -> None:
        with self._lock:
            self._record_rejections[reason] += 1

    def record_reconnect_attempt(self) -> None:
        with self._lock:
            self._reconnect_attempts += 1

    def record_bento_error(self) -> None:
        with self._lock:
            self._bento_errors += 1

    def record_unexpected_error(self) -> None:
        with self._lock:
            self._unexpected_errors += 1

    def record_circuit_breaker(self) -> None:
        with self._lock:
            self._circuit_breakers += 1

    def record_supervisor_restart(self) -> None:
        with self._lock:
            self._supervisor_restarts += 1

    def record_queue_drop(self) -> None:
        with self._lock:
            self._queue_dropped += 1

    def record_replay_completed(self) -> None:
        with self._lock:
            self._replay_completions += 1

    def record_bar_age(self, ts_event: float, ts_recv: float) -> None:
        """Analogous to ``a0_contract.py::data_age_ms``: how stale the bar
        was when Databento stamped its receipt time, not wall-clock-at-read."""
        age_ms = max(0.0, (ts_recv - ts_event) * 1000.0)
        with self._lock:
            self._last_data_age_ms = age_ms
            self._max_data_age_ms = max(self._max_data_age_ms, age_ms)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "connected": self._connected,
                "records_received": self._records_received,
                "record_rejections": dict(self._record_rejections),
                "reconnect_attempts": self._reconnect_attempts,
                "bento_errors": self._bento_errors,
                "unexpected_errors": self._unexpected_errors,
                "circuit_breakers": self._circuit_breakers,
                "supervisor_restarts": self._supervisor_restarts,
                "queue_dropped": self._queue_dropped,
                "replay_completions": self._replay_completions,
                "data_age_ms": self._last_data_age_ms,
                "data_age_ms_max": self._max_data_age_ms,
            }

    def render_prometheus(self) -> str:
        snap = self.snapshot()
        lines = [
            _gauge("databento_quote_feed_connected", int(snap["connected"])),
            _counter("databento_quote_feed_records_received_total", snap["records_received"]),
            _counter("databento_quote_feed_reconnect_attempts_total", snap["reconnect_attempts"]),
            _counter("databento_quote_feed_bento_errors_total", snap["bento_errors"]),
            _counter("databento_quote_feed_unexpected_errors_total", snap["unexpected_errors"]),
            _counter("databento_quote_feed_circuit_breakers_total", snap["circuit_breakers"]),
            _counter("databento_quote_feed_supervisor_restarts_total", snap["supervisor_restarts"]),
            _counter("databento_quote_feed_queue_dropped_total", snap["queue_dropped"]),
            _counter("databento_quote_feed_replay_completions_total", snap["replay_completions"]),
            _gauge(
                "databento_quote_feed_data_age_ms",
                snap["data_age_ms"] if snap["data_age_ms"] is not None else 0.0,
            ),
            _gauge("databento_quote_feed_data_age_ms_max", snap["data_age_ms_max"]),
        ]
        lines.append("# TYPE databento_quote_feed_records_rejected_total counter\n")
        for reason, count in sorted(snap["record_rejections"].items()):
            lines.append(f'databento_quote_feed_records_rejected_total{{reason="{reason}"}} {count}\n')
        return "".join(lines)


def _counter(name: str, value: int | float) -> str:
    return f"# TYPE {name} counter\n{name} {value}\n"


def _gauge(name: str, value: int | float) -> str:
    return f"# TYPE {name} gauge\n{name} {value}\n"


# ---------------------------------------------------------------------------
# Record parsing helpers
# ---------------------------------------------------------------------------


def _epoch_seconds(value: Any) -> float:
    """Scale a Databento timestamp (ns/ms/s) to epoch seconds. Ported from
    ``open_prep/a0_stream.py::_epoch_seconds``."""
    epoch = float(value)
    if epoch >= 100_000_000_000_000_000:
        return epoch / 1_000_000_000.0
    if epoch >= 1_000_000_000_000:
        return epoch / 1000.0
    return epoch


def _session_date_et(ts_event: float) -> str:
    return datetime.fromtimestamp(ts_event, _ET).date().isoformat()


def _is_regular_session(ts_event: float) -> bool:
    """Regular-trading-hours gate — mirrors
    ``open_prep/a0_stream_state.py::A0StreamState.apply``'s ``OUTSIDE_SESSION``
    check (non-trading day, or before 09:30 / at-or-after the regular close,
    including early-close days). Pre-market and post-market bars are outside
    this window and must not reach the cache: the whole open_prep/a0 pipeline
    is RTH-centric, and the producer hot path this feed backs only runs while
    ``market_session == "regular"``."""
    event_et = datetime.fromtimestamp(ts_event, _ET)
    minute = event_et.hour * 60 + event_et.minute
    close_minute = regular_session_close_minutes(event_et.date())
    return is_us_equity_trading_day(event_et.date()) and _OPEN_MINUTES <= minute < close_minute


def _symbol_from_record(record: Any, symbol_map: dict[int, str]) -> str | None:
    """Resolve instrument_id -> ticker via the session symmap. Ported from
    ``services/live_overlay_daemon/feed.py::_symbol_from_record``."""
    try:
        iid = getattr(record, "instrument_id", None)
        if iid is None:
            iid = getattr(getattr(record, "hd", None), "instrument_id", None)
        if iid is None:
            return None
        sym = symbol_map.get(iid)
        return sym.upper() if sym else None
    except Exception:
        return None


def _parse_ohlcv_record(record: Any, *, symbol: str) -> BarState | None:
    """Convert a DBN OhlcvMsg record into a ``BarState``, or None if the
    record is malformed. Price scaling ported from feed.py/a0_stream.py."""
    try:
        raw_open = getattr(record, "open", None)
        raw_high = getattr(record, "high", None)
        raw_low = getattr(record, "low", None)
        raw_close = getattr(record, "close", None)
        raw_volume = getattr(record, "volume", None)
        raw_ts_event = getattr(record, "ts_event", None)
        if raw_ts_event is None:
            raw_ts_event = getattr(getattr(record, "hd", None), "ts_event", None)
        if (
            raw_open is None
            or raw_high is None
            or raw_low is None
            or raw_close is None
            or raw_volume is None
            or raw_ts_event is None
        ):
            return None

        ts_event = _epoch_seconds(raw_ts_event)
        raw_ts_recv = getattr(record, "ts_recv", None)
        # ts_recv absent (record shapes that omit it — e.g. some test fixtures)
        # falls back to ts_event so data_age_ms (max(0, ts_recv - ts_event) in
        # record_bar_age) reads 0 rather than a bogus negative/huge age; it is
        # never fabricated as "now". Mirrors a0_contract's receipt-time handling.
        ts_recv = _epoch_seconds(raw_ts_recv) if raw_ts_recv is not None else ts_event

        open_ = float(raw_open) * _PRICE_SCALE
        high = float(raw_high) * _PRICE_SCALE
        low = float(raw_low) * _PRICE_SCALE
        close = float(raw_close) * _PRICE_SCALE
        volume = int(raw_volume)
        if open_ <= 0 or high <= 0 or low <= 0 or close <= 0 or volume < 0:
            return None

        return BarState(
            symbol=symbol,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            ts_event=ts_event,
            ts_recv=ts_recv,
        )
    except Exception:
        return None


def _system_code_matches(record: Any, *, code_int: int, code_name: str) -> bool:
    """Match a SystemMsg's code, whichever shape it arrives in: the real
    ``databento_dbn.SystemCode`` enum (int-valued, via ``.value``), a bare
    int, or a plain string (test fixtures, mirroring a0's fake style)."""
    code = getattr(record, "code", None)
    if code is None:
        return False
    value = getattr(code, "value", code)
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value == code_int
    return str(value).strip().lower() == code_name


# ---------------------------------------------------------------------------
# Feed
# ---------------------------------------------------------------------------


class DatabentoQuoteFeed:
    """``db.Live(EQUS.MINI, ohlcv-1s)`` consumer with a thread-safe per-symbol
    bar cache, reconnect, and intraday replay.

    ``client_or_factory`` mirrors
    ``services.a0_fast_detector.live_runtime.start_live_reader``: either an
    already-constructed client (reused across reconnects — sufficient for
    tests that don't exercise the reconnect path) or a zero-arg callable
    returning a fresh client per connection attempt (required in production
    so the ``db.Live()`` socket is genuinely replaced on reconnect).

    ``replay_start`` must be the session-open timestamp the caller wants
    replayed from (mirrors ``live_runtime``'s ``replay_start`` contract —
    this module does not duplicate market-calendar logic). On reconnect the
    feed advances the effective replay start past the last bar it has
    already committed to the cache, so a transient disconnect backfills only
    the gap instead of replaying the whole session again.
    """

    def __init__(
        self,
        symbols: list[str],
        client_or_factory: Any,
        *,
        replay_start: datetime,
        telemetry: DatabentoFeedTelemetry | None = None,
        queue_max: int = 2000,
        reconnect_delay_secs: float = 10.0,
        reconnect_backoff_secs: float = 120.0,
        max_reconnect_attempts: int = 5,
        max_consecutive_failures: int = 10,
        supervisor_cooldown_secs: float = 300.0,
    ) -> None:
        if not symbols:
            raise ValueError("symbols must not be empty")
        self._symbols = [s.strip().upper() for s in symbols]
        self._symbol_set = set(self._symbols)
        self._client_or_factory = client_or_factory
        self._replay_start = replay_start
        self.telemetry = telemetry or DatabentoFeedTelemetry()

        self._queue: queue.Queue[Any] = queue.Queue(maxsize=max(1, int(queue_max)))
        self._reconnect_delay_secs = float(reconnect_delay_secs)
        self._reconnect_backoff_secs = float(reconnect_backoff_secs)
        self._max_reconnect_attempts = int(max_reconnect_attempts)
        self._max_consecutive_failures = int(max_consecutive_failures)
        self._supervisor_cooldown_secs = max(0.0, float(supervisor_cooldown_secs))

        # Cache: written only under _cache_lock, from the ingest thread's
        # barrier flush. Read from any thread via latest_bar/cumulative_volume
        # /session_high_low, also under _cache_lock.
        self._cache_lock = threading.Lock()
        self._cache: dict[str, _SymbolCacheEntry] = {}
        self._last_committed_ts_event: float | None = None

        # Pending batch for the interval currently in flight. Owned solely by
        # the ingest thread (never touched by the feed thread or by readers)
        # so no lock is needed for it.
        self._pending: dict[str, BarState] = {}

        # Active client + stop-event: let stop() break a blocked
        # `for record in client:` iteration, same pattern as feed.py.
        self._active_client_lock = threading.Lock()
        self._active_client: Any = None

        self._lifecycle_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._feed_thread: threading.Thread | None = None
        self._ingest_thread: threading.Thread | None = None

    # -- lifecycle -----------------------------------------------------

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._feed_thread is not None and self._feed_thread.is_alive():
                return
            self._stop_event.clear()
            self._feed_thread = threading.Thread(
                target=self._run_feed_loop,
                args=(self._stop_event,),
                daemon=True,
                name="databento-quote-feed",
            )
            self._ingest_thread = threading.Thread(
                target=self._run_ingest_loop,
                args=(self._stop_event,),
                daemon=True,
                name="databento-quote-ingest",
            )
            self._feed_thread.start()
            self._ingest_thread.start()

    def stop(self) -> None:
        with self._lifecycle_lock:
            self._stop_event.set()
            with self._active_client_lock:
                client = self._active_client
            if client is not None:
                try:
                    client.stop()
                except Exception:
                    logger.debug("client.stop() error during shutdown", exc_info=True)
            with contextlib.suppress(queue.Full):
                self._queue.put_nowait(_STOP_SENTINEL)
            if self._feed_thread is not None and self._feed_thread.is_alive():
                self._feed_thread.join(timeout=5)
            if self._ingest_thread is not None and self._ingest_thread.is_alive():
                self._ingest_thread.join(timeout=5)
            self.telemetry.set_connected(False)

    def update_symbols(self, symbols: list[str]) -> bool:
        """Replace the subscribed symbol set (e.g. on a daily watchlist
        rotation) and force a reconnect so the new ``ohlcv-1s`` subscription
        takes effect. No-op returning ``False`` if the set is unchanged.

        Thread-safe: ``_symbols``/``_symbol_set`` are only ever *rebound* here
        (never mutated in place), so the feed thread — which reads them
        unlocked at subscribe time and in the symbol-membership check — sees
        either the whole old set or the whole new one, never a torn view. The
        swap and the active-client read are done under ``_active_client_lock``
        so concurrent callers can't race the compare-and-swap.

        The reconnect advances the effective replay start past the last
        committed bar (``_next_replay_start``), so this backfills only the gap
        rather than replaying the whole session again — which correctly avoids
        double-counting the cumulative volume of symbols that were already
        subscribed. A symbol newly ADDED intraday therefore backfills only
        from that cursor, not from session open; in practice watchlist
        rotations land pre-session (every symbol starts fresh at 09:30 ET),
        where this is exact."""
        normalized: list[str] = []
        new_set: set[str] = set()
        for raw in symbols:
            if not raw or not raw.strip():
                continue
            sym = raw.strip().upper()
            if sym not in new_set:  # dedupe, order-preserving
                new_set.add(sym)
                normalized.append(sym)
        if not new_set:
            return False  # never resubscribe to an empty universe
        with self._active_client_lock:
            if new_set == self._symbol_set:
                return False
            self._symbols = normalized
            self._symbol_set = new_set
            client = self._active_client
        # Break the in-flight ``for record in client:`` so the feed loop falls
        # through to its reconnect and re-subscribes with the new list. No-op
        # if nothing is connected yet — the next connect already reads the new
        # symbols.
        if client is not None:
            with contextlib.suppress(Exception):
                client.stop()
        return True

    # -- reads (thread-safe) --------------------------------------------

    def latest_bar(self, symbol: str) -> BarState | None:
        with self._cache_lock:
            entry = self._cache.get(symbol.strip().upper())
            return entry.latest_bar if entry is not None else None

    def cumulative_volume(self, symbol: str) -> int:
        with self._cache_lock:
            entry = self._cache.get(symbol.strip().upper())
            return entry.cumulative_volume if entry is not None else 0

    def session_high_low(self, symbol: str) -> tuple[float | None, float | None]:
        with self._cache_lock:
            entry = self._cache.get(symbol.strip().upper())
            if entry is None:
                return (None, None)
            return (entry.session_high, entry.session_low)

    # -- feed thread: reconnect loop -------------------------------------

    def _run_feed_loop(self, stop: threading.Event) -> None:
        """Persistent reconnect loop for the db.Live() consumer. Ported from
        ``services/live_overlay_daemon/feed.py::_run_feed_loop``."""
        # databento.live uses asyncio internally; a background thread has no
        # event loop by default (avoids uvloop transport errors).
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            consecutive_failures = 0
            while not stop.is_set():
                client: Any = None
                try:
                    client = (
                        self._client_or_factory()
                        if callable(self._client_or_factory)
                        else self._client_or_factory
                    )
                    with self._active_client_lock:
                        self._active_client = client
                    client.subscribe(
                        dataset="EQUS.MINI",
                        schema="ohlcv-1s",
                        symbols=self._symbols,
                        stype_in="raw_symbol",
                        start=self._next_replay_start(),
                    )
                    self.telemetry.set_connected(True)
                    consecutive_failures = 0
                    replay_active = True
                    symbol_map: dict[int, str] = {}

                    for record in client:
                        if stop.is_set():
                            break
                        record_type = type(record).__name__

                        if record_type == "SymbolMappingMsg":
                            iid = getattr(record, "instrument_id", None)
                            raw = getattr(record, "stype_out_symbol", None) or getattr(
                                record, "raw_symbol", None
                            )
                            if iid is not None and raw:
                                symbol_map[int(iid)] = str(raw).strip().upper()
                            continue

                        if record_type == "SystemMsg":
                            if _system_code_matches(
                                record,
                                code_int=_SYSTEM_CODE_REPLAY_COMPLETED,
                                code_name="replay_completed",
                            ):
                                replay_active = False
                                self.telemetry.record_replay_completed()
                            elif _system_code_matches(
                                record,
                                code_int=_SYSTEM_CODE_END_OF_INTERVAL,
                                code_name="end_of_interval",
                            ):
                                self._enqueue_barrier(replay_active=replay_active)
                            continue

                        record_type_upper = record_type.upper()
                        if "OHLCV" not in record_type_upper and "BAR" not in record_type_upper:
                            continue

                        self.telemetry.record_received()
                        symbol = _symbol_from_record(record, symbol_map)
                        if symbol is None or symbol not in self._symbol_set:
                            self.telemetry.record_rejected("unmapped_symbol")
                            continue

                        bar = _parse_ohlcv_record(record, symbol=symbol)
                        if bar is None:
                            self.telemetry.record_rejected("invalid_record")
                            continue

                        self.telemetry.record_bar_age(bar.ts_event, bar.ts_recv)
                        self._enqueue_bar(symbol, bar, replay_active=replay_active)

                except db.BentoError:
                    consecutive_failures += 1
                    self.telemetry.record_bento_error()
                    self.telemetry.set_connected(False)
                    logger.warning("db.Live() BentoError (failure %d)", consecutive_failures, exc_info=True)
                except Exception:
                    consecutive_failures += 1
                    self.telemetry.record_unexpected_error()
                    self.telemetry.set_connected(False)
                    logger.warning("db.Live() unexpected error (failure %d)", consecutive_failures, exc_info=True)
                finally:
                    with self._active_client_lock:
                        self._active_client = None
                    if client is not None:
                        try:
                            client.stop()
                        except Exception:
                            logger.debug("client.stop() error during cleanup", exc_info=True)

                if stop.is_set():
                    break

                self.telemetry.set_connected(False)

                if consecutive_failures >= self._max_consecutive_failures:
                    self.telemetry.record_circuit_breaker()
                    logger.critical(
                        "Databento feed exceeded %d consecutive failures — circuit-breaker "
                        "tripped; supervisor cooling down %.0fs before re-arming.",
                        self._max_consecutive_failures,
                        self._supervisor_cooldown_secs,
                    )
                    # Supervisor restart (was: permanent break). A dead feed
                    # thread silently freezes the cache — the source-side
                    # staleness gate (DatabentoQuoteSource.max_bar_age) then ages
                    # every symbol out so no frozen price is served, but only a
                    # re-arm restores live data without a full process restart.
                    # Cool down long enough not to hammer Databento after a real
                    # outage, then reset the failure counter and reconnect. Still
                    # bounded by stop(): a shutdown during cooldown breaks out.
                    if stop.wait(self._supervisor_cooldown_secs):
                        break
                    self.telemetry.record_supervisor_restart()
                    consecutive_failures = 0
                    continue

                delay = (
                    self._reconnect_backoff_secs
                    if consecutive_failures >= self._max_reconnect_attempts
                    else self._reconnect_delay_secs
                )
                self.telemetry.record_reconnect_attempt()
                stop.wait(delay)

            logger.info("Databento quote feed thread stopped.")
        finally:
            loop.close()

    def _next_replay_start(self) -> datetime:
        with self._cache_lock:
            last_ts = self._last_committed_ts_event
        if last_ts is None:
            return self._replay_start
        return datetime.fromtimestamp(last_ts + 1.0, tz=UTC)

    def _enqueue_bar(self, symbol: str, bar: BarState, *, replay_active: bool) -> None:
        item = (symbol, bar, time.monotonic())
        if replay_active:
            # Replay arrives far faster than wall clock; block (bounded by
            # stop()) rather than drop so complete source history survives.
            while not self._stop_event.is_set():
                try:
                    self._queue.put(item, timeout=0.5)
                    return
                except queue.Full:
                    continue
            return
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            self.telemetry.record_queue_drop()

    def _enqueue_barrier(self, *, replay_active: bool) -> None:
        # During replay the queue is deliberately kept full by the blocking
        # bar puts, so a put_nowait barrier would be dropped — and a dropped
        # barrier lets multiple intervals' bars overwrite in _pending (keyed
        # by symbol), silently undercounting cumulative volume at the
        # session-open backfill (verified live 2026-07-27: queue=50 stress
        # lost up to 2.2%). Block (bounded by stop) during replay so every
        # interval flushes exactly once, at any queue size.
        if replay_active:
            while not self._stop_event.is_set():
                try:
                    self._queue.put(_BARRIER_SENTINEL, timeout=0.5)
                    return
                except queue.Full:
                    continue
            return
        # Live: best-effort. A dropped live barrier only delays visibility of
        # the in-flight batch by <=1s until the next barrier — negligible, and
        # never blocks the feed thread on a wedged consumer.
        with contextlib.suppress(queue.Full):
            self._queue.put_nowait(_BARRIER_SENTINEL)

    # -- ingest thread: drain queue, flush pending on barrier -------------

    def _run_ingest_loop(self, stop: threading.Event) -> None:
        while True:
            if stop.is_set() and self._queue.empty():
                break
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if item is _STOP_SENTINEL:
                self._queue.task_done()
                if stop.is_set():
                    break
                continue

            if item is _BARRIER_SENTINEL:
                self._flush_pending()
                self._queue.task_done()
                continue

            symbol, bar, _queued_at = item
            self._pending[symbol] = bar
            self._queue.task_done()

        # Flush whatever the current interval accumulated so far — a stream
        # that ends mid-interval (test fixture, or a genuine disconnect)
        # must not silently lose its last bar.
        self._flush_pending()
        logger.info("Databento quote ingest thread stopped.")

    def _flush_pending(self) -> None:
        if not self._pending:
            return
        batch = self._pending
        self._pending = {}
        with self._cache_lock:
            for symbol, bar in batch.items():
                applied = self._apply_bar_to_cache(symbol, bar)
                if not applied:
                    continue
                self._last_committed_ts_event = (
                    bar.ts_event
                    if self._last_committed_ts_event is None
                    else max(self._last_committed_ts_event, bar.ts_event)
                )

    def _apply_bar_to_cache(self, symbol: str, bar: BarState) -> bool:
        """Must be called with ``_cache_lock`` held. Cumulative-volume-since-
        session-open semantics ported from ``open_prep/a0_stream_state.py``,
        including its RTH gate: a pre-market/post-market/non-trading-day bar
        causes no mutation at all (not to cumulative_volume, session hi/lo,
        *or* latest_bar) — same as ``A0StreamState.apply``'s early-return on
        ``OUTSIDE_SESSION``. Returns True if the bar was applied."""
        if not _is_regular_session(bar.ts_event):
            return False
        session_date = _session_date_et(bar.ts_event)
        entry = self._cache.get(symbol)
        if entry is None or entry.session_date != session_date:
            entry = _SymbolCacheEntry(
                session_date=session_date,
                latest_bar=bar,
                cumulative_volume=bar.volume,
                session_high=bar.high,
                session_low=bar.low,
            )
        else:
            entry.latest_bar = bar
            entry.cumulative_volume += bar.volume
            entry.session_high = max(entry.session_high, bar.high)
            entry.session_low = min(entry.session_low, bar.low)
        self._cache[symbol] = entry
        return True

"""Databento Live connection loop for the OPRA shadow daemon."""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import databento_usage

from .config import Config, read_hotlist_file
from .definitions import BootstrapPlanner, bootstrap_definitions
from .state import OpraShadowState, _mapping

logger = logging.getLogger(__name__)


def _is_definition(record: Any) -> bool:
    name = type(record).__name__.lower()
    row = _mapping(record)
    return "definition" in name or (
        "instrument_class" in row and ("underlying" in row or "asset" in row)
    )


# Non-market-data record types a parent-symbology live session interleaves
# with the data: 123,294 SymbolMappingMsg arrived in a 20s five-parent sample
# (2026-08-04). They carry instrument_id + timestamps but no prices, so
# without this sink they would flow into add_trade as phantom activity.
_CONTROL_TYPE_FRAGMENTS = ("symbolmapping", "system", "error", "stat")


def _is_control(record: Any) -> bool:
    if isinstance(record, Mapping):
        return False
    name = type(record).__name__.lower()
    return any(fragment in name for fragment in _CONTROL_TYPE_FRAGMENTS)


def route_record(state: OpraShadowState, record: Any) -> str:
    """Dispatch one live record to its path; returns the route taken.

    Order matters: control messages are dropped first, then definitions, then
    quotes (tcbbo, BBO-bearing), and everything else is a trades-schema record
    that gets COUNTED. Extracted from the live loop so the routing is
    unit-testable without a Live client — and tested against OBJECT fakes,
    not only dicts: the 2026-08-04 outage lived exactly in that gap.
    """
    if _is_control(record):
        return "control"
    if _is_definition(record):
        row = _mapping(record)
        state.add_definition(row, ts_ns=int(row.get("ts_recv") or 0))
        return "definition"
    if _is_quote(record):
        state.update_quote(record)
        return "quote"
    state.add_trade(record)
    return "trade"


def _is_quote(record: Any) -> bool:
    """tcbbo (CMBP1) records carry the BBO; trades (TradeMsg) records do not.

    Since #4368 the tcbbo stream is the quote source only — counting happens
    on the trades stream, whose ``sequence`` field distinguishes genuine
    identical child fills that tcbbo cannot (it has no sequence field at all).
    """
    if isinstance(record, Mapping):
        return "bid_px_00" in record or "ask_px_00" in record
    return hasattr(record, "bid_px_00") or hasattr(record, "ask_px_00")


def _parent_symbols(hotlist: tuple[str, ...]) -> list[str]:
    return [f"{ticker}.OPT" for ticker in hotlist]


# Poll cadence of the connection-supervision loop below (seconds). It only
# paces stop/hotlist/disconnect checks — records never wait on it, they are
# dispatched by the session's own thread via the callback.
_WAIT_TICK_SECONDS = 1.0

# Bootstrap retry pacing. The delay doubles per consecutive failure up to the
# cap, so the 2026-08-04 Databento Historical outage (504 for hours) costs a
# handful of requests instead of one per supervision tick — and the daemon
# still recovers on its own within the cap once the gateway answers again.
_BOOTSTRAP_RETRY_SECONDS = 30.0
_BOOTSTRAP_MAX_RETRY_SECONDS = 900.0


def _bootstrap_if_due(
    planner: BootstrapPlanner,
    make_provider: Any,
    state: OpraShadowState,
    *,
    symbols: list[str],
) -> bool:
    """Run one bootstrap attempt when the planner says it is owed; else no-op.

    Returns whether an attempt ran. Called from the supervision loop, which
    tolerates the blocking HTTP range request: records arrive on the session's
    own thread and never wait on this one.
    """
    session = state.session_date or datetime.now(UTC).date().isoformat()
    if not planner.due(
        time.monotonic(), session_date=session, definition_count=state.definition_count
    ):
        return False
    loaded = 0
    try:
        # Constructing the provider inside the attempt keeps a client-side
        # failure (TLS env, bad key at boot) on the same retry path as a
        # gateway failure instead of killing the feed thread outright.
        for definition in bootstrap_definitions(
            make_provider(), symbols=symbols, instant=datetime.now(UTC)
        ):
            state.add_definition(definition)
            loaded += 1
        if loaded:
            logger.info("OPRA definition bootstrap loaded %d definitions", loaded)
        else:
            logger.warning("OPRA definition bootstrap returned no definitions")
    except Exception:
        logger.warning(
            "OPRA definition bootstrap failed; live updates remain active, retrying",
            exc_info=True,
        )
    # The session captured BEFORE the request is what this attempt satisfied:
    # if the UTC day rolled while it ran, state cleared what we just loaded and
    # the new session is still owed a bootstrap.
    planner.record_attempt(time.monotonic(), ok=loaded > 0, session_date=session)
    return True


def _hotlist_changed(config: Config, state: OpraShadowState) -> bool:
    """Reload the hotlist file; True (and state updated) when it differs.

    Checked from the supervision loop, NOT per-record: the old per-1000-records
    check both did file I/O on the hot path and could never fire on a quiet
    feed. A change tears the connection down for a resubscribe.
    """
    if config.hotlist_path is None or not config.hotlist_path.exists():
        return False
    updated = read_hotlist_file(config.hotlist_path)
    if updated and frozenset(updated) != state.hotlist:
        state.update_hotlist(updated)
        return True
    return False


class _UsageBatcher:
    """Thread-safe batcher for the usage ledger (flushes every 1000 records).

    The callback runs on the session's thread while the supervision loop
    drains the remainder from the feed thread — hence the lock, and hence a
    class rather than closure-mutated ``nonlocal`` state (which the repo's
    nonlocal-budget guard rejects for exactly this shape).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending = 0

    def bump(self) -> int:
        """Count one record; returns the batch to flush now, else 0."""
        with self._lock:
            self._pending += 1
            if self._pending >= 1000:
                flushed, self._pending = self._pending, 0
                return flushed
            return 0

    def drain(self) -> int:
        """Take whatever is pending (connection teardown flush)."""
        with self._lock:
            remainder, self._pending = self._pending, 0
            return remainder


def run(config: Config, state: OpraShadowState, stop: threading.Event) -> None:
    """Run until stopped; reconnect with bounded exponential backoff and jitter.

    Records are consumed via the callback API (``add_callback`` + ``start``),
    NEVER the ``Live`` iterator. The iterator path stalled twice in production
    on 2026-08-04 (the #4370 live acceptance): databento-python 0.79.0 pauses
    the transport when its DBNQueue fills during the subscribe-time burst
    (~40k OPRA definition-snapshot records) and the resume in
    ``LiveIterator.__next__`` silently no-ops once ``_transport`` is gone —
    the feed thread then starves in ``DBNQueue.get`` on an empty queue while
    the asyncio thread idles with reading paused (py-spy-verified; exactly one
    "record queue is full" warning per boot, ``records_in_window`` frozen at 0
    for 90+ minutes). Callbacks are dispatched by the session directly and
    never touch the DBNQueue, so that pause/resume mechanic cannot strand them.
    """
    if not config.enabled:
        logger.info("OPRA live daemon is off; no provider connection opened")
        return
    from databento_client import _import_databento
    from databento_provider import DabentoProvider

    db = _import_databento()
    symbols = _parent_symbols(tuple(sorted(state.hotlist)))
    def make_provider() -> Any:
        return DabentoProvider(config.api_key)

    planner = BootstrapPlanner(
        retry_seconds=_BOOTSTRAP_RETRY_SECONDS,
        max_retry_seconds=_BOOTSTRAP_MAX_RETRY_SECONDS,
    )
    _bootstrap_if_due(planner, make_provider, state, symbols=symbols)

    failures = 0
    while not stop.is_set():
        symbols = _parent_symbols(tuple(sorted(state.hotlist)))
        client = None
        batcher = _UsageBatcher()

        def _on_record(record: Any, *, _batcher: _UsageBatcher = batcher) -> None:
            """Session-thread dispatch: route, count, batch the usage ledger.

            Must stay cheap (dict ops only) — it runs on the network loop.
            A poison record is logged and skipped rather than allowed to tear
            the connection down; the record is lost either way, the session
            need not be.
            """
            if stop.is_set():
                return
            try:
                if route_record(state, record) in ("definition", "control"):
                    return
            except Exception:
                logger.warning("OPRA record dispatch failed; record skipped", exc_info=True)
                databento_usage.record(
                    dataset=config.dataset,
                    schema=config.schema,
                    mode="live",
                    consumer="opra-shadow",
                    errors=1,
                )
                return
            flush = _batcher.bump()
            if flush:
                databento_usage.record(
                    dataset=config.dataset,
                    schema=config.schema,
                    mode="live",
                    consumer="opra-shadow",
                    records=flush,
                )

        try:
            client = db.Live(key=config.api_key)
            client.subscribe(
                dataset=config.dataset,
                schema="definition",
                symbols=symbols,
                stype_in="parent",
            )
            client.subscribe(
                dataset=config.dataset,
                schema=config.schema,
                symbols=symbols,
                stype_in="parent",
            )
            # Count source (#4368): trades carries the sequence numbers that
            # distinguish genuine identical child fills; tcbbo above stays
            # subscribed purely as the BBO-at-trade source. Measured volume:
            # trades == tcbbo record-for-record, so this doubles the trade
            # stream — NOT the 91x a cbbo-1s quote subscription would cost.
            client.subscribe(
                dataset=config.dataset,
                schema="trades",
                symbols=symbols,
                stype_in="parent",
            )
            databento_usage.record(
                dataset=config.dataset,
                schema=config.schema,
                mode="live",
                consumer="opra-shadow",
                subscriptions=3,
                symbols_requested=len(symbols),
            )
            client.add_callback(_on_record)
            client.start()
            failures = 0
            # Supervision only: records arrive via _on_record on the session's
            # thread. NOTE deliberately not block_for_close(timeout=...) — that
            # TERMINATES the session on timeout in databento 0.79.0.
            while not stop.is_set() and client.is_connected():
                if _hotlist_changed(config, state):
                    logger.info("OPRA hotlist changed; reconnecting subscriptions")
                    break
                _bootstrap_if_due(planner, make_provider, state, symbols=symbols)
                stop.wait(_WAIT_TICK_SECONDS)
        except Exception:
            failures += 1
            databento_usage.record(
                dataset=config.dataset,
                schema=config.schema,
                mode="live",
                consumer="opra-shadow",
                errors=1,
                reconnects=1,
            )
            logger.warning("OPRA live connection failed", exc_info=True)
        finally:
            remainder = batcher.drain()
            if remainder:
                databento_usage.record(
                    dataset=config.dataset,
                    schema=config.schema,
                    mode="live",
                    consumer="opra-shadow",
                    records=remainder,
                )
            if client is not None:
                try:
                    client.stop()
                except Exception:
                    logger.debug("OPRA client stop failed", exc_info=True)
        if not stop.is_set():
            delay = min(60.0, 2.0 ** min(failures, 5)) + random.uniform(0.0, 1.0)
            stop.wait(delay)


def start(config: Config, state: OpraShadowState, stop: threading.Event) -> threading.Thread:
    thread = threading.Thread(
        target=run,
        args=(config, state, stop),
        name="opra-live-feed",
        daemon=True,
    )
    thread.start()
    return thread

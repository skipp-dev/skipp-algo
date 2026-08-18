"""Databento reader thread feeding the bounded A0-Fast bar buffer."""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from typing import Any

from open_prep.a0_stream import DatabentoOhlcv1sAdapter
from open_prep.a0_stream_buffer import BoundedBarBuffer

from .telemetry import A0FastTelemetry

logger = logging.getLogger(__name__)

# 2026-08-18 (Grenzgaenger D6): stall self-heal for a blocked
# ``for record in client:`` iterator — the same failure the live-overlay
# daemon defends against in services/live_overlay_daemon/feed.py (supervisor
# WP1), ported to the ONLY undefended Databento live consumer. A
# subscribe-time burst can fill the SDK's DBNQueue, pause the transport and
# block the iterator forever WITHOUT an exception; the worker then loops
# ``buffer.take(timeout=0.5)`` for good, and the consumer-side max_bar_age
# gate only degrades (ages symbols out) instead of recovering. The watchdog
# counts EVERY record (heartbeat SystemMsgs included) as liveness, so a
# healthy-but-quiet overnight stream never trips it; a genuinely paused
# transport stops heartbeats too and IS broken, which routes the reader into
# the worker's existing reconnect + resync path.
_STALL_DEFAULT_SECS = 300.0


def _stall_break_after_secs() -> float:
    raw = os.environ.get("A0_FAST_READER_STALL_SECS", "")
    try:
        value = float(raw)
    except ValueError:
        return _STALL_DEFAULT_SECS
    return max(60.0, value)


def _exit_for_restart(code: int) -> None:
    """Module-level so tests can monkeypatch the escalation (a SystemExit
    raised in a non-main thread does NOT stop the process — same rationale
    as the daemon supervisor's os._exit)."""
    os._exit(code)


def start_live_reader(
    client_or_factory: Any,
    *,
    symbols: list[str],
    buffer: BoundedBarBuffer,
    telemetry: A0FastTelemetry,
    replay_start: datetime,
    stall_break_after_secs: float | None = None,
) -> threading.Thread:
    """Create, subscribe, and drain the SDK client on one daemon thread.

    Databento's live client owns an event loop with thread affinity, so a
    factory must be constructed inside this reader thread in production.
    Pre-built iterator fakes remain supported for focused tests.

    A watchdog thread breaks the blocked iterator via ``client.stop()`` when
    no record of ANY kind has arrived for ``stall_break_after_secs``
    (default: env ``A0_FAST_READER_STALL_SECS``, min 60s, fallback 300s);
    the buffer then closes with reason ``reader_stalled`` and the worker's
    reconnect path takes over.
    """
    threshold = (
        stall_break_after_secs
        if stall_break_after_secs is not None
        else _stall_break_after_secs()
    )
    activity = {"at": time.monotonic()}
    client_slot: dict[str, Any] = {}
    stall_flag = threading.Event()
    done = threading.Event()

    def target() -> None:
        reason = "stream_ended"
        try:
            client = client_or_factory() if callable(client_or_factory) else client_or_factory
            client_slot["client"] = client
            _read(
                client,
                symbols=symbols,
                buffer=buffer,
                telemetry=telemetry,
                replay_start=replay_start,
                activity=activity,
            )
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            logger.warning("A0-Fast live reader stopped: %s", reason)
        finally:
            done.set()
            if stall_flag.is_set():
                reason = "reader_stalled"
            telemetry.set_connected(False)
            buffer.close(reason)

    def watchdog() -> None:
        poll = min(30.0, max(0.05, threshold / 4.0))
        while not done.wait(timeout=poll):
            idle = time.monotonic() - activity["at"]
            if idle <= threshold:
                continue
            client = client_slot.get("client")
            if client is None:
                continue
            stall_flag.set()
            logger.warning(
                "A0-Fast reader stalled (%.0fs without any record, "
                "heartbeats included); breaking the blocked iterator",
                idle,
            )
            try:
                client.stop()
            except Exception:
                logger.warning(
                    "A0-Fast stall-breaker client.stop() failed", exc_info=True
                )
            # Escalation (mirrors the daemon supervisor): if stop() did not
            # unblock the reader within a grace period, only a process
            # restart can recover — Railway's restart policy brings the
            # service back and the session replay refills state. SystemExit
            # in a non-main thread would not stop the process; os._exit is
            # the reliable escalation.
            if not done.wait(timeout=max(60.0, poll * 4.0)):
                logger.error(
                    "A0-Fast reader still blocked after client.stop(); "
                    "escalating to process restart"
                )
                _exit_for_restart(1)
            return

    thread = threading.Thread(target=target, name="a0-fast-live-reader", daemon=True)
    thread.start()
    threading.Thread(
        target=watchdog, name="a0-fast-reader-watchdog", daemon=True
    ).start()
    return thread


def _read(
    client: Any,
    *,
    symbols: list[str],
    buffer: BoundedBarBuffer,
    telemetry: A0FastTelemetry,
    replay_start: datetime,
    activity: dict[str, float] | None = None,
) -> None:
    client.subscribe(
        dataset="EQUS.MINI",
        schema="ohlcv-1s",
        symbols=symbols,
        stype_in="raw_symbol",
        start=replay_start,
    )
    telemetry.set_connected(True)
    adapter = DatabentoOhlcv1sAdapter()
    symbol_map: dict[int, str] = {}
    replay_active = True
    for record in client:
        if activity is not None:
            # Any record — mappings, heartbeats, bars — proves the transport
            # is alive; the stall watchdog keys off this timestamp.
            activity["at"] = time.monotonic()
        record_type = type(record).__name__
        if record_type == "SymbolMappingMsg":
            instrument_id = getattr(record, "instrument_id", None)
            raw_symbol = getattr(record, "stype_out_symbol", None)
            if instrument_id is not None and raw_symbol:
                symbol_map[int(instrument_id)] = str(raw_symbol).strip().upper()
            continue
        if record_type == "SystemMsg":
            if _system_code(record) == "replay_completed":
                replay_active = False
            continue
        if "OHLCV" not in record_type.upper() and "BAR" not in record_type.upper():
            continue
        telemetry.record_received()
        symbol = _symbol_from_record(record, symbol_map)
        if symbol is None:
            telemetry.record_rejected("unmapped_symbol")
            continue
        try:
            bar = adapter.normalize(record, symbol=symbol)
        except (TypeError, ValueError, OverflowError):
            telemetry.record_rejected("invalid_record")
            logger.debug("A0-Fast rejected malformed stream record", exc_info=True)
            continue
        # Intraday replay arrives much faster than wall clock.  Apply bounded
        # backpressure until Databento announces replay completion so complete
        # source history is preserved.  Once live, prefer latency and retain
        # the existing fail-closed drop/resync contract on overload.
        offer = buffer.put(bar) if replay_active else buffer.offer(bar)
        if offer.dropped is not None:
            telemetry.record_queue_drop()
        telemetry.set_buffer(buffer.snapshot())


def _system_code(record: Any) -> str:
    code = getattr(record, "code", "")
    value = getattr(code, "value", code)
    return str(value).strip().lower()


def _symbol_from_record(record: Any, symbol_map: dict[int, str]) -> str | None:
    instrument_id = getattr(record, "instrument_id", None)
    if instrument_id is None:
        header = getattr(record, "hd", None)
        instrument_id = getattr(header, "instrument_id", None)
    return symbol_map.get(instrument_id) if instrument_id is not None else None

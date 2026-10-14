"""Bounded A0 stream-buffer and fail-closed overflow tests."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from open_prep.a0_stream_buffer import BoundedBarBuffer
from open_prep.a0_stream_state import (
    A0StreamState,
    StreamApplyStatus,
    StreamBar,
    StreamReference,
)

_OPEN = datetime(2026, 7, 17, 9, 30, tzinfo=ZoneInfo("America/New_York"))


def _bar(symbol: str, offset: int) -> StreamBar:
    event = _OPEN + timedelta(seconds=offset)
    return StreamBar(symbol, 102.0, 100, event.timestamp(), event.timestamp() + 0.1)


def _state() -> A0StreamState:
    state = A0StreamState()
    state.set_reference(StreamReference(
        symbol="NVDA",
        previous_close=100.0,
        average_daily_volume=10_000.0,
        source="databento:daily",
        as_of_session="2026-07-16",
        lookback_sessions=20,
        reference_version="daily-v1",
        corporate_action_version="corp-v1",
    ))
    return state


def test_buffer_is_bounded_and_marks_dropped_symbol_for_resync() -> None:
    buffer = BoundedBarBuffer(capacity=2)
    buffer.offer(_bar("NVDA", 0))
    buffer.offer(_bar("AMD", 0))
    overflow = buffer.offer(_bar("NVDA", 1))
    assert overflow.dropped == _bar("NVDA", 0)
    assert buffer.snapshot().depth == 2
    assert buffer.snapshot().high_watermark == 2
    assert buffer.snapshot().dropped_total == 1

    assert buffer.take(timeout=0).bar.symbol == "AMD"
    nvda = buffer.take(timeout=0)
    assert nvda.bar.symbol == "NVDA"
    assert nvda.resync_required is True
    assert buffer.snapshot().resync_required_symbols == ("NVDA",)
    buffer.acknowledge_resync("NVDA")
    assert buffer.snapshot().resync_required_symbols == ()


def test_invalidation_forces_recovery_even_before_first_state_bar() -> None:
    state = _state()
    state.invalidate("NVDA")
    result = state.apply(_bar("NVDA", 1))
    assert result.status is StreamApplyStatus.GAP_DETECTED
    assert result.snapshot is None
    assert state.state_snapshot("NVDA")["invalidated"] is True

    state.bootstrap(
        symbol="NVDA",
        session_date="2026-07-17",
        cumulative_volume=100,
        last_ts_event=_OPEN.timestamp(),
    )
    recovered = state.apply(_bar("NVDA", 1))
    assert recovered.status is StreamApplyStatus.ACCEPTED
    assert state.state_snapshot("NVDA")["invalidated"] is False


def test_close_drains_existing_items_and_rejects_new_offers() -> None:
    buffer = BoundedBarBuffer(capacity=1)
    buffer.offer(_bar("NVDA", 0))
    buffer.close("disconnect")
    assert buffer.take(timeout=0) is not None
    assert buffer.take(timeout=0) is None
    assert buffer.snapshot().closed is True
    assert buffer.snapshot().close_reason == "disconnect"
    with pytest.raises(RuntimeError, match="closed"):
        buffer.offer(_bar("NVDA", 1))


def test_disconnect_discard_marks_all_queued_symbols_for_resync() -> None:
    buffer = BoundedBarBuffer(capacity=3)
    buffer.offer(_bar("NVDA", 0))
    buffer.offer(_bar("AMD", 0))
    buffer.close("socket closed")
    assert buffer.discard_all() == 2
    snapshot = buffer.snapshot()
    assert snapshot.depth == 0
    assert snapshot.dropped_total == 2
    assert snapshot.resync_required_symbols == ("AMD", "NVDA")

"""Replay-window regression tests for the A0-Fast shadow worker."""

from datetime import UTC, datetime

from services.a0_fast_detector.worker import _live_replay_start


def test_replay_start_respects_eq_us_utc_midnight_floor_after_session() -> None:
    now = datetime(2026, 7, 26, 2, 16, tzinfo=UTC)

    assert _live_replay_start(now) == datetime(2026, 7, 26, tzinfo=UTC)


def test_replay_start_keeps_session_open_during_regular_hours() -> None:
    now = datetime(2026, 7, 24, 15, 0, tzinfo=UTC)

    assert _live_replay_start(now) == datetime(2026, 7, 24, 13, 30, tzinfo=UTC)


def test_replay_start_uses_current_time_before_session_open() -> None:
    now = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)

    assert _live_replay_start(now) == now

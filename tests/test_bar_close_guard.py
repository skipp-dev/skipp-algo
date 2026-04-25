"""Tests for :mod:`smc_core.bar_close_guard` (H-7, system review 2026-04-24)."""
from __future__ import annotations

import pandas as pd
import pytest

from smc_core.bar_close_guard import (
    _INTERVAL_SECONDS,
    guard_closed_bars,
    interval_seconds,
)


def _make_frame(starts: list[int]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": starts,
            "open": [1.0] * len(starts),
            "high": [1.0] * len(starts),
            "low": [1.0] * len(starts),
            "close": [1.0] * len(starts),
        }
    )


def test_interval_seconds_canonical_values() -> None:
    assert interval_seconds("1m") == 60
    assert interval_seconds("5m") == 300
    assert interval_seconds("1h") == 3600
    assert interval_seconds("1d") == 86400


def test_interval_seconds_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown bar interval"):
        interval_seconds("3m")


def test_interval_seconds_table_complete() -> None:
    # Smoke: every documented interval round-trips.
    for token in _INTERVAL_SECONDS:
        assert interval_seconds(token) == _INTERVAL_SECONDS[token]


def test_guard_drops_trailing_in_progress_5m_bar() -> None:
    # 5m bars at 0, 300, 600 — "now" = 700 means bar starting at 600 is
    # only 100s into its 300s window, so it is in-progress and dropped.
    df = _make_frame([0, 300, 600])
    out = guard_closed_bars(df, interval="5m", now=700)
    assert list(out["timestamp"]) == [0, 300]


def test_guard_keeps_just_closed_bar() -> None:
    # Bar starting at 600 closes at exactly 900 — guard requires
    # close_time > now to drop, so now == 900 means the bar is closed.
    df = _make_frame([0, 300, 600])
    out = guard_closed_bars(df, interval="5m", now=900)
    assert list(out["timestamp"]) == [0, 300, 600]


def test_guard_drops_multiple_trailing_bars() -> None:
    # All three trailing 1m bars unfinished.
    df = _make_frame([0, 60, 120, 180])
    out = guard_closed_bars(df, interval="1m", now=125)
    assert list(out["timestamp"]) == [0, 60]


def test_guard_no_op_when_now_is_none() -> None:
    df = _make_frame([0, 300, 600])
    out = guard_closed_bars(df, interval="5m", now=None)
    assert out is df  # identity preserved — guarantee for hot paths


def test_guard_no_op_on_empty_frame() -> None:
    df = _make_frame([])
    out = guard_closed_bars(df, interval="5m", now=999_999)
    assert len(out) == 0


def test_guard_fail_soft_when_timestamp_column_missing() -> None:
    df = pd.DataFrame({"close": [1.0, 2.0, 3.0]})
    out = guard_closed_bars(df, interval="5m", now=999_999)
    assert out is df  # no-op — caller may not be using the canonical schema


def test_guard_drops_only_contiguous_suffix() -> None:
    # Middle row has a bogus future timestamp (clock skew); guard must
    # only walk the contiguous trailing window.
    df = _make_frame([0, 9_999_999, 600])
    out = guard_closed_bars(df, interval="5m", now=900)
    # Last bar closes at 900 == now, so kept; middle row preserved.
    assert list(out["timestamp"]) == [0, 9_999_999, 600]


def test_guard_handles_all_bars_in_progress() -> None:
    df = _make_frame([1000, 1060, 1120])
    out = guard_closed_bars(df, interval="1m", now=500)
    assert len(out) == 0

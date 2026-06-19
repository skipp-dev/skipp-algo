"""Property tests for ``smc_core.bar_close_guard`` (H-7, 2026-04-24).

Pins the contract of the bar-close guard used by every "snapshot the
last bar" consumer (vol-regime ATR, structure state, imbalance
lifecycle, HTF bias):

  * :func:`smc_core.bar_close_guard.interval_seconds`
  * :func:`smc_core.bar_close_guard.guard_closed_bars`

Existing unit tests cover the happy path. This file pins the harder
invariants — identity preservation on no-op, contiguous-suffix-only
drop semantics, the ``close_time > now`` strict-inequality boundary,
fail-soft on missing column, parametrized intervals, non-mutation of
inputs.

Continues the PQ Re-Audit Tier-1 spillover series (#2350, #2363, #2366,
#2370, #2371, #2372, #2373, #2374, #2375, #2376, #2377, #2378).
"""

from __future__ import annotations

import pandas as pd
import pytest

from smc_core.bar_close_guard import (
    _INTERVAL_SECONDS,
    guard_closed_bars,
    interval_seconds,
)

# ---------------------------------------------------------------------------
# interval_seconds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("1m", 60),
        ("5m", 300),
        ("10m", 600),
        ("15m", 900),
        ("30m", 1800),
        ("1h", 3600),
        ("4h", 14400),
        ("1d", 86400),
        ("1w", 604800),
    ],
)
def test_interval_seconds_canonical_table(token: str, expected: int) -> None:
    assert interval_seconds(token) == expected


def test_interval_seconds_table_round_trip() -> None:
    """Every key in `_INTERVAL_SECONDS` resolves to its value through the public API."""
    for token, expected in _INTERVAL_SECONDS.items():
        assert interval_seconds(token) == expected


def test_interval_seconds_values_strictly_increasing_in_documented_order() -> None:
    """1m < 5m < 10m < 15m < 30m < 1h < 4h < 1d < 1w — pins the documented progression."""
    tokens = ["1m", "5m", "10m", "15m", "30m", "1h", "4h", "1d", "1w"]
    values = [interval_seconds(t) for t in tokens]
    assert values == sorted(values)
    assert len(set(values)) == len(values)  # strictly increasing


@pytest.mark.parametrize("bad", ["", "3m", "2h", "1M", "5M", "60s", "1H", "1D", "weekly", "  1m"])
def test_interval_seconds_unknown_raises_value_error(bad: str) -> None:
    """Unknown / mis-cased / whitespace-padded tokens raise ValueError."""
    with pytest.raises(ValueError, match="Unknown bar interval"):
        interval_seconds(bad)


def test_interval_seconds_error_lists_known_tokens() -> None:
    """Error message must list the known intervals (helps callers self-correct)."""
    with pytest.raises(ValueError) as exc_info:
        interval_seconds("3m")
    msg = str(exc_info.value)
    for token in _INTERVAL_SECONDS:
        assert repr(token) in msg or token in msg


# ---------------------------------------------------------------------------
# guard_closed_bars — fixture helper
# ---------------------------------------------------------------------------


def _frame(starts: list[float]) -> pd.DataFrame:
    """Minimal OHLC frame with the project-wide `timestamp` column."""
    return pd.DataFrame(
        {
            "timestamp": starts,
            "open": [1.0] * len(starts),
            "high": [1.0] * len(starts),
            "low": [1.0] * len(starts),
            "close": [1.0] * len(starts),
        }
    )


# ---------------------------------------------------------------------------
# guard_closed_bars — identity & no-op cases
# ---------------------------------------------------------------------------


def test_guard_now_none_returns_identity() -> None:
    df = _frame([0.0, 300.0, 600.0])
    assert guard_closed_bars(df, interval="5m", now=None) is df


def test_guard_empty_frame_returns_identity() -> None:
    df = _frame([])
    assert guard_closed_bars(df, interval="5m", now=1_000_000.0) is df


def test_guard_none_dataframe_returned_unchanged() -> None:
    """Fail-soft: `df is None` short-circuits before any column access."""
    assert guard_closed_bars(None, interval="5m", now=1_000_000.0) is None  # type: ignore[arg-type]


def test_guard_missing_timestamp_column_returns_identity() -> None:
    """Fail-soft: cannot decide without `timestamp` column → leave untouched."""
    df = pd.DataFrame({"open": [1.0], "close": [1.0]})
    assert guard_closed_bars(df, interval="5m", now=1_000_000.0) is df


def test_guard_custom_timestamp_column_respected() -> None:
    df = pd.DataFrame({"ts": [0.0, 300.0, 600.0], "close": [1.0, 1.0, 1.0]})
    out = guard_closed_bars(df, interval="5m", now=700.0, timestamp_column="ts")
    assert list(out["ts"]) == [0.0, 300.0]


def test_guard_no_trailing_in_progress_bars_returns_identity() -> None:
    """If nothing is dropped, the original df object is returned (not a copy)."""
    df = _frame([0.0, 300.0, 600.0])
    out = guard_closed_bars(df, interval="5m", now=900.0)
    assert out is df


# ---------------------------------------------------------------------------
# guard_closed_bars — boundary semantics
# ---------------------------------------------------------------------------


def test_guard_close_time_equal_to_now_is_kept() -> None:
    """Strict inequality: a bar with close_time == now is **closed** and kept."""
    df = _frame([0.0, 300.0, 600.0])
    out = guard_closed_bars(df, interval="5m", now=900.0)
    assert list(out["timestamp"]) == [0.0, 300.0, 600.0]


def test_guard_close_time_just_above_now_is_dropped() -> None:
    df = _frame([0.0, 300.0, 600.0])
    out = guard_closed_bars(df, interval="5m", now=899.999999)
    assert list(out["timestamp"]) == [0.0, 300.0]


def test_guard_all_bars_in_progress_returns_empty_slice() -> None:
    df = _frame([1000.0, 1300.0, 1600.0])
    out = guard_closed_bars(df, interval="5m", now=500.0)
    assert len(out) == 0
    # iloc[0:0] preserves columns & dtypes:
    assert list(out.columns) == list(df.columns)


# ---------------------------------------------------------------------------
# guard_closed_bars — contiguous suffix only
# ---------------------------------------------------------------------------


def test_guard_drops_only_contiguous_trailing_suffix() -> None:
    """Mid-frame stale bar (close > now) is preserved — only the trailing
    contiguous in-progress suffix is dropped (documented invariant)."""
    # Frame is [0, 999999, 300, 999999] with interval=5m (300s) and now=700.
    # Closes: 0→300 (≤700 closed), 999999→far future (in-progress, mid-frame),
    # 300→600 (≤700 closed), 999999→far future (in-progress, trailing).
    # The guard scans from the tail and stops at the first closed bar, so
    # only the trailing in-progress bar is dropped — the mid-frame
    # "future" bar at index 1 is preserved.
    df = _frame([0.0, 999999.0, 300.0, 999999.0])
    out = guard_closed_bars(df, interval="5m", now=700.0)
    # Walking from tail: 999999 → in-progress (drop). 300 → closed at 600
    # which is < 700 (stop). So drop_count = 1.
    assert list(out["timestamp"]) == [0.0, 999999.0, 300.0]


@pytest.mark.parametrize(
    ("interval", "duration"),
    [("1m", 60), ("5m", 300), ("15m", 900), ("1h", 3600), ("1d", 86400)],
)
def test_guard_drop_count_matches_naive_suffix_scan(interval: str, duration: int) -> None:
    """For every interval, the number of dropped rows equals the trailing
    run of bars whose `start + duration > now`."""
    starts = [float(i * duration) for i in range(10)]
    now = float(7 * duration)  # bars 0..6 closed (close <= now), bars 7..9 open
    df = _frame(starts)
    out = guard_closed_bars(df, interval=interval, now=now)
    assert list(out["timestamp"]) == starts[:7]


# ---------------------------------------------------------------------------
# guard_closed_bars — non-mutation of input
# ---------------------------------------------------------------------------


def test_guard_does_not_mutate_input_frame() -> None:
    starts = [0.0, 300.0, 600.0, 900.0]
    df = _frame(starts)
    before = df.copy(deep=True)
    guard_closed_bars(df, interval="5m", now=700.0)
    pd.testing.assert_frame_equal(df, before)


# ---------------------------------------------------------------------------
# guard_closed_bars — defensive coercion
# ---------------------------------------------------------------------------


def test_guard_non_numeric_trailing_timestamp_breaks_scan() -> None:
    """A non-numeric trailing timestamp aborts the tail scan (defensive):
    the row stays and earlier rows are not re-evaluated."""
    df = pd.DataFrame(
        {
            "timestamp": [0.0, 300.0, "not-a-number"],
            "open": [1.0, 1.0, 1.0],
            "high": [1.0, 1.0, 1.0],
            "low": [1.0, 1.0, 1.0],
            "close": [1.0, 1.0, 1.0],
        }
    )
    out = guard_closed_bars(df, interval="5m", now=10_000_000.0)
    # Non-numeric tail short-circuits → drop_count stays 0 → identity returned.
    assert out is df


def test_guard_string_numeric_timestamp_is_coerced() -> None:
    """`float("300.0")` succeeds → string-numeric tails ARE evaluated."""
    df = pd.DataFrame(
        {
            "timestamp": [0.0, 300.0, "600.0"],
            "open": [1.0, 1.0, 1.0],
            "high": [1.0, 1.0, 1.0],
            "low": [1.0, 1.0, 1.0],
            "close": [1.0, 1.0, 1.0],
        }
    )
    out = guard_closed_bars(df, interval="5m", now=700.0)
    # bar starting at "600.0" closes at 900 > 700 → dropped
    assert list(out["timestamp"]) == [0.0, 300.0]


# ---------------------------------------------------------------------------
# guard_closed_bars — single-row frames
# ---------------------------------------------------------------------------


def test_guard_single_in_progress_row_returns_empty_slice() -> None:
    df = _frame([1000.0])
    out = guard_closed_bars(df, interval="5m", now=500.0)
    assert len(out) == 0


def test_guard_single_closed_row_returned_unchanged() -> None:
    df = _frame([0.0])
    out = guard_closed_bars(df, interval="5m", now=10_000.0)
    assert out is df


# ---------------------------------------------------------------------------
# Integration: unknown interval propagates from interval_seconds
# ---------------------------------------------------------------------------


def test_guard_unknown_interval_raises_value_error() -> None:
    df = _frame([0.0, 300.0])
    with pytest.raises(ValueError, match="Unknown bar interval"):
        guard_closed_bars(df, interval="3m", now=1_000_000.0)

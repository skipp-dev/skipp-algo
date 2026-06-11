"""Property tests for ``smc_core.bar_utils`` pure helpers.

Pins the contract of the bar-frame normalisation primitives that
underlie every downstream pure-math module (``htf_context``,
``session_context``, ``layering``, ``fvg_quality``, ``scoring``):

  * :data:`smc_core.bar_utils.REQUIRED_BAR_COLUMNS`
  * :func:`smc_core.bar_utils.coerce_timestamps_to_epoch_seconds`
  * :func:`smc_core.bar_utils.normalize_bars`

Continues the PQ Re-Audit Tier-1 spillover series
(PRs #2350, #2363, #2366, #2370, #2371, #2372, #2373, #2374, #2375, #2376).
Pure stdlib + pandas (already a hard dep of ``bar_utils``); ≤ 2s.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from smc_core.bar_utils import (
    REQUIRED_BAR_COLUMNS,
    coerce_timestamps_to_epoch_seconds,
    normalize_bars,
)

# ---------------------------------------------------------------------------
# REQUIRED_BAR_COLUMNS
# ---------------------------------------------------------------------------


def test_required_bar_columns_pinned() -> None:
    assert REQUIRED_BAR_COLUMNS == ["timestamp", "open", "high", "low", "close", "volume"]


# ---------------------------------------------------------------------------
# coerce_timestamps_to_epoch_seconds
# ---------------------------------------------------------------------------


def test_coerce_numeric_passes_through_unchanged() -> None:
    s = pd.Series([1, 2, 3], dtype="int64")
    out = coerce_timestamps_to_epoch_seconds(s)
    assert list(out) == [1, 2, 3]


def test_coerce_float_numeric_preserves_fractional_seconds() -> None:
    s = pd.Series([1.25, 2.5, 3.75], dtype="float64")
    out = coerce_timestamps_to_epoch_seconds(s)
    assert list(out) == [1.25, 2.5, 3.75]


def test_coerce_numeric_with_nan_returns_nan() -> None:
    s = pd.Series([1.0, float("nan"), 3.0])
    out = coerce_timestamps_to_epoch_seconds(s)
    assert out.iloc[0] == 1.0
    assert math.isnan(out.iloc[1])
    assert out.iloc[2] == 3.0


def test_coerce_iso_string_returns_epoch_seconds() -> None:
    s = pd.Series(["1970-01-01T00:00:00Z", "1970-01-01T00:00:01Z", "2025-01-01T00:00:00Z"])
    out = coerce_timestamps_to_epoch_seconds(s)
    assert int(out.iloc[0]) == 0
    assert int(out.iloc[1]) == 1
    expected = int(pd.Timestamp("2025-01-01", tz="UTC").timestamp())
    assert int(out.iloc[2]) == expected


def test_coerce_string_uses_utc_when_no_offset() -> None:
    """Naive datetime strings are interpreted as UTC (``utc=True`` kw)."""
    s = pd.Series(["2025-01-01 00:00:00", "2025-01-01 01:30:00"])
    out = coerce_timestamps_to_epoch_seconds(s)
    midnight_utc = int(pd.Timestamp("2025-01-01", tz="UTC").timestamp())
    assert int(out.iloc[0]) == midnight_utc
    assert int(out.iloc[1]) == midnight_utc + 5400


def test_coerce_string_honours_explicit_offset() -> None:
    """Strings with an offset are normalised to UTC (offset honored)."""
    s = pd.Series(["2025-01-01T05:00:00+05:00"])  # = 2025-01-01T00:00:00Z
    out = coerce_timestamps_to_epoch_seconds(s)
    assert int(out.iloc[0]) == int(pd.Timestamp("2025-01-01", tz="UTC").timestamp())


def test_coerce_string_floors_to_whole_seconds() -> None:
    """The `//` against `Timedelta('1s')` floors sub-second components."""
    s = pd.Series(["2025-01-01T00:00:00.999999Z"])
    out = coerce_timestamps_to_epoch_seconds(s)
    assert int(out.iloc[0]) == int(pd.Timestamp("2025-01-01", tz="UTC").timestamp())


def test_coerce_unparseable_string_returns_nan() -> None:
    """`errors='coerce'` turns garbage into NaT/NaN instead of raising."""
    s = pd.Series(["not-a-date", "still-not"])
    out = coerce_timestamps_to_epoch_seconds(s)
    assert out.isna().all()


def test_coerce_empty_series_returns_empty() -> None:
    s = pd.Series([], dtype="object")
    out = coerce_timestamps_to_epoch_seconds(s)
    assert len(out) == 0


# ---------------------------------------------------------------------------
# normalize_bars — missing columns
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("missing", REQUIRED_BAR_COLUMNS)
def test_normalize_bars_raises_on_missing_column(missing: str) -> None:
    cols = [c for c in REQUIRED_BAR_COLUMNS if c != missing]
    df = pd.DataFrame({c: [1.0, 2.0] for c in cols})
    with pytest.raises(ValueError, match="Missing required bar columns"):
        normalize_bars(df)


def test_normalize_bars_missing_columns_message_lists_all_missing() -> None:
    df = pd.DataFrame({"timestamp": [1, 2], "open": [1, 2], "high": [1, 2]})
    with pytest.raises(ValueError, match=r"\['close', 'low', 'volume'\]"):
        normalize_bars(df)


# ---------------------------------------------------------------------------
# normalize_bars — sort + NaN drop
# ---------------------------------------------------------------------------


def _df(rows: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=REQUIRED_BAR_COLUMNS)


def test_normalize_bars_sorts_by_timestamp_ascending() -> None:
    df = _df([(3, 1, 1, 1, 1, 1), (1, 2, 2, 2, 2, 2), (2, 3, 3, 3, 3, 3)])
    out = normalize_bars(df)
    assert list(out["timestamp"]) == [1, 2, 3]
    assert list(out["open"]) == [2.0, 3.0, 1.0]


def test_normalize_bars_resets_index_after_sort() -> None:
    df = _df([(3, 1, 1, 1, 1, 1), (1, 2, 2, 2, 2, 2), (2, 3, 3, 3, 3, 3)])
    out = normalize_bars(df)
    assert list(out.index) == [0, 1, 2]


def test_normalize_bars_drops_nan_in_ohlc_or_timestamp() -> None:
    df = _df([
        (1, 1.0, 1.0, 1.0, 1.0, 1.0),
        (2, float("nan"), 2.0, 2.0, 2.0, 2.0),  # NaN open → dropped
        (3, 3.0, 3.0, float("nan"), 3.0, 3.0),  # NaN low → dropped
        (4, 4.0, 4.0, 4.0, 4.0, 4.0),
        (5, 5.0, 5.0, 5.0, 5.0, float("nan")),  # NaN volume → kept
    ])
    out = normalize_bars(df)
    assert list(out["timestamp"]) == [1, 4, 5]


def test_normalize_bars_unparseable_timestamp_dropped() -> None:
    df = pd.DataFrame(
        [["bad-ts", 1, 1, 1, 1, 1], ["2025-01-01T00:00:00Z", 2, 2, 2, 2, 2]],
        columns=REQUIRED_BAR_COLUMNS,
    )
    out = normalize_bars(df)
    assert len(out) == 1
    assert out.iloc[0]["open"] == 2.0


def test_normalize_bars_does_not_mutate_input() -> None:
    """``df.copy()`` at the top of normalize_bars must keep the caller's frame intact."""
    df = _df([(3, 1, 1, 1, 1, 1), (1, 2, 2, 2, 2, 2)])
    snapshot = df.copy()
    _ = normalize_bars(df)
    pd.testing.assert_frame_equal(df, snapshot)


def test_normalize_bars_string_numeric_coerced_to_float() -> None:
    df = pd.DataFrame(
        [[1, "1.5", "2.5", "0.5", "2.0", "100"]],
        columns=REQUIRED_BAR_COLUMNS,
    )
    out = normalize_bars(df)
    assert out.iloc[0]["open"] == 1.5
    assert out.iloc[0]["close"] == 2.0
    assert out.iloc[0]["volume"] == 100.0


def test_normalize_bars_empty_frame_returns_empty_with_required_columns() -> None:
    df = pd.DataFrame({c: [] for c in REQUIRED_BAR_COLUMNS})
    out = normalize_bars(df)
    assert len(out) == 0
    assert set(REQUIRED_BAR_COLUMNS).issubset(out.columns)


def test_normalize_bars_keeps_extra_columns() -> None:
    rows = [(1, 1, 1, 1, 1, 1), (2, 2, 2, 2, 2, 2)]
    df = pd.DataFrame(rows, columns=REQUIRED_BAR_COLUMNS)
    df["extra"] = ["a", "b"]
    out = normalize_bars(df)
    assert "extra" in out.columns
    assert list(out["extra"]) == ["a", "b"]


def test_normalize_bars_iso_timestamps_converted_to_epoch_seconds() -> None:
    df = pd.DataFrame(
        [["2025-01-01T00:00:00Z", 1, 1, 1, 1, 1],
         ["2025-01-01T00:00:01Z", 2, 2, 2, 2, 2]],
        columns=REQUIRED_BAR_COLUMNS,
    )
    out = normalize_bars(df)
    base = int(pd.Timestamp("2025-01-01", tz="UTC").timestamp())
    assert list(out["timestamp"]) == [base, base + 1]

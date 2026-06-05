"""Unit tests for the HY tick-trades normalizer (scope step 1).

The contract that matters here and nowhere else: **nanosecond precision is
preserved**. The ADR-0016 ``normalize_trades_frame`` floors to seconds; this one
must not, because sub-second async timing is the Hayashi-Yoshida signal.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.pull_tick_trades import normalize_tick_trades_frame

_T0_NS = 1_700_000_000_000_000_000  # arbitrary fixed ns epoch


def _raw_trades_frame(offsets_ns: list[int], prices: list[float]) -> pd.DataFrame:
    """Synthetic Databento ``trades`` frame on a ns DatetimeIndex."""
    index = pd.to_datetime([_T0_NS + o for o in offsets_ns], utc=True)
    return pd.DataFrame(
        {"price": prices, "size": np.ones(len(prices))},
        index=pd.DatetimeIndex(index, name="ts_event"),
    )


def test_preserves_nanosecond_precision() -> None:
    # Three prints 500us apart -- all collapse to the same second, so a
    # second-floored clock would make them simultaneous (HY-blind).
    raw = _raw_trades_frame([0, 500_000, 1_000_000], [10.0, 11.0, 12.0])
    out = normalize_tick_trades_frame(raw, symbol="spy")

    assert list(out.columns) == ["symbol", "ts_ns", "price"]
    assert out["ts_ns"].tolist() == [_T0_NS, _T0_NS + 500_000, _T0_NS + 1_000_000]
    # The sub-second deltas survive (would all be 0 under second-flooring).
    assert out["ts_ns"].diff().dropna().tolist() == [500_000, 500_000]
    assert (out["symbol"] == "SPY").all()


def test_sorts_by_timestamp() -> None:
    raw = _raw_trades_frame([900_000, 100_000, 500_000], [3.0, 1.0, 2.0])
    out = normalize_tick_trades_frame(raw, symbol="SPY")
    assert out["ts_ns"].is_monotonic_increasing
    assert out["price"].tolist() == [1.0, 2.0, 3.0]


def test_drops_unpriced_rows() -> None:
    raw = _raw_trades_frame([0, 100, 200], [10.0, float("nan"), 12.0])
    out = normalize_tick_trades_frame(raw, symbol="SPY")
    assert out["price"].tolist() == [10.0, 12.0]


def test_rejects_missing_price_column() -> None:
    raw = _raw_trades_frame([0, 100], [1.0, 1.0]).drop(columns=["price"])
    with pytest.raises(ValueError, match="missing required column"):
        normalize_tick_trades_frame(raw, symbol="SPY")


def test_rejects_empty() -> None:
    with pytest.raises(ValueError, match="empty"):
        normalize_tick_trades_frame(pd.DataFrame(), symbol="SPY")


def test_accepts_ts_event_column_not_index() -> None:
    raw = _raw_trades_frame([0, 100], [1.0, 2.0]).reset_index()
    out = normalize_tick_trades_frame(raw, symbol="SPY")
    assert out["ts_ns"].tolist() == [_T0_NS, _T0_NS + 100]

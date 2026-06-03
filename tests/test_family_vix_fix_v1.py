"""Tests for the ADR-0019 step-2 downside-volatility extractor (Williams VIX Fix)."""

from __future__ import annotations

import pytest

from governance.family_vix_fix_v1 import (
    WILLIAMS_VIX_FIX_SOURCE,
    WVF_LOOKBACK,
    williams_vix_fix_at,
)


def _bars(
    closes: list[float | None],
    lows: list[float] | None = None,
) -> list[dict]:
    """OHLC bars; a ``None`` close omits the key entirely (absent, not zero)."""
    rows: list[dict] = []
    for i, close in enumerate(closes):
        low = lows[i] if lows is not None else (close if close is not None else 9.0)
        row: dict = {"timestamp": float(i), "high": 10.0, "low": float(low)}
        if close is not None:
            row["close"] = close
        rows.append(row)
    return rows


def test_wvf_value_against_flat_close_peak() -> None:
    # Trailing closes all 100, anchor low 90 -> (100-90)/100*100 = 10.0.
    closes: list[float | None] = [100.0] * (WVF_LOOKBACK + 5)
    lows = [100.0] * (WVF_LOOKBACK + 5)
    anchor = WVF_LOOKBACK + 1
    lows[anchor] = 90.0
    assert williams_vix_fix_at(_bars(closes, lows), anchor) == pytest.approx(10.0)


def test_wvf_zero_when_low_equals_close_peak() -> None:
    closes: list[float | None] = [100.0] * (WVF_LOOKBACK + 5)
    lows = [100.0] * (WVF_LOOKBACK + 5)
    assert williams_vix_fix_at(_bars(closes, lows), WVF_LOOKBACK + 1) == pytest.approx(
        0.0
    )


def test_wvf_uses_trailing_close_peak_not_anchor_close() -> None:
    # A higher close earlier in the window sets the peak; anchor low far below.
    closes: list[float | None] = [100.0] * (WVF_LOOKBACK + 5)
    lows = [100.0] * (WVF_LOOKBACK + 5)
    anchor = WVF_LOOKBACK + 1
    closes[anchor - 3] = 200.0  # peak in the trailing window
    lows[anchor] = 150.0
    wvf = williams_vix_fix_at(_bars(closes, lows), anchor)
    assert wvf == pytest.approx((200.0 - 150.0) / 200.0 * 100.0)


def test_wvf_none_when_insufficient_history() -> None:
    closes: list[float | None] = [100.0] * (WVF_LOOKBACK + 5)
    # anchor_idx < lookback - 1 -> not enough trailing closes.
    assert williams_vix_fix_at(_bars(closes), WVF_LOOKBACK - 2) is None


def test_wvf_none_when_window_close_absent() -> None:
    closes: list[float | None] = [100.0] * (WVF_LOOKBACK + 5)
    anchor = WVF_LOOKBACK + 1
    closes[anchor - 2] = None  # a window bar lacks close -> feature absent
    assert williams_vix_fix_at(_bars(closes), anchor) is None


def test_wvf_none_when_anchor_low_absent() -> None:
    closes: list[float | None] = [100.0] * (WVF_LOOKBACK + 5)
    anchor = WVF_LOOKBACK + 1
    bars = _bars(closes)
    del bars[anchor]["low"]  # anchor bar carries no low -> absent, not zero
    assert williams_vix_fix_at(bars, anchor) is None


def test_wvf_none_when_close_peak_non_positive() -> None:
    closes: list[float | None] = [0.0] * (WVF_LOOKBACK + 5)
    lows = [0.0] * (WVF_LOOKBACK + 5)
    anchor = WVF_LOOKBACK + 1
    assert williams_vix_fix_at(_bars(closes, lows), anchor) is None


def test_wvf_is_leak_free() -> None:
    # Mutating bars strictly AFTER the anchor must not change the value.
    closes: list[float | None] = [100.0] * (WVF_LOOKBACK + 5)
    lows = [100.0] * (WVF_LOOKBACK + 5)
    anchor = WVF_LOOKBACK + 1
    lows[anchor] = 80.0
    bars = _bars(closes, lows)
    before = williams_vix_fix_at(bars, anchor)
    for k in range(anchor + 1, len(bars)):
        bars[k]["close"] = 99999.0
        bars[k]["low"] = 0.1
    after = williams_vix_fix_at(bars, anchor)
    assert before == after == pytest.approx(20.0)


def test_wvf_none_for_nan_close() -> None:
    closes: list[float | None] = [100.0] * (WVF_LOOKBACK + 5)
    anchor = WVF_LOOKBACK + 1
    closes[anchor] = float("nan")  # invalid close -> absent
    assert williams_vix_fix_at(_bars(closes), anchor) is None


def test_wvf_is_deterministic() -> None:
    closes: list[float | None] = [100.0] * (WVF_LOOKBACK + 5)
    lows = [100.0] * (WVF_LOOKBACK + 5)
    anchor = WVF_LOOKBACK + 1
    lows[anchor] = 95.0
    bars = _bars(closes, lows)
    assert williams_vix_fix_at(bars, anchor) == williams_vix_fix_at(bars, anchor)


def test_source_tag_is_versioned_v1() -> None:
    assert WILLIAMS_VIX_FIX_SOURCE == "downside_volatility_williams_vix_fix_v1"

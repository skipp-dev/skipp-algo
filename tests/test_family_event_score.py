"""Tests for the EV-24 raw per-family event score."""

from __future__ import annotations

import pytest

from governance.family_event_score import ATR_PERIOD, atr_at, raw_score


def _flat_bars(n: int, *, high: float, low: float, close: float) -> list[dict]:
    return [
        {"timestamp": float(i), "high": high, "low": low, "close": close}
        for i in range(n)
    ]


def test_atr_constant_range() -> None:
    # Every bar spans [9, 10], prev close 9.5 -> true range == 1.0 -> ATR 1.0.
    bars = _flat_bars(ATR_PERIOD + 5, high=10.0, low=9.0, close=9.5)
    assert atr_at(bars, ATR_PERIOD + 1) == pytest.approx(1.0)


def test_atr_none_when_insufficient_history() -> None:
    bars = _flat_bars(ATR_PERIOD + 5, high=10.0, low=9.0, close=9.5)
    # anchor_idx < ATR_PERIOD -> not enough trailing bars -> point-in-time None.
    assert atr_at(bars, ATR_PERIOD - 1) is None


def test_zone_score_is_height_over_atr() -> None:
    bars = _flat_bars(ATR_PERIOD + 5, high=10.0, low=9.0, close=9.5)
    score = raw_score("FVG", bars=bars, anchor_idx=ATR_PERIOD + 1, zone_low=100.0, zone_high=102.0)
    assert score == pytest.approx(2.0)  # height 2.0 / atr 1.0


def test_zone_score_monotone_in_height() -> None:
    bars = _flat_bars(ATR_PERIOD + 5, high=10.0, low=9.0, close=9.5)
    idx = ATR_PERIOD + 1
    thin = raw_score("OB", bars=bars, anchor_idx=idx, zone_low=100.0, zone_high=100.5)
    thick = raw_score("OB", bars=bars, anchor_idx=idx, zone_low=100.0, zone_high=103.0)
    assert thin is not None and thick is not None
    assert thick > thin


def test_zone_score_none_for_degenerate_height() -> None:
    bars = _flat_bars(ATR_PERIOD + 5, high=10.0, low=9.0, close=9.5)
    assert raw_score("FVG", bars=bars, anchor_idx=ATR_PERIOD + 1, zone_low=100.0, zone_high=100.0) is None


def test_level_score_is_true_range_over_atr() -> None:
    bars = _flat_bars(ATR_PERIOD + 5, high=10.0, low=9.0, close=9.5)
    score = raw_score("BOS", bars=bars, anchor_idx=ATR_PERIOD + 1)
    assert score == pytest.approx(1.0)  # anchor TR 1.0 / atr 1.0


def test_unknown_family_returns_none() -> None:
    bars = _flat_bars(ATR_PERIOD + 5, high=10.0, low=9.0, close=9.5)
    assert raw_score("NOPE", bars=bars, anchor_idx=ATR_PERIOD + 1) is None  # type: ignore[arg-type]


def test_score_is_deterministic() -> None:
    bars = _flat_bars(ATR_PERIOD + 5, high=10.0, low=9.0, close=9.5)
    idx = ATR_PERIOD + 1
    a = raw_score("FVG", bars=bars, anchor_idx=idx, zone_low=100.0, zone_high=101.5)
    b = raw_score("FVG", bars=bars, anchor_idx=idx, zone_low=100.0, zone_high=101.5)
    assert a == b

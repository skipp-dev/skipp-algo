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


# ---------------------------------------------------------------------------
# EV#7: point_in_time_regime (trend / range / neutral)
# ---------------------------------------------------------------------------


def _bars_from_closes(closes: list[float]) -> list[dict]:
    """OHLC bars whose closes follow ``closes`` (high/low bracket each close)."""
    return [
        {"timestamp": float(i), "high": c + 0.5, "low": c - 0.5, "close": c}
        for i, c in enumerate(closes)
    ]


def test_regime_trending_for_monotone_closes() -> None:
    from governance.family_event_score import REGIME_WINDOW, point_in_time_regime

    # Strictly rising closes: net travel == path length -> ER == 1 -> TRENDING.
    closes = [100.0 + i for i in range(REGIME_WINDOW + 3)]
    bars = _bars_from_closes(closes)
    assert point_in_time_regime(bars, REGIME_WINDOW + 1) == "TRENDING"


def test_regime_ranging_for_oscillating_closes() -> None:
    from governance.family_event_score import REGIME_WINDOW, point_in_time_regime

    # Saw-tooth around a flat level: large path, ~zero net travel -> ER~0 -> RANGING.
    closes = [100.0 + (1.0 if i % 2 else -1.0) for i in range(REGIME_WINDOW + 3)]
    bars = _bars_from_closes(closes)
    assert point_in_time_regime(bars, REGIME_WINDOW + 1) == "RANGING"


def test_regime_none_when_insufficient_history() -> None:
    from governance.family_event_score import REGIME_WINDOW, point_in_time_regime

    closes = [100.0 + i for i in range(REGIME_WINDOW + 3)]
    bars = _bars_from_closes(closes)
    # anchor_idx < REGIME_WINDOW -> not enough trailing closes -> None.
    assert point_in_time_regime(bars, REGIME_WINDOW - 1) is None


def test_regime_none_for_perfectly_flat_window() -> None:
    from governance.family_event_score import REGIME_WINDOW, point_in_time_regime

    bars = _bars_from_closes([100.0] * (REGIME_WINDOW + 3))
    # Zero path length -> no regime, never invented into one.
    assert point_in_time_regime(bars, REGIME_WINDOW + 1) is None


def test_regime_is_point_in_time_ignores_future_bars() -> None:
    from governance.family_event_score import REGIME_WINDOW, point_in_time_regime

    # Trending trailing window; whatever happens AFTER the anchor must not
    # change the label (leak-free by construction).
    trailing = [100.0 + i for i in range(REGIME_WINDOW + 1)]
    anchor = REGIME_WINDOW
    quiet_future = _bars_from_closes(trailing + [anchor + 100.0] * 5)
    wild_future = _bars_from_closes(
        trailing + [anchor + 100.0 + (5.0 if i % 2 else -5.0) for i in range(5)]
    )
    assert (
        point_in_time_regime(quiet_future, anchor)
        == point_in_time_regime(wild_future, anchor)
        == "TRENDING"
    )


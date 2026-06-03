"""Tests for the ADR-0019 step-1 order-flow extractor (family score v2)."""

from __future__ import annotations

import pytest

from governance.family_event_score import ATR_PERIOD
from governance.family_score_features_v2 import (
    RELATIVE_VOLUME_SOURCE,
    relative_volume_at,
)


def _bars(volumes: list[float | None]) -> list[dict]:
    """OHLCV bars; a ``None`` volume omits the key entirely (absent, not zero)."""
    rows: list[dict] = []
    for i, vol in enumerate(volumes):
        row: dict = {"timestamp": float(i), "high": 10.0, "low": 9.0, "close": 9.5}
        if vol is not None:
            row["volume"] = vol
        rows.append(row)
    return rows


def test_relative_volume_ratio_against_flat_baseline() -> None:
    # Trailing period bars all volume 100, anchor volume 250 -> ratio 2.5.
    vols: list[float | None] = [100.0] * (ATR_PERIOD + 5)
    anchor = ATR_PERIOD + 1
    vols[anchor] = 250.0
    assert relative_volume_at(_bars(vols), anchor) == pytest.approx(2.5)


def test_relative_volume_equal_when_anchor_matches_baseline() -> None:
    vols: list[float | None] = [100.0] * (ATR_PERIOD + 5)
    assert relative_volume_at(_bars(vols), ATR_PERIOD + 1) == pytest.approx(1.0)


def test_relative_volume_thin_formation_below_one() -> None:
    vols: list[float | None] = [100.0] * (ATR_PERIOD + 5)
    anchor = ATR_PERIOD + 1
    vols[anchor] = 40.0
    rel = relative_volume_at(_bars(vols), anchor)
    assert rel is not None and rel < 1.0


def test_relative_volume_none_when_insufficient_history() -> None:
    vols: list[float | None] = [100.0] * (ATR_PERIOD + 5)
    # anchor_idx < period -> not enough trailing baseline bars.
    assert relative_volume_at(_bars(vols), ATR_PERIOD - 1) is None


def test_relative_volume_none_when_anchor_volume_absent() -> None:
    vols: list[float | None] = [100.0] * (ATR_PERIOD + 5)
    anchor = ATR_PERIOD + 1
    vols[anchor] = None  # anchor bar carries no volume -> absent, not zero
    assert relative_volume_at(_bars(vols), anchor) is None


def test_relative_volume_none_when_baseline_bar_absent() -> None:
    vols: list[float | None] = [100.0] * (ATR_PERIOD + 5)
    anchor = ATR_PERIOD + 1
    vols[anchor - 2] = None  # a baseline bar lacks volume -> feature absent
    assert relative_volume_at(_bars(vols), anchor) is None


def test_relative_volume_none_when_baseline_non_positive() -> None:
    vols: list[float | None] = [0.0] * (ATR_PERIOD + 5)
    anchor = ATR_PERIOD + 1
    vols[anchor] = 100.0  # baseline mean 0 -> degenerate -> None
    assert relative_volume_at(_bars(vols), anchor) is None


def test_relative_volume_is_leak_free() -> None:
    # Mutating bars strictly AFTER the anchor must not change the value.
    vols: list[float | None] = [100.0] * (ATR_PERIOD + 5)
    anchor = ATR_PERIOD + 1
    vols[anchor] = 175.0
    bars = _bars(vols)
    before = relative_volume_at(bars, anchor)
    for k in range(anchor + 1, len(bars)):
        bars[k]["volume"] = 99999.0
    after = relative_volume_at(bars, anchor)
    assert before == after == pytest.approx(1.75)


def test_relative_volume_none_for_negative_volume() -> None:
    vols: list[float | None] = [100.0] * (ATR_PERIOD + 5)
    anchor = ATR_PERIOD + 1
    vols[anchor] = -5.0  # invalid negative volume -> absent
    assert relative_volume_at(_bars(vols), anchor) is None


def test_relative_volume_is_deterministic() -> None:
    vols: list[float | None] = [100.0] * (ATR_PERIOD + 5)
    anchor = ATR_PERIOD + 1
    vols[anchor] = 130.0
    bars = _bars(vols)
    assert relative_volume_at(bars, anchor) == relative_volume_at(bars, anchor)


def test_source_tag_is_versioned_v2() -> None:
    assert RELATIVE_VOLUME_SOURCE == "orderflow_relative_volume_v2"

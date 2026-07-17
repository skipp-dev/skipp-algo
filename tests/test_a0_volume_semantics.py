"""Focused tests for explicit A0 volume semantics and early warning."""

from __future__ import annotations

from open_prep import realtime_signals as rt


def test_volume_semantics_separates_raw_ratio_from_normalized_pace() -> None:
    raw, expected, normalized = rt._volume_semantics(200_000, 1_000_000, 0.25)
    assert raw == 0.2
    assert expected == 0.25
    assert normalized == 0.8


def test_upcoming_a2_uses_normalized_volume_pace() -> None:
    raw, _expected, normalized = rt._volume_semantics(200_000, 1_000_000, 0.25)
    assert raw < 0.8
    assert rt._is_upcoming_a2(normalized, 0.8, 1.0, 1.0)

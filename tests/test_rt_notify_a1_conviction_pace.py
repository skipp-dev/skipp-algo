"""RN-1: the A1 "⭐ high-conviction" detection + calibrated P% lookup must key on
the NORMALIZED volume pace (what the A0/A1 volume floors and the calibration
table use), not the raw daily volume_ratio the signal carries for display.

RealtimeSignal.volume_ratio is the RAW daily ratio ("display raw, not
normalized"); the normalized pace lives in details["normalized_volume_pace"].
The calibrator keys strictly on the normalized pace and the fallback midpoint
_A1_STRONG_VOL_RATIO=2.0 is a normalized floor — so passing the raw ratio buckets
a morning high-pace A1 into the wrong (low) bucket and drops the ⭐. Display-only
(Slack tail), but it mislabels the flagship conviction signal.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import open_prep.rt_notify as rt_notify
from open_prep.rt_notify import _is_high_conviction_a1


@pytest.fixture(autouse=True)
def _unarmed_calibration(monkeypatch):
    # Isolate the (default) fallback path from any calibration-file state.
    monkeypatch.setattr(rt_notify, "_calibrated_follow_through_p", lambda *a, **k: None)


def _sig(*, raw_vol: float, norm_pace: float, change: float = 1.0) -> SimpleNamespace:
    return SimpleNamespace(
        level="A1", volume_ratio=raw_vol, change_pct=change,
        details={"normalized_volume_pace": norm_pace},
    )


def test_conviction_uses_normalized_pace_not_raw_ratio() -> None:
    # Morning high-pace A1: raw daily ratio 0.5 (low early in the session) but
    # normalized pace 2.5 (past the A1->A0 midpoint of 2.0) => high-conviction.
    assert _is_high_conviction_a1(_sig(raw_vol=0.5, norm_pace=2.5)) is True


def test_high_raw_but_low_pace_is_not_conviction() -> None:
    # Inverse: raw ratio 3.0 but normalized pace 0.8 (slow grinder). The raw ratio
    # must not sneak a low-pace signal into high-conviction.
    assert _is_high_conviction_a1(_sig(raw_vol=3.0, norm_pace=0.8)) is False


def test_legacy_signal_without_pace_falls_back_to_raw() -> None:
    # A legacy signal with no normalized_volume_pace in details falls back to raw.
    s = SimpleNamespace(level="A1", volume_ratio=2.5, change_pct=1.0, details={})
    assert _is_high_conviction_a1(s) is True

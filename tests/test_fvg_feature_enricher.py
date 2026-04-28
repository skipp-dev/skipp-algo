"""Tests for the FVG quality-feature enricher in measurement_evidence."""

from __future__ import annotations

import pandas as pd

from smc_integration.measurement_evidence import (
    _atr_at,
    _fvg_quality_features,
)


def _bars(n: int = 80) -> pd.DataFrame:
    """Build a deterministic synthetic bar series with controlled vol."""
    rows = []
    px = 100.0
    for i in range(n):
        # Slight drift + 1% range
        op = px
        cl = px + (0.5 if i % 2 else -0.3)
        hi = max(op, cl) + 0.4
        lo = min(op, cl) - 0.4
        rows.append({"time": float(i), "open": op, "high": hi, "low": lo, "close": cl})
        px = cl
    return pd.DataFrame(rows)


def test_atr_returns_positive_finite() -> None:
    bars = _bars()
    atr = _atr_at(bars, anchor_idx=30)
    assert atr is not None
    assert atr > 0


def test_atr_returns_none_for_short_window() -> None:
    bars = _bars(n=10)
    assert _atr_at(bars, anchor_idx=5) is None


def test_features_full_payload() -> None:
    bars = _bars()
    feats = _fvg_quality_features(
        event={"id": "f1"},
        bars=bars,
        anchor_idx=60,
        low=99.5,
        high=100.5,
        direction="BULL",
        event_context={"session": "NY_AM"},
        bias_direction="BULL",
    )
    assert "gap_size_atr" in feats
    assert feats["gap_size_atr"] > 0
    assert "distance_to_price_atr" in feats
    assert feats["htf_aligned"] is True
    assert feats["is_full_body"] in (True, False)
    assert "hurst_50" in feats
    assert 0.0 <= feats["hurst_50"] <= 1.0


def test_htf_alignment_false_when_directions_differ() -> None:
    bars = _bars()
    feats = _fvg_quality_features(
        event={},
        bars=bars,
        anchor_idx=60,
        low=99.5,
        high=100.5,
        direction="BEAR",
        event_context={},
        bias_direction="BULL",
    )
    assert feats["htf_aligned"] is False


def test_features_omit_atr_dependent_when_no_atr() -> None:
    bars = _bars(n=10)
    feats = _fvg_quality_features(
        event={},
        bars=bars,
        anchor_idx=5,
        low=99.5,
        high=100.5,
        direction="BULL",
        event_context={},
        bias_direction="BULL",
    )
    # ATR available only with >= 14 prior bars; gap_size_atr must drop out.
    assert "gap_size_atr" not in feats
    assert "distance_to_price_atr" not in feats
    # Boolean features still present.
    assert "htf_aligned" in feats
    assert "is_full_body" in feats


def test_features_keys_match_recalibration_contract() -> None:
    from scripts.fvg_quality_recalibration import FEATURE_KEYS

    bars = _bars()
    feats = _fvg_quality_features(
        event={},
        bars=bars,
        anchor_idx=60,
        low=99.5,
        high=100.5,
        direction="BULL",
        event_context={},
        bias_direction="BULL",
    )
    # Every key produced by the enricher must be a recognised feature.
    for key in feats:
        assert key in FEATURE_KEYS

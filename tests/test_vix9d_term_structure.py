"""Tests for the VIX9D term-structure observe-only feature (eval D5).

``vix9d_vix_ratio`` = VIX9D / VIX. > 1 ⇒ inverted short-term structure ⇒
the market prices an imminent event risk. Recorded per outcome record for
FI evidence; intentionally NOT mapped to a scorer weight.
"""
from __future__ import annotations

from datetime import date

from open_prep.outcomes import (
    FEATURE_KEYS,
    FEATURE_TO_WEIGHT_KEY,
    PASS_THROUGH_FEATURE_KEYS,
    prepare_outcome_snapshot,
)


class TestVix9dFeatureWiring:
    def test_in_feature_keys(self) -> None:
        assert "vix9d_vix_ratio" in FEATURE_KEYS

    def test_is_pass_through(self) -> None:
        assert "vix9d_vix_ratio" in PASS_THROUGH_FEATURE_KEYS

    def test_not_weighted(self) -> None:
        # Observe-only: must NOT map to a scorer weight.
        assert "vix9d_vix_ratio" not in FEATURE_TO_WEIGHT_KEY

    def test_snapshot_carries_ratio(self) -> None:
        rows = [{
            "symbol": "NVDA", "gap_pct": 5.0, "volume": 2_000_000,
            "avg_volume": 1_000_000, "score": 9.0,
            "playbook": {"playbook": "GAP_AND_GO"},
            "vix9d_vix_ratio": 1.0858,
        }]
        rec = prepare_outcome_snapshot(rows, date(2026, 6, 11))[0]
        assert rec["vix9d_vix_ratio"] == 1.0858

    def test_snapshot_none_when_missing(self) -> None:
        rows = [{
            "symbol": "NVDA", "gap_pct": 5.0, "volume": 2_000_000,
            "avg_volume": 1_000_000, "score": 9.0,
        }]
        rec = prepare_outcome_snapshot(rows, date(2026, 6, 11))[0]
        assert rec["vix9d_vix_ratio"] is None


class TestRatioComputation:
    """Mirror the pipeline's ratio guard logic."""

    @staticmethod
    def _ratio(vix9d: float | None, vix: float | None) -> float | None:
        if vix9d is not None and vix is not None and vix > 0:
            return round(vix9d / vix, 4)
        return None

    def test_inverted_structure_gt_one(self) -> None:
        # 2026-06-11 live values: VIX9D 22.53 vs VIX 20.75.
        assert self._ratio(22.53, 20.75) == 1.0858

    def test_normal_structure_lt_one(self) -> None:
        assert self._ratio(14.0, 17.5) == 0.8

    def test_missing_vix9d_returns_none(self) -> None:
        assert self._ratio(None, 20.0) is None

    def test_missing_vix_returns_none(self) -> None:
        assert self._ratio(22.0, None) is None

    def test_zero_vix_returns_none(self) -> None:
        assert self._ratio(22.0, 0.0) is None

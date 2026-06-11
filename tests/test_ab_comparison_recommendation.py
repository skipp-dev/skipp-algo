"""Tests for the A/B comparison Promote/Hold/Rollback decision (ENG-WS4-04)."""
from __future__ import annotations

import json

from scripts.run_ab_comparison import (
    HIT_RATE_REGRESSION_TOLERANCE,
    PROMOTE_IMPROVEMENT,
    ROLLBACK_REGRESSION,
    compare,
    decide_recommendation,
    render_comparison,
)


def _row(metric: str, control: float, treatment: float) -> dict:
    return {
        "metric": metric,
        "control": control,
        "treatment": treatment,
        "delta": round(treatment - control, 4),
        "direction": "n/a",
    }


# ── decide_recommendation ────────────────────────────────────────────


class TestDecideRecommendation:
    def test_promote_when_both_calibration_metrics_improve(self) -> None:
        rows = [
            _row("brier", 0.30, 0.29),
            _row("calibrated_brier", 0.20, 0.19),  # delta -0.01 ≤ -PROMOTE
            _row("calibrated_ece", 0.05, 0.04),    # delta -0.01 ≤ -PROMOTE
            _row("hit_rate_pct", 55.0, 55.5),
        ]
        d = decide_recommendation(rows)
        assert d["recommendation"] == "promote"
        assert "improve" in d["reason"]
        assert d["kpi_thresholds"]["promote_improvement"] == PROMOTE_IMPROVEMENT

    def test_rollback_when_calibrated_brier_regresses(self) -> None:
        rows = [
            _row("brier", 0.30, 0.30),
            _row("calibrated_brier", 0.20, 0.215),  # delta +0.015 > rollback 0.010
            _row("calibrated_ece", 0.05, 0.05),
            _row("hit_rate_pct", 55.0, 55.0),
        ]
        d = decide_recommendation(rows)
        assert d["recommendation"] == "rollback"
        assert d["kpi_thresholds"]["rollback_regression"] == ROLLBACK_REGRESSION

    def test_rollback_when_calibrated_ece_regresses(self) -> None:
        rows = [
            _row("brier", 0.30, 0.30),
            _row("calibrated_brier", 0.20, 0.20),
            _row("calibrated_ece", 0.05, 0.07),  # delta +0.02 > rollback 0.010
            _row("hit_rate_pct", 55.0, 56.0),
        ]
        d = decide_recommendation(rows)
        assert d["recommendation"] == "rollback"

    def test_hold_when_metrics_drift_only_marginally(self) -> None:
        rows = [
            _row("brier", 0.30, 0.301),
            _row("calibrated_brier", 0.20, 0.201),  # +0.001, neither side
            _row("calibrated_ece", 0.05, 0.051),
            _row("hit_rate_pct", 55.0, 55.0),
        ]
        d = decide_recommendation(rows)
        assert d["recommendation"] == "hold"

    def test_hold_when_calibration_improves_but_hit_rate_collapses(self) -> None:
        rows = [
            _row("brier", 0.30, 0.29),
            _row("calibrated_brier", 0.20, 0.19),
            _row("calibrated_ece", 0.05, 0.04),
            # hit_rate drops by 5pp – exceeds tolerance.
            _row("hit_rate_pct", 55.0, 50.0),
        ]
        d = decide_recommendation(rows)
        assert d["recommendation"] == "hold"
        assert d["kpi_thresholds"]["hit_rate_regression_tolerance"] == \
            HIT_RATE_REGRESSION_TOLERANCE


# ── compare() integration ────────────────────────────────────────────


def _pair(symbol: str, brier: float, cb: float, ce: float, hr: float) -> dict:
    return {
        "symbol": symbol,
        "timeframe": "5m",
        "n_events": 100,
        "brier": brier,
        "log_score": 0.5,
        "hit_rate_pct": hr,
        "calibration_method": "isotonic",
        "calibrated_brier": cb,
        "calibrated_ece": ce,
        "raw_ece": ce + 0.01,
        "ensemble_score": 0.5,
        "ensemble_tier": "B",
        "populated_buckets": 4,
    }


class TestCompareIntegration:
    def test_compare_includes_recommendation(self) -> None:
        ctrl = [_pair("AAA", 0.30, 0.20, 0.05, 55.0)]
        treat = [_pair("AAA", 0.29, 0.19, 0.04, 55.5)]
        digest = compare(ctrl, treat, "static-vs-auto_tuned")
        assert digest["recommendation"] in ("promote", "hold", "rollback")
        assert digest["recommendation"] == "promote"
        assert "kpi_thresholds" in digest

    def test_compare_is_deterministic(self) -> None:
        ctrl = [_pair("AAA", 0.30, 0.20, 0.05, 55.0)]
        treat = [_pair("AAA", 0.29, 0.19, 0.04, 55.5)]
        d1 = compare(ctrl, treat, "x")
        d2 = compare(ctrl, treat, "x")
        # JSON-equal — same inputs → same digest.
        assert json.dumps(d1, sort_keys=True) == json.dumps(d2, sort_keys=True)

    def test_render_includes_decision_block(self) -> None:
        digest = {
            "experiment": "x",
            "control_pairs": 1,
            "treatment_pairs": 1,
            "control_grade": "B",
            "treatment_grade": "A",
            "metrics": [
                _row("brier", 0.30, 0.29),
                _row("calibrated_brier", 0.20, 0.19),
                _row("calibrated_ece", 0.05, 0.04),
                _row("hit_rate_pct", 55.0, 55.5),
            ],
            "recommendation": "promote",
            "recommendation_reason": "deltas within thresholds",
            "kpi_thresholds": {
                "promote_improvement": PROMOTE_IMPROVEMENT,
                "rollback_regression": ROLLBACK_REGRESSION,
                "hit_rate_regression_tolerance": HIT_RATE_REGRESSION_TOLERANCE,
            },
        }
        md = render_comparison(digest)
        assert "## Recommendation" in md
        assert "`PROMOTE`" in md
        assert "promote_improvement" in md


# ---------------------------------------------------------------------------
# W4-2 regression: delta None / NaN must not silently suppress rollback
# ---------------------------------------------------------------------------

import math  # noqa: E402 — appended after existing imports


def test_w4_2_missing_calibrated_brier_row_yields_hold_with_reason() -> None:
    """W4-2: missing calibrated_brier row must surface as explicit hold.

    Previously `None or 0.0 == 0.0` silenced a potential rollback.
    """
    rows = [
        _row("calibrated_ece", 0.05, 0.08),  # +0.03 regression — should rollback
        # calibrated_brier row intentionally absent
    ]
    rec = decide_recommendation(rows)
    assert rec["recommendation"] == "hold", (
        f"expected hold for missing calibrated_brier, got {rec['recommendation']}"
    )
    assert "calibrated_brier" in rec["reason"]
    assert "unavailable" in rec["reason"] or "NaN" in rec["reason"]


def test_w4_2_nan_calibrated_ece_delta_yields_hold_with_reason() -> None:
    """W4-2: NaN delta in calibrated_ece must surface as explicit hold.

    Previously bool(NaN)=True → NaN or 0.0 = NaN → NaN > threshold = False
    → silently fell through to HOLD but with no diagnostic reason.
    """
    rows = [
        {"metric": "calibrated_brier", "control": 0.20, "treatment": 0.23, "delta": float("nan")},
        {"metric": "calibrated_ece", "control": 0.05, "treatment": 0.08, "delta": float("nan")},
        _row("hit_rate_pct", 55.0, 54.0),
    ]
    rec = decide_recommendation(rows)
    assert rec["recommendation"] == "hold"
    assert "unavailable" in rec["reason"] or "NaN" in rec["reason"]


def test_w4_2_normal_regression_still_triggers_rollback() -> None:
    """W4-2: a real numeric regression above ROLLBACK_REGRESSION fires rollback."""
    rows = [
        _row("calibrated_brier", 0.20, 0.215),  # delta = +0.015 > 0.010
        _row("calibrated_ece", 0.05, 0.06),
        _row("hit_rate_pct", 55.0, 54.5),
    ]
    rec = decide_recommendation(rows)
    assert rec["recommendation"] == "rollback"

"""Tests for Phase G — Automated Scorer Tuning (G1–G2).

G3 arm-routing is tested in ``tests/test_ab_arms.py`` (run-granular,
``open_prep/ab_arms.py``); the per-symbol ``Experiment.resolve_weight_set``
tests that used to live here were removed 2026-07-29 together with the
never-wired ``scripts/smc_ab_experiment.py``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from open_prep.outcomes import (
    FEATURE_KEYS,
    FEATURE_TO_WEIGHT_KEY,
    PASS_THROUGH_FEATURE_KEYS,
    check_scorer_drift,
    compute_weight_adjustments,
    scorer_update_to_json,
)

# ── G1: Feature-to-weight mapping ───────────────────────────────


def test_feature_to_weight_covers_all_weighted_keys() -> None:
    """Every FEATURE_KEY except pass-throughs maps to a weight."""
    for fk in FEATURE_KEYS:
        if fk in PASS_THROUGH_FEATURE_KEYS:
            assert fk not in FEATURE_TO_WEIGHT_KEY
        else:
            assert fk in FEATURE_TO_WEIGHT_KEY, f"{fk} missing from mapping"


def test_weight_keys_exist_in_defaults() -> None:
    """All mapped weight keys exist in DEFAULT_WEIGHTS."""
    from open_prep.scorer import DEFAULT_WEIGHTS

    for wk in FEATURE_TO_WEIGHT_KEY.values():
        assert wk in DEFAULT_WEIGHTS, f"weight key '{wk}' not in DEFAULT_WEIGHTS"


# ── G2: compute_weight_adjustments ──────────────────────────────


def _make_fi_report(
    importances: dict[str, float] | None = None,
    labeled: int = 100,
    *,
    fdr_significant: bool = True,
) -> dict[str, Any]:
    """Build a synthetic feature importance report.

    ``fdr_significant`` defaults to True so the legacy weight-movement
    tests exercise the data-driven path; the BH-FDR gating itself is
    covered by ``test_weight_adjustments_non_significant_is_neutral``.
    """
    features: dict[str, Any] = {}
    for key in FEATURE_KEYS:
        imp = (importances or {}).get(key, 0.5)
        features[key] = {
            "pearson_r": 0.3,
            "mean_separation": imp,
            "mean_win": 0.5,
            "mean_loss": 0.3,
            "importance_normalized": imp,
            "p_value": 0.001 if fdr_significant else 0.9,
            "fdr_significant": fdr_significant,
        }
    return {
        "total_samples": labeled,
        "labeled_samples": labeled,
        "features": features,
        "recommendations": [],
    }


def test_weight_adjustments_neutral_importance() -> None:
    """importance=0.5 for all features should change weights minimally."""
    from open_prep.scorer import DEFAULT_WEIGHTS

    report = _make_fi_report()  # all 0.5
    update = compute_weight_adjustments(report, dict(DEFAULT_WEIGHTS))
    for wk in FEATURE_TO_WEIGHT_KEY.values():
        # With imp=0.5: data_weight = cur * 1.0 = cur; blend is exact prior
        assert abs(update.updated_weights[wk] - DEFAULT_WEIGHTS[wk]) < 0.01


def test_weight_adjustments_high_importance_increases() -> None:
    """importance=1.0 should increase the weight."""
    from open_prep.scorer import DEFAULT_WEIGHTS

    report = _make_fi_report({"gap_component": 1.0})
    update = compute_weight_adjustments(report, dict(DEFAULT_WEIGHTS), smoothing=0.0)
    # data_weight = 0.8 * (0.5 + 1.0) = 1.2 → with smoothing=0.0, new = 1.2
    assert update.updated_weights["gap"] == pytest.approx(1.2, abs=0.01)
    assert update.deltas["gap"] > 0


def test_weight_adjustments_low_importance_decreases() -> None:
    """importance=0.0 should decrease the weight."""
    from open_prep.scorer import DEFAULT_WEIGHTS

    report = _make_fi_report({"rvol_component": 0.0})
    update = compute_weight_adjustments(report, dict(DEFAULT_WEIGHTS), smoothing=0.0)
    # data_weight = 1.2 * (0.5 + 0.0) = 0.6 → with smoothing=0.0, new = 0.6
    assert update.updated_weights["rvol"] == pytest.approx(0.6, abs=0.01)
    assert update.deltas["rvol"] < 0


def test_weight_adjustments_smoothing_blends_with_prior() -> None:
    """smoothing=1.0 should return pure prior regardless of data."""
    from open_prep.scorer import DEFAULT_WEIGHTS

    report = _make_fi_report({"gap_component": 1.0})
    update = compute_weight_adjustments(
        report, dict(DEFAULT_WEIGHTS), smoothing=1.0,
    )
    # Pure prior blend → should equal DEFAULT_WEIGHTS
    assert update.updated_weights["gap"] == pytest.approx(
        DEFAULT_WEIGHTS["gap"], abs=0.01,
    )


def test_weight_adjustments_non_significant_is_neutral() -> None:
    """Features failing the BH-FDR gate must NOT move weights (eval B3)."""
    from open_prep.scorer import DEFAULT_WEIGHTS

    report = _make_fi_report({"gap_component": 1.0}, fdr_significant=False)
    update = compute_weight_adjustments(report, dict(DEFAULT_WEIGHTS), smoothing=0.0)
    # imp forced to neutral 0.5 → data_weight == current → no movement.
    assert update.updated_weights["gap"] == pytest.approx(
        DEFAULT_WEIGHTS["gap"], abs=0.01,
    )


def test_weight_adjustments_error_report_raises() -> None:
    """An error report should raise ValueError."""
    report = {"error": "insufficient labeled samples", "labeled_samples": 3}
    with pytest.raises(ValueError, match="insufficient"):
        compute_weight_adjustments(report, {})


def test_weight_adjustments_preserves_unrelated_keys() -> None:
    """Penalty weights not in FEATURE_TO_WEIGHT_KEY pass through."""
    from open_prep.scorer import DEFAULT_WEIGHTS

    report = _make_fi_report()
    update = compute_weight_adjustments(report, dict(DEFAULT_WEIGHTS))
    # Penalty keys should be unchanged
    assert update.updated_weights["liquidity_penalty"] == DEFAULT_WEIGHTS["liquidity_penalty"]
    assert update.updated_weights["corporate_action_penalty"] == DEFAULT_WEIGHTS["corporate_action_penalty"]


def test_weight_adjustments_floor_at_001() -> None:
    """Weights must never drop below 0.01."""
    from open_prep.scorer import DEFAULT_WEIGHTS

    # Give hvb (default 0.3) importance=0.0 with smoothing=0.0
    # data_weight = 0.3 * 0.5 = 0.15 — above floor
    # Try a very small current weight
    weights = dict(DEFAULT_WEIGHTS)
    weights["hvb"] = 0.01
    report = _make_fi_report({"hvb_component": 0.0})
    update = compute_weight_adjustments(report, weights, smoothing=0.0)
    # data_weight = 0.01 * 0.5 = 0.005 → floored to 0.01
    assert update.updated_weights["hvb"] >= 0.01


# ── G2: check_scorer_drift ──────────────────────────────────────


def test_no_drift_from_defaults() -> None:
    from open_prep.scorer import DEFAULT_WEIGHTS

    violations = check_scorer_drift(dict(DEFAULT_WEIGHTS))
    assert violations == []


def test_drift_detected() -> None:
    from open_prep.scorer import DEFAULT_WEIGHTS

    weights = dict(DEFAULT_WEIGHTS)
    weights["gap"] = 5.0  # drift = |5.0 - 0.8| = 4.2
    violations = check_scorer_drift(weights, max_drift=0.50)
    assert len(violations) >= 1
    assert any("gap" in v for v in violations)


def test_drift_threshold_customizable() -> None:
    from open_prep.scorer import DEFAULT_WEIGHTS

    weights = dict(DEFAULT_WEIGHTS)
    weights["rvol"] = 1.3  # drift = |1.3 - 1.2| = 0.1
    # Should pass at max_drift=0.50
    assert check_scorer_drift(weights, max_drift=0.50) == []
    # Should fail at max_drift=0.05
    violations = check_scorer_drift(weights, max_drift=0.05)
    assert any("rvol" in v for v in violations)


# ── G2: scorer_update_to_json ───────────────────────────────────


def test_scorer_update_json_serializable() -> None:
    from open_prep.scorer import DEFAULT_WEIGHTS

    report = _make_fi_report()
    update = compute_weight_adjustments(report, dict(DEFAULT_WEIGHTS))
    d = scorer_update_to_json(update)
    assert "updated_weights" in d
    assert "labeled_samples" in d
    json.dumps(d)  # must be serializable

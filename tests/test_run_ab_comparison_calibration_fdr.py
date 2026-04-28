"""S-2 follow-up: Bootstrap-FDR over family×{brier,ece} cells.

Permutation-based BH-FDR layer on calibration metrics
(``digest["fdr_calibration"]``). The layer is **advisory only** — it
must never alter Promote/Hold/Rollback or the existing hit-rate
``digest["fdr"]`` block. The Phipson-Smyth ``(r+1)/(B+1)`` correction
must clamp p-values away from exactly 0/1.
"""
from __future__ import annotations

import math
import random
from typing import Any

import pytest

from scripts.run_ab_comparison import (
    MIN_EVENTS_PER_ARM_FOR_BOOTSTRAP,
    _calibration_fdr_layer,
    _metric_brier,
    _metric_ece,
    _permutation_p_delta_metric,
    compare,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _gen_events(
    n: int, *, p_true: float, label_bias: float = 0.0, seed: int = 0
) -> list[tuple[float, bool]]:
    """Synthetic (prob, outcome) events.

    ``p_true`` is the model's emitted probability (constant across events
    for simplicity), ``label_bias`` shifts the actual outcome probability
    away from ``p_true`` so we can simulate calibration error.
    """
    rng = random.Random(seed)
    out: list[tuple[float, bool]] = []
    for _ in range(n):
        p = max(0.0, min(1.0, p_true + rng.gauss(0.0, 0.05)))
        actual_p = max(0.0, min(1.0, p_true + label_bias))
        outcome = rng.random() < actual_p
        out.append((p, outcome))
    return out


def _baseline_pairs(n_pairs: int = 1) -> list[dict[str, Any]]:
    """Minimal non-empty pair dicts so ``compare()`` can run."""
    return [
        {
            "symbol": "TEST",
            "timeframe": "5m",
            "n_events": 100,
            "brier": 0.20,
            "log_score": 0.30,
            "hit_rate_pct": 55.0,
            "calibrated_brier": 0.20,
            "calibrated_ece": 0.05,
            "raw_ece": 0.05,
            "family_metrics": {
                "FVG": {"n_events": 50, "hit_rate": 0.55},
            },
        }
        for _ in range(n_pairs)
    ]


# ---------------------------------------------------------------------------
# Metric-fn unit tests
# ---------------------------------------------------------------------------


def test_brier_known_value() -> None:
    events = [(0.8, True), (0.2, False), (0.5, True), (0.5, False)]
    # ((0.8-1)^2 + (0.2-0)^2 + (0.5-1)^2 + (0.5-0)^2) / 4
    expected = (0.04 + 0.04 + 0.25 + 0.25) / 4
    assert _metric_brier(events) == pytest.approx(expected)


def test_brier_nan_on_empty() -> None:
    assert math.isnan(_metric_brier([]))


def test_ece_perfect_calibration_is_zero() -> None:
    # 100 events at p=0.5 with exactly 50% positive outcomes → ECE = 0.
    events = [(0.5, i < 50) for i in range(100)]
    assert _metric_ece(events) == pytest.approx(0.0, abs=1e-9)


def test_ece_nan_on_empty() -> None:
    assert math.isnan(_metric_ece([]))


# ---------------------------------------------------------------------------
# Permutation p-value
# ---------------------------------------------------------------------------


def test_permutation_returns_none_below_min_events() -> None:
    treat = _gen_events(MIN_EVENTS_PER_ARM_FOR_BOOTSTRAP - 1, p_true=0.5, seed=1)
    ctrl = _gen_events(MIN_EVENTS_PER_ARM_FOR_BOOTSTRAP, p_true=0.5, seed=2)
    p = _permutation_p_delta_metric(
        treatment=treat, control=ctrl, metric_fn=_metric_brier, B=50, seed=42
    )
    assert p is None


def test_permutation_seed_determinism() -> None:
    treat = _gen_events(60, p_true=0.5, label_bias=-0.05, seed=11)
    ctrl = _gen_events(60, p_true=0.5, seed=22)
    p1 = _permutation_p_delta_metric(
        treatment=treat, control=ctrl, metric_fn=_metric_brier, B=200, seed=42
    )
    p2 = _permutation_p_delta_metric(
        treatment=treat, control=ctrl, metric_fn=_metric_brier, B=200, seed=42
    )
    assert p1 == p2


def test_permutation_phipson_smyth_clamps_pvalue() -> None:
    # Even with a clearly extreme observation, p must satisfy
    # 1/(B+1) <= p <= B/(B+1) — never exactly 0 or 1.
    treat = [(0.05, False)] * 60        # extremely low brier
    ctrl = [(0.95, False)] * 60         # extremely high brier
    B = 100
    p = _permutation_p_delta_metric(
        treatment=treat, control=ctrl, metric_fn=_metric_brier, B=B, seed=7
    )
    assert p is not None
    assert 1 / (B + 1) <= p <= B / (B + 1)


# ---------------------------------------------------------------------------
# Calibration-FDR layer integration
# ---------------------------------------------------------------------------


def _make_ledger_pair(
    events_per_family: dict[str, list[tuple[float, bool]]],
) -> list[tuple[str, float, bool]]:
    rows: list[tuple[str, float, bool]] = []
    for family, events in events_per_family.items():
        for prob, outcome in events:
            rows.append((family, prob, outcome))
    return rows


def test_disabled_returns_skipped_disabled() -> None:
    out = _calibration_fdr_layer(
        control_ledgers=None, treatment_ledgers=None, enabled=False
    )
    assert out == {"skipped_reason": "disabled", "method": "permutation_bh"}


def test_ledger_missing_returns_skipped_reason() -> None:
    out = _calibration_fdr_layer(
        control_ledgers=None, treatment_ledgers=None, enabled=True
    )
    assert out["skipped_reason"] == "ledger_not_provided"


def test_layer_skips_undersized_cells() -> None:
    # Only 10 events per family per arm → below MIN_EVENTS_PER_ARM_FOR_BOOTSTRAP.
    ledger_c = _make_ledger_pair(
        {"FVG": _gen_events(10, p_true=0.5, seed=1)}
    )
    ledger_t = _make_ledger_pair(
        {"FVG": _gen_events(10, p_true=0.5, seed=2)}
    )
    out = _calibration_fdr_layer(
        control_ledgers=[ledger_c],
        treatment_ledgers=[ledger_t],
        enabled=True,
        B=100,
    )
    assert out["tested_cells"] == 0
    assert out["skipped_cells"] == 2  # brier + ece both skipped
    for cell in out["cells"]:
        assert cell["skipped_reason"] == "insufficient_events_for_bootstrap"
        assert cell["rejected"] is False


def test_layer_runs_and_returns_well_formed_output_under_h0() -> None:
    # Both arms drawn from same distribution → expect mostly no rejections.
    ledger_c = _make_ledger_pair(
        {
            "FVG": _gen_events(60, p_true=0.5, seed=1),
            "BOS": _gen_events(60, p_true=0.5, seed=3),
        }
    )
    ledger_t = _make_ledger_pair(
        {
            "FVG": _gen_events(60, p_true=0.5, seed=2),
            "BOS": _gen_events(60, p_true=0.5, seed=4),
        }
    )
    out = _calibration_fdr_layer(
        control_ledgers=[ledger_c],
        treatment_ledgers=[ledger_t],
        enabled=True,
        B=200,
    )
    assert out["method"] == "permutation_bh"
    assert out["B"] == 200
    assert out["tested_cells"] == 4  # 2 families × 2 metrics
    assert out["skipped_cells"] == 0
    # Notes documents the post-calibration conditioning.
    assert "post-calibration" in out["notes"]
    # No cells should be rejected at q=0.05 in expectation under H0.
    assert len(out["rejected_cells"]) <= 1


def test_layer_detects_clear_treatment_improvement() -> None:
    # Treatment arm has perfectly calibrated probabilities (brier ~ 0.25
    # baseline for p=0.5). Control arm has biased probabilities (brier >> 0.25).
    # With enough events, treatment should be significantly better on brier.
    ctrl_events = [(0.9, False)] * 80 + [(0.1, True)] * 80    # brier ~ 0.81
    treat_events = [(0.5, True)] * 80 + [(0.5, False)] * 80   # brier = 0.25
    ledger_c = _make_ledger_pair({"FVG": ctrl_events})
    ledger_t = _make_ledger_pair({"FVG": treat_events})
    out = _calibration_fdr_layer(
        control_ledgers=[ledger_c],
        treatment_ledgers=[ledger_t],
        enabled=True,
        B=200,
    )
    brier_cell = next(c for c in out["cells"] if c["metric"] == "brier")
    assert brier_cell["delta"] is not None
    assert brier_cell["delta"] < 0  # treatment lower (better)
    assert brier_cell["rejected"] is True
    assert brier_cell["adjusted_p_value"] is not None
    assert brier_cell["adjusted_p_value"] < 0.05


# ---------------------------------------------------------------------------
# compare() integration + advisory-only contract
# ---------------------------------------------------------------------------


def test_compare_emits_fdr_calibration_field() -> None:
    digest = compare(
        _baseline_pairs(),
        _baseline_pairs(),
        "exp",
        enable_calibration_fdr=False,
    )
    assert "fdr_calibration" in digest
    assert digest["fdr_calibration"]["skipped_reason"] == "disabled"


def test_compare_advisory_only_does_not_change_recommendation() -> None:
    # Build a scenario where promote criteria are met by the metrics rows.
    pairs = _baseline_pairs()
    pairs_better = [
        {**pairs[0], "calibrated_brier": 0.18, "calibrated_ece": 0.04}
    ]
    # Construct ledgers where ALL calibration cells get rejected.
    ctrl_events = [(0.9, False)] * 80 + [(0.1, True)] * 80
    treat_events = [(0.5, True)] * 80 + [(0.5, False)] * 80
    ledger_c = [_make_ledger_pair({"FVG": ctrl_events, "BOS": ctrl_events})]
    ledger_t = [_make_ledger_pair({"FVG": treat_events, "BOS": treat_events})]

    digest_with_fdr = compare(
        pairs,
        pairs_better,
        "exp",
        control_ledgers=ledger_c,
        treatment_ledgers=ledger_t,
        enable_calibration_fdr=True,
        calibration_fdr_B=200,
    )
    digest_without = compare(pairs, pairs_better, "exp")

    # Recommendation, recommendation_reason, hit-rate FDR layer are unchanged.
    assert digest_with_fdr["recommendation"] == digest_without["recommendation"]
    assert digest_with_fdr["recommendation_reason"] == digest_without["recommendation_reason"]
    assert digest_with_fdr["fdr"] == digest_without["fdr"]
    assert digest_with_fdr["sprt"] == digest_without["sprt"]
    # And fdr_calibration did rejct at least one cell, proving the advisory
    # block was actually computed and non-trivial.
    assert len(digest_with_fdr["fdr_calibration"]["rejected_cells"]) >= 1

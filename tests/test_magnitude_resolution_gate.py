"""Unit tests for the ADR-0023 §2 move-size acceptance-bar estimators."""
from __future__ import annotations

import math
import random

import pytest

from governance.magnitude_resolution_gate import (
    MAG_AUC_CI_LOW_FLOOR,
    MAG_AUC_FLOOR,
    MAGNITUDE_GATE_SOURCE_TAG,
    _permutation_p_value,
    bootstrap_auc_ci,
    evaluate_family_magnitude_resolution,
    magnitude_resolution_report,
    permutation_resolution_null,
)


def _separable() -> tuple[list[float], list[float]]:
    # Forecasts perfectly ordered with the labels => AUC 1.0.
    outcomes = [0.0] * 50 + [1.0] * 50
    probs = [0.1 + 0.003 * i for i in range(50)] + [
        0.55 + 0.003 * i for i in range(50)
    ]
    return outcomes, probs


def test_bootstrap_ci_separable_is_high_and_ordered() -> None:
    outcomes, probs = _separable()
    low, high = bootstrap_auc_ci(
        outcomes, probs, n_boot=200, rng=random.Random(1)
    )
    assert 0.0 <= low <= high <= 1.0
    assert low > 0.9  # a cleanly separable signal keeps the CI lower bound high


def test_bootstrap_ci_single_class_is_degenerate_half() -> None:
    # roc_auc returns 0.5 for a single-class resample; the CI must collapse to it
    # rather than raise, so a degenerate family is penalised, not flattered.
    low, high = bootstrap_auc_ci(
        [1.0] * 40, [0.3 + 0.001 * i for i in range(40)],
        n_boot=100,
        rng=random.Random(2),
    )
    assert low == pytest.approx(0.5)
    assert high == pytest.approx(0.5)


def test_bootstrap_ci_is_deterministic_under_seed() -> None:
    outcomes, probs = _separable()
    a = bootstrap_auc_ci(outcomes, probs, n_boot=128, rng=random.Random(7))
    b = bootstrap_auc_ci(outcomes, probs, n_boot=128, rng=random.Random(7))
    assert a == b


def test_permutation_null_shape_and_nonnegative() -> None:
    outcomes, probs = _separable()
    null = permutation_resolution_null(
        outcomes, probs, n_perm=64, rng=random.Random(3)
    )
    assert len(null) == 64
    assert all(v >= 0.0 for v in null)


def test_permutation_p_value_extremes() -> None:
    null = [0.001, 0.002, 0.0015, 0.0008]
    # Observed strictly above every null draw => the add-one minimum p-value.
    assert _permutation_p_value(0.05, null) == pytest.approx(1 / (len(null) + 1))
    # Observed at/below every null draw => every draw counts as >=.
    assert _permutation_p_value(0.0, null) == pytest.approx(1.0)


def _synthetic_family(
    n: int, *, resolves: bool, seed: int
) -> dict[str, list[float]]:
    rng = random.Random(seed)
    scores: list[float] = []
    returns: list[float] = []
    anchor_ts: list[float] = []
    guard_end_ts: list[float] = []
    for i in range(n):
        s = rng.random()
        sign = 1.0 if rng.random() < 0.5 else -1.0
        if resolves:
            # |return| grows with the score => the score resolves move-size.
            magnitude = 0.001 + 0.02 * s + rng.gauss(0.0, 0.001)
        else:
            # |return| independent of the score => no move-size resolution.
            magnitude = 0.001 + 0.02 * rng.random()
        scores.append(s)
        returns.append(sign * abs(magnitude))
        anchor_ts.append(float(i))
        guard_end_ts.append(i + 0.5)
    return {
        "scores": scores,
        "returns": returns,
        "anchor_ts": anchor_ts,
        "guard_end_ts": guard_end_ts,
    }


def test_evaluate_thin_sample_returns_none() -> None:
    fam = _synthetic_family(20, resolves=True, seed=11)
    result = evaluate_family_magnitude_resolution(
        "BOS",
        fam["scores"],
        fam["returns"],
        fam["anchor_ts"],
        fam["guard_end_ts"],
        n_boot=32,
        n_perm=32,
    )
    assert result is None


def test_evaluate_resolving_family_passes() -> None:
    fam = _synthetic_family(400, resolves=True, seed=21)
    result = evaluate_family_magnitude_resolution(
        "SWEEP",
        fam["scores"],
        fam["returns"],
        fam["anchor_ts"],
        fam["guard_end_ts"],
        n_boot=200,
        n_perm=200,
    )
    assert result is not None
    assert result.source == MAGNITUDE_GATE_SOURCE_TAG
    assert result.mag_auc >= MAG_AUC_FLOOR
    assert result.auc_ci_low >= MAG_AUC_CI_LOW_FLOOR
    assert result.baseline_resolution > result.perm_null_p95
    assert result.passes is True
    assert result.verdict == "passes_magnitude_resolution_floor"
    assert not math.isnan(result.direction_brier)


def test_evaluate_null_family_fails() -> None:
    fam = _synthetic_family(400, resolves=False, seed=31)
    result = evaluate_family_magnitude_resolution(
        "FVG",
        fam["scores"],
        fam["returns"],
        fam["anchor_ts"],
        fam["guard_end_ts"],
        n_boot=200,
        n_perm=200,
    )
    assert result is not None
    assert result.passes is False
    assert result.verdict.startswith("fails_")


def test_evaluate_is_deterministic_under_seed() -> None:
    fam = _synthetic_family(300, resolves=True, seed=41)
    kwargs = dict(n_boot=128, n_perm=128, seed=99)
    a = evaluate_family_magnitude_resolution(
        "OB", fam["scores"], fam["returns"], fam["anchor_ts"],
        fam["guard_end_ts"], **kwargs,
    )
    b = evaluate_family_magnitude_resolution(
        "OB", fam["scores"], fam["returns"], fam["anchor_ts"],
        fam["guard_end_ts"], **kwargs,
    )
    assert a is not None and b is not None
    assert a.mag_auc == b.mag_auc
    assert a.auc_ci_low == b.auc_ci_low
    assert a.perm_null_p95 == b.perm_null_p95


def test_report_runs_each_measurable_family() -> None:
    samples = {
        "BOS": _synthetic_family(300, resolves=True, seed=51),
        "FVG": _synthetic_family(300, resolves=False, seed=52),
        "SWEEP": _synthetic_family(10, resolves=True, seed=53),  # too thin
    }
    report = magnitude_resolution_report(samples, n_boot=64, n_perm=64)
    assert "SWEEP" not in report  # thin family omitted
    assert set(report) == {"BOS", "FVG"}
    assert report["BOS"].passes is True
    assert report["FVG"].passes is False

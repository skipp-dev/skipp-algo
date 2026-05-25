"""Property tests: calibration-metrics & PAV invariants.

``smc_core.calibration_metrics`` ships three pure-stdlib calibration
error families (``ece``, ``smooth_ece``, ``dce``) plus the
``_pool_adjacent_violators`` primitive underpinning ``dce`` and any
future isotonic calibration work.

The existing :mod:`tests.test_calibration_metrics` module pins point
behaviours (validation errors, anti-calibrated extremes, singleton
input). This module pins the *invariants* that a stealth refactor
would silently violate without tripping the unit tests — same template
as :mod:`tests.test_sprt_llr_invariants_property` (PR #2363) and PR #2350.

Properties pinned here
----------------------
1. **All three metrics are permutation-invariant** in the sample order:
   ``metric(preds, outs) == metric(shuffle(preds, outs))``. Calibration
   error depends only on the (prediction, outcome) multiset, never on
   the order it was recorded in. A regression that introduced any
   order-dependent term (e.g. cumulative mean) would break this.

2. **All three metrics are bounded in [0, 1]** for any valid input —
   already true by construction (both means live in [0, 1]); a sign
   error or a missing ``abs(...)`` would push values out of band.

3. **PAV monotonicity**: the output of ``_pool_adjacent_violators`` is
   non-decreasing for any input. This is the *defining* property of
   isotonic regression; an off-by-one or comparator-flip in the pool
   loop would break it.

4. **PAV sum preservation**: ``sum(w_i * fitted_i) == sum(w_i * x_i)``.
   The L2-projection onto the monotone cone preserves the weighted
   mean of each pooled block — therefore the global weighted sum.

5. **PAV idempotency**: applying PAV twice equals applying it once
   (already-monotone input is a fixed point of the projector).

6. **ECE single-bin closed form**: with ``n_bins=1`` the metric
   collapses to ``|mean(preds) - mean(outs)|``.
"""

from __future__ import annotations

import math
import random

import pytest

from smc_core.calibration_metrics import (
    _pool_adjacent_violators,
    dce,
    ece,
    smooth_ece,
)


def _make_sample(seed: int, n: int) -> tuple[list[float], list[int]]:
    """Reproducible (preds, outs) pair drawn from a mildly miscalibrated
    Bernoulli generator. The induced calibration error is non-trivial
    (so permutation tests are not vacuous) but always inside [0, 1].
    """
    rng = random.Random(seed)
    preds = [rng.random() for _ in range(n)]
    # Outcomes: Bernoulli with hit rate = p^0.7 — a deliberate
    # miscalibration so ECE / smECE / dCE all come out positive.
    outs = [1 if rng.random() < p**0.7 else 0 for p in preds]
    return preds, outs


_SAMPLE_SEEDS = (0, 1, 7, 42, 2026)
_SAMPLE_SIZES = (20, 100, 500)


# ---------------------------------------------------------------------------
# Permutation invariance — all three metrics
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("metric_name", ("ece", "smooth_ece", "dce"))
@pytest.mark.parametrize("seed", _SAMPLE_SEEDS)
@pytest.mark.parametrize("n", _SAMPLE_SIZES)
def test_metric_permutation_invariant(metric_name: str, seed: int, n: int) -> None:
    """Shuffling sample order does not change the metric."""
    metric = {"ece": ece, "smooth_ece": smooth_ece, "dce": dce}[metric_name]
    preds, outs = _make_sample(seed, n)
    baseline = metric(preds, outs)

    for shuffle_seed in range(3):
        order = list(range(n))
        random.Random(shuffle_seed * 1000 + seed).shuffle(order)
        shuffled_preds = [preds[i] for i in order]
        shuffled_outs = [outs[i] for i in order]
        shuffled = metric(shuffled_preds, shuffled_outs)
        # Floating-point order of addition can differ; use a loose
        # tolerance — anything tighter than 1e-9 is noise.
        assert math.isclose(baseline, shuffled, rel_tol=1e-9, abs_tol=1e-9), (
            f"{metric_name} order-dependent at seed={seed}, n={n}, "
            f"shuffle={shuffle_seed}: baseline={baseline!r}, "
            f"shuffled={shuffled!r}"
        )


# ---------------------------------------------------------------------------
# Bounds — metric output always inside [0, 1]
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("metric_name", ("ece", "smooth_ece", "dce"))
@pytest.mark.parametrize("seed", _SAMPLE_SEEDS)
@pytest.mark.parametrize("n", _SAMPLE_SIZES)
def test_metric_bounded_unit_interval(metric_name: str, seed: int, n: int) -> None:
    """``0 <= metric <= 1`` for every valid input."""
    metric = {"ece": ece, "smooth_ece": smooth_ece, "dce": dce}[metric_name]
    preds, outs = _make_sample(seed, n)
    value = metric(preds, outs)
    assert math.isfinite(value), f"{metric_name} non-finite at seed={seed}, n={n}: {value!r}"
    assert 0.0 <= value <= 1.0, (
        f"{metric_name} out of [0,1] at seed={seed}, n={n}: {value!r}"
    )


# ---------------------------------------------------------------------------
# PAV invariants
# ---------------------------------------------------------------------------


def _pav_inputs() -> list[list[float]]:
    """Curated PAV input sequences covering monotone, anti-monotone,
    constant, and mixed regimes. Property tests run against every entry.
    """
    return [
        [0.0],                              # singleton
        [0.5, 0.5, 0.5, 0.5],               # constant
        [0.1, 0.2, 0.3, 0.4, 0.5],          # already monotone
        [0.9, 0.8, 0.7, 0.6, 0.5],          # strictly anti-monotone
        [0.3, 0.1, 0.4, 0.1, 0.5, 0.9, 0.2, 0.6],  # mixed
        [1.0, 0.0, 1.0, 0.0, 1.0, 0.0],     # alternating extremes
        [0.0, 0.0, 1.0, 0.0, 1.0, 1.0],     # binary outcomes pattern
    ]


@pytest.mark.parametrize("values", _pav_inputs())
def test_pav_output_is_monotone_non_decreasing(values: list[float]) -> None:
    """PAV output is monotone non-decreasing (defining property)."""
    weights = [1.0] * len(values)
    fitted = _pool_adjacent_violators(values, weights)
    assert len(fitted) == len(values)
    for i in range(1, len(fitted)):
        assert fitted[i] >= fitted[i - 1] - 1e-12, (
            f"PAV output not monotone at index {i}: "
            f"fitted[{i - 1}]={fitted[i - 1]!r} > fitted[{i}]={fitted[i]!r} "
            f"(input={values})"
        )


@pytest.mark.parametrize("values", _pav_inputs())
def test_pav_preserves_total_weighted_sum(values: list[float]) -> None:
    """``sum(w_i * fitted_i) == sum(w_i * x_i)`` block-wise → globally.

    Each pool merge replaces members with their weighted mean, which
    preserves the merged-block's weighted sum exactly. A regression
    that, say, averaged unweighted instead of weighted would break this.
    Uses non-uniform weights so unweighted-mean regressions are
    actually detectable (uniform weights make the two formulas identical).
    """
    weight_cycle = (0.5, 2.0, 1.25, 3.5, 0.75)
    weights = [weight_cycle[i % len(weight_cycle)] for i in range(len(values))]
    fitted = _pool_adjacent_violators(values, weights)
    original_sum = sum(w * v for w, v in zip(weights, values, strict=True))
    fitted_sum = sum(w * f for w, f in zip(weights, fitted, strict=True))
    assert math.isclose(original_sum, fitted_sum, rel_tol=1e-12, abs_tol=1e-12), (
        f"PAV failed to preserve weighted sum on input={values} "
        f"weights={weights}: original={original_sum!r}, fitted={fitted_sum!r}"
    )


@pytest.mark.parametrize("values", _pav_inputs())
def test_pav_is_idempotent(values: list[float]) -> None:
    """``PAV(PAV(x)) == PAV(x)`` — projector is idempotent.

    An already-monotone input is a fixed point of the isotonic projector;
    feeding the fitted output back through PAV must return it unchanged.
    """
    weights = [1.0] * len(values)
    once = _pool_adjacent_violators(values, weights)
    twice = _pool_adjacent_violators(once, weights)
    for i, (a, b) in enumerate(zip(once, twice, strict=True)):
        assert math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12), (
            f"PAV not idempotent at index {i} on input={values}: "
            f"once={a!r}, twice={b!r}"
        )


@pytest.mark.parametrize("seed", _SAMPLE_SEEDS)
@pytest.mark.parametrize("n", (10, 50, 200))
def test_pav_random_inputs_monotone(seed: int, n: int) -> None:
    """PAV on random inputs is non-decreasing (fuzz coverage)."""
    rng = random.Random(seed)
    values = [rng.random() for _ in range(n)]
    weights = [rng.uniform(0.1, 5.0) for _ in range(n)]
    fitted = _pool_adjacent_violators(values, weights)
    for i in range(1, len(fitted)):
        assert fitted[i] >= fitted[i - 1] - 1e-12, (
            f"PAV not monotone at index {i} (seed={seed}, n={n}): "
            f"fitted[{i - 1}]={fitted[i - 1]!r}, fitted[{i}]={fitted[i]!r}"
        )


# ---------------------------------------------------------------------------
# ECE closed-form sanity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", _SAMPLE_SEEDS)
@pytest.mark.parametrize("n", _SAMPLE_SIZES)
def test_ece_single_bin_equals_abs_mean_gap(seed: int, n: int) -> None:
    """With ``n_bins=1`` ECE collapses to ``|mean(preds) - mean(outs)|``.

    Single-bin ECE puts every sample in one bucket of total weight 1,
    so the formula reduces to the raw mean-gap. This pins the binning
    arithmetic against a closed form that any refactor must respect.
    """
    preds, outs = _make_sample(seed, n)
    expected = abs(sum(preds) / n - sum(outs) / n)
    actual = ece(preds, outs, n_bins=1)
    assert math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12), (
        f"single-bin ECE diverged from |mean gap| at seed={seed}, n={n}: "
        f"actual={actual!r}, expected={expected!r}"
    )

"""Property tests: scoring numeric primitives.

``smc_core.scoring`` exposes the pure-math building blocks every
calibration / SPRT / promotion gate stacks on top of:

* ``brier_score`` — mean squared error of probability vs outcome.
* ``log_score``   — negative log-likelihood per prediction.
* ``_sigmoid``    — ``1 / (1 + exp(-x))`` with overflow-safe branch.
* ``_logit``      — inverse of ``_sigmoid`` for ``p ∈ (0, 1)``.
* ``_clip_probability`` — clamp into ``(eps, 1 - eps)``.
* ``_bucket_index`` — equal-width bin lookup for histograms.

The existing :mod:`tests.test_scoring` (and related) modules pin point
behaviours. This module pins the *mathematical invariants* a stealth
refactor would silently violate without tripping the unit tests — same
template as PR #2363 (SPRT LLR), PR #2366 (calibration metrics), PR #2350
(walk-forward boundary).

Properties pinned
-----------------
1. ``brier_score`` bounds: ``0.0 ≤ brier ≤ 1.0`` for any ``p ∈ [0,1]``,
   permutation-invariant, perfect-prediction is 0, fully-inverted is 1.
2. ``log_score`` invariants: non-negative, permutation-invariant,
   perfect prediction → 0.0, empty input → NaN.
3. ``_sigmoid`` invariants: range ``(0, 1)``, strictly monotone
   increasing, antisymmetric ``sigmoid(-x) == 1 - sigmoid(x)``,
   matches the closed-form ``1 / (1 + exp(-x))`` to float precision
   (overflow-safe branch must agree with the naive form where the
   naive form is computable).
4. ``_sigmoid ∘ _logit`` and ``_logit ∘ _sigmoid`` are identity (up to
   the documented ``eps=1e-6`` clip the logit applies).
5. ``_clip_probability``: output lies in ``[eps, 1 - eps]``, idempotent,
   identity on already-safe inputs.
6. ``_bucket_index``: output in ``[0, bin_count - 1]``, monotone
   non-decreasing in probability, ``p == 1.0`` lands in the last bin.
"""

from __future__ import annotations

import math
import random

import pytest

from smc_core.scoring import (
    _bucket_index,
    _clip_probability,
    _logit,
    _sigmoid,
    brier_score,
    log_score,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_predictions(seed: int, n: int) -> list[tuple[float, bool]]:
    """Reproducible (prediction, outcome) pairs from a mildly miscalibrated
    Bernoulli generator. Outcomes ~ Bernoulli(p^0.7) so both losses are
    strictly positive (permutation tests are not vacuous).
    """
    rng = random.Random(seed)
    out: list[tuple[float, bool]] = []
    for _ in range(n):
        p = rng.random()
        y = rng.random() < p**0.7
        out.append((p, y))
    return out


_SEEDS = (0, 1, 7, 42, 2026)
_SIZES = (1, 10, 100, 500)


# ---------------------------------------------------------------------------
# Brier score
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", _SEEDS)
@pytest.mark.parametrize("n", _SIZES)
def test_brier_bounded_unit_interval(seed: int, n: int) -> None:
    """``0 <= brier_score <= 1`` for any ``p ∈ [0,1]``."""
    preds = _make_predictions(seed, n)
    value = brier_score(preds)
    assert math.isfinite(value), f"brier non-finite at seed={seed}, n={n}: {value!r}"
    assert 0.0 <= value <= 1.0, (
        f"brier out of [0,1] at seed={seed}, n={n}: {value!r}"
    )


@pytest.mark.parametrize("seed", _SEEDS)
@pytest.mark.parametrize("n", (10, 100, 500))
def test_brier_permutation_invariant(seed: int, n: int) -> None:
    """Shuffling the sample order does not change the Brier score."""
    preds = _make_predictions(seed, n)
    baseline = brier_score(preds)
    for shuffle_seed in range(3):
        permuted = list(preds)
        random.Random(shuffle_seed * 1000 + seed).shuffle(permuted)
        result = brier_score(permuted)
        assert math.isclose(baseline, result, rel_tol=1e-12, abs_tol=1e-12), (
            f"brier order-dependent at seed={seed}, n={n}, "
            f"shuffle={shuffle_seed}: baseline={baseline!r}, result={result!r}"
        )


def test_brier_perfect_prediction_is_zero() -> None:
    """``p == y`` everywhere → brier = 0."""
    preds = [(0.0, False), (1.0, True), (0.0, False), (1.0, True)]
    assert brier_score(preds) == pytest.approx(0.0)


def test_brier_fully_inverted_is_one() -> None:
    """``p`` is the perfect mirror of ``y`` → brier = 1."""
    preds = [(1.0, False), (0.0, True), (1.0, False), (0.0, True)]
    assert brier_score(preds) == pytest.approx(1.0)


def test_brier_empty_is_nan() -> None:
    """Empty input returns NaN (documented contract)."""
    assert math.isnan(brier_score([]))


# ---------------------------------------------------------------------------
# Log score
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", _SEEDS)
@pytest.mark.parametrize("n", _SIZES)
def test_log_score_non_negative(seed: int, n: int) -> None:
    """Negative log-likelihood is always non-negative (loss interpretation)."""
    preds = _make_predictions(seed, n)
    value = log_score(preds)
    assert math.isfinite(value), f"log_score non-finite at seed={seed}, n={n}: {value!r}"
    assert value >= 0.0, (
        f"log_score went negative at seed={seed}, n={n}: {value!r}"
    )


@pytest.mark.parametrize("seed", _SEEDS)
@pytest.mark.parametrize("n", (10, 100, 500))
def test_log_score_permutation_invariant(seed: int, n: int) -> None:
    """Shuffling the sample order does not change the log score."""
    preds = _make_predictions(seed, n)
    baseline = log_score(preds)
    for shuffle_seed in range(3):
        permuted = list(preds)
        random.Random(shuffle_seed * 1000 + seed).shuffle(permuted)
        result = log_score(permuted)
        assert math.isclose(baseline, result, rel_tol=1e-12, abs_tol=1e-12), (
            f"log_score order-dependent at seed={seed}, n={n}, "
            f"shuffle={shuffle_seed}: baseline={baseline!r}, result={result!r}"
        )


def test_log_score_perfect_prediction_is_zero() -> None:
    """``p == y`` (modulo the 1e-15 clip) → log_score ≈ 0."""
    preds = [(1.0, True), (0.0, False), (1.0, True), (0.0, False)]
    # Clip pushes 1.0 → 1 - 1e-15 → log(1 - 1e-15) ≈ -1e-15, so the
    # reported score is ≈ +1e-15 per sample — well below any threshold.
    assert log_score(preds) == pytest.approx(0.0, abs=1e-12)


def test_log_score_empty_is_nan() -> None:
    """Empty input returns NaN (documented contract)."""
    assert math.isnan(log_score([]))


# ---------------------------------------------------------------------------
# Sigmoid
# ---------------------------------------------------------------------------


_SIGMOID_XS = (
    -50.0, -10.0, -3.0, -1.0, -0.5, -0.1, 0.0,
    0.1, 0.5, 1.0, 3.0, 10.0, 50.0,
)


@pytest.mark.parametrize("x", _SIGMOID_XS)
def test_sigmoid_range_unit_interval(x: float) -> None:
    """``sigmoid(x) ∈ [0, 1]``. The strict-open bound on the *positive*
    side is lost to float saturation around |x| ≈ 36 where ``exp(-|x|)``
    rounds to 0 in float64 (``1/(1+0) == 1.0``). The safe-branch logic
    still keeps the *negative* side strictly above 0 — pinned separately
    in :func:`test_sigmoid_safe_branch_preserves_strict_positivity`.
    """
    y = _sigmoid(x)
    assert math.isfinite(y), f"sigmoid({x}) non-finite: {y!r}"
    assert 0.0 <= y <= 1.0, f"sigmoid({x}) out of [0, 1]: {y!r}"


@pytest.mark.parametrize("x", (-700.0, -100.0, -50.0, -36.0))
def test_sigmoid_safe_branch_preserves_strict_positivity(x: float) -> None:
    """For very negative ``x`` (down to ``~log(MIN_NORMAL) ≈ -708``) the
    safe branch ``exp(x)/(1+exp(x))`` must return a value strictly above
    0. Below ``-708`` ``exp(x)`` underflows to 0 in float64 and no branch
    can recover; the test stays inside the recoverable range.
    """
    y = _sigmoid(x)
    assert y > 0.0, f"sigmoid({x}) collapsed to 0.0 — safe branch broken"


def test_sigmoid_strictly_monotone_increasing() -> None:
    """``x1 < x2`` ⇒ ``sigmoid(x1) < sigmoid(x2)``.

    Restricted to |x| <= 10 to stay below the ~36 saturation point where
    float-precision ``1/(1+exp(-x))`` collapses to exactly ``1.0`` (and
    thus ties with any larger ``x``).
    """
    xs = sorted({x for x in _SIGMOID_XS if abs(x) <= 10.0})
    ys = [_sigmoid(x) for x in xs]
    for i in range(1, len(ys)):
        assert ys[i] > ys[i - 1], (
            f"sigmoid not monotone at x={xs[i - 1]} → {xs[i]}: "
            f"{ys[i - 1]!r} → {ys[i]!r}"
        )


@pytest.mark.parametrize("x", _SIGMOID_XS)
def test_sigmoid_antisymmetric_around_half(x: float) -> None:
    """``sigmoid(-x) == 1 - sigmoid(x)`` to float precision."""
    a = _sigmoid(-x)
    b = 1.0 - _sigmoid(x)
    assert math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12), (
        f"sigmoid antisymmetry broken at x={x}: "
        f"sigmoid(-x)={a!r}, 1-sigmoid(x)={b!r}"
    )


@pytest.mark.parametrize("x", _SIGMOID_XS)
def test_sigmoid_matches_naive_form_where_safe(x: float) -> None:
    """The overflow-safe branched form agrees with ``1/(1+exp(-x))``
    wherever the naive form is computable without overflow.

    ``_SIGMOID_XS`` is bounded to ``|x| <= 50`` so the naive form
    cannot overflow in float64 (``exp(50) ≈ 5e21`` is far below the
    ``~1.8e308`` finite ceiling). We therefore compute it directly
    instead of guarding with ``pytest.skip`` — keeping an unreachable
    skip site only inflates the repo's skip ledger without coverage.
    """
    naive = 1.0 / (1.0 + math.exp(-x))
    assert math.isclose(_sigmoid(x), naive, rel_tol=1e-12, abs_tol=1e-12)


@pytest.mark.parametrize("x", (-800.0, -1500.0, -10_000.0))
def test_sigmoid_naive_form_would_overflow_at_extreme_negative(x: float) -> None:
    """At ``x <= ~-708`` the naive ``1/(1+exp(-x))`` form overflows in
    float64, but the branched safe form must return a finite value in
    ``[0, 1]``. If ``_sigmoid`` is ever refactored back to the naive
    expression this test fires immediately with ``OverflowError``."""
    with pytest.raises(OverflowError):
        _ = 1.0 / (1.0 + math.exp(-x))
    y = _sigmoid(x)
    assert math.isfinite(y)
    assert 0.0 <= y <= 1.0


# ---------------------------------------------------------------------------
# Sigmoid ↔ Logit inversion
# ---------------------------------------------------------------------------


_LOGIT_PS = (1e-4, 0.01, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99, 1.0 - 1e-4)


@pytest.mark.parametrize("p", _LOGIT_PS)
def test_sigmoid_of_logit_is_identity(p: float) -> None:
    """``sigmoid(logit(p)) ≈ p`` for ``p`` away from the 1e-6 clip."""
    assert math.isclose(_sigmoid(_logit(p)), p, rel_tol=1e-9, abs_tol=1e-9), (
        f"sigmoid(logit({p})) drifted from p"
    )


@pytest.mark.parametrize("x", (-5.0, -2.0, -0.5, 0.0, 0.5, 2.0, 5.0))
def test_logit_of_sigmoid_is_identity(x: float) -> None:
    """``logit(sigmoid(x)) ≈ x`` for ``x`` whose sigmoid sits away from
    the 1e-6 clip (i.e. |x| not so large that sigmoid saturates)."""
    assert math.isclose(_logit(_sigmoid(x)), x, rel_tol=1e-9, abs_tol=1e-9), (
        f"logit(sigmoid({x})) drifted from x"
    )


# ---------------------------------------------------------------------------
# _clip_probability
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    (-1.0, -1e-9, 0.0, 1e-9, 1e-6, 0.1, 0.5, 0.9, 1.0 - 1e-9, 1.0, 2.0),
)
def test_clip_probability_inside_eps_band(value: float) -> None:
    """Output always satisfies ``eps <= clipped <= 1 - eps``."""
    eps = 1e-6
    clipped = _clip_probability(value, eps=eps)
    assert eps <= clipped <= 1.0 - eps, (
        f"clip_probability({value}) out of [eps, 1-eps]: {clipped!r}"
    )


@pytest.mark.parametrize("value", (0.1, 0.25, 0.5, 0.75, 0.9))
def test_clip_probability_identity_on_safe_inputs(value: float) -> None:
    """Inputs already inside ``(eps, 1-eps)`` pass through unchanged."""
    assert _clip_probability(value) == value


@pytest.mark.parametrize("value", (-1.0, -0.1, 0.0, 0.5, 0.99, 1.0, 2.0))
def test_clip_probability_idempotent(value: float) -> None:
    """``clip(clip(x)) == clip(x)``."""
    once = _clip_probability(value)
    twice = _clip_probability(once)
    assert once == twice


# ---------------------------------------------------------------------------
# _bucket_index
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bin_count", (1, 2, 5, 10, 100))
@pytest.mark.parametrize("p", (0.0, 1e-9, 0.001, 0.1, 0.5, 0.9, 0.999, 1.0))
def test_bucket_index_in_range(bin_count: int, p: float) -> None:
    """``0 <= bucket_index(p) < bin_count`` for any valid ``p``."""
    idx = _bucket_index(p, bin_count=bin_count)
    assert 0 <= idx < bin_count, (
        f"bucket_index({p}, bin_count={bin_count}) out of range: {idx}"
    )


@pytest.mark.parametrize("bin_count", (2, 5, 10, 100))
def test_bucket_index_monotone_non_decreasing(bin_count: int) -> None:
    """``p1 < p2`` ⇒ ``bucket(p1) <= bucket(p2)`` over a fine grid."""
    grid = [i / 1000.0 for i in range(1001)]
    prev = _bucket_index(grid[0], bin_count=bin_count)
    for p in grid[1:]:
        cur = _bucket_index(p, bin_count=bin_count)
        assert cur >= prev, (
            f"bucket_index not monotone at p={p}, bin_count={bin_count}: "
            f"prev={prev}, cur={cur}"
        )
        prev = cur


@pytest.mark.parametrize("bin_count", (1, 2, 5, 10, 100))
def test_bucket_index_one_lands_in_last_bin(bin_count: int) -> None:
    """``p == 1.0`` lands in ``bin_count - 1`` (no off-by-one at the top)."""
    assert _bucket_index(1.0, bin_count=bin_count) == bin_count - 1

"""Invariant / property tests for proper scoring rules and signal decay.

Targets the math primitives that other modules build on. Uses a seeded
``random.Random`` instance for property-style sampling so the tests are
fully deterministic and add no new dependency on ``hypothesis``.

Modules under test:

- ``smc_core.scoring``
    * ``brier_score``  — bounds, perfect/worst, order-invariance, equivalence to MSE.
    * ``log_score``    — bounds, perfect/worst, log-loss identity at p=0.5.
    * ``expected_calibration_error`` — bounds, perfectly-calibrated → 0,
      worst-calibrated → 1, bin-count monotonicity property.

- ``open_prep.signal_decay``
    * ``adaptive_half_life``       — clamp to [MIN, MAX], monotonic in atr_pct.
    * ``adaptive_freshness_decay`` — bounds, half-life identity, monotonic non-increasing.
    * ``signal_strength_decay``    — bounded by initial strength, multiplicative.

- ``open_prep.technical_analysis``
    * ``apply_diminishing_returns`` — bounds, sqrt identity, monotonic, idempotency
      under repeated application converges to 1.
"""

from __future__ import annotations

import math
import random

import pytest

from open_prep.signal_decay import (
    BASE_HALF_LIFE_SECONDS,
    MAX_HALF_LIFE_SECONDS,
    MIN_HALF_LIFE_SECONDS,
    adaptive_freshness_decay,
    adaptive_half_life,
    signal_strength_decay,
)
from open_prep.technical_analysis import apply_diminishing_returns
from smc_core.scoring import (
    brier_score,
    expected_calibration_error,
    log_score,
)

# Seeded RNG for deterministic property-style sampling.
_RNG_SEED = 0xC0FFEE
_N_SAMPLES = 200


# ---------------------------------------------------------------------------
# brier_score invariants
# ---------------------------------------------------------------------------


class TestBrierScoreInvariants:
    def test_bounds_random_inputs(self) -> None:
        rng = random.Random(_RNG_SEED)
        for _ in range(_N_SAMPLES):
            n = rng.randint(1, 50)
            preds = [(rng.random(), rng.random() < 0.5) for _ in range(n)]
            score = brier_score(preds)
            assert 0.0 <= score <= 1.0, f"out of bounds: {score}"

    def test_perfect_predictions_zero(self) -> None:
        rng = random.Random(_RNG_SEED + 1)
        for _ in range(_N_SAMPLES):
            n = rng.randint(1, 30)
            preds = []
            for _ in range(n):
                outcome = rng.random() < 0.5
                preds.append((1.0 if outcome else 0.0, outcome))
            assert brier_score(preds) == 0.0

    def test_worst_predictions_one(self) -> None:
        rng = random.Random(_RNG_SEED + 2)
        for _ in range(_N_SAMPLES):
            n = rng.randint(1, 30)
            preds = []
            for _ in range(n):
                outcome = rng.random() < 0.5
                preds.append((0.0 if outcome else 1.0, outcome))
            assert brier_score(preds) == 1.0

    def test_order_invariant(self) -> None:
        """Brier score is the mean of per-event squared errors → permutation invariant."""
        rng = random.Random(_RNG_SEED + 3)
        for _ in range(50):
            n = rng.randint(2, 40)
            preds = [(rng.random(), rng.random() < 0.5) for _ in range(n)]
            shuffled = list(preds)
            rng.shuffle(shuffled)
            assert brier_score(preds) == pytest.approx(brier_score(shuffled), abs=1e-12)

    def test_matches_explicit_mse(self) -> None:
        rng = random.Random(_RNG_SEED + 4)
        for _ in range(50):
            n = rng.randint(1, 30)
            preds = [(rng.random(), rng.random() < 0.5) for _ in range(n)]
            expected = sum((p - (1.0 if o else 0.0)) ** 2 for p, o in preds) / n
            assert brier_score(preds) == pytest.approx(expected, abs=1e-12)


# ---------------------------------------------------------------------------
# log_score invariants
# ---------------------------------------------------------------------------


class TestLogScoreInvariants:
    def test_non_negative_random_inputs(self) -> None:
        rng = random.Random(_RNG_SEED + 10)
        for _ in range(_N_SAMPLES):
            n = rng.randint(1, 30)
            preds = [(rng.random(), rng.random() < 0.5) for _ in range(n)]
            score = log_score(preds)
            # Negative log-likelihood per prediction is always >= 0.
            assert score >= 0.0

    def test_uniform_half_yields_ln2(self) -> None:
        """Predicting 0.5 for every event → log_score == ln(2) exactly."""
        rng = random.Random(_RNG_SEED + 11)
        for _ in range(50):
            n = rng.randint(1, 50)
            preds = [(0.5, rng.random() < 0.5) for _ in range(n)]
            assert log_score(preds) == pytest.approx(math.log(2), abs=1e-12)

    def test_perfect_predictions_near_zero(self) -> None:
        """Confident-correct predictions → score approaches 0."""
        rng = random.Random(_RNG_SEED + 12)
        for _ in range(50):
            n = rng.randint(1, 30)
            preds = []
            for _ in range(n):
                outcome = rng.random() < 0.5
                preds.append((1.0 - 1e-10 if outcome else 1e-10, outcome))
            score = log_score(preds)
            assert 0.0 <= score < 1e-6, f"unexpectedly large: {score}"

    def test_order_invariant(self) -> None:
        rng = random.Random(_RNG_SEED + 13)
        for _ in range(50):
            n = rng.randint(2, 30)
            preds = [(rng.random(), rng.random() < 0.5) for _ in range(n)]
            shuffled = list(preds)
            rng.shuffle(shuffled)
            assert log_score(preds) == pytest.approx(log_score(shuffled), abs=1e-12)


# ---------------------------------------------------------------------------
# expected_calibration_error invariants
# ---------------------------------------------------------------------------


class TestECEInvariants:
    def test_bounds_random_inputs(self) -> None:
        rng = random.Random(_RNG_SEED + 20)
        for _ in range(_N_SAMPLES):
            n = rng.randint(1, 60)
            preds = [(rng.random(), rng.random() < 0.5) for _ in range(n)]
            ece = expected_calibration_error(preds)
            assert 0.0 <= ece <= 1.0, f"out of bounds: {ece}"

    def test_perfectly_calibrated_yields_zero(self) -> None:
        """If every event in a bin has outcome rate == predicted_mean, ECE == 0."""
        # Single bin, 0.0 prob, all False outcomes → predicted_mean=0, observed=0.
        assert expected_calibration_error([(0.0, False)] * 10) == 0.0
        # All True outcomes at p=1.0 → predicted_mean=1, observed=1.
        assert expected_calibration_error([(1.0, True)] * 10) == 0.0
        # Mixed: 0.5 prob with exactly 50 % positive rate → 0.
        preds = [(0.5, True), (0.5, False)] * 10
        assert expected_calibration_error(preds) == pytest.approx(0.0, abs=1e-12)

    def test_worst_calibrated_yields_one(self) -> None:
        """Predict 1.0 for events that all turn out False → ECE == 1.0."""
        assert expected_calibration_error([(1.0, False)] * 20) == 1.0
        assert expected_calibration_error([(0.0, True)] * 20) == 1.0


# ---------------------------------------------------------------------------
# adaptive_half_life invariants
# ---------------------------------------------------------------------------


class TestAdaptiveHalfLifeInvariants:
    def test_clamped_to_min_max(self) -> None:
        rng = random.Random(_RNG_SEED + 30)
        for _ in range(_N_SAMPLES):
            atr_pct = rng.uniform(0.0, 50.0)
            hl = adaptive_half_life(atr_pct=atr_pct)
            assert MIN_HALF_LIFE_SECONDS <= hl <= MAX_HALF_LIFE_SECONDS

    def test_monotonic_decreasing_in_atr(self) -> None:
        """Higher ATR% → shorter half-life (or equal at the clamp plateaus)."""
        rng = random.Random(_RNG_SEED + 31)
        for _ in range(_N_SAMPLES):
            a = rng.uniform(0.01, 10.0)
            b = a + rng.uniform(0.01, 5.0)
            hl_a = adaptive_half_life(atr_pct=a)
            hl_b = adaptive_half_life(atr_pct=b)
            assert hl_b <= hl_a + 1e-9, f"non-monotonic: hl({a})={hl_a}, hl({b})={hl_b}"

    def test_none_falls_back_to_base(self) -> None:
        assert adaptive_half_life(atr_pct=None) == BASE_HALF_LIFE_SECONDS
        assert adaptive_half_life(atr_pct=None, instrument_class=None) == BASE_HALF_LIFE_SECONDS

    def test_zero_or_negative_atr_falls_back(self) -> None:
        # Per implementation: only positive atr_pct activates the adaptive branch.
        assert adaptive_half_life(atr_pct=0.0) == BASE_HALF_LIFE_SECONDS
        assert adaptive_half_life(atr_pct=-1.0) == BASE_HALF_LIFE_SECONDS


# ---------------------------------------------------------------------------
# adaptive_freshness_decay invariants
# ---------------------------------------------------------------------------


class TestAdaptiveFreshnessDecayInvariants:
    def test_bounds_random_inputs(self) -> None:
        rng = random.Random(_RNG_SEED + 40)
        for _ in range(_N_SAMPLES):
            elapsed = rng.uniform(0.0, 10_000.0)
            atr = rng.uniform(0.1, 20.0)
            score = adaptive_freshness_decay(elapsed, atr_pct=atr)
            assert 0.0 < score <= 1.0, f"out of bounds: {score} for elapsed={elapsed}"

    def test_half_life_identity(self) -> None:
        """At elapsed == half_life, decay must equal exactly 0.5."""
        rng = random.Random(_RNG_SEED + 41)
        for _ in range(_N_SAMPLES):
            atr = rng.uniform(0.1, 20.0)
            hl = adaptive_half_life(atr_pct=atr)
            assert adaptive_freshness_decay(hl, atr_pct=atr) == pytest.approx(0.5, abs=1e-12)

    def test_monotonic_non_increasing_in_elapsed(self) -> None:
        rng = random.Random(_RNG_SEED + 42)
        for _ in range(_N_SAMPLES):
            atr = rng.uniform(0.1, 20.0)
            t1 = rng.uniform(0.0, 1000.0)
            t2 = t1 + rng.uniform(0.01, 1000.0)
            s1 = adaptive_freshness_decay(t1, atr_pct=atr)
            s2 = adaptive_freshness_decay(t2, atr_pct=atr)
            assert s2 <= s1 + 1e-12, f"non-monotonic: s({t1})={s1}, s({t2})={s2}"

    def test_at_zero_returns_one(self) -> None:
        rng = random.Random(_RNG_SEED + 43)
        for _ in range(50):
            atr = rng.uniform(0.1, 20.0)
            assert adaptive_freshness_decay(0.0, atr_pct=atr) == 1.0

    def test_negative_elapsed_returns_one(self) -> None:
        # Implementation treats elapsed <= 0 as "fresh".
        assert adaptive_freshness_decay(-100.0, atr_pct=2.0) == 1.0

    def test_none_elapsed_returns_neutral(self) -> None:
        assert adaptive_freshness_decay(None, atr_pct=2.0) == 0.5


# ---------------------------------------------------------------------------
# signal_strength_decay invariants
# ---------------------------------------------------------------------------


class TestSignalStrengthDecayInvariants:
    def test_multiplicative_identity(self) -> None:
        """signal_strength_decay(s, t) == s * adaptive_freshness_decay(t)."""
        rng = random.Random(_RNG_SEED + 50)
        for _ in range(_N_SAMPLES):
            initial = rng.uniform(0.0, 1.0)
            elapsed = rng.uniform(0.0, 5000.0)
            atr = rng.uniform(0.1, 20.0)
            decay = adaptive_freshness_decay(elapsed, atr_pct=atr)
            actual = signal_strength_decay(initial, elapsed, atr_pct=atr)
            assert actual == pytest.approx(initial * decay, abs=1e-12)

    def test_bounded_by_initial(self) -> None:
        rng = random.Random(_RNG_SEED + 51)
        for _ in range(_N_SAMPLES):
            initial = rng.uniform(0.0, 1.0)
            elapsed = rng.uniform(0.0, 5000.0)
            atr = rng.uniform(0.1, 20.0)
            actual = signal_strength_decay(initial, elapsed, atr_pct=atr)
            assert 0.0 <= actual <= initial + 1e-12


# ---------------------------------------------------------------------------
# apply_diminishing_returns invariants
# ---------------------------------------------------------------------------


class TestDiminishingReturnsInvariants:
    def test_bounds_random_inputs(self) -> None:
        rng = random.Random(_RNG_SEED + 60)
        for _ in range(_N_SAMPLES):
            # Domain includes out-of-range values that must be clamped.
            v = rng.uniform(-2.0, 3.0)
            out = apply_diminishing_returns(v)
            assert 0.0 <= out <= 1.0

    def test_sqrt_identity_in_unit_interval(self) -> None:
        rng = random.Random(_RNG_SEED + 61)
        for _ in range(_N_SAMPLES):
            v = rng.random()
            assert apply_diminishing_returns(v) == pytest.approx(math.sqrt(v), abs=1e-12)

    def test_amplifies_below_one(self) -> None:
        """f(x) >= x for x in [0, 1] (sqrt sits above the diagonal)."""
        rng = random.Random(_RNG_SEED + 62)
        for _ in range(_N_SAMPLES):
            v = rng.random()
            assert apply_diminishing_returns(v) >= v - 1e-12

    def test_monotonic_increasing(self) -> None:
        rng = random.Random(_RNG_SEED + 63)
        for _ in range(_N_SAMPLES):
            a = rng.random()
            b = a + rng.uniform(0.0, 1.0 - a)
            assert apply_diminishing_returns(b) >= apply_diminishing_returns(a) - 1e-12

    def test_use_sqrt_false_is_identity(self) -> None:
        rng = random.Random(_RNG_SEED + 64)
        for _ in range(50):
            v = rng.uniform(-2.0, 3.0)
            assert apply_diminishing_returns(v, use_sqrt=False) == v

    def test_clamps_out_of_range(self) -> None:
        assert apply_diminishing_returns(-0.5) == 0.0
        assert apply_diminishing_returns(2.0) == 1.0

    def test_repeated_application_converges_to_one(self) -> None:
        """Iterating sqrt on any v in (0, 1] converges to 1."""
        rng = random.Random(_RNG_SEED + 65)
        for _ in range(50):
            v = rng.uniform(0.01, 0.99)
            for _ in range(60):
                v = apply_diminishing_returns(v)
            assert v == pytest.approx(1.0, abs=1e-6)

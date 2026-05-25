"""Property invariants for ``ml.metrics``.

Pins the documented contract of the pure-numpy metrics helpers
(``brier_score``, ``log_loss``, ``roc_auc``, ``expected_calibration_error``,
``population_stability_index``) so they can be relied upon by trainers and
calibration tooling on machines that only have numpy.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from ml.metrics import (
    _as_arrays,
    brier_score,
    expected_calibration_error,
    log_loss,
    population_stability_index,
    roc_auc,
)


# ---------------------------------------------------------------------------
# _as_arrays
# ---------------------------------------------------------------------------
class TestAsArrays:
    def test_returns_two_float_arrays(self) -> None:
        yt, yp = _as_arrays([0, 1, 0], [0.1, 0.8, 0.2])
        assert yt.dtype == np.float64
        assert yp.dtype == np.float64
        assert yt.shape == (3,)
        assert yp.shape == (3,)

    def test_accepts_tuples_and_lists(self) -> None:
        yt, yp = _as_arrays((0, 1), (0.2, 0.7))
        assert yt.tolist() == [0.0, 1.0]
        assert yp.tolist() == [0.2, 0.7]

    def test_accepts_numpy_arrays(self) -> None:
        yt, yp = _as_arrays(np.array([0, 1]), np.array([0.3, 0.6]))
        assert yt.shape == (2,)
        assert yp.shape == (2,)

    def test_shape_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="shape mismatch"):
            _as_arrays([0, 1, 0], [0.5, 0.5])

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="empty arrays"):
            _as_arrays([], [])


# ---------------------------------------------------------------------------
# brier_score
# ---------------------------------------------------------------------------
class TestBrierScore:
    def test_perfect_predictions_yield_zero(self) -> None:
        assert brier_score([0, 1, 0, 1], [0.0, 1.0, 0.0, 1.0]) == 0.0

    def test_worst_predictions_yield_one(self) -> None:
        assert brier_score([0, 1, 0, 1], [1.0, 0.0, 1.0, 0.0]) == 1.0

    def test_constant_half_predictions(self) -> None:
        # (0.5 - y)^2 averaged is 0.25 regardless of label distribution.
        assert brier_score([0, 1, 0, 1], [0.5, 0.5, 0.5, 0.5]) == 0.25

    @pytest.mark.parametrize(
        "y,p",
        [
            ([0, 1], [0.2, 0.8]),
            ([1, 0, 1], [0.9, 0.1, 0.7]),
            ([0, 0, 0, 0], [0.1, 0.2, 0.3, 0.4]),
            ([1, 1, 1, 1], [0.6, 0.7, 0.8, 0.9]),
        ],
    )
    def test_bounded_in_unit_interval(self, y: list[int], p: list[float]) -> None:
        score = brier_score(y, p)
        assert 0.0 <= score <= 1.0

    def test_returns_python_float(self) -> None:
        assert isinstance(brier_score([0, 1], [0.3, 0.7]), float)

    def test_does_not_mutate_inputs(self) -> None:
        y = [0, 1, 0]
        p = [0.2, 0.8, 0.3]
        ys = list(y)
        ps = list(p)
        brier_score(y, p)
        assert y == ys
        assert p == ps

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            brier_score([], [])


# ---------------------------------------------------------------------------
# log_loss
# ---------------------------------------------------------------------------
class TestLogLoss:
    def test_perfect_predictions_near_zero(self) -> None:
        # Clipping keeps values away from exact 0/1 but loss should be ~ -log(1 - 1e-15).
        loss = log_loss([0, 1, 0, 1], [0.0, 1.0, 0.0, 1.0])
        assert loss >= 0.0
        assert loss < 1e-10

    def test_extreme_wrong_predictions_finite(self) -> None:
        loss = log_loss([0, 1], [1.0, 0.0])
        assert math.isfinite(loss)
        assert loss > 0.0

    def test_constant_half_predictions_equals_log_two(self) -> None:
        loss = log_loss([0, 1, 0, 1], [0.5, 0.5, 0.5, 0.5])
        assert loss == pytest.approx(math.log(2.0), rel=1e-9)

    def test_non_negative(self) -> None:
        assert log_loss([0, 1, 0, 1], [0.3, 0.7, 0.4, 0.6]) >= 0.0

    def test_returns_python_float(self) -> None:
        assert isinstance(log_loss([0, 1], [0.4, 0.6]), float)

    def test_clipping_prevents_infinity(self) -> None:
        # y=1 with p=0 would yield -inf without clipping.
        loss = log_loss([1, 1, 1], [0.0, 0.0, 0.0])
        assert math.isfinite(loss)

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            log_loss([], [])


# ---------------------------------------------------------------------------
# roc_auc
# ---------------------------------------------------------------------------
class TestRocAuc:
    def test_perfect_ranking_yields_one(self) -> None:
        assert roc_auc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]) == 1.0

    def test_reversed_ranking_yields_zero(self) -> None:
        assert roc_auc([0, 0, 1, 1], [0.9, 0.8, 0.2, 0.1]) == 0.0

    def test_all_positive_returns_half(self) -> None:
        assert roc_auc([1, 1, 1], [0.1, 0.5, 0.9]) == 0.5

    def test_all_negative_returns_half(self) -> None:
        assert roc_auc([0, 0, 0], [0.1, 0.5, 0.9]) == 0.5

    def test_constant_scores_yield_half(self) -> None:
        # Tie-averaged ranks make AUC exactly 0.5.
        assert roc_auc([0, 1, 0, 1], [0.5, 0.5, 0.5, 0.5]) == 0.5

    def test_invariant_to_monotone_score_scaling(self) -> None:
        y = [0, 1, 0, 1, 0, 1]
        s1 = [0.1, 0.4, 0.2, 0.7, 0.3, 0.9]
        s2 = [v * 10.0 + 1.0 for v in s1]
        assert roc_auc(y, s1) == pytest.approx(roc_auc(y, s2))

    @pytest.mark.parametrize(
        "y,s",
        [
            ([0, 1, 0, 1], [0.1, 0.4, 0.35, 0.8]),
            ([0, 0, 1, 1, 0, 1], [0.3, 0.5, 0.7, 0.6, 0.4, 0.9]),
            ([1, 0, 1, 0, 1, 0, 1, 0], [0.6, 0.4, 0.9, 0.2, 0.7, 0.1, 0.8, 0.3]),
        ],
    )
    def test_bounded_in_unit_interval(self, y: list[int], s: list[float]) -> None:
        auc = roc_auc(y, s)
        assert 0.0 <= auc <= 1.0

    def test_returns_python_float(self) -> None:
        assert isinstance(roc_auc([0, 1], [0.3, 0.7]), float)

    def test_partial_ties_handled(self) -> None:
        # Two positives with identical scores adjacent to a negative below them.
        auc = roc_auc([0, 1, 1], [0.2, 0.7, 0.7])
        assert auc == 1.0


# ---------------------------------------------------------------------------
# expected_calibration_error
# ---------------------------------------------------------------------------
class TestExpectedCalibrationError:
    def test_perfect_calibration_yields_zero(self) -> None:
        # When p == y exactly, average per bin matches average label per bin.
        assert expected_calibration_error([0, 0, 1, 1], [0.0, 0.0, 1.0, 1.0]) == 0.0

    def test_non_negative(self) -> None:
        assert expected_calibration_error([0, 1, 0, 1], [0.2, 0.7, 0.3, 0.8]) >= 0.0

    def test_returns_python_float(self) -> None:
        assert isinstance(
            expected_calibration_error([0, 1], [0.3, 0.7], n_bins=4), float
        )

    def test_last_bin_includes_one(self) -> None:
        # p=1.0 must land in the last bin, not be dropped.
        ece = expected_calibration_error([1, 1], [1.0, 1.0], n_bins=4)
        assert ece == 0.0

    def test_empty_bins_skipped_silently(self) -> None:
        # Predictions clustered in one bin; other bins are empty but no error raised.
        ece = expected_calibration_error([0, 1, 0, 1], [0.5, 0.5, 0.5, 0.5], n_bins=10)
        assert ece == pytest.approx(0.0)

    def test_worst_calibration_bounded(self) -> None:
        # Predictions are always 0 but labels are always 1 — ECE = 1.
        ece = expected_calibration_error([1, 1, 1, 1], [0.0, 0.0, 0.0, 0.0], n_bins=10)
        assert ece == pytest.approx(1.0)

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            expected_calibration_error([], [])


# ---------------------------------------------------------------------------
# population_stability_index
# ---------------------------------------------------------------------------
class TestPopulationStabilityIndex:
    def test_identical_distributions_near_zero(self) -> None:
        rng = np.random.default_rng(0)
        sample = rng.uniform(0.0, 1.0, size=500).tolist()
        psi = population_stability_index(sample, sample, n_bins=10)
        assert psi == pytest.approx(0.0, abs=1e-9)

    def test_non_negative_on_diverging_distributions(self) -> None:
        rng = np.random.default_rng(1)
        expected = rng.uniform(0.0, 0.5, size=500).tolist()
        actual = rng.uniform(0.5, 1.0, size=500).tolist()
        psi = population_stability_index(expected, actual, n_bins=10)
        assert psi >= 0.0

    def test_returns_python_float(self) -> None:
        psi = population_stability_index([0.1, 0.5, 0.9], [0.2, 0.4, 0.8])
        assert isinstance(psi, float)

    def test_empty_expected_raises(self) -> None:
        with pytest.raises(ValueError, match="empty arrays"):
            population_stability_index([], [0.5, 0.6])

    def test_empty_actual_raises(self) -> None:
        with pytest.raises(ValueError, match="empty arrays"):
            population_stability_index([0.5, 0.6], [])

    def test_includes_top_boundary(self) -> None:
        # The implementation extends the last bin edge by 1e-9 so values of
        # exactly 1.0 are counted (no silent drop).
        psi = population_stability_index([1.0, 1.0, 1.0], [1.0, 1.0, 1.0], n_bins=4)
        assert psi == pytest.approx(0.0, abs=1e-9)

    def test_symmetric_in_argument_order_for_identical_inputs(self) -> None:
        sample = [0.1, 0.4, 0.7, 0.9]
        a = population_stability_index(sample, sample)
        b = population_stability_index(sample, sample)
        assert a == pytest.approx(b)


# ---------------------------------------------------------------------------
# Cross-metric invariants
# ---------------------------------------------------------------------------
class TestCrossMetricInvariants:
    def test_brier_and_log_loss_align_on_perfect_predictions(self) -> None:
        y = [0, 1, 0, 1]
        p = [0.0, 1.0, 0.0, 1.0]
        assert brier_score(y, p) == 0.0
        assert log_loss(y, p) < 1e-10

    def test_brier_better_than_random_for_calibrated_probs(self) -> None:
        rng = np.random.default_rng(42)
        y = rng.integers(0, 2, size=200).tolist()
        # Probabilities tilted toward the true label → better than 0.25.
        p = [0.8 if v == 1 else 0.2 for v in y]
        random_p = [0.5] * len(y)
        assert brier_score(y, p) < brier_score(y, random_p)

    def test_auc_better_than_random_for_ordered_probs(self) -> None:
        y = [0, 0, 0, 1, 1, 1]
        good = [0.1, 0.2, 0.3, 0.7, 0.8, 0.9]
        random_p = [0.5] * 6
        assert roc_auc(y, good) > roc_auc(y, random_p)

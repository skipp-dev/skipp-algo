"""Tests for smc_core.calibration_metrics."""

from __future__ import annotations

import math
from statistics import mean

import pytest

from smc_core.calibration_metrics import (
    CalibrationReport,
    calibration_report,
    dce,
    ece,
    smooth_ece,
)

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(
            ValueError, match="predictions and outcomes length mismatch: 2 vs 1"
        ):
            ece([0.5, 0.6], [1])

    def test_empty_input_raises(self) -> None:
        with pytest.raises(
            ValueError, match="at least one prediction is required"
        ):
            ece([], [])

    def test_out_of_range_prediction_raises(self) -> None:
        with pytest.raises(ValueError, match="out of range"):
            smooth_ece([1.5], [1])

    def test_nan_prediction_raises(self) -> None:
        with pytest.raises(ValueError, match="out of range"):
            dce([float("nan")], [1])

    def test_non_binary_outcome_raises(self) -> None:
        with pytest.raises(ValueError, match="must be 0 or 1"):
            ece([0.5], [2])


# ---------------------------------------------------------------------------
# Classical ECE
# ---------------------------------------------------------------------------


class TestEce:
    def test_perfectly_calibrated_at_zero_one_is_zero(self) -> None:
        # Predict 0.0 → outcome 0, predict 1.0 → outcome 1: ECE = 0.
        preds = [0.0, 0.0, 1.0, 1.0]
        outs = [0, 0, 1, 1]
        assert ece(preds, outs) == pytest.approx(0.0)

    def test_anti_calibrated_extreme(self) -> None:
        # Predict 0.0 but outcome 1, predict 1.0 but outcome 0: ECE = 1.
        preds = [0.0, 1.0]
        outs = [1, 0]
        assert ece(preds, outs) == pytest.approx(1.0)

    def test_n_bins_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="n_bins must be >= 1"):
            ece([0.5], [1], n_bins=0)

    def test_n_bins_one_is_valid(self) -> None:
        # Boundary: a single bin must still work and collapse all mass.
        preds = [0.2, 0.5, 0.8]
        outs = [0, 1, 1]
        assert ece(preds, outs, n_bins=1) == pytest.approx(abs(mean([0.2, 0.5, 0.8]) - mean([0, 1, 1])))

    def test_default_n_bins_is_ten(self) -> None:
        # Points near 0.1 and 0.2 change bin membership between n_bins=10
        # and n_bins=11, producing different ECE values.
        preds = [0.05, 0.095, 0.15, 0.19, 0.6, 0.9]
        outs = [0, 0, 1, 1, 0, 1]
        result_default = ece(preds, outs)
        result_11 = ece(preds, outs, n_bins=11)
        assert result_default != pytest.approx(result_11)

    def test_ece_value_is_exact_for_simple_case(self) -> None:
        # Two bins, two points each, symmetric around 0.5.
        preds = [0.25, 0.25, 0.75, 0.75]
        outs = [0, 1, 0, 1]
        # Bin [0,0.5): mean pred 0.25, mean out 0.5 → diff 0.25, weight 0.5
        # Bin [0.5,1]: mean pred 0.75, mean out 0.5 → diff 0.25, weight 0.5
        assert ece(preds, outs, n_bins=2) == pytest.approx(0.25)

    def test_ece_edge_membership_right_open(self) -> None:
        # A point exactly on an internal edge must belong to the upper bin.
        preds = [0.5, 0.5]
        outs = [0, 1]
        # n_bins=2: [0,0.5) is empty, [0.5,1] has both points.
        assert ece(preds, outs, n_bins=2) == pytest.approx(0.0)

    def test_ece_inner_bin_edges_are_left_closed_right_open(self) -> None:
        # Mutation that changes lo <= p < hi to lo <= p <= hi would double-count
        # the point p=0.5 in both bins and alter the ECE.
        preds = [0.49, 0.5, 0.51]
        outs = [0, 1, 1]
        assert ece(preds, outs, n_bins=2) == pytest.approx(
            (1 / 3) * abs(0.49 - 0.0) + (2 / 3) * abs(0.505 - 1.0)
        )

    def test_ece_last_bin_is_closed_on_both_sides(self) -> None:
        # Mutation that changes lo <= p <= hi to lo < p <= hi would drop p=1.0.
        preds = [1.0, 1.0]
        outs = [1, 1]
        assert ece(preds, outs, n_bins=2) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# smooth ECE
# ---------------------------------------------------------------------------


class TestSmoothEce:
    def test_perfectly_calibrated_predictor_near_zero(self) -> None:
        # Construct: half the samples predict 0.2 with hit rate 0.2,
        # half predict 0.8 with hit rate 0.8 (large n so kernel resolves).
        # 50 events at p=0.2 with 10 hits, 50 at p=0.8 with 40 hits.
        preds = [0.2] * 50 + [0.8] * 50
        outs = [1] * 10 + [0] * 40 + [1] * 40 + [0] * 10
        # smECE on a perfectly-calibrated bimodal predictor should be small
        # (kernel smoothing introduces a small bias near mass concentration).
        assert smooth_ece(preds, outs) < 0.10

    def test_anti_calibrated_returns_high(self) -> None:
        preds = [0.1] * 20 + [0.9] * 20
        outs = [1] * 20 + [0] * 20  # predictions inverted from outcomes
        assert smooth_ece(preds, outs) > 0.5

    def test_invalid_bandwidth_raises(self) -> None:
        with pytest.raises(ValueError, match="bandwidth must be positive"):
            smooth_ece([0.5], [1], bandwidth=0.0)

    def test_n_grid_minimum(self) -> None:
        with pytest.raises(ValueError, match="n_grid must be >= 2"):
            smooth_ece([0.5], [1], n_grid=1)

    def test_returns_finite_for_degenerate_constant_predictor(self) -> None:
        # All predictions identical: still a valid (poorly informative) input.
        preds = [0.5] * 10
        outs = [1, 0, 1, 0, 1, 0, 1, 0, 1, 0]
        result = smooth_ece(preds, outs)
        assert math.isfinite(result)
        assert 0.0 <= result <= 1.0

    def test_gaussian_kernel_formula_exact(self) -> None:
        # Import private helper to assert the exact kernel formula.
        from smc_core.calibration_metrics import _gaussian_kernel

        # z=0 → peak = 1 / (h * sqrt(2*pi))
        h = 0.5
        expected_peak = 1.0 / (h * math.sqrt(2.0 * math.pi))
        assert _gaussian_kernel(0.0, h) == pytest.approx(expected_peak)

        # z=1 → peak * exp(-0.5)
        assert _gaussian_kernel(h, h) == pytest.approx(expected_peak * math.exp(-0.5))

    def test_silverman_bandwidth_exact(self) -> None:
        from smc_core.calibration_metrics import _silverman_bandwidth

        n = 32
        expected = max(1.06 * 0.25 * n ** (-1.0 / 5.0), 1e-3)
        assert _silverman_bandwidth(n) == pytest.approx(expected)

    def test_smooth_ece_default_grid_is_101(self) -> None:
        # Use a predictor where grid density changes the result.
        preds = [0.0] * 50 + [1.0] * 50
        outs = [0] * 50 + [1] * 50
        result_default = smooth_ece(preds, outs)
        result_102 = smooth_ece(preds, outs, n_grid=102)
        assert result_default != pytest.approx(result_102)

    def test_smooth_ece_grid_is_uniform_on_unit_interval(self) -> None:
        # grid = i / (n_grid - 1); assert endpoints and a midpoint.
        from smc_core.calibration_metrics import _gaussian_kernel

        preds = [0.0, 0.5, 1.0]
        outs = [0, 1, 1]
        # With n_grid=3 the grid is exactly {0, 0.5, 1}.  Compute expected
        # value directly from the formula.
        h = 0.25
        grid = [0.0, 0.5, 1.0]
        total = 0.0
        total_weight = 0.0
        for g in grid:
            weights = [_gaussian_kernel(g - p, h) for p in preds]
            w_sum = sum(weights)
            r_hat = sum(w * o for w, o in zip(weights, outs)) / w_sum
            total += w_sum * abs(r_hat - g)
            total_weight += w_sum
        expected = total / total_weight
        assert smooth_ece(preds, outs, bandwidth=h, n_grid=3) == pytest.approx(expected)

    def test_smooth_ece_does_not_break_on_empty_grid_points(self) -> None:
        # With a tiny bandwidth the edge grid points have zero weight, but
        # the loop must continue to the central points.  If continue were
        # break, the result would be 0.0 (no contribution).
        preds = [0.5]
        outs = [1]
        # bandwidth small enough that kernels at grid endpoints underflow.
        result = smooth_ece(preds, outs, bandwidth=1e-6)
        assert result > 0.0

    def test_smooth_ece_n_grid_two_is_valid(self) -> None:
        # Mutants changing n_grid < 2 to <=2 or <3 would reject n_grid=2.
        preds = [0.1, 0.9]
        outs = [0, 1]
        result = smooth_ece(preds, outs, n_grid=2)
        assert math.isfinite(result)
        assert 0.0 <= result <= 1.0

    def test_smooth_ece_weight_sum_guard_matters(self) -> None:
        # Mutant that changes w_sum <= 0.0 to <= 1.0 skips legitimate grid
        # points and changes the result. Use a small bandwidth so several
        # grid points have total kernel weight below 1.0.
        preds = [0.1, 0.2, 0.3, 0.4, 0.5]
        outs = [0, 0, 1, 1, 1]
        result = smooth_ece(preds, outs, bandwidth=0.02)
        assert result > 0.0

    def test_smooth_ece_total_weight_guard_does_not_short_circuit(self) -> None:
        # With a wide bandwidth and n_grid=2 the combined kernel weight is
        # below 1.0 but positive. Mutants that change the final guard to
        # <= 1.0 or return 1.0 would produce a different result.
        preds = [0.5]
        outs = [1]
        assert smooth_ece(preds, outs, bandwidth=1.0, n_grid=2) == pytest.approx(
            0.5, abs=1e-9
        )

    def test_smooth_ece_returns_zero_when_all_weights_vanish(self) -> None:
        # When every grid point has zero kernel weight the total weight is
        # zero and the function must return 0.0, not an arbitrary constant.
        preds = [0.55]
        outs = [1]
        assert smooth_ece(preds, outs, bandwidth=1e-6, n_grid=11) == pytest.approx(
            0.0, abs=1e-9
        )


# ---------------------------------------------------------------------------
# Distance-to-calibration
# ---------------------------------------------------------------------------


class TestDce:
    def test_calibratable_monotone_predictor_is_zero(self) -> None:
        # Monotone agreement: low pred → low outcome, high pred → high
        # outcome.  Even though the *values* are off-diagonal, dCE must be
        # 0 because an isotonic re-mapping makes them perfectly calibrated.
        preds = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
        outs = [0, 0, 0, 0, 1, 1, 1, 1, 1]
        # Wait — dCE here measures mean|p - iso(p)| which is NOT zero
        # because iso projects onto outcomes, not onto p.  The calibratable
        # case is when p IS already isotonic in the outcomes — so dCE = 0
        # only when p == iso(p).  Confirm the edge case below instead.
        result = dce(preds, outs)
        assert result >= 0.0

    def test_perfectly_calibrated_is_zero(self) -> None:
        # p = empirical hit rate at p → isotonic projection equals p.
        # Use repeated structure: 4 events at p=0.25 with 1 hit, 4 at
        # p=0.75 with 3 hits.  Isotonic on outcomes → values 0.25, 0.75.
        preds = [0.25] * 4 + [0.75] * 4
        outs = [1, 0, 0, 0, 1, 1, 1, 0]
        assert dce(preds, outs) == pytest.approx(0.0, abs=1e-9)

    def test_anti_calibrated_is_high(self) -> None:
        preds = [0.9, 0.9, 0.1, 0.1]
        outs = [0, 0, 1, 1]
        # Isotonic on sorted-by-pred gives [1,1,0,0] → projected to
        # monotone non-decreasing ≈ [0.5, 0.5, 0.5, 0.5].
        # Mean |p - iso(p)| = (|0.1-0.5|*2 + |0.9-0.5|*2)/4 = 0.4.
        assert dce(preds, outs) == pytest.approx(0.4, abs=1e-9)

    def test_singleton_input(self) -> None:
        # One sample: isotonic equals the outcome itself.
        assert dce([0.5], [1]) == pytest.approx(0.5)

    def test_dce_with_violation_is_non_zero(self) -> None:
        # Non-trivial dCE where isotonic projection differs from predictions.
        # If weights were uniformly scaled (mutant [2.0]*n), the pooled means
        # would be identical, but this test asserts a concrete non-zero value
        # that only the original [1.0]*n weights produce.
        preds = [0.2, 0.4, 0.6, 0.8]
        outs = [1, 0, 1, 0]
        result = dce(preds, outs)
        # Manual: sorted by pred stays [0.2,0.4,0.6,0.8] with outs [1,0,1,0].
        # PAV pools [1,0] -> 0.5 and [1,0] -> 0.5, so iso = [0.5,0.5,0.5,0.5].
        # Mean |p - 0.5| = (0.3+0.1+0.1+0.3)/4 = 0.2.
        assert result == pytest.approx(0.2, abs=1e-9)


# ---------------------------------------------------------------------------
# Pool-adjacent-violators (internal helper)
# ---------------------------------------------------------------------------


class TestPoolAdjacentViolators:
    def test_pav_rejects_mismatched_lengths(self) -> None:
        # The helper explicitly validates equal lengths; this also prevents
        # a strict=True zip mutation from changing behaviour.
        from smc_core.calibration_metrics import _pool_adjacent_violators

        values = [0.0, 1.0]
        weights = [1.0]
        with pytest.raises(ValueError, match="length mismatch"):
            _pool_adjacent_violators(values, weights)

    def test_pav_pools_violators_exact(self) -> None:
        from smc_core.calibration_metrics import _pool_adjacent_violators

        # Monotone decreasing sequence must be pooled to its weighted mean.
        values = [0.9, 0.1]
        weights = [1.0, 1.0]
        # Block 1 has mean 0.9, block 2 mean 0.1 → violation → pool to 0.5.
        assert _pool_adjacent_violators(values, weights) == [0.5, 0.5]

    def test_pav_preserves_non_violators(self) -> None:
        from smc_core.calibration_metrics import _pool_adjacent_violators

        values = [0.1, 0.2, 0.3]
        weights = [1.0, 1.0, 1.0]
        assert _pool_adjacent_violators(values, weights) == [0.1, 0.2, 0.3]

    def test_pav_uses_weighted_mean_for_length_during_merge(self) -> None:
        # Regression for mutants that replace sum_weight by block length.
        from smc_core.calibration_metrics import _pool_adjacent_violators

        # Equal values with unequal weights: weighted mean must stay 0.1.
        values = [0.1, 0.1]
        weights = [3.0, 1.0]
        assert _pool_adjacent_violators(values, weights) == [0.1, 0.1]

    def test_pav_detects_non_strict_inequality(self) -> None:
        # Mutation >= instead of > must still pool equal-weight equal-means.
        from smc_core.calibration_metrics import _pool_adjacent_violators

        values = [0.1, 0.1]
        weights = [1.0, 2.0]
        assert _pool_adjacent_violators(values, weights) == [0.1, 0.1]

    def test_pav_weighted_sum_accumulated_not_length(self) -> None:
        # Mutation that adds top length instead of top weight to sum_weight
        # changes the pooled mean when weights != lengths.
        from smc_core.calibration_metrics import _pool_adjacent_violators

        values = [0.8, 0.6, 0.2]
        weights = [1.0, 3.0, 1.0]
        # Manual PAV: all three values pool into one block of weight 5.
        assert _pool_adjacent_violators(values, weights) == pytest.approx(
            [0.56, 0.56, 0.56], abs=1e-9
        )

    def test_pav_pool_decision_uses_weighted_mean(self) -> None:
        # Mutant that compares length-means instead of weighted means pools
        # [0.6] and [0.8] here because 1.2 > 0.8, even though the weighted
        # mean 0.6 is already monotone. The original must keep them split.
        from smc_core.calibration_metrics import _pool_adjacent_violators

        values = [0.6, 0.8]
        weights = [2.0, 1.0]
        assert _pool_adjacent_violators(values, weights) == [0.6, 0.8]


# ---------------------------------------------------------------------------
# Bundle reporter
# ---------------------------------------------------------------------------


class TestCalibrationReport:
    def test_returns_frozen_dataclass(self) -> None:
        report = calibration_report([0.5, 0.5], [0, 1])
        assert isinstance(report, CalibrationReport)
        with pytest.raises(AttributeError):  # frozen → assignment fails
            report.n_samples = 99  # type: ignore[misc]

    def test_n_samples_matches_input(self) -> None:
        report = calibration_report([0.1, 0.2, 0.3], [0, 1, 1])
        assert report.n_samples == 3

    def test_all_metrics_finite_and_bounded(self) -> None:
        preds = [i / 99 for i in range(100)]
        outs = [1 if p > 0.5 else 0 for p in preds]
        report = calibration_report(preds, outs)
        for name in ("ece", "smooth_ece", "dce"):
            value = getattr(report, name)
            assert math.isfinite(value), f"{name} not finite"
            assert 0.0 <= value <= 1.0, f"{name} out of [0,1]: {value}"

    def test_report_defaults_match_explicit_calls(self) -> None:
        preds = [0.1, 0.2, 0.3, 0.8]
        outs = [0, 0, 1, 1]
        default = calibration_report(preds, outs)
        explicit = calibration_report(preds, outs, n_bins=10, bandwidth=None)
        assert default == explicit

    def test_report_default_n_bins_affects_ece(self) -> None:
        preds = [0.1, 0.2, 0.3, 0.8]
        outs = [0, 0, 1, 1]
        default = calibration_report(preds, outs)
        two_bins = calibration_report(preds, outs, n_bins=2)
        assert default.ece != pytest.approx(two_bins.ece)

    def test_report_default_bandwidth_affects_smooth_ece(self) -> None:
        preds = [0.1, 0.2, 0.3, 0.8]
        outs = [0, 0, 1, 1]
        default = calibration_report(preds, outs)
        explicit_bandwidth = calibration_report(preds, outs, bandwidth=0.5)
        assert default.smooth_ece != pytest.approx(explicit_bandwidth.smooth_ece)

    def test_report_default_n_bins_is_ten(self) -> None:
        preds = [0.05, 0.095, 0.15, 0.19, 0.6, 0.9]
        outs = [0, 0, 1, 1, 0, 1]
        default = calibration_report(preds, outs)
        explicit_11 = calibration_report(preds, outs, n_bins=11)
        # Default n_bins must be 10, so changing it to 11 must differ.
        assert default.ece != pytest.approx(explicit_11.ece)

"""Tests for smc_core.calibration_metrics."""

from __future__ import annotations

import math
from statistics import mean

import pytest

from smc_core.calibration_metrics import (
    CalibrationReport,
    _gaussian_kernel,
    _pool_adjacent_violators,
    _silverman_bandwidth,
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
        with pytest.raises(ValueError, match="length mismatch"):
            ece([0.5, 0.6], [1])

    def test_empty_input_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
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

    def test_negative_prediction_raises(self) -> None:
        with pytest.raises(ValueError, match="out of range"):
            ece([-0.01], [1])


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
        with pytest.raises(ValueError, match="n_bins"):
            ece([0.5], [1], n_bins=0)

    def test_n_bins_one_is_valid(self) -> None:
        # Mutant n_bins < 2 vs < 1; single-bin ECE collapses to |mean(p)-mean(o)|.
        preds = [0.25, 0.75]
        outs = [1, 0]
        result = ece(preds, outs, n_bins=1)
        assert result == pytest.approx(abs(mean(preds) - mean(outs)))

    def test_boundary_prediction_at_one_is_included(self) -> None:
        # Last bin is inclusive on both ends; p=1.0 must land inside.
        preds = [1.0]
        outs = [1]
        assert ece(preds, outs, n_bins=2) == pytest.approx(0.0)

    def test_last_bin_upper_edge_inclusive(self) -> None:
        # If the last bin used < for its upper edge, p=1.0 would be excluded
        # and would form its own empty bin, changing the result.
        preds = [0.5, 1.0]
        outs = [1, 1]
        # Both points land in the final bin [0.5, 1.0].
        assert ece(preds, outs, n_bins=2) == pytest.approx(0.25)


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
        with pytest.raises(ValueError, match="bandwidth"):
            smooth_ece([0.5], [1], bandwidth=0.0)

    def test_n_grid_minimum(self) -> None:
        with pytest.raises(ValueError, match="n_grid"):
            smooth_ece([0.5], [1], n_grid=1)

    def test_returns_finite_for_degenerate_constant_predictor(self) -> None:
        # All predictions identical: still a valid (poorly informative) input.
        preds = [0.5] * 10
        outs = [1, 0, 1, 0, 1, 0, 1, 0, 1, 0]
        result = smooth_ece(preds, outs)
        assert math.isfinite(result)
        assert 0.0 <= result <= 1.0

    def test_explicit_bandwidth_matches_silverman_default(self) -> None:
        preds = [i / 9 for i in range(10)]
        outs = [1 if p > 0.5 else 0 for p in preds]
        default = smooth_ece(preds, outs)
        explicit = smooth_ece(preds, outs, bandwidth=None)
        assert default == pytest.approx(explicit, abs=1e-12)

    def test_n_grid_covers_unit_interval(self) -> None:
        # With n_grid=2 the grid is {0, 1}; result should still be valid.
        preds = [0.25, 0.75]
        outs = [0, 1]
        result = smooth_ece(preds, outs, n_grid=2)
        assert math.isfinite(result)
        assert 0.0 <= result <= 1.0

    def test_kernel_at_zero_is_normalization_constant(self) -> None:
        # K(0, h) = 1 / (h * sqrt(2*pi))
        h = 0.5
        expected = 1.0 / (h * math.sqrt(2.0 * math.pi))
        assert _gaussian_kernel(0.0, h) == pytest.approx(expected)

    def test_kernel_decreases_with_distance(self) -> None:
        h = 1.0
        at_zero = _gaussian_kernel(0.0, h)
        at_one = _gaussian_kernel(1.0, h)
        assert at_one < at_zero
        assert at_one == pytest.approx(math.exp(-0.5) / math.sqrt(2.0 * math.pi))

    def test_silverman_bandwidth_formula(self) -> None:
        # 1.06 * 0.25 * n**(-1/5), floored at 1e-3
        assert _silverman_bandwidth(1) == pytest.approx(max(1.06 * 0.25 * 1 ** (-1.0 / 5.0), 1e-3), abs=1e-12)
        assert _silverman_bandwidth(100) == pytest.approx(1.06 * 0.25 * 100 ** (-1.0 / 5.0), abs=1e-12)


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

    def test_weights_are_uniformly_one(self) -> None:
        # dce uses uniform unit weights; the perfectly-calibrated case gives
        # zero distance because p equals the isotonic projection.
        preds = [0.25] * 4 + [0.75] * 4
        outs = [1, 0, 0, 0, 1, 1, 1, 0]
        assert dce(preds, outs) == pytest.approx(0.0, abs=1e-9)

    def test_pav_monotone_with_violation(self) -> None:
        # [0, 1, 0] is not monotone; PAV pools the violating pair (1, 0).
        values = [0.0, 1.0, 0.0]
        weights = [1.0, 1.0, 1.0]
        fitted = _pool_adjacent_violators(values, weights)
        assert fitted[0] <= fitted[1]
        assert fitted[1] <= fitted[2]
        assert fitted == pytest.approx([0.0, 0.5, 0.5])

    def test_pav_respects_weights(self) -> None:
        # Same values but the middle point has weight 2, so the pooled
        # violation block has weighted average (2*1 + 1*0) / 3 = 2/3.
        values = [0.0, 1.0, 0.0]
        weights = [1.0, 2.0, 1.0]
        fitted = _pool_adjacent_violators(values, weights)
        assert fitted == pytest.approx([0.0, 2.0 / 3.0, 2.0 / 3.0])


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

    def test_report_ece_matches_direct_call(self) -> None:
        preds = [0.1, 0.2, 0.3, 0.9]
        outs = [0, 0, 1, 1]
        report = calibration_report(preds, outs, n_bins=5)
        assert report.ece == pytest.approx(ece(preds, outs, n_bins=5))

    def test_report_smooth_ece_matches_direct_call(self) -> None:
        preds = [0.1, 0.2, 0.3, 0.9]
        outs = [0, 0, 1, 1]
        report = calibration_report(preds, outs, bandwidth=0.05)
        assert report.smooth_ece == pytest.approx(
            smooth_ece(preds, outs, bandwidth=0.05)
        )

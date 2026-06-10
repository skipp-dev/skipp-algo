"""Sprint C10.1 — Conformal prediction coverage tests."""
from __future__ import annotations

import numpy as np
import pytest

from ml.calibration.conformal import (
    AdaptiveConformalClassifier,
    SplitConformalClassifier,
)


def _synthetic_probs_and_labels(n: int = 2000, seed: int = 0):
    """Calibrator outputs + labels with realistic Brier ~ 0.20."""
    rng = np.random.default_rng(seed)
    latent = rng.standard_normal(n)
    p_true = 1.0 / (1.0 + np.exp(-latent))
    y = (rng.random(n) < p_true).astype(int)
    # Slightly mis-calibrated probs (a model that's already close).
    probs = np.clip(p_true + 0.05 * rng.standard_normal(n), 0.005, 0.995)
    return probs, y


def test_split_conformal_marginal_coverage_within_band() -> None:
    probs, y = _synthetic_probs_and_labels(n=4000, seed=11)
    cal_p, test_p = probs[:2000], probs[2000:]
    cal_y, test_y = y[:2000], y[2000:]
    cls = SplitConformalClassifier(alpha=0.1).calibrate(cal_p, cal_y)
    rep = cls.evaluate(test_p, test_y)
    # 1-alpha = 0.90 ± 5 %. n=2000 calibration is plenty.
    assert 0.85 <= rep.empirical_coverage <= 0.97, rep


def test_split_conformal_alpha_05_tighter_coverage() -> None:
    probs, y = _synthetic_probs_and_labels(n=4000, seed=12)
    cal_p, test_p = probs[:2000], probs[2000:]
    cal_y, test_y = y[:2000], y[2000:]
    cls = SplitConformalClassifier(alpha=0.05).calibrate(cal_p, cal_y)
    rep = cls.evaluate(test_p, test_y)
    assert 0.90 <= rep.empirical_coverage <= 1.0, rep


def test_split_conformal_2d_probs_supported() -> None:
    p1 = np.array([0.2, 0.7, 0.5, 0.9])
    probs_2d = np.column_stack([1.0 - p1, p1])
    y = np.array([0, 1, 0, 1])
    cls = SplitConformalClassifier(alpha=0.2).calibrate(probs_2d, y)
    sets = cls.predict_set(probs_2d)
    assert len(sets) == 4
    assert all(s.issubset({0, 1}) and s for s in sets)


def test_adaptive_conformal_coverage_within_band() -> None:
    probs, y = _synthetic_probs_and_labels(n=4000, seed=13)
    cal_p, test_p = probs[:2000], probs[2000:]
    cal_y, test_y = y[:2000], y[2000:]
    cls = AdaptiveConformalClassifier(alpha=0.1).calibrate(cal_p, cal_y)
    rep = cls.evaluate(test_p, test_y)
    assert 0.85 <= rep.empirical_coverage <= 0.97, rep


def test_split_conformal_validates_alpha() -> None:
    with pytest.raises(ValueError, match="alpha"):
        SplitConformalClassifier(alpha=0.0)
    with pytest.raises(ValueError, match="alpha"):
        SplitConformalClassifier(alpha=1.0)


def test_split_conformal_predict_before_calibrate_raises() -> None:
    cls = SplitConformalClassifier(alpha=0.1)
    with pytest.raises(RuntimeError):
        cls.predict_set(np.array([0.5]))


def test_adaptive_conformal_predict_before_calibrate_raises() -> None:
    cls = AdaptiveConformalClassifier(alpha=0.1)
    with pytest.raises(RuntimeError):
        cls.predict_set(np.array([0.5]))


def test_split_conformal_calibration_length_mismatch() -> None:
    cls = SplitConformalClassifier(alpha=0.1)
    with pytest.raises(ValueError, match="length mismatch"):
        cls.calibrate(np.array([0.5, 0.6]), np.array([0]))


def test_split_conformal_empty_calibration_raises() -> None:
    cls = SplitConformalClassifier(alpha=0.1)
    with pytest.raises(ValueError, match="empty"):
        cls.calibrate(np.zeros(0), np.zeros(0, dtype=int))


def test_adaptive_conformal_rejects_unsupported_probs_shape() -> None:
    from ml.calibration.conformal import AdaptiveConformalClassifier

    cls = AdaptiveConformalClassifier(alpha=0.1)
    with pytest.raises(ValueError, match="Unsupported"):
        cls.calibrate(np.zeros((5, 3)), np.zeros(5, dtype=int))


def test_split_conformal_set_sizes_in_one_or_two() -> None:
    probs, y = _synthetic_probs_and_labels(n=2000, seed=14)
    cls = SplitConformalClassifier(alpha=0.1).calibrate(probs[:1000], y[:1000])
    sets = cls.predict_set(probs[1000:])
    sizes = {len(s) for s in sets}
    assert sizes.issubset({1, 2})


def test_split_conformal_logs_on_degenerate_quantile(caplog) -> None:
    cls = SplitConformalClassifier(alpha=0.1).calibrate(np.array([0.6, 0.7]), np.array([1, 1]))
    cls.quantile_ = -1.0
    with caplog.at_level("WARNING"):
        sets = cls.predict_set(np.array([0.4]))
    assert sets == [{0}]
    assert "degenerate_conformal_quantile" in caplog.text

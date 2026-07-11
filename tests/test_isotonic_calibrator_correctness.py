"""Correctness pins for IsotonicCalibrator's Pool-Adjacent-Violators fit and
for training model_version data-sensitivity.

The previous PAV implementation double-counted block weights (it wrote the
pooled weight onto both merged elements) and then took an *unweighted* mean per
unique x, so the fit converged to a wrong fixed point (e.g. y=[1,1,0] gave the
1/phi point 0.618 instead of the correct 2/3) and no longer preserved the label
sum. The smoke test only checks monotonicity + range, so it never caught this.
These tests pin the analytic PAV answers and sum preservation.
"""
from __future__ import annotations

import numpy as np

from ml.calibration import IsotonicCalibrator
from ml.training import FamilyDataset
from ml.training.base import _hash_version


def test_pav_pools_all_violations_to_grand_mean():
    # Strictly decreasing labels must pool to the grand mean everywhere.
    x = np.array([0.0, 1.0, 2.0])
    y = np.array([0.9, 0.5, 0.1])
    cal = IsotonicCalibrator().fit(x, y)
    out = cal.transform(x)
    assert np.allclose(out, 0.5), out


def test_pav_partial_pool_matches_closed_form():
    # y=[1,1,0] pools the trailing violation across all three points -> 2/3,
    # NOT the 1/phi ~= 0.618 fixed point the buggy pairwise averaging produced.
    x = np.array([0.0, 1.0, 2.0])
    y = np.array([1.0, 1.0, 0.0])
    cal = IsotonicCalibrator().fit(x, y)
    out = cal.transform(x)
    assert np.allclose(out, 2.0 / 3.0), out


def test_pav_leaves_monotone_input_unchanged():
    x = np.array([0.0, 1.0, 2.0, 3.0])
    y = np.array([0.1, 0.3, 0.6, 0.9])
    cal = IsotonicCalibrator().fit(x, y)
    assert np.allclose(cal.transform(x), y)


def test_pav_preserves_label_sum():
    # A correct (weighted) PAV preserves the total: summed fitted values over
    # all training points equal the summed labels.
    rng = np.random.default_rng(11)
    scores = rng.uniform(size=400)
    y = (rng.uniform(size=400) < scores).astype(float)
    cal = IsotonicCalibrator().fit(scores, y)
    assert np.isclose(cal.transform(scores).sum(), y.sum())


def test_pav_handles_duplicate_scores():
    # Ties in x are aggregated into one weighted point; the fit must still pool
    # correctly. Two points at x=0 (labels 1,0 -> mean 0.5) then x=1 label 0
    # -> the whole thing pools to the grand mean 1/3.
    x = np.array([0.0, 0.0, 1.0])
    y = np.array([1.0, 0.0, 0.0])
    cal = IsotonicCalibrator().fit(x, y)
    assert np.allclose(cal.transform(np.array([0.0, 1.0])), 1.0 / 3.0)
    assert np.isclose(cal.transform(x).sum(), y.sum())


def test_pav_output_is_monotone_and_in_range():
    rng = np.random.default_rng(3)
    scores = rng.uniform(size=300)
    y = (rng.uniform(size=300) < scores).astype(float)
    cal = IsotonicCalibrator().fit(scores, y)
    grid = np.linspace(0.0, 1.0, 50)
    p = cal.transform(grid)
    assert np.all(np.diff(p) >= -1e-12)
    assert np.all((p >= 0.0) & (p <= 1.0))


def _dataset(seed: int, *, family: str = "BOS", n: int = 64) -> FamilyDataset:
    rng = np.random.default_rng(seed)
    return FamilyDataset(
        family=family,  # type: ignore[arg-type]
        X=rng.normal(size=(n, 4)),
        y=(rng.uniform(size=n) < 0.5).astype(float),
        feature_names=("f0", "f1", "f2", "f3"),
    )


def test_model_version_distinguishes_different_data_of_same_shape():
    # A fixed-size rolling-window retrain feeds new data of identical shape each
    # cycle; the version must change so drift/provenance can tell the fits apart.
    a = _dataset(seed=1)
    b = _dataset(seed=2)  # same shape/family/feature_names, different content
    va = _hash_version("logistic", a, seed=0)
    vb = _hash_version("logistic", b, seed=0)
    assert va != vb


def test_model_version_is_stable_for_identical_inputs():
    a = _dataset(seed=1)
    b = _dataset(seed=1)  # identical data
    assert _hash_version("logistic", a, seed=0) == _hash_version("logistic", b, seed=0)

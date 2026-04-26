"""Sprint C10.1 — Stacking meta-learner smoke tests."""
from __future__ import annotations

import numpy as np
import pytest

from ml.stacking import StackedMetaLearner, mean_of_family_baseline
from ml.stacking.meta_learner import _project_simplex


def _make_synthetic(n: int = 1200, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Three-family synthetic where family 0 is informative + 1,2 noise.

    This is the worst case for the mean-of-family baseline (it averages
    away the only informative signal). Stacking should learn to put
    weight on family 0.
    """
    rng = np.random.default_rng(seed)
    # Latent risk score; label = sigmoid + noise.
    latent = rng.standard_normal(n)
    p_true = 1.0 / (1.0 + np.exp(-latent))
    y = (rng.random(n) < p_true).astype(int)
    # Family 0: informative — wraps p_true in light noise.
    p0 = np.clip(p_true + 0.03 * rng.standard_normal(n), 0.01, 0.99)
    # Families 1 + 2: pure noise around 0.5 (much wider than family 0).
    p1 = np.clip(0.5 + 0.20 * rng.standard_normal(n), 0.01, 0.99)
    p2 = np.clip(0.5 + 0.20 * rng.standard_normal(n), 0.01, 0.99)
    return np.column_stack([p0, p1, p2]), y


def test_meta_learner_beats_mean_baseline_by_5pct() -> None:
    P, y = _make_synthetic(n=1500, seed=42)
    n_train = 1000
    P_tr, P_va = P[:n_train], P[n_train:]
    y_tr, y_va = y[:n_train], y[n_train:]
    mdl = StackedMetaLearner(learning_rate=0.5, max_iter=3000).fit(P_tr, y_tr)
    report = mdl.evaluate(P_va, y_va, n_train=n_train)
    # Spec target: ≥ 5 % Brier improvement.
    assert report.brier_improvement_pct >= 5.0, report


def test_meta_learner_weights_concentrate_on_informative_family() -> None:
    P, y = _make_synthetic(n=1500, seed=7)
    mdl = StackedMetaLearner(learning_rate=0.5, max_iter=3000).fit(P, y)
    assert mdl.weights_ is not None
    # Family 0 should get the largest weight.
    assert int(np.argmax(mdl.weights_)) == 0


def test_meta_learner_weights_sum_to_one() -> None:
    P, y = _make_synthetic(n=400, seed=0)
    mdl = StackedMetaLearner(max_iter=500).fit(P, y)
    assert mdl.weights_ is not None
    assert mdl.weights_.sum() == pytest.approx(1.0, abs=1e-6)
    assert (mdl.weights_ >= -1e-9).all()


def test_meta_learner_predict_before_fit_raises() -> None:
    mdl = StackedMetaLearner()
    with pytest.raises(RuntimeError):
        mdl.predict_proba(np.zeros((3, 2)))


def test_meta_learner_validates_shapes() -> None:
    mdl = StackedMetaLearner()
    with pytest.raises(ValueError, match="2D"):
        mdl.fit(np.zeros(5), np.zeros(5))
    with pytest.raises(ValueError, match="len"):
        mdl.fit(np.zeros((5, 2)), np.zeros(4))


def test_mean_of_family_baseline() -> None:
    P = np.array([[0.2, 0.4, 0.6], [0.1, 0.1, 0.1]])
    out = mean_of_family_baseline(P)
    np.testing.assert_allclose(out, [0.4, 0.1])


def test_project_simplex_unit_sum_and_nonneg() -> None:
    w = np.array([2.0, -1.0, 0.5, 0.3])
    projected = _project_simplex(w)
    assert projected.sum() == pytest.approx(1.0)
    assert (projected >= 0.0).all()

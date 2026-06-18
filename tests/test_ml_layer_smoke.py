"""C10 ML-Layer end-to-end smoke test on synthetic data.

Exercises the full pipeline:
    walk-forward fit -> calibration -> predictor swap -> drift detection.

Uses only numpy + stdlib. The XGBoost/LightGBM trainers are exercised through
``BaseFamilyTrainer`` polymorphism by substituting ``LogisticBaseline``.
"""
from __future__ import annotations

import numpy as np
import pytest

from ml.calibration import (
    IsotonicCalibrator,
    OnlineRecalibrator,
    PlattCalibrator,
)
from ml.drift import MLDriftDetector
from ml.features import (
    bid_ask_imbalance,
    cyclical_encoding,
    garman_klass_volatility,
    parkinson_volatility,
    realized_volatility,
    session_marker,
    volume_imbalance,
    vpin,
)
from ml.inference import FamilyPredictor, ModelArtifact
from ml.metrics import brier_score, expected_calibration_error, log_loss, population_stability_index, roc_auc
from ml.training import FamilyDataset, LogisticBaseline
from ml.types import EventFamily, MLPrediction, TrainingReport


def _make_synthetic_dataset(family: EventFamily, n: int = 600, seed: int = 0):
    rng = np.random.default_rng(seed)
    X = rng.normal(0.0, 1.0, size=(n, 6))
    # Linear logit so logistic regression is well-calibrated by construction.
    true_w = np.array([0.9, -0.7, 0.4, 0.2, -0.3, 0.5])
    logits = X @ true_w + 0.1
    p = 1.0 / (1.0 + np.exp(-logits))
    y = (rng.uniform(size=n) < p).astype(float)
    return FamilyDataset(
        family=family,
        X=X,
        y=y,
        feature_names=("f0", "f1", "f2", "f3", "f4", "f5"),
    )


def test_logistic_baseline_walkforward_smoke():
    ds = _make_synthetic_dataset("BOS", n=500, seed=7)
    trainer = LogisticBaseline(seed=7, max_iter=300)
    fitted, report = trainer.fit(ds)
    assert isinstance(report, TrainingReport)
    assert report.backend == "logistic"
    assert report.n_train == 500
    # On a well-specified linear problem we expect AUC > 0.7 and Brier < 0.25.
    assert report.auc > 0.7, report
    assert report.brier < 0.25, report
    assert len(report.fold_metrics) == 5
    # Predict_proba must return values in [0, 1].
    p = fitted.predict_proba(ds.X[:20])
    assert p.shape == (20,)
    assert np.all((p >= 0.0) & (p <= 1.0))


def test_platt_calibrator_improves_brier_on_miscalibrated_scores():
    rng = np.random.default_rng(11)
    n = 400
    raw = rng.normal(0.0, 1.5, size=n)
    p_true = 1.0 / (1.0 + np.exp(-raw))
    y = (rng.uniform(size=n) < p_true).astype(float)
    # "Miscalibrated" scores: shift + scale.
    scores = 2.0 * raw + 0.5
    # Pre-calibration interpretation as probability via sigmoid.
    pre = 1.0 / (1.0 + np.exp(-scores))
    cal = PlattCalibrator().fit(scores, y)
    post = cal.transform(scores)
    assert brier_score(y, post) <= brier_score(y, pre) + 1e-9
    assert cal.version.startswith("platt-")


def test_isotonic_is_monotone_non_decreasing():
    rng = np.random.default_rng(3)
    scores = rng.uniform(size=300)
    y = (rng.uniform(size=300) < scores).astype(float)
    cal = IsotonicCalibrator().fit(scores, y)
    grid = np.linspace(0.0, 1.0, 50)
    p = cal.transform(grid)
    assert np.all(np.diff(p) >= -1e-12)
    assert np.all((p >= 0.0) & (p <= 1.0))


def test_predictor_atomic_swap_is_consistent():
    ds = _make_synthetic_dataset("FVG", n=400, seed=2)
    fitted, _ = LogisticBaseline(seed=2).fit(ds)
    cal = PlattCalibrator().fit(fitted.predict_proba(ds.X), ds.y)
    pred = FamilyPredictor()
    pred.swap({"FVG": ModelArtifact(fitted=fitted, calibrator=cal)})
    out = pred.predict("FVG", ds.X[0])
    assert isinstance(out, MLPrediction)
    assert 0.0 <= out.probability <= 1.0
    assert out.model_version == fitted.model_version
    batch = pred.predict_batch("FVG", ds.X[:5])
    assert len(batch) == 5


def test_predictor_raises_on_unknown_family():
    pred = FamilyPredictor()
    with pytest.raises(KeyError):
        pred.predict("OB", np.zeros(6))


def test_drift_detector_flags_distribution_shift():
    rng = np.random.default_rng(0)
    ref = rng.beta(2, 5, size=500)
    same = rng.beta(2, 5, size=500)
    shifted = rng.beta(5, 2, size=500)
    det = MLDriftDetector(warn=0.10, alarm=0.20)
    assert det.evaluate("BOS", ref, same).severity == "ok"
    assert det.evaluate("BOS", ref, shifted).severity == "alarm"


def test_online_recalibrator_triggers_on_psi_drift():
    rng = np.random.default_rng(0)
    ref = rng.beta(2, 5, size=300)
    live = rng.beta(5, 2, size=300)
    outcomes = (rng.uniform(size=300) < live).astype(float)
    rec = OnlineRecalibrator(psi_threshold=0.20, brier_regret_threshold=0.5)
    decision = rec.evaluate(ref, live, outcomes, reference_brier=0.15)
    assert decision.refit
    assert "psi" in decision.reason


def test_metrics_basic_properties():
    y = np.array([0.0, 0.0, 1.0, 1.0])
    p = np.array([0.1, 0.2, 0.8, 0.9])
    assert brier_score(y, p) < 0.1
    assert log_loss(y, p) > 0.0
    assert abs(roc_auc(y, p) - 1.0) < 1e-9
    assert expected_calibration_error(y, p, n_bins=4) >= 0.0


def test_microstructure_features_shapes_and_bounds():
    bid = np.array([100.0, 50.0, 0.0, 200.0])
    ask = np.array([100.0, 150.0, 0.0, 50.0])
    bai = bid_ask_imbalance(bid, ask)
    assert bai.shape == (4,)
    assert np.all((bai >= -1.0) & (bai <= 1.0))
    assert bai[2] == 0.0  # zero-volume guard
    assert volume_imbalance(bid, ask).shape == (4,)
    v = vpin(bid, ask, bucket_size=2)
    assert v.shape == (2,)
    assert np.all((v >= 0.0) & (v <= 1.0))


def test_volatility_features_non_negative():
    rng = np.random.default_rng(0)
    n = 100
    close = 100.0 + rng.normal(0, 1.0, size=n).cumsum()
    high = close + rng.uniform(0.1, 1.0, size=n)
    low = close - rng.uniform(0.1, 1.0, size=n)
    open_ = close + rng.normal(0, 0.3, size=n)
    rv = realized_volatility(close, window=10)
    gk = garman_klass_volatility(high, low, open_, close)
    pk = parkinson_volatility(high, low)
    assert rv.shape == (n,)
    assert np.all(rv >= 0.0)
    assert pk.shape == (n,)
    assert np.all(pk >= 0.0)
    # GK can theoretically be negative for adversarial inputs but should be
    # finite and well-defined here.
    assert np.all(np.isfinite(gk))


def test_temporal_encodings_shapes():
    minutes = np.arange(0, 1440, 60)
    enc = cyclical_encoding(minutes, period=1440)
    assert enc.shape == (24, 2)
    # sin^2 + cos^2 == 1
    assert np.allclose(np.sum(enc * enc, axis=1), 1.0)
    sess = session_marker([0, 545, 600, 970, 1100, 1300])
    assert list(sess) == [0, 1, 2, 3, 0, 0]


def test_xgb_and_lgbm_trainers_optional_dep_contract():
    """When the heavy dep is absent, instantiation must fail loudly."""
    from ml.training import LGBMFamilyTrainer, XGBFamilyTrainer

    if not XGBFamilyTrainer.available:
        with pytest.raises(RuntimeError, match="xgboost is not installed"):
            XGBFamilyTrainer()
    if not LGBMFamilyTrainer.available:
        with pytest.raises(RuntimeError, match="lightgbm is not installed"):
            LGBMFamilyTrainer()


# --- B1 regression: NaN/Inf must raise ValueError, not silently propagate ---
# Fuzzer-RCA (ref 8eb32df3): brier_score([0,1],[nan,0.5]) returned nan;
# roc_auc returned 0.0; psi returned 13.8. All now raise immediately.


@pytest.mark.parametrize(
    "func,args",
    [
        (brier_score, ([0, 1], [float("nan"), 0.5])),
        (brier_score, ([0, 1], [float("inf"), 0.5])),
        (brier_score, ([float("nan"), 1], [0.3, 0.5])),
        (log_loss, ([0, 1], [float("nan"), 0.5])),
        (log_loss, ([0, 1], [float("inf"), 0.5])),
        (roc_auc, ([0, 1], [float("nan"), 0.5])),
        (roc_auc, ([0, 1], [float("inf"), 0.5])),
        (expected_calibration_error, ([0, 1], [float("nan"), 0.5])),
        (expected_calibration_error, ([0, 1], [float("inf"), 0.5])),
    ],
)
def test_metrics_reject_nan_inf_inputs(func, args):
    """B1 regression: any metric must raise ValueError on NaN/Inf, not return nan."""
    with pytest.raises(ValueError, match="NaN or Inf"):
        func(*args)


def test_population_stability_index_rejects_nan_inf():
    """B1 regression: PSI must raise ValueError on NaN/Inf inputs."""
    with pytest.raises(ValueError, match="NaN or Inf"):
        population_stability_index([float("nan")], [0.5])
    with pytest.raises(ValueError, match="NaN or Inf"):
        population_stability_index([0.5], [float("inf")])

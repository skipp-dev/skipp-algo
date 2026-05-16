from __future__ import annotations

import types

import numpy as np

from scripts.ml_research_common import build_dataset_bundle, parse_families
from scripts.run_ml_explainability_report import build_parser as build_explainability_parser
from scripts.run_ml_family_training import (
    build_parser as build_training_parser,
    run_training as run_training_payload,
)
from scripts.run_ml_optuna_tuning import build_parser as build_tuning_parser


def test_parse_families_normalises_and_dedupes() -> None:
    assert parse_families("bos, FVG, bos, sweep") == ("BOS", "FVG", "SWEEP")


def test_build_dataset_bundle_is_deterministic() -> None:
    bundle_a = build_dataset_bundle(("BOS", "FVG"), n_samples=120, n_features=6, seed=11)
    bundle_b = build_dataset_bundle(("BOS", "FVG"), n_samples=120, n_features=6, seed=11)
    assert np.allclose(bundle_a["BOS"].X, bundle_b["BOS"].X)
    assert np.allclose(bundle_a["FVG"].y, bundle_b["FVG"].y)


def test_training_parser_defaults_to_training_artifact() -> None:
    args = build_training_parser().parse_args([])
    assert args.backend == "xgboost"
    assert str(args.output_path).replace("\\", "/").endswith("artifacts/ml/research/training/latest.json")


def test_training_payload_preserves_requested_device_intent() -> None:
    payload = run_training_payload(
        backend="logistic",
        device="cuda",
        families_raw="BOS",
        samples_per_family=120,
        feature_count=6,
        seed=11,
    )
    assert payload["requested_device"] == "cuda"
    assert payload["resolved_devices"] == ["cpu"]
    assert payload["family_reports"][0]["device_fallback_reason"] == "logistic_cpu_only"


def test_training_payload_detects_xgboost_silent_cpu_fallback(monkeypatch) -> None:
    import ml.training.xgb_family_trainer as xgb_family_trainer

    class FakeBooster:
        def save_config(self) -> str:
            return '{"learner": {"generic_param": {"device": "cpu"}}}'

    class FakeClassifier:
        def __init__(self, **params) -> None:
            self.params = params

        def fit(self, X, y, verbose=False):
            return self

        def predict_proba(self, X):
            rows = int(X.shape[0])
            return np.column_stack((np.full(rows, 0.4), np.full(rows, 0.6)))

        def get_booster(self):
            return FakeBooster()

    monkeypatch.setattr(xgb_family_trainer, "_HAS_XGB", True)
    monkeypatch.setattr(
        xgb_family_trainer,
        "xgb",
        types.SimpleNamespace(XGBClassifier=FakeClassifier),
    )

    payload = run_training_payload(
        backend="xgboost",
        device="cuda",
        families_raw="BOS",
        samples_per_family=120,
        feature_count=6,
        seed=11,
    )

    assert payload["requested_device"] == "cuda"
    assert payload["resolved_devices"] == ["cpu"]
    assert payload["family_reports"][0]["resolved_device"] == "cpu"
    assert payload["family_reports"][0]["device_fallback_reason"] == "requested_cuda_unavailable"


def test_explainability_parser_defaults_to_json_and_markdown() -> None:
    args = build_explainability_parser().parse_args([])
    assert str(args.output_path).replace("\\", "/").endswith("artifacts/ml/research/explainability/latest.json")
    assert str(args.markdown_path).replace("\\", "/").endswith("artifacts/ml/research/explainability/latest.md")


def test_optuna_parser_defaults_to_positive_trials() -> None:
    args = build_tuning_parser().parse_args([])
    assert args.trials > 0
    assert str(args.output_path).replace("\\", "/").endswith("artifacts/ml/research/optuna/latest.json")
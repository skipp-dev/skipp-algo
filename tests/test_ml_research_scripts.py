from __future__ import annotations

import numpy as np

from scripts.ml_research_common import build_dataset_bundle, parse_families
from scripts.run_ml_explainability_report import build_parser as build_explainability_parser
from scripts.run_ml_family_training import build_parser as build_training_parser
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


def test_explainability_parser_defaults_to_json_and_markdown() -> None:
    args = build_explainability_parser().parse_args([])
    assert str(args.output_path).replace("\\", "/").endswith("artifacts/ml/research/explainability/latest.json")
    assert str(args.markdown_path).replace("\\", "/").endswith("artifacts/ml/research/explainability/latest.md")


def test_optuna_parser_defaults_to_positive_trials() -> None:
    args = build_tuning_parser().parse_args([])
    assert args.trials > 0
    assert str(args.output_path).replace("\\", "/").endswith("artifacts/ml/research/optuna/latest.json")
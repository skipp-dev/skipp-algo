from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from open_prep.pre_a0_model import (
    ModelStatus,
    PreA0ShadowScorer,
    average_precision,
    brier_score,
    compute_artifact_id,
    expected_calibration_error,
    fit_platt_calibration,
    load_artifact,
    make_artifact,
    reliability_bins,
    train_logistic_regression,
    train_monotone_stump_boost,
)

FEATURES = ("price_progress", "volume_progress")


def _training_rows():
    return [
        {"price_progress": index / 39, "volume_progress": index / 39}
        for index in range(40)
    ]


def _artifact():
    rows = _training_rows()
    labels = [int(index >= 20) for index in range(40)]
    model = train_logistic_regression(rows, labels, FEATURES)
    raw = [model.raw_score(row) for row in rows]
    calibration = fit_platt_calibration(raw, labels)
    return make_artifact(
        model,
        calibration,
        schema_version="pre-a0-snapshot-v1",
        feature_version="pre-a0-features-v1",
        split_manifest_sha256="abc",
        trained_window=("2026-06-01", "2026-06-30"),
        calibrated_window=("2026-07-01", "2026-07-05"),
        review_after="2026-08-01T00:00:00Z",
        horizons=(30, 60, 180),
        metrics={"brier": 0.1},
        gates={"offline_evaluated": True},
    )


def test_model_and_calibration_are_deterministic_and_bounded() -> None:
    first = _artifact()
    second = _artifact()
    assert first.artifact_id == second.artifact_id
    scorer = PreA0ShadowScorer(ModelStatus.READY, first)
    low = scorer.score({"price_progress": 0.2, "volume_progress": 0.2}, horizon_s=60)
    high = scorer.score({"price_progress": 0.9, "volume_progress": 0.9}, horizon_s=60)
    assert low.probability is not None and high.probability is not None
    assert 0 <= low.probability < high.probability <= 1
    assert high.is_calibrated is True
    assert brier_score([0.1, 0.9], [0, 1]) == pytest.approx(0.01)
    assert expected_calibration_error([0.1, 0.9], [0, 1]) > 0
    assert average_precision([0.1, 0.9], [0, 1]) == 1.0
    assert sum(row["count"] for row in reliability_bins([0.1, 0.9], [0, 1])) == 2
    assert first.artifact_id == compute_artifact_id(
        contract_version=first.contract_version,
        schema_version=first.schema_version,
        feature_version=first.feature_version,
        split_manifest_sha256=first.split_manifest_sha256,
        model=first.model,
        calibration=first.calibration,
    )


def test_monotone_stump_boost_never_decreases_with_progress() -> None:
    rows = _training_rows()
    labels = [int(index >= 20) for index in range(40)]
    model = train_monotone_stump_boost(rows, labels, FEATURES)
    probabilities = [model.probability(row) for row in rows]
    assert model.stumps
    assert probabilities == sorted(probabilities)


def test_artifact_loader_fails_closed_for_expiry_and_incompatibility(tmp_path) -> None:
    artifact = _artifact()
    path = tmp_path / "model.json"
    path.write_text(json.dumps(artifact.to_dict()), encoding="utf-8")
    status, loaded, reason = load_artifact(
        path,
        expected_schema="pre-a0-snapshot-v1",
        expected_feature_version="pre-a0-features-v1",
        now=datetime(2026, 8, 2, tzinfo=UTC),
    )
    assert (status, loaded, reason) == (ModelStatus.EXPIRED, None, "artifact_expired")
    status, loaded, _ = load_artifact(
        path,
        expected_schema="wrong",
        expected_feature_version="pre-a0-features-v1",
        now=datetime(2026, 7, 2, tzinfo=UTC),
    )
    assert status is ModelStatus.INCOMPATIBLE
    assert loaded is None


def test_artifact_loader_rejects_content_tampering(tmp_path) -> None:
    payload = _artifact().to_dict()
    payload["model"]["intercept"] += 0.01
    path = tmp_path / "model.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    status, loaded, reason = load_artifact(
        path,
        expected_schema="pre-a0-snapshot-v1",
        expected_feature_version="pre-a0-features-v1",
        now=datetime(2026, 7, 2, tzinfo=UTC),
    )
    assert (status, loaded, reason) == (ModelStatus.INVALID, None, "artifact_identity_mismatch")


def test_shadow_scorer_rejects_missing_features_without_a_probability() -> None:
    score = PreA0ShadowScorer(ModelStatus.READY, _artifact()).score(
        {"price_progress": 0.8}, horizon_s=60
    )
    assert score.status is ModelStatus.INCOMPATIBLE
    assert score.probability is None
    assert score.missing_features == ("volume_progress",)

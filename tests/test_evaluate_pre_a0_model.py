from __future__ import annotations

import json
import sys
from pathlib import Path

from open_prep.pre_a0_model import (
    fit_platt_calibration,
    make_artifact,
    parse_artifact,
    train_logistic_regression,
    verify_artifact_id,
)
from scripts import evaluate_pre_a0_model


def test_evaluation_emits_governance_bundle_contract(tmp_path: Path, monkeypatch, capsys) -> None:
    feature_names = ("progress",)
    features = [{"progress": index / 39} for index in range(40)]
    labels = [int(index >= 20) for index in range(40)]
    model = train_logistic_regression(features, labels, feature_names)
    raw = [model.raw_score(row) for row in features]
    calibration = fit_platt_calibration(raw, labels)
    artifact = make_artifact(
        model,
        calibration,
        schema_version="pre-a0-snapshot-v1",
        feature_version="pre-a0-features-v1",
        split_manifest_sha256="split-manifest",
        trained_window=("2026-06-01", "2026-06-30"),
        calibrated_window=("2026-07-01", "2026-07-05"),
        review_after="2026-08-01T00:00:00Z",
        horizons=(60,),
        metrics={"calibration_brier": 0.1},
        gates={"offline_evaluated": False, "shadow_evaluated": False},
    )
    artifact_path = tmp_path / "model.json"
    test_path = tmp_path / "test.json"
    report_path = tmp_path / "report.json"
    validated_path = tmp_path / "validated.json"
    artifact_path.write_text(json.dumps(artifact.to_dict()), encoding="utf-8")
    test_rows = [
        {"features": row, "label": label}
        for _ in range(5)
        for row, label in zip(features, labels, strict=True)
    ]
    test_path.write_text(
        json.dumps({"split_sha256": "sealed-test-split", "rows": test_rows}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate_pre_a0_model.py",
            str(artifact_path),
            str(test_path),
            str(report_path),
            "--validated-artifact-output",
            str(validated_path),
        ],
    )
    assert evaluate_pre_a0_model.main() == 0
    capsys.readouterr()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    validated = parse_artifact(json.loads(validated_path.read_text(encoding="utf-8")))
    assert report["split_sha256"] == "split-manifest"
    assert report["sealed_split_sha256"] == "sealed-test-split"
    assert report["metrics"]["test_rows"] == 200.0
    assert report["offline_gate_passed"] is True
    assert validated.artifact_id == artifact.artifact_id
    assert validated.gates["offline_evaluated"] is True
    assert validated.metrics == report["metrics"]
    assert verify_artifact_id(validated) is True

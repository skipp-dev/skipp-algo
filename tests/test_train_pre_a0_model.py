from __future__ import annotations

import json
import sys
from pathlib import Path

from open_prep import pre_a0_mlflow
from scripts import train_pre_a0_model


def test_training_cli_logs_only_when_mlflow_uri_is_explicit(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    rows = [
        {"features": {"progress": index / 39}, "label": int(index >= 20)}
        for index in range(40)
    ]
    payload = {
        "feature_names": ["progress"],
        "train": rows,
        "calibration": rows,
        "schema_version": "pre-a0-snapshot-v1",
        "feature_version": "pre-a0-features-v1",
        "trained_window": ["2026-06-01", "2026-06-30"],
        "calibrated_window": ["2026-07-01", "2026-07-05"],
        "horizons": [60],
    }
    input_path = tmp_path / "training.json"
    output_path = tmp_path / "model.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_log_training_run(**kwargs) -> str:
        captured.update(kwargs)
        return "run-123"

    monkeypatch.setattr(pre_a0_mlflow, "log_training_run", fake_log_training_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "train_pre_a0_model.py",
            str(input_path),
            str(output_path),
            "--split-hash",
            "sealed-split",
            "--review-after",
            "2026-08-01T00:00:00Z",
            "--mlflow-tracking-uri",
            "https://mlflow.example.test",
            "--mlflow-run-name",
            "test-run",
        ],
    )
    assert train_pre_a0_model.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mlflow_run_id"] == "run-123"
    assert captured["tracking_uri"] == "https://mlflow.example.test"
    assert captured["run_name"] == "test-run"
    assert captured["training_input_path"] == input_path
    assert captured["training_rows"] == 40
    assert captured["calibration_rows"] == 40
    assert output_path.is_file()

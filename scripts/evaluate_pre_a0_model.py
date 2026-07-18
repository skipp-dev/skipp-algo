#!/usr/bin/env python3
"""Evaluate a PRE-A0 artifact on a sealed JSON test split."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from open_prep.pre_a0_model import (
    average_precision,
    base_rate,
    brier_score,
    expected_calibration_error,
    parse_artifact,
    reliability_bins,
    verify_artifact_id,
)
from scripts.smc_atomic_write import atomic_write_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    parser.add_argument("test_split", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--validated-artifact-output",
        type=Path,
        help="optional JSON artifact with offline metrics/gate folded in",
    )
    args = parser.parse_args()
    artifact = parse_artifact(json.loads(args.artifact.read_text(encoding="utf-8")))
    if not verify_artifact_id(artifact):
        raise ValueError("artifact identity mismatch")
    payload = json.loads(args.test_split.read_text(encoding="utf-8"))
    rows = payload["rows"]
    labels = [int(row["label"]) for row in rows]
    raw = [artifact.model.raw_score(row["features"]) for row in rows]
    probabilities = [
        artifact.calibration.apply(score) if artifact.calibration else artifact.model.probability(row["features"])
        for score, row in zip(raw, rows, strict=True)
    ]
    rate = base_rate(labels)
    model_brier = brier_score(probabilities, labels)
    test_metrics = {
        "test_rows": float(len(rows)),
        "test_base_rate_brier": brier_score([rate] * len(labels), labels),
        "test_brier": model_brier,
        "test_average_precision": average_precision(probabilities, labels),
        "test_ece": expected_calibration_error(probabilities, labels),
    }
    metrics = {**artifact.metrics, **test_metrics}
    report = {
        "artifact_id": artifact.artifact_id,
        "split_sha256": artifact.split_manifest_sha256,
        "sealed_split_sha256": payload["split_sha256"],
        "rows": len(rows),
        "base_rate": rate,
        "base_rate_brier": test_metrics["test_base_rate_brier"],
        "model_brier": model_brier,
        "average_precision": test_metrics["test_average_precision"],
        "ece": test_metrics["test_ece"],
        "metrics": metrics,
        "reliability": reliability_bins(probabilities, labels),
    }
    report["beats_base_rate"] = report["model_brier"] < report["base_rate_brier"]
    report["offline_gate_passed"] = report["beats_base_rate"]
    atomic_write_json(report, args.output, sort_keys=True)
    if args.validated_artifact_output:
        validated_artifact = replace(
            artifact,
            metrics=metrics,
            gates={**artifact.gates, "offline_evaluated": bool(report["offline_gate_passed"])},
        )
        atomic_write_json(validated_artifact.to_dict(), args.validated_artifact_output, sort_keys=True)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

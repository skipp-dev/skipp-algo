#!/usr/bin/env python3
"""Evaluate a PRE-A0 artifact on a sealed JSON test split."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from open_prep.pre_a0_model import (
    average_precision,
    base_rate,
    brier_score,
    expected_calibration_error,
    parse_artifact,
    reliability_bins,
)
from scripts.smc_atomic_write import atomic_write_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    parser.add_argument("test_split", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    artifact = parse_artifact(json.loads(args.artifact.read_text(encoding="utf-8")))
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
    report = {
        "artifact_id": artifact.artifact_id,
        "sealed_split_sha256": payload["split_sha256"],
        "rows": len(rows),
        "base_rate": rate,
        "base_rate_brier": brier_score([rate] * len(labels), labels),
        "model_brier": model_brier,
        "average_precision": average_precision(probabilities, labels),
        "ece": expected_calibration_error(probabilities, labels),
        "reliability": reliability_bins(probabilities, labels),
    }
    report["beats_base_rate"] = report["model_brier"] < report["base_rate_brier"]
    atomic_write_json(report, args.output, sort_keys=True)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

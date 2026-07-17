#!/usr/bin/env python3
"""Train the deterministic PRE-A0 logistic and Platt baselines from JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from open_prep.pre_a0_model import (
    brier_score,
    expected_calibration_error,
    fit_platt_calibration,
    make_artifact,
    train_logistic_regression,
)
from scripts.smc_atomic_write import atomic_write_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--split-hash", required=True)
    parser.add_argument("--review-after", required=True)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    feature_names = tuple(payload["feature_names"])
    train = payload["train"]
    calibration_rows = payload["calibration"]
    model = train_logistic_regression(
        [row["features"] for row in train], [int(row["label"]) for row in train], feature_names
    )
    raw = [model.raw_score(row["features"]) for row in calibration_rows]
    labels = [int(row["label"]) for row in calibration_rows]
    calibration = fit_platt_calibration(raw, labels)
    probabilities = [calibration.apply(score) for score in raw]
    metrics = {
        "calibration_brier": brier_score(probabilities, labels),
        "calibration_ece": expected_calibration_error(probabilities, labels),
    }
    artifact = make_artifact(
        model,
        calibration,
        schema_version=payload["schema_version"],
        feature_version=payload["feature_version"],
        split_manifest_sha256=args.split_hash,
        trained_window=tuple(payload["trained_window"]),
        calibrated_window=tuple(payload["calibrated_window"]),
        review_after=args.review_after,
        horizons=payload.get("horizons", [30, 60, 180]),
        metrics=metrics,
        gates={"offline_evaluated": False, "shadow_evaluated": False},
    )
    atomic_write_json(artifact.to_dict(), args.output, sort_keys=True)
    print(json.dumps({"artifact_id": artifact.artifact_id, "metrics": metrics}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

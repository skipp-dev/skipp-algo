#!/usr/bin/env python3
"""Create deterministic, leakage-bounded PRE-A0 train/calibration/test JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from open_prep.pre_a0_labels import audit_dataset, build_walk_forward_manifest, label_snapshots
from open_prep.pre_a0_model import parse_artifact, verify_artifact_id
from scripts import evaluate_pre_a0_shadow as shadow
from scripts.smc_atomic_write import atomic_write_json


def _features(row: Any, names: tuple[str, ...], horizon: int) -> dict[str, float] | None:
    values = {
        "price_progress": row.price_progress,
        "volume_progress": row.volume_progress,
        "price_distance_pct": row.price_distance_pct,
        "volume_distance_pace": row.volume_distance_pace,
        "price_slope_15s": row.price_slope_15s,
        "volume_slope_15s": row.volume_slope_15s,
        "direction_stability": row.direction_stability,
        "direction": 1.0 if row.direction == "up" else -1.0 if row.direction == "down" else 0.0,
        "horizon_s": float(horizon),
    }
    if any(values.get(name) is None for name in names):
        return None
    return {name: float(values[name]) for name in names}


def prepare(
    *,
    artifact_path: Path,
    snapshot_root: Path,
    journal_paths: list[Path],
    code_revision: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    artifact = parse_artifact(shadow._read_object(artifact_path, "artifact"))
    if not verify_artifact_id(artifact):
        raise ValueError("artifact identity mismatch")
    frame, snapshot_paths = shadow._load_snapshots(snapshot_root)
    rows = shadow._rows(frame)
    events = shadow._events(journal_paths)
    split = build_walk_forward_manifest(rows, code_revision=code_revision)
    audit = audit_dataset(rows, split_by_record=split["assignments"])
    if not audit["passed"]:
        raise ValueError("snapshot audit failed")
    observation_end = frame.groupby("session_date")["prediction_time"].max().to_dict()
    labels = label_snapshots(rows, events, session_end_by_date=observation_end)
    labels_by_id = {label.record_id: label for label in labels}
    names = artifact.model.feature_names
    datasets: dict[str, list[dict[str, Any]]] = {name: [] for name in ("train", "calibration", "test")}
    skipped_missing_features = 0
    for row in rows:
        target = split["assignments"][row.record_id]
        label = labels_by_id[row.record_id]
        for horizon in artifact.horizons:
            outcome = getattr(label, f"y_{horizon}")
            if outcome is None:
                continue
            feature_values = _features(row, names, horizon)
            if feature_values is None:
                skipped_missing_features += 1
                continue
            datasets[target].append(
                {
                    "features": feature_values,
                    "label": int(outcome),
                    "sample_weight": float(row.sample_weight),
                    "record_id": row.record_id,
                    "session_date": row.session_date,
                    "horizon_s": horizon,
                }
            )
    for name, records in datasets.items():
        if not records or len({record["label"] for record in records}) < 2:
            raise ValueError(f"{name} split requires rows from both classes")
    train_payload = {
        "contract_version": "pre-a0-training-input-v1",
        "feature_names": list(names),
        "schema_version": artifact.schema_version,
        "feature_version": artifact.feature_version,
        "horizons": list(artifact.horizons),
        "trained_window": [split["days"]["train"][0], split["days"]["train"][-1]],
        "calibrated_window": [
            split["days"]["calibration"][0],
            split["days"]["calibration"][-1],
        ],
        "train": datasets["train"],
        "calibration": datasets["calibration"],
    }
    test_payload = {
        "contract_version": "pre-a0-sealed-test-v1",
        "split_sha256": split["split_sha256"],
        "rows": datasets["test"],
    }
    provenance = {
        "contract_version": "pre-a0-training-provenance-v1",
        "source_artifact_id": artifact.artifact_id,
        "code_revision": code_revision,
        "snapshot_sha256": shadow._file_hash(snapshot_paths),
        "journal_sha256": shadow._file_hash(journal_paths),
        "split_manifest": split,
        "audit": audit,
        "counts": {name: len(records) for name, records in datasets.items()},
        "skipped_missing_features": skipped_missing_features,
        "reproducible": True,
    }
    return train_payload, test_payload, provenance


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    parser.add_argument("snapshot_root", type=Path)
    parser.add_argument("training_output", type=Path)
    parser.add_argument("test_output", type=Path)
    parser.add_argument("provenance_output", type=Path)
    parser.add_argument("journals", nargs="+", type=Path)
    parser.add_argument("--code-revision", required=True)
    args = parser.parse_args()
    training, test, provenance = prepare(
        artifact_path=args.artifact,
        snapshot_root=args.snapshot_root,
        journal_paths=args.journals,
        code_revision=args.code_revision,
    )
    atomic_write_json(training, args.training_output, sort_keys=True)
    atomic_write_json(test, args.test_output, sort_keys=True)
    atomic_write_json(provenance, args.provenance_output, sort_keys=True)
    print(json.dumps(provenance["counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

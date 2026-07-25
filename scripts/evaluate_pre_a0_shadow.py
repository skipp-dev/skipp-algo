#!/usr/bin/env python3
"""Build fail-closed PRE-A0 shadow evidence from scored snapshots and A0 journals."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import MISSING, asdict, fields, replace
from pathlib import Path
from typing import Any

import pandas as pd

from open_prep.a0_parity_store import load_shadow_decisions
from open_prep.pre_a0_labels import audit_dataset, label_snapshots
from open_prep.pre_a0_model import (
    average_precision,
    base_rate,
    brier_score,
    expected_calibration_error,
    parse_artifact,
    verify_artifact_id,
)
from open_prep.pre_a0_outcomes import ConfirmedA0
from open_prep.pre_a0_schema import PreA0SnapshotRow
from scripts.smc_atomic_write import atomic_write_json


def _read_object(path: Path, label: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def _file_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path).encode())
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _load_snapshots(root: Path) -> tuple[pd.DataFrame, list[Path]]:
    paths = sorted(root.rglob("*.parquet"))
    if not paths:
        raise ValueError("snapshot root contains no Parquet files")
    frames: list[pd.DataFrame] = []
    for path in paths:
        manifest_path = path.with_suffix(".manifest.json")
        manifest = _read_object(manifest_path, f"manifest for {path.name}")
        if manifest.get("status") != "complete" or manifest.get("data_file") != path.name:
            raise ValueError(f"incomplete or mismatched snapshot manifest: {manifest_path}")
        frame = pd.read_parquet(path)
        if len(frame) != int(manifest.get("row_count", -1)):
            raise ValueError(f"snapshot row count mismatch: {path}")
        rows_sha256 = hashlib.sha256(
            json.dumps(
                [asdict(row) for row in sorted(_rows(frame), key=lambda item: item.record_id)],
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        if manifest.get("rows_sha256") != rows_sha256:
            raise ValueError(f"snapshot content hash mismatch: {path}")
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    if combined["record_id"].duplicated().any():
        # record_id is content-addressed and the store's in-memory de-dup set
        # resets on restart, so a mid-session restart or a duplicate producer /
        # replay re-emits byte-identical rows into a fresh part file (observed
        # 2026-07-23). Collapse those idempotently; only record_ids whose
        # CONTENT conflicts are real corruption and still fail closed.
        seen: dict[str, str] = {}
        keep: list[int] = []
        for index, row in enumerate(_rows(combined)):
            canonical = json.dumps(asdict(row), sort_keys=True, separators=(",", ":"))
            previous = seen.get(row.record_id)
            if previous is None:
                seen[row.record_id] = canonical
                keep.append(index)
            elif previous != canonical:
                raise ValueError(
                    "snapshot dataset contains conflicting duplicate record_id values"
                )
        combined = combined.iloc[keep].reset_index(drop=True)
    return combined, paths


def _value(value: Any) -> Any:
    return None if pd.isna(value) else value


def _rows(frame: pd.DataFrame) -> list[PreA0SnapshotRow]:
    names = {field.name for field in fields(PreA0SnapshotRow)}
    required = {
        field.name
        for field in fields(PreA0SnapshotRow)
        if field.default is MISSING and field.default_factory is MISSING
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"snapshot schema is missing required columns: {sorted(missing)}")
    output: list[PreA0SnapshotRow] = []
    for record in frame.to_dict(orient="records"):
        output.append(
            PreA0SnapshotRow(**{name: _value(record[name]) for name in names if name in record})
        )
    return output


def _events(paths: list[Path]) -> list[ConfirmedA0]:
    decisions = load_shadow_decisions(paths, expected_source="databento", include_core_a0=True)
    return [
        ConfirmedA0(
            decision.symbol,
            decision.decision_at,
            "up" if decision.direction == "LONG" else "down",
            decision.reason_codes,
        )
        for decision in decisions
    ]


def _horizon_metrics(
    frame: pd.DataFrame,
    labels_by_id: dict[str, Any],
    horizon: int,
    artifact_id: str,
) -> dict[str, float]:
    label_name = f"y_{horizon}"
    probability_name = f"probability_{horizon}"
    status_name = f"score_status_{horizon}"
    reason_name = f"score_reason_{horizon}"
    eligible = [
        record
        for record in frame.to_dict(orient="records")
        if getattr(labels_by_id[str(record["record_id"])], label_name) is not None
    ]
    valid: list[tuple[float, int]] = []
    for record in eligible:
        probability = _value(record.get(probability_name))
        status = _value(record.get(status_name))
        reason = _value(record.get(reason_name))
        if (
            record.get("model_artifact_id") == artifact_id
            and status == "ready"
            and reason is None
            and probability is not None
            and math.isfinite(float(probability))
            and 0 <= float(probability) <= 1
        ):
            label = int(getattr(labels_by_id[str(record["record_id"])], label_name))
            valid.append((float(probability), label))
    probabilities = [row[0] for row in valid]
    labels = [row[1] for row in valid]
    positives = sum(labels)
    result = {
        "eligible_rows": float(len(eligible)),
        "scored_rows": float(len(valid)),
        "positive_rows": float(positives),
        "score_coverage": len(valid) / len(eligible) if eligible else 0.0,
    }
    if not valid or not positives or positives == len(valid):
        return result
    rate = base_rate(labels)
    result.update(
        {
            "brier": brier_score(probabilities, labels),
            "base_rate_brier": brier_score([rate] * len(labels), labels),
            "average_precision": average_precision(probabilities, labels),
            "ece": expected_calibration_error(probabilities, labels),
        }
    )
    return result


def evaluate(
    *,
    artifact_path: Path,
    offline_report_path: Path,
    policy_path: Path,
    snapshot_root: Path,
    journal_paths: list[Path],
) -> tuple[dict[str, Any], Any]:
    artifact = parse_artifact(_read_object(artifact_path, "artifact"))
    if not verify_artifact_id(artifact):
        raise ValueError("artifact identity mismatch")
    offline_report = _read_object(offline_report_path, "offline report")
    if offline_report.get("artifact_id") != artifact.artifact_id:
        raise ValueError("offline report is linked to another artifact")
    policy = _read_object(policy_path, "promotion policy")
    shadow_policy = policy.get("shadow")
    if not isinstance(shadow_policy, dict):
        raise ValueError("promotion policy has no shadow section")

    frame, snapshot_paths = _load_snapshots(snapshot_root)
    rows = _rows(frame)
    audit = audit_dataset(rows)
    events = _events(journal_paths)
    observation_end = frame.groupby("session_date")["prediction_time"].max().to_dict()
    labels = label_snapshots(rows, events, session_end_by_date=observation_end)
    labels_by_id = {label.record_id: label for label in labels}
    horizons = [horizon for horizon in artifact.horizons if horizon in (30, 60, 180)]
    metrics = {
        str(horizon): _horizon_metrics(frame, labels_by_id, horizon, artifact.artifact_id)
        for horizon in horizons
    }

    reasons: list[str] = []
    sessions = int(frame["session_date"].nunique())
    artifact_ids = sorted(
        str(value) for value in frame["model_artifact_id"].dropna().unique()
    )
    if sessions < int(shadow_policy["min_sessions"]):
        reasons.append("shadow_sessions_below_minimum")
    if shadow_policy.get("require_zero_audit_findings", True) and not audit["passed"]:
        reasons.append("shadow_dataset_audit_failed")
    if shadow_policy.get("require_single_artifact", True) and artifact_ids != [artifact.artifact_id]:
        reasons.append("shadow_artifact_identity_mismatch")
    for horizon, values in metrics.items():
        prefix = f"shadow_{horizon}"
        if values["eligible_rows"] < float(shadow_policy["min_labeled_rows_per_horizon"]):
            reasons.append(f"{prefix}_rows_below_minimum")
        if values["positive_rows"] < float(shadow_policy["min_positive_rows_per_horizon"]):
            reasons.append(f"{prefix}_positives_below_minimum")
        if values["score_coverage"] < float(shadow_policy["min_score_coverage"]):
            reasons.append(f"{prefix}_score_coverage_below_minimum")
        if "brier" not in values:
            reasons.append(f"{prefix}_class_diversity_missing")
            continue
        if values["brier"] / values["base_rate_brier"] >= float(shadow_policy["max_brier_ratio"]):
            reasons.append(f"{prefix}_brier_does_not_beat_baseline")
        if values["ece"] > float(shadow_policy["max_ece"]):
            reasons.append(f"{prefix}_ece_above_maximum")
        if values["average_precision"] < float(shadow_policy["min_average_precision"]):
            reasons.append(f"{prefix}_average_precision_below_minimum")

    passed = not reasons
    flat_metrics = {
        f"shadow_{horizon}_{name}": float(value)
        for horizon, values in metrics.items()
        for name, value in values.items()
    }
    report = {
        **offline_report,
        "metrics": {**offline_report.get("metrics", {}), **flat_metrics},
        "shadow_gate_passed": passed,
        "shadow_evaluation": {
            "contract_version": "pre-a0-shadow-evaluation-v1",
            "artifact_id": artifact.artifact_id,
            "snapshot_sha256": _file_hash(snapshot_paths),
            "journal_sha256": _file_hash(journal_paths),
            "snapshot_files": len(snapshot_paths),
            "journal_files": len(journal_paths),
            "sessions": sessions,
            "rows": len(frame),
            "confirmed_a0_events": len(events),
            "artifact_ids": artifact_ids,
            "audit": audit,
            "horizons": metrics,
            "passed": passed,
            "reasons": reasons,
        },
    }
    validated = replace(
        artifact,
        metrics={**artifact.metrics, **flat_metrics},
        gates={**artifact.gates, "shadow_evaluated": passed},
    )
    return report, validated


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    parser.add_argument("offline_report", type=Path)
    parser.add_argument("policy", type=Path)
    parser.add_argument("snapshot_root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("journals", nargs="+", type=Path)
    parser.add_argument("--validated-artifact-output", type=Path)
    args = parser.parse_args()
    report, validated = evaluate(
        artifact_path=args.artifact,
        offline_report_path=args.offline_report,
        policy_path=args.policy,
        snapshot_root=args.snapshot_root,
        journal_paths=args.journals,
    )
    atomic_write_json(report, args.output, sort_keys=True)
    if args.validated_artifact_output:
        if not report["shadow_gate_passed"]:
            raise ValueError("shadow gate failed; refusing to write a promoted artifact")
        atomic_write_json(validated.to_dict(), args.validated_artifact_output, sort_keys=True)
    print(json.dumps(report["shadow_evaluation"], sort_keys=True))
    return 0 if report["shadow_gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

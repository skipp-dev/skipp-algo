"""Leakage-bounded PRE-A0 episode labels, audits, and day splits."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

from .pre_a0_outcomes import ConfirmedA0
from .pre_a0_schema import PreA0SnapshotRow

HORIZONS = (30, 60, 180)


@dataclass(frozen=True, slots=True)
class PreA0Label:
    record_id: str
    episode_id: str | None
    y_30: bool | None
    y_60: bool | None
    y_180: bool | None
    time_to_a0_s: float | None
    a0_direction: str | None
    a0_reason_codes: tuple[str, ...]
    censor_reason: str | None


@dataclass(frozen=True, slots=True)
class AuditFinding:
    severity: str
    code: str
    record_id: str | None
    detail: str


def label_snapshots(
    rows: Sequence[PreA0SnapshotRow],
    events: Sequence[ConfirmedA0],
    *,
    session_end_by_date: dict[str, float],
) -> list[PreA0Label]:
    """Label each row only with events inside its declared horizon."""
    sorted_events = sorted(events, key=lambda event: event.occurred_at)
    output: list[PreA0Label] = []
    for row in rows:
        session_end = session_end_by_date.get(row.session_date)
        if session_end is None or not row.gap_complete:
            reason = "session_end_unknown" if session_end is None else "gap_or_stale"
            output.append(_censored(row, reason))
            continue
        matches = [
            event
            for event in sorted_events
            if event.symbol == row.symbol
            and event.direction == row.direction
            and 0 <= event.occurred_at - row.prediction_time <= max(HORIZONS)
        ]
        match = matches[0] if matches else None
        lead = match.occurred_at - row.prediction_time if match else None
        labels: dict[int, bool | None] = {}
        for horizon in HORIZONS:
            if row.prediction_time + horizon > session_end:
                labels[horizon] = None
            else:
                labels[horizon] = lead is not None and lead <= horizon
        censor_reason = "session_end" if any(value is None for value in labels.values()) else None
        output.append(
            PreA0Label(
                record_id=row.record_id,
                episode_id=row.episode_id,
                y_30=labels[30],
                y_60=labels[60],
                y_180=labels[180],
                time_to_a0_s=lead,
                a0_direction=match.direction if match else None,
                a0_reason_codes=match.reason_codes if match else (),
                censor_reason=censor_reason,
            )
        )
    return output


def _censored(row: PreA0SnapshotRow, reason: str) -> PreA0Label:
    return PreA0Label(row.record_id, row.episode_id, None, None, None, None, None, (), reason)


def audit_dataset(
    rows: Sequence[PreA0SnapshotRow],
    *,
    split_by_record: dict[str, str] | None = None,
) -> dict[str, Any]:
    findings: list[AuditFinding] = []
    counts = Counter(row.record_id for row in rows)
    for row in rows:
        if row.max_feature_time > row.prediction_time:
            findings.append(
                AuditFinding("critical", "future_feature", row.record_id, "feature time exceeds prediction time")
            )
        if row.schema_version != "pre-a0-snapshot-v1":
            findings.append(AuditFinding("critical", "schema_drift", row.record_id, row.schema_version))
        if not row.gap_complete:
            findings.append(AuditFinding("info", "known_gap", row.record_id, "row must remain censored"))
        if counts[row.record_id] > 1:
            findings.append(AuditFinding("critical", "duplicate_record", row.record_id, "record_id repeats"))
    if split_by_record:
        episode_splits: dict[str, set[str]] = {}
        for row in rows:
            if row.episode_id and row.record_id in split_by_record:
                episode_splits.setdefault(row.episode_id, set()).add(split_by_record[row.record_id])
        for episode_id, splits in episode_splits.items():
            if len(splits) > 1:
                findings.append(
                    AuditFinding("critical", "episode_split_leakage", None, f"{episode_id}: {sorted(splits)}")
                )
    critical = sum(finding.severity == "critical" for finding in findings)
    return {
        "audit_version": "pre-a0-audit-v1",
        "row_count": len(rows),
        "critical_count": critical,
        "passed": critical == 0,
        "missingness": _missingness(rows),
        "findings": [asdict(finding) for finding in findings],
    }


def _missingness(rows: Sequence[PreA0SnapshotRow]) -> dict[str, int]:
    return {
        "price_slope_15s": sum(row.price_slope_15s is None for row in rows),
        "volume_slope_15s": sum(row.volume_slope_15s is None for row in rows),
        "data_age_ms": sum(row.data_age_ms is None for row in rows),
    }


def build_walk_forward_manifest(
    rows: Sequence[PreA0SnapshotRow],
    *,
    code_revision: str,
    calibration_days: int = 1,
    test_days: int = 1,
    embargo_seconds: int = 180,
) -> dict[str, Any]:
    days = sorted({row.session_date for row in rows})
    minimum = calibration_days + test_days + 1
    if len(days) < minimum:
        raise ValueError(f"at least {minimum} complete days required")
    train_days = days[: -(calibration_days + test_days)]
    calibration = days[-(calibration_days + test_days) : -test_days]
    test = days[-test_days:]
    split_by_day = {day: "train" for day in train_days}
    split_by_day.update({day: "calibration" for day in calibration})
    split_by_day.update({day: "test" for day in test})
    assignments = {row.record_id: split_by_day[row.session_date] for row in rows}
    dataset_hash = hashlib.sha256(
        json.dumps([asdict(row) for row in sorted(rows, key=lambda item: item.record_id)], sort_keys=True).encode()
    ).hexdigest()
    split_hash = hashlib.sha256(
        json.dumps(assignments, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "split_version": "pre-a0-walk-forward-v1",
        "dataset_sha256": dataset_hash,
        "split_sha256": split_hash,
        "code_revision": code_revision,
        "purge_seconds": max(HORIZONS),
        "embargo_seconds": max(embargo_seconds, max(HORIZONS)),
        "days": {"train": train_days, "calibration": calibration, "test": test},
        "assignments": assignments,
        "final_test_sealed": True,
    }

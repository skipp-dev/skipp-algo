"""Record and aggregate a broker-free commercial shadow campaign.

Each invocation consumes one already-local PIT payload. It delegates signal
validation and audit creation to ``run_commercial_family_shadow``, stores an
immutable attempt record, then rebuilds a campaign report. The module has no
provider, network, or broker execution capability.
"""

from __future__ import annotations

import argparse
import json
import math
import secrets
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.build_commercial_family_setups import (
    FAMILY_VARIANTS,
    commercial_snapshot_id,
)
from scripts.run_commercial_family_shadow import (
    ExclusiveRunLock,
    parse_utc_datetime,
    read_shadow_audit,
    run_shadow_once,
)
from scripts.smc_atomic_write import atomic_write_json

_DEFAULT_MIN_UNIQUE_SNAPSHOTS = 20
_DEFAULT_MAX_FAILURE_RATE = 0.05
_DEFAULT_MAX_SOURCE_AGE_P95_SECONDS = 300.0
_DEFAULT_LOCK_STALE_SECONDS = 900
_ATTEMPT_SCHEMA_VERSION = 1
_REPORT_SCHEMA_VERSION = 1
_CONTRACT_SCHEMA_VERSION = 1
_ATTEMPT_STATUSES = frozenset({"COMPLETED", "FAILED", "NO_SETUPS", "REPLAY_SKIPPED"})


class CampaignObservationError(RuntimeError):
    """Raised after a failed observation has been durably recorded."""


def _normalise_now(now: datetime | None) -> datetime:
    instant = now if now is not None else datetime.now(UTC)
    if instant.tzinfo is None:
        return instant.replace(tzinfo=UTC)
    return instant.astimezone(UTC)


def _attempt_path(campaign_dir: Path, now: datetime) -> tuple[str, Path]:
    attempt_id = f"{now.strftime('%Y%m%dT%H%M%S%fZ')}-{secrets.token_hex(8)}"
    return attempt_id, campaign_dir / "attempts" / f"{attempt_id}.json"


def _load_attempts(campaign_dir: Path) -> list[dict[str, Any]]:
    attempts_dir = campaign_dir / "attempts"
    if not attempts_dir.exists():
        return []
    attempts: list[dict[str, Any]] = []
    for path in sorted(attempts_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid campaign attempt JSON: {path}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"campaign attempt must be an object: {path}")
        if payload.get("schema_version") != _ATTEMPT_SCHEMA_VERSION:
            raise ValueError(f"unsupported campaign attempt schema: {path}")
        if payload.get("attempt_id") != path.stem:
            raise ValueError(f"campaign attempt ID does not match filename: {path}")
        status = payload.get("status")
        if status not in _ATTEMPT_STATUSES:
            raise ValueError(f"campaign attempt has unsupported status: {path}")
        parse_utc_datetime(payload.get("observed_at"), label="attempt.observed_at")
        processing_seconds = payload.get("processing_seconds")
        if (
            isinstance(processing_seconds, bool)
            or not isinstance(processing_seconds, (int, float))
            or not math.isfinite(float(processing_seconds))
            or float(processing_seconds) < 0
        ):
            raise ValueError(f"campaign attempt has invalid processing_seconds: {path}")
        source_age_seconds = payload.get("source_age_seconds")
        if source_age_seconds is not None and (
            isinstance(source_age_seconds, bool)
            or not isinstance(source_age_seconds, (int, float))
            or not math.isfinite(float(source_age_seconds))
        ):
            raise ValueError(f"campaign attempt has invalid source_age_seconds: {path}")
        if source_age_seconds is None and status != "FAILED":
            raise ValueError(f"campaign attempt is missing source_age_seconds: {path}")
        snapshot_id = payload.get("source_snapshot_id")
        if status != "FAILED" and (not isinstance(snapshot_id, str) or not snapshot_id.startswith("sha256:")):
            raise ValueError(f"campaign attempt has invalid source snapshot ID: {path}")
        families = payload.get("families")
        expected_families = list(FAMILY_VARIANTS) if status in {"COMPLETED", "REPLAY_SKIPPED"} else []
        if families != expected_families:
            raise ValueError(f"campaign attempt has invalid families: {path}")
        error_type = payload.get("error_type")
        error = payload.get("error")
        if status == "FAILED":
            if not isinstance(error_type, str) or not error_type:
                raise ValueError(f"failed campaign attempt has no error type: {path}")
            if not isinstance(error, str) or not error:
                raise ValueError(f"failed campaign attempt has no error: {path}")
        elif error_type is not None or error is not None:
            raise ValueError(f"successful campaign attempt records an error: {path}")
        if payload.get("network_io") is not False or payload.get("broker_io") is not False:
            raise ValueError(f"campaign attempt violates broker-free contract: {path}")
        if payload.get("paper_orders_placed") != 0:
            raise ValueError(f"campaign attempt records paper orders: {path}")
        attempts.append(payload)
    return attempts


def _validate_thresholds(
    *,
    min_unique_snapshots: int,
    max_failure_rate: float,
    max_source_age_p95_seconds: float,
) -> None:
    if isinstance(min_unique_snapshots, bool) or min_unique_snapshots <= 0:
        raise ValueError("min_unique_snapshots must be positive")
    if isinstance(max_failure_rate, bool) or not math.isfinite(max_failure_rate) or not 0 <= max_failure_rate <= 1:
        raise ValueError("max_failure_rate must be finite and in [0, 1]")
    if (
        isinstance(max_source_age_p95_seconds, bool)
        or not math.isfinite(max_source_age_p95_seconds)
        or max_source_age_p95_seconds < 0
    ):
        raise ValueError("max_source_age_p95_seconds must be finite and non-negative")


def _campaign_contract(
    *,
    quantity: int,
    stop_buffer_bps: float,
    rr_target: float,
    max_event_age_seconds: int | None,
    max_setup_age_seconds: int,
    min_unique_snapshots: int,
    max_failure_rate: float,
    max_source_age_p95_seconds: float,
) -> dict[str, Any]:
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise ValueError("quantity must be a positive integer")
    if isinstance(stop_buffer_bps, bool) or not math.isfinite(stop_buffer_bps) or not 0 < stop_buffer_bps < 1_000:
        raise ValueError("stop_buffer_bps must be finite and in (0, 1000)")
    if isinstance(rr_target, bool) or not math.isfinite(rr_target) or rr_target <= 0:
        raise ValueError("rr_target must be finite and positive")
    if max_event_age_seconds is not None and (
        isinstance(max_event_age_seconds, bool)
        or not isinstance(max_event_age_seconds, int)
        or max_event_age_seconds < 0
    ):
        raise ValueError("max_event_age_seconds must be a non-negative integer")
    if (
        isinstance(max_setup_age_seconds, bool)
        or not isinstance(max_setup_age_seconds, int)
        or max_setup_age_seconds < 0
    ):
        raise ValueError("max_setup_age_seconds must be a non-negative integer")
    _validate_thresholds(
        min_unique_snapshots=min_unique_snapshots,
        max_failure_rate=max_failure_rate,
        max_source_age_p95_seconds=max_source_age_p95_seconds,
    )
    return {
        "schema_version": _CONTRACT_SCHEMA_VERSION,
        "campaign_mode": "audit_only_shadow",
        "decision_contract": {
            "quantity": quantity,
            "stop_buffer_bps": float(stop_buffer_bps),
            "rr_target": float(rr_target),
            "max_event_age_seconds": max_event_age_seconds,
            "max_setup_age_seconds": max_setup_age_seconds,
        },
        "observation_thresholds": {
            "min_unique_snapshots": min_unique_snapshots,
            "max_failure_rate": float(max_failure_rate),
            "max_source_age_p95_seconds": float(max_source_age_p95_seconds),
        },
        "network_io": False,
        "broker_io": False,
    }


def _read_campaign_contract(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid campaign contract JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"campaign contract must be an object: {path}")
    if payload.get("schema_version") != _CONTRACT_SCHEMA_VERSION:
        raise ValueError(f"unsupported campaign contract schema: {path}")
    return payload


def _ensure_campaign_contract(campaign_dir: Path, expected: dict[str, Any]) -> None:
    path = campaign_dir / "campaign_contract.json"
    if path.exists():
        if _read_campaign_contract(path) != expected:
            raise ValueError(
                "campaign contract drift; start a new campaign directory for "
                "different decision parameters or observation thresholds"
            )
        return
    attempts_dir = campaign_dir / "attempts"
    audit_path = campaign_dir / "audit" / "incubation_audit.jsonl"
    if any(attempts_dir.glob("*.json")) or (audit_path.exists() and audit_path.stat().st_size > 0):
        raise ValueError("campaign contract is missing from an existing campaign")
    atomic_write_json(expected, path, indent=2, sort_keys=True, fsync=True)


def _numeric_summary(values: list[float]) -> dict[str, float | int | None]:
    finite = sorted(value for value in values if math.isfinite(value))
    if not finite:
        return {"count": 0, "min": None, "p50": None, "p95": None, "max": None}
    middle = len(finite) // 2
    p50 = finite[middle] if len(finite) % 2 else (finite[middle - 1] + finite[middle]) / 2.0
    p95_index = max(0, math.ceil(0.95 * len(finite)) - 1)
    return {
        "count": len(finite),
        "min": finite[0],
        "p50": p50,
        "p95": finite[p95_index],
        "max": finite[-1],
    }


def _audit_integrity(
    audit_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, int]]:
    expected_families = set(FAMILY_VARIANTS)
    seen: Counter[tuple[str, str]] = Counter()
    family_snapshots: dict[str, set[str]] = {family: set() for family in FAMILY_VARIANTS}
    audited_snapshots: set[str] = set()
    invalid_rows = 0
    for row in audit_rows:
        snapshot_id = row.get("source_snapshot_id")
        intent_id = row.get("intent_id")
        family = row.get("family")
        if (
            row.get("action") != "audit_only"
            or not isinstance(snapshot_id, str)
            or not snapshot_id.startswith("sha256:")
            or not isinstance(intent_id, str)
            or not intent_id
            or family not in expected_families
        ):
            invalid_rows += 1
            continue
        seen[(snapshot_id, intent_id)] += 1
        audited_snapshots.add(snapshot_id)
        family_snapshots[str(family)].add(snapshot_id)
    duplicate_rows = sum(count - 1 for count in seen.values() if count > 1)
    integrity = {
        "audit_rows": len(audit_rows),
        "valid_audit_rows": sum(seen.values()),
        "invalid_audit_rows": invalid_rows,
        "duplicate_snapshot_intent_rows": duplicate_rows,
        "unique_audited_snapshots": len(audited_snapshots),
        "unique_audited_intents": len(seen),
    }
    counts = {family: len(snapshot_ids) for family, snapshot_ids in family_snapshots.items()}
    return integrity, counts


def build_campaign_report(
    campaign_dir: Path,
    *,
    generated_at: datetime | None = None,
    min_unique_snapshots: int = _DEFAULT_MIN_UNIQUE_SNAPSHOTS,
    max_failure_rate: float = _DEFAULT_MAX_FAILURE_RATE,
    max_source_age_p95_seconds: float = _DEFAULT_MAX_SOURCE_AGE_P95_SECONDS,
) -> dict[str, Any]:
    """Rebuild aggregate campaign evidence from attempts and audit rows."""
    _validate_thresholds(
        min_unique_snapshots=min_unique_snapshots,
        max_failure_rate=max_failure_rate,
        max_source_age_p95_seconds=max_source_age_p95_seconds,
    )

    contract_path = campaign_dir / "campaign_contract.json"
    contract = _read_campaign_contract(contract_path) if contract_path.exists() else None
    expected_thresholds = {
        "min_unique_snapshots": min_unique_snapshots,
        "max_failure_rate": float(max_failure_rate),
        "max_source_age_p95_seconds": float(max_source_age_p95_seconds),
    }
    if contract is not None and contract.get("observation_thresholds") != expected_thresholds:
        raise ValueError("campaign report thresholds differ from the campaign contract")

    now = _normalise_now(generated_at)
    attempts = _load_attempts(campaign_dir)
    audit_rows = read_shadow_audit(campaign_dir / "audit" / "incubation_audit.jsonl")
    if contract is None and (attempts or audit_rows):
        raise ValueError("campaign contract is missing from an existing campaign")
    status_counts = Counter(str(row.get("status", "UNKNOWN")) for row in attempts)
    failure_types = Counter(str(row.get("error_type", "unknown")) for row in attempts if row.get("status") == "FAILED")
    attempt_snapshot_ids = {
        str(row["source_snapshot_id"]) for row in attempts if isinstance(row.get("source_snapshot_id"), str)
    }
    substantive_attempts = [row for row in attempts if row.get("status") != "REPLAY_SKIPPED"]
    source_age = _numeric_summary(
        [
            float(row["source_age_seconds"])
            for row in substantive_attempts
            if isinstance(row.get("source_age_seconds"), (int, float))
            and not isinstance(row.get("source_age_seconds"), bool)
        ]
    )
    processing = _numeric_summary(
        [
            float(row["processing_seconds"])
            for row in substantive_attempts
            if isinstance(row.get("processing_seconds"), (int, float))
            and not isinstance(row.get("processing_seconds"), bool)
        ]
    )
    integrity, family_snapshot_counts = _audit_integrity(audit_rows)
    audited_count = int(integrity["unique_audited_snapshots"])
    family_coverage_pct = {
        family: 100.0 * count / audited_count if audited_count else 0.0
        for family, count in family_snapshot_counts.items()
    }
    failure_rate = status_counts["FAILED"] / len(substantive_attempts) if substantive_attempts else 0.0

    hard_failures: list[str] = []
    if integrity["invalid_audit_rows"]:
        hard_failures.append("invalid_audit_rows")
    if integrity["duplicate_snapshot_intent_rows"]:
        hard_failures.append("duplicate_snapshot_intent_rows")
    pending_reasons: list[str] = []
    if audited_count < min_unique_snapshots:
        pending_reasons.append("insufficient_unique_audited_snapshots")
    missing_families = [family for family, count in family_snapshot_counts.items() if count == 0]
    threshold_failures: list[str] = []
    if failure_rate > max_failure_rate:
        threshold_failures.append("failure_rate_exceeded")
    if source_age["p95"] is None:
        threshold_failures.append("source_age_p95_unknown")
    elif float(source_age["p95"]) > max_source_age_p95_seconds:
        threshold_failures.append("source_age_p95_exceeded")
    if source_age["min"] is not None and float(source_age["min"]) < 0:
        threshold_failures.append("future_source_timestamp_observed")
    if missing_families:
        threshold_failures.append("missing_family_coverage")

    if hard_failures:
        observation_verdict = "FAIL"
        observation_reasons = hard_failures
    elif pending_reasons:
        observation_verdict = "PENDING"
        observation_reasons = pending_reasons
    elif threshold_failures:
        observation_verdict = "FAIL"
        observation_reasons = threshold_failures
    else:
        observation_verdict = "PASS"
        observation_reasons = []

    observed_values = sorted(str(row["observed_at"]) for row in attempts if isinstance(row.get("observed_at"), str))
    return {
        "schema_version": _REPORT_SCHEMA_VERSION,
        "campaign_mode": "audit_only_shadow",
        "campaign_contract": contract,
        "generated_at": now.isoformat(),
        "attempts_total": len(attempts),
        "substantive_attempts_total": len(substantive_attempts),
        "attempt_status_counts": dict(sorted(status_counts.items())),
        "unique_attempted_snapshots": len(attempt_snapshot_ids),
        "first_observed_at": observed_values[0] if observed_values else None,
        "last_observed_at": observed_values[-1] if observed_values else None,
        "failure_rate": failure_rate,
        "failures_by_type": dict(sorted(failure_types.items())),
        "source_age_seconds": source_age,
        "processing_seconds": processing,
        "audit_integrity": integrity,
        "family_snapshot_counts": family_snapshot_counts,
        "family_coverage_pct": family_coverage_pct,
        "observation_gate": {
            "verdict": observation_verdict,
            "reasons": observation_reasons,
            "current_threshold_warnings": (threshold_failures if observation_verdict == "PENDING" else []),
            "missing_families": missing_families,
            "thresholds": {
                "min_unique_snapshots": min_unique_snapshots,
                "max_failure_rate": max_failure_rate,
                "max_source_age_p95_seconds": max_source_age_p95_seconds,
            },
        },
        "promotion_gate": {
            "verdict": "NO_GO",
            "reasons": [
                "audit_only_campaign_has_no_closed_paper_outcomes",
                "broker_submission_not_exercised",
                "manual_review_not_completed",
            ],
        },
        "network_io": False,
        "broker_io": False,
        "paper_orders_placed": 0,
    }


def run_campaign_observation(
    *,
    payload: dict[str, Any],
    campaign_dir: Path,
    now: datetime | None = None,
    quantity: int = 1,
    stop_buffer_bps: float = 10.0,
    rr_target: float = 2.0,
    max_event_age_seconds: int | None = None,
    max_setup_age_seconds: int = 300,
    min_unique_snapshots: int = _DEFAULT_MIN_UNIQUE_SNAPSHOTS,
    max_failure_rate: float = _DEFAULT_MAX_FAILURE_RATE,
    max_source_age_p95_seconds: float = _DEFAULT_MAX_SOURCE_AGE_P95_SECONDS,
    lock_stale_seconds: int = _DEFAULT_LOCK_STALE_SECONDS,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run one local observation and durably refresh campaign evidence."""
    run_now = _normalise_now(now)
    attempt_id, attempt_path = _attempt_path(campaign_dir, run_now)
    started = time.monotonic()
    failure: BaseException | None = None
    snapshot_id: str | None = None
    source_asof_ts: float | None = None
    source_age_seconds: float | None = None
    manifest: dict[str, Any] | None = None
    contract = _campaign_contract(
        quantity=quantity,
        stop_buffer_bps=stop_buffer_bps,
        rr_target=rr_target,
        max_event_age_seconds=max_event_age_seconds,
        max_setup_age_seconds=max_setup_age_seconds,
        min_unique_snapshots=min_unique_snapshots,
        max_failure_rate=max_failure_rate,
        max_source_age_p95_seconds=max_source_age_p95_seconds,
    )

    with ExclusiveRunLock(
        campaign_dir / ".campaign.lock",
        stale_seconds=lock_stale_seconds,
    ):
        _ensure_campaign_contract(campaign_dir, contract)
        if attempt_path.exists():
            raise RuntimeError(f"campaign attempt already exists: {attempt_path}")
        try:
            snapshot_id = commercial_snapshot_id(payload)
            source_asof = parse_utc_datetime(payload.get("as_of"), label="input.as_of")
            source_asof_ts = source_asof.timestamp()
            source_age_seconds = run_now.timestamp() - source_asof_ts
            snapshot_dir = campaign_dir / "snapshots" / snapshot_id[7:]
            manifest = run_shadow_once(
                payload=payload,
                setups_path=snapshot_dir / "setups.json",
                gate_status_path=snapshot_dir / "gates.json",
                diagnostics_path=snapshot_dir / "diagnostics.json",
                audit_path=campaign_dir / "audit" / "incubation_audit.jsonl",
                manifest_path=snapshot_dir / "latest_manifest.json",
                now=run_now,
                quantity=quantity,
                stop_buffer_bps=stop_buffer_bps,
                rr_target=rr_target,
                max_event_age_seconds=max_event_age_seconds,
                max_setup_age_seconds=max_setup_age_seconds,
                lock_stale_seconds=lock_stale_seconds,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            failure = exc

        if failure is None and manifest is None:
            failure = RuntimeError("shadow observation returned no manifest")
        attempt = {
            "schema_version": _ATTEMPT_SCHEMA_VERSION,
            "attempt_id": attempt_id,
            "observed_at": run_now.isoformat(),
            "source_snapshot_id": snapshot_id,
            "source_asof_ts": source_asof_ts,
            "source_age_seconds": source_age_seconds,
            "processing_seconds": time.monotonic() - started,
            "status": "FAILED" if failure is not None else manifest["status"],
            "families": [] if manifest is None else manifest["families"],
            "error_type": None if failure is None else type(failure).__name__,
            "error": None if failure is None else str(failure),
            "network_io": False,
            "broker_io": False,
            "paper_orders_placed": 0,
        }
        atomic_write_json(
            attempt,
            attempt_path,
            indent=2,
            sort_keys=True,
            fsync=True,
        )
        report = build_campaign_report(
            campaign_dir,
            generated_at=run_now,
            min_unique_snapshots=min_unique_snapshots,
            max_failure_rate=max_failure_rate,
            max_source_age_p95_seconds=max_source_age_p95_seconds,
        )
        atomic_write_json(
            report,
            campaign_dir / "campaign_report.json",
            indent=2,
            sort_keys=True,
            fsync=True,
        )

    if failure is not None:
        raise CampaignObservationError(str(failure)) from failure
    return attempt, report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Record one local commercial-family shadow campaign observation; "
            "the command cannot perform provider, network, or broker I/O."
        )
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--quantity", type=int, default=1)
    parser.add_argument("--stop-buffer-bps", type=float, default=10.0)
    parser.add_argument("--rr-target", type=float, default=2.0)
    parser.add_argument("--max-event-age-seconds", type=int)
    parser.add_argument("--max-setup-age-seconds", type=int, default=300)
    parser.add_argument(
        "--min-unique-snapshots",
        type=int,
        default=_DEFAULT_MIN_UNIQUE_SNAPSHOTS,
    )
    parser.add_argument(
        "--max-failure-rate",
        type=float,
        default=_DEFAULT_MAX_FAILURE_RATE,
    )
    parser.add_argument(
        "--max-source-age-p95-seconds",
        type=float,
        default=_DEFAULT_MAX_SOURCE_AGE_P95_SECONDS,
    )
    parser.add_argument(
        "--lock-stale-seconds",
        type=int,
        default=_DEFAULT_LOCK_STALE_SECONDS,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("input root must be a JSON object")
        attempt, report = run_campaign_observation(
            payload=payload,
            campaign_dir=args.campaign_dir,
            quantity=args.quantity,
            stop_buffer_bps=args.stop_buffer_bps,
            rr_target=args.rr_target,
            max_event_age_seconds=args.max_event_age_seconds,
            max_setup_age_seconds=args.max_setup_age_seconds,
            min_unique_snapshots=args.min_unique_snapshots,
            max_failure_rate=args.max_failure_rate,
            max_source_age_p95_seconds=args.max_source_age_p95_seconds,
            lock_stale_seconds=args.lock_stale_seconds,
        )
    except (
        OSError,
        CampaignObservationError,
        RuntimeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"attempt": attempt, "report": report}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

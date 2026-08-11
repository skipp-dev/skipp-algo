"""Run one broker-free, replay-safe commercial-family shadow observation.

The orchestrator owns a dedicated audit path. It transforms one point-in-time
market snapshot into the four commercial family setups, runs the strict PAPER
evidence boundary with the audit-only submitter, and records a restart-repairable
manifest. It has no network or broker execution option.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import secrets
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from scripts.build_commercial_family_setups import build_commercial_family_setups
from scripts.live_risk_limits import AccountState, RiskLimits
from scripts.run_smc_live_incubation import run_live_incubation
from scripts.smc_atomic_write import atomic_write_json, atomic_write_text
from scripts.smc_to_ibkr_adapter import (
    PHASE_B_RECOMMENDED_SIZE_SCALE,
    IBKRExecutionConfig,
    build_ibkr_intents_from_smc_setups,
)

_LOCK_STALE_SECONDS = 900


def parse_utc_datetime(value: object, *, label: str) -> datetime:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be epoch seconds or an ISO timestamp")
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if not math.isfinite(timestamp) or timestamp <= 0:
            raise ValueError(f"{label} must be a finite positive timestamp")
        try:
            instant = datetime.fromtimestamp(timestamp, UTC)
        except (OSError, OverflowError) as exc:
            raise ValueError(f"{label} is outside the supported range") from exc
    elif isinstance(value, str):
        text = value.strip()
        try:
            timestamp = float(text)
        except ValueError:
            instant = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if instant.tzinfo is None:
                instant = instant.replace(tzinfo=UTC)
            instant = instant.astimezone(UTC)
        else:
            if not math.isfinite(timestamp) or timestamp <= 0:
                raise ValueError(f"{label} must be a finite positive timestamp")
            try:
                instant = datetime.fromtimestamp(timestamp, UTC)
            except (OSError, OverflowError) as exc:
                raise ValueError(f"{label} is outside the supported range") from exc
    else:
        raise ValueError(f"{label} must be epoch seconds or an ISO timestamp")
    if not math.isfinite(instant.timestamp()) or instant.timestamp() <= 0:
        raise ValueError(f"{label} must be a positive timestamp")
    return instant


def read_shadow_audit(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"audit JSONL {path} has invalid line {line_number}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"audit JSONL {path} line {line_number} must be an object")
        records.append(record)
    return records


class ExclusiveRunLock:
    """Portable O_EXCL lease with conservative stale-lock recovery."""

    def __init__(self, path: Path, *, stale_seconds: int) -> None:
        if isinstance(stale_seconds, bool) or stale_seconds <= 0:
            raise ValueError("lock_stale_seconds must be positive")
        self.path = path
        self.stale_seconds = stale_seconds
        self.token = secrets.token_hex(16)

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "token": self.token,
            "pid": os.getpid(),
            "created_at_ts": datetime.now(UTC).timestamp(),
        }

    def _create(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(
            self.path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        try:
            encoded = json.dumps(self._payload(), sort_keys=True).encode("utf-8")
            offset = 0
            while offset < len(encoded):
                written = os.write(fd, encoded[offset:])
                if written <= 0:
                    raise OSError("commercial shadow lock write made no progress")
                offset += written
            os.fsync(fd)
        except BaseException:
            self.path.unlink(missing_ok=True)
            raise
        finally:
            os.close(fd)

    def _recover_if_stale(self) -> bool:
        try:
            observed = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return False
        if not isinstance(observed, dict):
            return False
        observed_token = observed.get("token")
        created_at = observed.get("created_at_ts")
        if (
            not isinstance(observed_token, str)
            or isinstance(created_at, bool)
            or not isinstance(created_at, (int, float))
            or not math.isfinite(float(created_at))
        ):
            return False
        age = datetime.now(UTC).timestamp() - float(created_at)
        if age <= self.stale_seconds:
            return False
        try:
            current = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return False
        if not isinstance(current, dict) or current.get("token") != observed_token:
            return False
        self.path.unlink(missing_ok=True)
        return True

    def __enter__(self) -> ExclusiveRunLock:
        try:
            self._create()
        except FileExistsError:
            if not self._recover_if_stale():
                raise RuntimeError(f"commercial shadow run already locked: {self.path}") from None
            try:
                self._create()
            except FileExistsError as exc:
                raise RuntimeError(f"commercial shadow lock raced during recovery: {self.path}") from exc
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        try:
            current = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return
        if isinstance(current, dict) and current.get("token") == self.token:
            self.path.unlink(missing_ok=True)


def _manifest(
    *,
    status: str,
    now: datetime,
    snapshot_id: str,
    source_asof_ts: float,
    setups: list[dict[str, Any]],
    audit_rows: list[dict[str, Any]],
    runner_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "orchestrator_mode": "audit_only_shadow",
        "status": status,
        "observed_at": now.astimezone(UTC).isoformat(),
        "source_snapshot_id": snapshot_id,
        "source_asof_ts": source_asof_ts,
        "families": [setup["family"] for setup in setups],
        "expected_intent_ids": [setup["order_ref"] for setup in setups],
        "audit_records_for_snapshot": len(audit_rows),
        "audit_actions": sorted({str(row.get("action", "")) for row in audit_rows}),
        "runner_summary": runner_summary,
        "network_io": False,
        "broker_io": False,
        "paper_orders_placed": 0,
    }


def _matching_snapshot_rows(
    audit_path: Path,
    snapshot_id: str,
) -> list[dict[str, Any]]:
    return [row for row in read_shadow_audit(audit_path) if row.get("source_snapshot_id") == snapshot_id]


def _is_complete_replay(
    rows: list[dict[str, Any]],
    expected_by_intent_id: dict[str, dict[str, Any]],
) -> bool:
    if len(rows) != len(expected_by_intent_id):
        return False
    seen: set[str] = set()
    for row in rows:
        intent_id = row.get("intent_id")
        if not isinstance(intent_id, str) or not intent_id or intent_id in seen:
            return False
        expected = expected_by_intent_id.get(intent_id)
        if expected is None or any(row.get(key) != value for key, value in expected.items()):
            return False
        seen.add(intent_id)
    return seen == set(expected_by_intent_id)


def _expected_audit_contract(
    setups: list[dict[str, Any]],
    execution_cfg: IBKRExecutionConfig,
) -> dict[str, dict[str, Any]]:
    intents = build_ibkr_intents_from_smc_setups(
        setups,
        execution_cfg,
        size_scale=PHASE_B_RECOMMENDED_SIZE_SCALE,
    )
    if len(intents) != len(setups):
        raise ValueError("commercial snapshot did not map one setup to one intent")
    expected: dict[str, dict[str, Any]] = {}
    for setup, intent in zip(setups, intents, strict=True):
        if intent.order_ref in expected:
            raise ValueError("commercial snapshot emitted duplicate order_ref values")
        expected[intent.order_ref] = {
            "action": "audit_only",
            "variant": setup["variant"],
            "family": setup["family"],
            "symbol": intent.symbol,
            "entry_price": float(intent.entry_limit),
            "stop_loss": float(intent.stop_loss),
            "take_profit": float(intent.take_profit),
            "quantity": int(intent.quantity),
            "source_event_id": setup["source_event_id"],
            "source_anchor_ts": setup["source_anchor_ts"],
            "source_asof_ts": setup["source_asof_ts"],
            "source_timeframe": setup["source_timeframe"],
            "source_snapshot_id": setup["source_snapshot_id"],
            "source_provenance": setup["source_provenance"],
        }
    return expected


def run_shadow_once(
    *,
    payload: dict[str, Any],
    setups_path: Path,
    gate_status_path: Path,
    diagnostics_path: Path,
    audit_path: Path,
    manifest_path: Path,
    now: datetime | None = None,
    quantity: int = 1,
    stop_buffer_bps: float = 10.0,
    rr_target: float = 2.0,
    max_event_age_seconds: int | None = None,
    max_setup_age_seconds: int = 300,
    lock_path: Path | None = None,
    lock_stale_seconds: int = _LOCK_STALE_SECONDS,
) -> dict[str, Any]:
    """Execute or safely replay one audit-only snapshot observation."""
    run_now = now if now is not None else datetime.now(UTC)
    if run_now.tzinfo is None:
        run_now = run_now.replace(tzinfo=UTC)
    else:
        run_now = run_now.astimezone(UTC)
    source_asof = parse_utc_datetime(payload.get("as_of"), label="input.as_of")
    trade_date = source_asof.date().isoformat()
    resolved_lock = lock_path or Path(f"{audit_path}.lock")

    with ExclusiveRunLock(resolved_lock, stale_seconds=lock_stale_seconds):
        setups, diagnostics = build_commercial_family_setups(
            payload,
            trade_date=trade_date,
            quantity=quantity,
            stop_buffer_bps=stop_buffer_bps,
            rr_target=rr_target,
            max_event_age_seconds=max_event_age_seconds,
        )
        snapshot_id = str(diagnostics["source_snapshot_id"])
        gates = {setup["variant"]: "amber" for setup in setups}
        atomic_write_text(
            json.dumps(setups, indent=2, sort_keys=True),
            setups_path,
            fsync=True,
        )
        atomic_write_json(gates, gate_status_path, sort_keys=True, fsync=True)
        atomic_write_json(
            diagnostics,
            diagnostics_path,
            indent=2,
            sort_keys=True,
            fsync=True,
        )

        execution_cfg = IBKRExecutionConfig()
        expected = _expected_audit_contract(setups, execution_cfg)
        existing = _matching_snapshot_rows(audit_path, snapshot_id)
        if existing:
            if not _is_complete_replay(existing, expected):
                raise ValueError("commercial snapshot has a partial or inconsistent audit; manual review required")
            manifest = _manifest(
                status="REPLAY_SKIPPED",
                now=run_now,
                snapshot_id=snapshot_id,
                source_asof_ts=source_asof.timestamp(),
                setups=setups,
                audit_rows=existing,
                runner_summary=None,
            )
            atomic_write_json(manifest, manifest_path, indent=2, sort_keys=True, fsync=True)
            return manifest

        if not setups:
            manifest = _manifest(
                status="NO_SETUPS",
                now=run_now,
                snapshot_id=snapshot_id,
                source_asof_ts=source_asof.timestamp(),
                setups=setups,
                audit_rows=[],
                runner_summary=None,
            )
            atomic_write_json(manifest, manifest_path, indent=2, sort_keys=True, fsync=True)
            return manifest

        account_state = AccountState(
            as_of=date.fromisoformat(trade_date),
            equity=100_000.0,
            starting_equity_today=100_000.0,
            high_water_mark=100_000.0,
            open_positions=0,
            gross_exposure_pct=0.0,
            last_n_pnls=(),
        )
        runner_summary = run_live_incubation(
            setup_records=setups,
            gate_status_by_variant=gates,
            risk_limits=RiskLimits(),
            account_state=account_state,
            execution_cfg=execution_cfg,
            audit_path=audit_path,
            phase="paper",
            size_scale=PHASE_B_RECOMMENDED_SIZE_SCALE,
            now=run_now,
            prospective_paper_pilot=True,
            max_setup_age_seconds=max_setup_age_seconds,
        )
        written = _matching_snapshot_rows(audit_path, snapshot_id)
        if not _is_complete_replay(written, expected):
            raise RuntimeError("commercial shadow audit did not commit the expected complete snapshot")
        manifest = _manifest(
            status="COMPLETED",
            now=run_now,
            snapshot_id=snapshot_id,
            source_asof_ts=source_asof.timestamp(),
            setups=setups,
            audit_rows=written,
            runner_summary=runner_summary,
        )
        atomic_write_json(manifest, manifest_path, indent=2, sort_keys=True, fsync=True)
        return manifest


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a restart-safe commercial-family audit-only shadow observation; "
            "the command cannot perform network or broker I/O."
        )
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--setups-output", type=Path, required=True)
    parser.add_argument("--gate-status-output", type=Path, required=True)
    parser.add_argument("--diagnostics-output", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    parser.add_argument("--quantity", type=int, default=1)
    parser.add_argument("--stop-buffer-bps", type=float, default=10.0)
    parser.add_argument("--rr-target", type=float, default=2.0)
    parser.add_argument("--max-event-age-seconds", type=int)
    parser.add_argument("--max-setup-age-seconds", type=int, default=300)
    parser.add_argument("--lock-stale-seconds", type=int, default=_LOCK_STALE_SECONDS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("input root must be a JSON object")
        manifest = run_shadow_once(
            payload=payload,
            setups_path=args.setups_output,
            gate_status_path=args.gate_status_output,
            diagnostics_path=args.diagnostics_output,
            audit_path=args.audit_output,
            manifest_path=args.manifest_output,
            quantity=args.quantity,
            stop_buffer_bps=args.stop_buffer_bps,
            rr_target=args.rr_target,
            max_event_age_seconds=args.max_event_age_seconds,
            max_setup_age_seconds=args.max_setup_age_seconds,
            lock_stale_seconds=args.lock_stale_seconds,
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

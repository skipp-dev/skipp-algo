#!/usr/bin/env python3
"""Reconcile receiver-ledger deliveries into the Hold Manager shadow observations.

This is the delivered-alert half of the R2 observation chain:

    TradingView server alerts
        -> hold_manager_shadow_receiver (per-event SQLite ledger)
        -> authenticated GET /tradingview/hold-manager-shadow/state
           (``sessions`` breakdown per US-market session date)
        -> THIS script: fill ``sessions[*].deliveredServerAlerts`` in
           ``smc_hold_manager_shadow_observations.json``
        -> scripts/evaluate_smc_hold_manager_shadow.py (expected == delivered)

The expected-alert side (Pine edges, exit-signal/strategy comparison, binding
checks) stays operator-recorded per the pre-registered protocol; this script
only replaces the previously manual — and therefore unverifiable — delivered
counts with the receiver ledger's numbers, fail-closed:

* the receiver state must carry the ``sessions`` breakdown (older receivers
  without it are rejected rather than silently treated as zero deliveries);
* receiver sessions that are not recorded in the observations are blockers
  (the operator must record or exclude the session, never drop deliveries);
* already-filled rows must match the ledger exactly (conflicts are blockers,
  never overwritten).

The operator fetches the state with the receiver token, e.g.::

    curl -sS -H "X-Hold-Manager-Shadow-Token: $TOKEN" \
        https://<host>/tradingview/hold-manager-shadow/state > state.json
    python -m scripts.reconcile_smc_hold_manager_shadow_deliveries \
        --state state.json
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_hold_manager_shadow_contract.json"
)
DEFAULT_OBSERVATIONS = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_hold_manager_shadow_observations.json"
)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _channel_counts(
    raw: object,
    channels: tuple[str, ...],
    blockers: list[str],
    label: str,
) -> dict[str, int]:
    counts = {channel: 0 for channel in channels}
    if not isinstance(raw, Mapping):
        blockers.append(f"{label}: missing alert-count object")
        return counts
    if set(raw) != set(channels):
        blockers.append(
            f"{label}: channels must exactly match {list(channels)!r}"
        )
        return counts
    for channel in channels:
        value = raw.get(channel)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            counts[channel] = value
        else:
            blockers.append(f"{label}.{channel}: expected non-negative integer")
    return counts


def reconcile_deliveries(
    contract: Mapping[str, Any],
    state: Mapping[str, Any],
    observations: dict[str, Any],
) -> dict[str, Any]:
    """Fill ``deliveredServerAlerts`` from the receiver state, fail-closed."""
    blockers: list[str] = []
    channels = tuple(contract["activationRequirements"]["holdAlertChannels"])
    market_timezone = contract["tradingView"]["marketTimezone"]

    for label, actual, expected in (
        ("state.schemaVersion", state.get("schemaVersion"), 1),
        (
            "state.requirementId",
            state.get("requirementId"),
            contract.get("requirementId"),
        ),
        (
            "observations.requirementId",
            observations.get("requirementId"),
            contract.get("requirementId"),
        ),
        ("state.marketTimezone", state.get("marketTimezone"), market_timezone),
    ):
        if actual != expected:
            blockers.append(f"{label}: expected {expected!r}, observed {actual!r}")

    state_sessions = state.get("sessions")
    if not isinstance(state_sessions, list):
        blockers.append(
            "state.sessions: missing session breakdown — the deployed receiver "
            "predates the per-session state and must be redeployed first"
        )
        state_sessions = []

    ledger_by_date: dict[str, dict[str, dict[str, int]]] = {}
    for index, row in enumerate(state_sessions, start=1):
        prefix = f"state.sessions[{index}]"
        if not isinstance(row, Mapping):
            blockers.append(f"{prefix}: expected an object")
            continue
        session_date = row.get("sessionDate")
        try:
            date.fromisoformat(session_date)
        except (TypeError, ValueError):
            blockers.append(f"{prefix}.sessionDate: expected ISO calendar date")
            continue
        if session_date in ledger_by_date:
            blockers.append(f"{prefix}.sessionDate: duplicate date {session_date}")
            continue
        ledger_by_date[session_date] = {
            "delivered": _channel_counts(
                row.get("uniqueByChannel"),
                channels,
                blockers,
                f"{prefix}.uniqueByChannel",
            ),
            "duplicates": _channel_counts(
                row.get("duplicatesByChannel"),
                channels,
                blockers,
                f"{prefix}.duplicatesByChannel",
            ),
        }

    rows_raw = observations.get("sessions")
    rows = rows_raw if isinstance(rows_raw, list) else []
    if rows_raw is None or not isinstance(rows_raw, list):
        blockers.append("observations.sessions: expected an array")

    filled = 0
    confirmed = 0
    observed_dates: set[str] = set()
    for index, row in enumerate(rows, start=1):
        prefix = f"observations.sessions[{index}]"
        if not isinstance(row, dict):
            blockers.append(f"{prefix}: expected an object")
            continue
        session_date = row.get("sessionDate")
        try:
            date.fromisoformat(session_date)
        except (TypeError, ValueError):
            blockers.append(f"{prefix}.sessionDate: expected ISO calendar date")
            continue
        observed_dates.add(session_date)
        ledger = ledger_by_date.get(session_date)
        delivered = (
            ledger["delivered"]
            if ledger is not None
            else {channel: 0 for channel in channels}
        )
        duplicates = (
            ledger["duplicates"]
            if ledger is not None
            else {channel: 0 for channel in channels}
        )
        existing = row.get("deliveredServerAlerts")
        if existing is not None:
            recorded = _channel_counts(
                existing, channels, blockers, f"{prefix}.deliveredServerAlerts"
            )
            if recorded != delivered:
                blockers.append(
                    f"{prefix}.deliveredServerAlerts: recorded {recorded!r} "
                    f"conflicts with receiver ledger {delivered!r}"
                )
                continue
            confirmed += 1
        else:
            filled += 1
        row["deliveredServerAlerts"] = delivered
        row["deliveredServerAlertsSource"] = "receiver_ledger"
        row["receiverDuplicateDeliveries"] = duplicates

    for session_date in sorted(set(ledger_by_date) - observed_dates):
        blockers.append(
            f"receiver ledger has deliveries on {session_date} but the "
            "observations record no such session — record or exclude it"
        )

    return {
        "schemaVersion": 1,
        "requirementId": contract.get("requirementId"),
        "verdict": "reconciled" if not blockers else "blocked",
        "sessionsFilled": filled,
        "sessionsConfirmed": confirmed,
        "receiverSessionCount": len(ledger_by_date),
        "blockers": blockers,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument(
        "--observations", type=Path, default=DEFAULT_OBSERVATIONS
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify only; never write the observations file",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    observations = _load_json(args.observations)
    result = reconcile_deliveries(
        _load_json(args.contract),
        _load_json(args.state),
        observations,
    )
    if result["verdict"] == "reconciled" and not args.check:
        atomic_write_text(
            json.dumps(observations, indent=2) + "\n",
            args.observations,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["verdict"] == "reconciled" else 2


if __name__ == "__main__":
    raise SystemExit(main())

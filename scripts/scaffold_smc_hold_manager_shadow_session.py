#!/usr/bin/env python3
"""Scaffold one Hold Manager R2 shadow session row for operator completion.

Appends the next session row (in activation order) to
``smc_hold_manager_shadow_observations.json``: the pre-registered identity
constants (market timezone, layout, source hash, producer, BUS schema) come
from the contract; every field that requires a TradingView-side observation is
written as ``null`` so the evaluator keeps blocking until the operator fills
it. The delivered side stays absent — it is reconciled from the receiver
ledger by ``scripts/reconcile_smc_hold_manager_shadow_deliveries.py``.

Fail-closed refusals (exit 2): no recorded activation yet, duplicate date,
date before the first evaluable session, or out-of-order recording.

Landing checklist printed on success: complete the null fields, run the
reconcile (without ``--check``), re-run the evaluator, and move the pinned
checked-in-state test expectations in the same PR.
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

# Every TradingView-side fact the pre-registered protocol assigns to the
# operator; scaffolded as null so the evaluator enumerates them as blockers.
OPERATOR_FIELDS = (
    "completeUsMarketSession",
    "exclusionReason",
    "bindingStatus",
    "activeActionableExitModes",
    "exitSignalCompared",
    "strategyCompared",
    "runtimeErrorCount",
    "falseExitAlertCount",
    "duplicateActionableExitAlertCount",
    "unclassifiedTransitionDifferenceCount",
    "expectedServerAlerts",
)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def scaffold_session(
    contract: Mapping[str, Any],
    observations: dict[str, Any],
    session_date: str,
) -> dict[str, Any]:
    """Append the next session row; return a fail-closed summary."""
    blockers: list[str] = []

    try:
        date.fromisoformat(session_date)
    except (TypeError, ValueError):
        blockers.append(f"sessionDate {session_date!r}: expected ISO calendar date")

    if observations.get("requirementId") != contract.get("requirementId"):
        blockers.append("observations.requirementId does not match the contract")

    activation = observations.get("activation")
    if not isinstance(activation, Mapping):
        blockers.append(
            "activation is not recorded — sessions may only be scaffolded "
            "after the shadow activation"
        )
        activation = {}

    first_evaluable = activation.get("firstEvaluableSessionDate")
    if (
        not blockers
        and isinstance(first_evaluable, str)
        and session_date < first_evaluable
    ):
        blockers.append(
            f"sessionDate {session_date} precedes the first evaluable "
            f"session {first_evaluable}"
        )

    rows_raw = observations.get("sessions")
    rows = rows_raw if isinstance(rows_raw, list) else []
    if not isinstance(rows_raw, list):
        blockers.append("observations.sessions: expected an array")

    recorded_dates = [
        row.get("sessionDate") for row in rows if isinstance(row, Mapping)
    ]
    if session_date in recorded_dates:
        blockers.append(f"session {session_date} is already recorded")
    if not blockers and recorded_dates and max(recorded_dates) > session_date:
        blockers.append(
            f"sessions must be recorded in order: {session_date} is earlier "
            f"than the already-recorded {max(recorded_dates)}"
        )

    if blockers:
        return {
            "verdict": "refused",
            "sessionDate": session_date,
            "blockers": blockers,
        }

    trading_view = contract["tradingView"]
    row: dict[str, Any] = {
        "activationSequence": len(rows) + 1,
        "sessionDate": session_date,
        "marketTimezone": trading_view["marketTimezone"],
        "layout": trading_view["validationLayout"],
        "sourceSha256": contract["source"]["sha256"],
        "producer": trading_view["producer"],
        "busSchema": trading_view["busSchema"],
    }
    for field in OPERATOR_FIELDS:
        row[field] = None
    rows.append(row)
    observations["sessions"] = rows

    return {
        "verdict": "scaffolded",
        "sessionDate": session_date,
        "activationSequence": row["activationSequence"],
        "operatorTodo": list(OPERATOR_FIELDS),
        "landingChecklist": [
            "Fill every operatorTodo field from the TradingView-side observation.",
            "Run scripts/reconcile_smc_hold_manager_shadow_deliveries.py "
            "--state <today's snapshot> (without --check) to fill "
            "deliveredServerAlerts.",
            "Run scripts/evaluate_smc_hold_manager_shadow.py and commit the "
            "regenerated evidence.",
            "Move the pinned checked-in-state test expectations in the same PR.",
        ],
        "blockers": [],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="ISO session date (ET)")
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
    result = scaffold_session(
        _load_json(args.contract), observations, args.date
    )
    if result["verdict"] == "scaffolded" and not args.check:
        atomic_write_text(
            json.dumps(observations, indent=2) + "\n",
            args.observations,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["verdict"] == "scaffolded" else 2


if __name__ == "__main__":
    raise SystemExit(main())

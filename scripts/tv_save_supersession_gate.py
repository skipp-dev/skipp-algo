"""Decide whether a queued tv-save-consumer-source run is superseded.

2026-08-22: the shared ``tradingview-session`` concurrency group queues FIFO
(``queue: max`` since 2026-08-06), so every automated save trigger lines up
behind every ~2h publish. Measured that morning: 14 pending saves, none of
which had produced a verdict for 19 hours, while both TV drift alerts burned.
The runs are interchangeable BY CONSTRUCTION — a save rebuilds its proposal on
current main at runtime — so only the newest queued automated run has any
effect the others would not repeat. This module is that supersession decision,
kept import-testable and free of subprocess/network: the workflow feeds it the
run list JSON on stdin.

Interchangeable means SAME-EVENT only: a ``workflow_run`` (write-chain) run
is repeated by a newer ``workflow_run`` run, a ``schedule`` (read-only
verify) run by a newer ``schedule`` run. The two are NOT substitutes — a
verify never saves, so letting a write abdicate to a verify would silently
drop the only run that refreshes the saved sources (measured 2026-08-22: the
bot-dispatched 18:50Z run was verify-only). ``workflow_dispatch`` runs are
excluded in BOTH directions: their mode hangs on inputs (operator intent,
verify-only, R1 re-attestation on a bump branch) that no other run repeats.

Fail-open: any parse or shape error answers "not superseded" — a lost dedup
costs one redundant save; a wrong abdication would silently drop the only run
that refreshes the binding snapshot.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

_SUPERSEDABLE_EVENTS = frozenset({"workflow_run", "schedule"})
_ACTIVE_STATUSES = frozenset(
    {"queued", "waiting", "pending", "requested", "in_progress"}
)


def decide(
    *,
    own_run_number: int,
    own_event: str,
    runs: list[dict[str, Any]],
) -> int | None:
    """Return the run_number of a superseding run, or None to proceed.

    A run is superseded when a NEWER (higher ``run_number``) still-active run
    of the SAME event kind exists. The newest run of each kind therefore never
    abdicates, and dispatch runs never take part in either direction.
    """
    if own_event not in _SUPERSEDABLE_EVENTS:
        return None
    superseding: int | None = None
    for run in runs:
        try:
            number = int(run["run_number"])
            status = str(run.get("status") or "")
            event = str(run.get("event") or "")
        except (KeyError, TypeError, ValueError):
            continue  # fail-open per run: an unreadable row never abdicates us
        if number <= own_run_number or status not in _ACTIVE_STATUSES:
            continue
        if event != own_event:
            continue
        if superseding is None or number > superseding:
            superseding = number
    return superseding


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        runs = payload["workflow_runs"]
        verdict = decide(
            own_run_number=int(os.environ["GATE_RUN_NUMBER"]),
            own_event=os.environ["GATE_EVENT_NAME"],
            runs=runs,
        )
    except Exception as exc:  # fail-open is the contract here
        print(f"superseded=false\nreason=gate_error:{type(exc).__name__}")
        return 0
    if verdict is None:
        print("superseded=false\nreason=newest_of_kind_or_not_supersedable")
    else:
        print(f"superseded=true\nreason=newer_same_event_run_{verdict}_queued")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

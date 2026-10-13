"""ADR-0023 Stage-1 → promotion-gate snapshot wiring.

The daily shadow runner (``scripts/run_magnitude_shadow_ledger.py``) appends one
graded row per family per day to the move-size shadow ledger. The promotion gate
(``governance.promotion_gate``) consumes per-family ``FamilyMetrics`` snapshots
whose ``magnitude_resolution_pass`` / ``magnitude_auc`` fields drive the additive
``ok_magnitude`` qualifier.

This module is the **bridge**: it reads the latest ledger row per family and
turns it into a snapshot value that can be applied to a ``FamilyMetrics``.

Status → ``magnitude_resolution_pass`` mapping (matches the gate's 3-state)
--------------------------------------------------------------------------
* ``PASS``         → ``True``  (cleared the §2 bar)
* ``FAIL``         → ``False`` (measurable, missed the bar → hard blocker)
* ``INCONCLUSIVE`` → ``None``  (too few OOS samples → not yet measured / lax)

Layering note: this lives in ``scripts/`` (the orchestration layer) so that
``governance/`` stays free of any dependency on the ledger I/O code. The gate
itself never imports from here — the caller wires the snapshots in.

Stage-1 is measure-only: by default :func:`gate_snapshots` returns **candidate**
families only (BOS / SWEEP). The FVG / OB control families are expected to FAIL
by construction, so feeding their ``False`` into a gate would hard-block a
diagnostic that is not a promotion target. The full set is still available via
:func:`load_magnitude_snapshots` for reporting.

Exit codes (CLI)
----------------
* ``0`` -- snapshots produced.
* ``3`` -- the ledger is empty or missing.
* ``1`` -- usage/config error (including a corrupt ledger line, W7-1).
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from dataclasses import dataclass
from datetime import date as _date
from typing import Any

from governance.promotion_gate import FamilyMetrics
from scripts.run_magnitude_shadow_ledger import (
    CANDIDATE_FAMILIES,
    DEFAULT_LEDGER,
    load_ledger,
)

_STATUS_PASS = "PASS"
_STATUS_FAIL = "FAIL"
_STATUS_INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class MagnitudeSnapshot:
    """Latest move-size verdict for one family, gate-ready.

    ``magnitude_resolution_pass`` / ``magnitude_auc`` line up 1:1 with the
    same-named ``FamilyMetrics`` fields. ``status`` / ``date`` are carried for
    provenance and reporting.
    """

    family: str
    magnitude_resolution_pass: bool | None
    magnitude_auc: float | None
    status: str | None
    date: str | None


def _status_to_pass(status: Any) -> bool | None:
    """Map a ledger ``status`` literal to the gate's 3-state pass field."""
    if status == _STATUS_PASS:
        return True
    if status == _STATUS_FAIL:
        return False
    # INCONCLUSIVE or anything unrecognised → "not yet measured".
    return None


def _coerce_auc(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, (int, float)) else None


def _parse_iso_date(value: Any) -> _date | None:
    """Parse a ledger ``date`` string into a :class:`datetime.date`.

    Returns ``None`` for non-strings and unparseable values so callers can
    treat them as "no usable date" instead of comparing raw strings.
    """
    if not isinstance(value, str):
        return None
    try:
        return _date.fromisoformat(value)
    except ValueError:
        return None


def snapshot_from_row(row: dict[str, Any]) -> MagnitudeSnapshot:
    """Build a :class:`MagnitudeSnapshot` from one ledger row."""
    return MagnitudeSnapshot(
        family=str(row.get("family")),
        magnitude_resolution_pass=_status_to_pass(row.get("status")),
        magnitude_auc=_coerce_auc(row.get("magnitude_auc")),
        status=row.get("status") if isinstance(row.get("status"), str) else None,
        date=row.get("date") if isinstance(row.get("date"), str) else None,
    )


def latest_rows_by_family(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Pick the row with the most recent ``date`` for each family.

    Dates are compared as **parsed dates**, not as raw strings — a
    lexicographic compare silently mis-orders any non-ISO value that leaks
    into the ledger (same bug class as the weekly-eval fix in #2715). Rows
    whose ``date`` does not parse can never win "latest". Ties on ``date``
    resolve to the row that appears last in ``rows`` (the ledger is
    append-only and latest-wins), preserving the runner's ordering.
    """
    latest: dict[str, tuple[_date, dict[str, Any]]] = {}
    for row in rows:
        family = row.get("family")
        if not isinstance(family, str):
            continue
        parsed = _parse_iso_date(row.get("date"))
        if parsed is None:
            continue
        current = latest.get(family)
        if current is None or parsed >= current[0]:
            latest[family] = (parsed, row)
    return {family: row for family, (_d, row) in latest.items()}


def load_magnitude_snapshots(
    ledger_path: str = DEFAULT_LEDGER,
) -> dict[str, MagnitudeSnapshot]:
    """Latest snapshot for *every* family present in the ledger."""
    rows = load_ledger(ledger_path)
    latest = latest_rows_by_family(rows)
    return {
        family: snapshot_from_row(row)
        for family, row in sorted(latest.items())
    }


def gate_snapshots(
    ledger_path: str = DEFAULT_LEDGER,
    *,
    candidate_families: frozenset[str] = CANDIDATE_FAMILIES,
) -> dict[str, MagnitudeSnapshot]:
    """Snapshots for the promotion gate — candidate families only.

    Control families (FVG / OB) are excluded: they FAIL by design and are not
    promotion targets, so their ``False`` must never reach the gate.
    """
    return {
        family: snap
        for family, snap in load_magnitude_snapshots(ledger_path).items()
        if family in candidate_families
    }


def apply_to_family_metrics(
    metrics: FamilyMetrics,
    snapshot: MagnitudeSnapshot,
) -> FamilyMetrics:
    """Return a copy of ``metrics`` with the move-size fields set.

    Non-mutating: uses :func:`dataclasses.replace` so the caller's original
    snapshot object is untouched.
    """
    return dataclasses.replace(
        metrics,
        magnitude_resolution_pass=snapshot.magnitude_resolution_pass,
        magnitude_auc=snapshot.magnitude_auc,
    )


def _snapshot_to_dict(snap: MagnitudeSnapshot) -> dict[str, Any]:
    return {
        "family": snap.family,
        "magnitude_resolution_pass": snap.magnitude_resolution_pass,
        "magnitude_auc": snap.magnitude_auc,
        "status": snap.status,
        "date": snap.date,
    }


def render_text(snapshots: dict[str, MagnitudeSnapshot]) -> str:
    lines = ["ADR-0023 Stage-1 promotion-gate snapshots (move-size):"]
    for family, snap in snapshots.items():
        auc = snap.magnitude_auc
        auc_s = f"{auc:.3f}" if isinstance(auc, (int, float)) else "n/a"
        pass_s = {True: "PASS", False: "FAIL", None: "unmeasured"}[
            snap.magnitude_resolution_pass
        ]
        lines.append(
            f"  {family:<6} {pass_s:<10} AUC={auc_s} "
            f"(status={snap.status}, date={snap.date})"
        )
    if len(lines) == 1:
        lines.append("  (no matching families in ledger)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ledger",
        default=DEFAULT_LEDGER,
        help=f"shadow ledger JSONL path (default: {DEFAULT_LEDGER})",
    )
    parser.add_argument(
        "--all-families",
        action="store_true",
        help="include control families (FVG/OB), not just gate candidates",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="output format (default: text)",
    )
    args = parser.parse_args(argv)

    try:
        rows = load_ledger(args.ledger)
    except ValueError as exc:
        # W7-1: a corrupt ledger is a usage/config error (rc 1), not "empty"
        # (rc 3) — picking the newest *parseable* row would resurrect
        # yesterday's PASS after today's FAIL line got mangled.
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not rows:
        print(f"error: empty or missing ledger: {args.ledger}", file=sys.stderr)
        return 3

    snapshots = (
        load_magnitude_snapshots(args.ledger)
        if args.all_families
        else gate_snapshots(args.ledger)
    )

    if args.format == "json":
        print(
            json.dumps(
                {f: _snapshot_to_dict(s) for f, s in snapshots.items()},
                sort_keys=True,
                indent=2,
            )
        )
    else:
        print(render_text(snapshots))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

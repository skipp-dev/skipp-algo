#!/usr/bin/env python3
"""Back-fill the event ledger's ``calibrated_prob`` from the family calibrator.

Stage #5, PR 3. The measurement ledger (schema 1.2) carries an optional, leak-free
out-of-sample ``calibrated_prob`` that is NULL at write time — it can only be
produced offline, after the fact, by the walk-forward family calibrator
(``governance/family_calibration``), which is per-family-pooled and covers only a
partial subset of events. This joins that calibrator output onto the persisted
ledger by ``event_id`` and rewrites each row's ``calibrated_prob``.

Data flow (all offline):

    structure + bars
      -> family_events_from_structure           (each FamilyEvent carries event_id)
      -> to_build_spec                           (walk-forward OOS, event_id-aligned)
      -> spec["families"][F]["calibrated_prob_by_event"] = {event_id: oos_prob}

    this script:
      spec (JSON)  +  benchmark_dir/*/*/events_*.jsonl
        -> {event_id: calibrated_prob}           (merged across families)
        -> for each ledger record: calibrated_prob = mapping.get(event_id)
        -> atomic rewrite (strict-validated; a corrupt file is never rewritten)

Coverage is PARTIAL by construction: an event that the calibrator never scored
out-of-sample (training regions, thin/unfittable folds, sub-``min_oos`` families,
or an event with no id) keeps ``calibrated_prob = null``. Idempotent: re-running
with the same spec produces the same rows.

Exit codes: 0 = done · 3 = spec had no ``calibrated_prob_by_event`` (nothing to
join) · 1 = usage/read error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text
from smc_core.event_ledger import read_event_ledger, validate_event_ledger_record

# Mirrors ``event_ledger._LEDGER_TREE_GLOB`` (SYMBOL/TF/events_*.jsonl).
_LEDGER_TREE_GLOB = "*/*/events_*.jsonl"


def calibrated_prob_map(spec: dict[str, Any]) -> dict[str, float]:
    """Merge every family's ``calibrated_prob_by_event`` into one ``{event_id: prob}``.

    Event ids are globally unique (an event belongs to exactly one family), so the
    per-family maps are disjoint; a defensive last-writer-wins covers the
    impossible-collision case without failing the join.
    """
    out: dict[str, float] = {}
    families = spec.get("families")
    if not isinstance(families, dict):
        return out
    for entry in families.values():
        by_event = entry.get("calibrated_prob_by_event") if isinstance(entry, dict) else None
        if isinstance(by_event, dict):
            for eid, prob in by_event.items():
                out[str(eid)] = float(prob)
    return out


def backfill_ledger_file(
    path: Path, mapping: dict[str, float], *, dry_run: bool = False
) -> tuple[int, int]:
    """Set ``calibrated_prob`` on each record whose ``event_id`` is in ``mapping``.

    Returns ``(n_records, n_filled)``. Every record is validated (strict) AFTER
    the join, so a join that would produce an off-schema row raises instead of
    persisting it, and a corrupt input file is never rewritten. ``dry_run``
    computes the counts without writing.
    """
    records = list(read_event_ledger(path, strict=True))  # fail-closed on corruption
    filled = 0
    for rec in records:
        eid = str(rec.get("event_id", ""))
        if eid and eid in mapping:
            rec["calibrated_prob"] = mapping[eid]
            filled += 1
        validate_event_ledger_record(rec, source=str(path))
    if not dry_run and filled:
        text = "".join(
            json.dumps(r, separators=(",", ":"), allow_nan=False) + "\n" for r in records
        )
        atomic_write_text(text, path)
    return len(records), filled


def backfill_ledger_tree(
    root: Path, mapping: dict[str, float], *, dry_run: bool = False
) -> dict[str, int]:
    """Back-fill every ``SYMBOL/TF/events_*.jsonl`` under ``root``."""
    stats = {"files": 0, "records": 0, "filled": 0}
    for path in sorted(root.glob(_LEDGER_TREE_GLOB)):
        n_records, filled = backfill_ledger_file(path, mapping, dry_run=dry_run)
        stats["files"] += 1
        stats["records"] += n_records
        stats["filled"] += filled
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--benchmark-dir", type=Path, required=True, help="Ledger tree root (SYMBOL/TF/events_*.jsonl).")
    parser.add_argument(
        "--spec", type=Path, required=True,
        help="to_build_spec JSON carrying per-family calibrated_prob_by_event.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report counts without rewriting.")
    args = parser.parse_args(argv)

    try:
        spec = json.loads(args.spec.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if not isinstance(spec, dict):
        print(f"ERROR: {args.spec}: expected a JSON object", file=sys.stderr)
        return 1

    mapping = calibrated_prob_map(spec)
    if not mapping:
        print("backfill: spec carries no calibrated_prob_by_event — nothing to join")
        return 3

    stats = backfill_ledger_tree(args.benchmark_dir, mapping, dry_run=args.dry_run)
    print(
        f"backfill calibrated_prob{' [dry-run]' if args.dry_run else ''}: "
        f"{stats['filled']}/{stats['records']} records filled across {stats['files']} files "
        f"({len(mapping)} mapped event_ids)"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

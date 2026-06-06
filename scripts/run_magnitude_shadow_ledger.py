"""ADR-0023 Stage-1 shadow ledger: daily move-size resolution monitoring.

Stage 1 of the ADR-0023 live rollout (see
``docs/governance/adr0023_live_rollout_handover.md`` §4) is *measure-only*: on
each run it grades every family against the pre-registered §2 move-size
acceptance bar and appends one row per family to an append-only JSONL ledger.
Nothing is wired into the promotion gate here — this is the passive shadow feed
that the weekly k-of-n judgement reads.

All four families are recorded every run:

* ``BOS`` / ``SWEEP`` are the **candidates** (they cleared the §2 bar on real
  data); we confirm they stay stably above the bar.
* ``FVG`` / ``OB`` are the **negative control** (real-but-sub-threshold); we
  confirm they stay below. If all four pass on the same day that is a
  data/pipeline-artifact red flag, not skill.

The bar itself is frozen in ``governance.magnitude_resolution_gate`` and is
neither relaxed nor re-tuned here.

Input
-----
A JSON file containing a list of ``FamilyEvent`` records (same shape as
``run_magnitude_resolution_gate.py``), or ``-`` to read that list from stdin.

Ledger
------
Append-only JSONL, default ``artifacts/governance/magnitude_resolution_shadow.jsonl``.
Each line is one ``(date, family)`` observation. Re-running for the same
``(date, family, events_hash)`` is idempotent: the latest row replaces the
earlier one rather than duplicating it. History is never truncated.

Exit codes
----------
* ``0`` -- at least one family PASSES the §2 bar on this run.
* ``2`` -- families were measurable but NONE passes (expected negative run).
* ``3`` -- no family produced a verdict (every sample too thin).
* ``1`` -- usage/config error (bad path, malformed JSON, empty event list).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from typing import Any

from governance.family_returns import DEFAULT_COST_BPS
from governance.magnitude_resolution_gate import (
    DEFAULT_N_BOOTSTRAP,
    DEFAULT_N_PERMUTATION,
    DEFAULT_SEED,
)
from scripts.run_magnitude_resolution_gate import (
    _load_events,
    _verdict_exit_code,
    build_report,
)
from scripts.smc_atomic_write import atomic_write_text

DEFAULT_LEDGER = "artifacts/governance/magnitude_resolution_shadow.jsonl"

# Families that cleared the ADR-0023 §2 bar on real data; the rest are tracked
# as the negative-control group. This is a *monitoring designation*, not a
# bar — a control that later crosses above the unchanged bar is recorded as a
# PASS just the same.
CANDIDATE_FAMILIES = frozenset({"BOS", "SWEEP"})

# Ledger column order (documented in the handover §4.2).
LEDGER_COLUMNS = (
    "date",
    "events_hash",
    "seed",
    "family",
    "role",
    "n_oos",
    "magnitude_auc",
    "auc_ci_low",
    "baseline_resolution",
    "perm_null_p95",
    "perm_p",
    "passes",
    "status",
    "fail_reasons",
)


def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def events_content_hash(events: list[dict[str, Any]]) -> str:
    """Stable short content hash of the event list (order-sensitive)."""
    canonical = json.dumps(events, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def classify_family(result: dict[str, Any]) -> tuple[str, list[str]]:
    """Map a §2 result dict to a daily status + fail reasons (handover §4.3).

    * ``INCONCLUSIVE`` -- too few OOS samples to judge (``min_sample_pass``).
    * ``PASS`` -- clears the full §2 bar.
    * ``FAIL`` -- measurable but misses at least one sub-condition.
    """
    if not result.get("min_sample_pass", False):
        return "INCONCLUSIVE", ["n_oos_below_min"]
    if result.get("passes", False):
        return "PASS", []
    reasons: list[str] = []
    if not result.get("auc_floor_pass", False):
        reasons.append("auc_floor")
    if not result.get("auc_ci_pass", False):
        reasons.append("auc_ci")
    if not result.get("resolution_pass", False):
        reasons.append("resolution_null")
    return "FAIL", reasons


def build_ledger_rows(
    report: dict[str, Any], *, date: str, events_hash: str
) -> list[dict[str, Any]]:
    """One tidy ledger row per measured family, sorted by family."""
    seed = int(report.get("seed", DEFAULT_SEED))
    rows: list[dict[str, Any]] = []
    for family, result in sorted(report.get("results", {}).items()):
        status, fail_reasons = classify_family(result)
        rows.append(
            {
                "date": date,
                "events_hash": events_hash,
                "seed": seed,
                "family": family,
                "role": "candidate" if family in CANDIDATE_FAMILIES else "control",
                "n_oos": result.get("n_oos"),
                "magnitude_auc": result.get("mag_auc"),
                "auc_ci_low": result.get("auc_ci_low"),
                "baseline_resolution": result.get("baseline_resolution"),
                "perm_null_p95": result.get("perm_null_p95"),
                "perm_p": result.get("perm_p_value"),
                "passes": bool(result.get("passes", False)),
                "status": status,
                "fail_reasons": fail_reasons,
            }
        )
    return rows


def load_ledger(path: str) -> list[dict[str, Any]]:
    """Read an existing JSONL ledger, skipping malformed lines."""
    rows: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    rows.append(parsed)
    except FileNotFoundError:
        return []
    return rows


def merge_rows(
    existing: list[dict[str, Any]], new: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Append-only merge, idempotent on ``(date, family, events_hash)``.

    A re-run for the same day/data/family overwrites the earlier observation
    rather than duplicating it. Rows are returned sorted by ``(date, family)``
    so the file is stable and diff-friendly; history is never dropped.
    """
    def key(row: dict[str, Any]) -> tuple[Any, Any, Any]:
        return (row.get("date"), row.get("family"), row.get("events_hash"))

    merged: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    for row in existing:
        merged[key(row)] = row
    for row in new:
        merged[key(row)] = row
    return sorted(
        merged.values(),
        key=lambda r: (str(r.get("date")), str(r.get("family"))),
    )


def append_shadow_ledger(
    report: dict[str, Any],
    *,
    ledger_path: str = DEFAULT_LEDGER,
    date: str | None = None,
    events_hash: str,
) -> list[dict[str, Any]]:
    """Build today's rows, merge into the ledger, and write it atomically."""
    date = date or _today_utc()
    new_rows = build_ledger_rows(report, date=date, events_hash=events_hash)
    merged = merge_rows(load_ledger(ledger_path), new_rows)
    rendered = "\n".join(json.dumps(row, sort_keys=True) for row in merged)
    atomic_write_text(rendered + "\n", ledger_path)
    return new_rows


def _summarize(new_rows: list[dict[str, Any]]) -> str:
    parts = []
    for row in new_rows:
        parts.append(
            f"{row['family']}({row['role']}): {row['status']}"
            + (f" [{','.join(row['fail_reasons'])}]" if row["fail_reasons"] else "")
        )
    return " | ".join(parts) if parts else "no families measured"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "events",
        help="path to a JSON list of FamilyEvent records, or '-' for stdin",
    )
    parser.add_argument(
        "--ledger",
        default=DEFAULT_LEDGER,
        help=f"append-only JSONL ledger path (default: {DEFAULT_LEDGER})",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="observation date YYYY-MM-DD (default: today UTC)",
    )
    parser.add_argument(
        "--cost-bps",
        type=float,
        default=DEFAULT_COST_BPS,
        help=f"round-trip cost in basis points (default: {DEFAULT_COST_BPS})",
    )
    parser.add_argument(
        "--mag-q",
        type=float,
        default=0.5,
        help="per-fold |return| quantile for the magnitude label (default: 0.5)",
    )
    parser.add_argument(
        "--n-bootstrap",
        type=int,
        default=DEFAULT_N_BOOTSTRAP,
        help=f"AUC bootstrap resamples (default: {DEFAULT_N_BOOTSTRAP})",
    )
    parser.add_argument(
        "--n-permutation",
        type=int,
        default=DEFAULT_N_PERMUTATION,
        help=f"resolution label-permutations (default: {DEFAULT_N_PERMUTATION})",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"RNG seed for the CI/null (default: {DEFAULT_SEED})",
    )
    args = parser.parse_args(argv)

    try:
        events = _load_events(args.events)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: could not load events: {exc}", file=sys.stderr)
        return 1

    if not events:
        print("error: event list is empty", file=sys.stderr)
        return 1

    report = build_report(
        events,
        cost_bps=args.cost_bps,
        mag_q=args.mag_q,
        n_boot=args.n_bootstrap,
        n_perm=args.n_permutation,
        seed=args.seed,
    )

    new_rows = append_shadow_ledger(
        report,
        ledger_path=args.ledger,
        date=args.date,
        events_hash=events_content_hash(events),
    )

    print(f"shadow ledger {args.ledger}: {_summarize(new_rows)}", file=sys.stderr)
    return _verdict_exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())

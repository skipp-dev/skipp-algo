"""Plan 2.8 ledger status-share calculator.

Computes the share (percentage of records) of each valid status
across the full ledger. Output percentages are rounded to 2dp
and always sum to at most 100.00; ``skipped`` tallies records
whose status was invalid or unparseable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

VALID_STATUSES = ("green", "amber", "red", "unknown")


def _iter_records(ledger: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not ledger.exists():
        return out
    for line in ledger.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            rec = json.loads(s)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def compute(records: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {k: 0 for k in VALID_STATUSES}
    skipped = 0
    for rec in records:
        raw = rec.get("status")
        if not isinstance(raw, str):
            skipped += 1
            continue
        s = raw.strip().lower()
        if s not in counts:
            skipped += 1
            continue
        counts[s] += 1
    total = sum(counts.values())
    shares: dict[str, float] = {}
    if total > 0:
        for k in VALID_STATUSES:
            shares[k] = round((counts[k] / total) * 100.0, 2)
    else:
        for k in VALID_STATUSES:
            shares[k] = 0.0
    return {
        "schema_version": 1,
        "total":          total,
        "counts":         counts,
        "shares_pct":     shares,
        "skipped":        skipped,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 status share",
        "",
        f"- total:   {report['total']}",
        f"- skipped: {report['skipped']}",
        "",
        "| status | count | share (%) |",
        "|---|---:|---:|",
    ]
    for k in VALID_STATUSES:
        lines.append(
            f"| {k} | {report['counts'][k]} "
            f"| {report['shares_pct'][k]:.2f} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compute per-status share-of-time.",
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-below-green", type=float, default=None)
    args = parser.parse_args(argv)

    if not args.ledger.exists():
        print(f"ERROR: ledger not found: {args.ledger}", file=sys.stderr)
        return 1

    report = compute(_iter_records(args.ledger))
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_below_green is not None \
            and report["shares_pct"]["green"] < args.fail_below_green:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

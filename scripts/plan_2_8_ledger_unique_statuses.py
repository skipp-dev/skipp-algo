"""Plan 2.8 ledger unique statuses.

Lists the distinct valid statuses observed in the ledger.
Unknown/malformed statuses are ignored. Output includes the
sorted list plus counts per status.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
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
    counts: Counter[str] = Counter()
    for rec in records:
        raw = rec.get("status")
        if not isinstance(raw, str):
            continue
        key = raw.strip().lower()
        if key in VALID_STATUSES:
            counts[key] += 1
    return {
        "schema_version":  1,
        "unique_count":    len(counts),
        "statuses":        sorted(counts),
        "counts":          dict(counts),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 ledger unique statuses",
        "",
        f"- unique_count: {report['unique_count']}",
    ]
    if report["statuses"]:
        lines.append("")
        for st in report["statuses"]:
            lines.append(f"- {st}: {report['counts'][st]}")
    else:
        lines.append("- _none_")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Distinct valid statuses observed in ledger.",
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument(
        "--fail-below-count", type=int, default=None,
        help="Exit 1 if unique_count is below this threshold.",
    )
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
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
    if (args.fail_below_count is not None
            and report["unique_count"] < args.fail_below_count):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

"""Plan 2.8 status-transition matrix.

Walks the ledger in order and counts every status transition
(from -> to) as a 4x4 dict-of-dicts (green/amber/red/unknown).
Complements flap_rate which only tracks *any* transition.
"""

from __future__ import annotations

import argparse
import json
import sys
from itertools import pairwise
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
    matrix: dict[str, dict[str, int]] = {
        k: {j: 0 for j in VALID_STATUSES} for k in VALID_STATUSES
    }
    cleaned: list[str] = []
    for rec in records:
        raw = rec.get("status")
        if not isinstance(raw, str):
            continue
        s = raw.strip().lower()
        if s in VALID_STATUSES:
            cleaned.append(s)
    total = 0
    for a, b in pairwise(cleaned):
        if a != b:
            matrix[a][b] += 1
            total += 1
    return {
        "schema_version":    1,
        "total_transitions": total,
        "matrix":            matrix,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 status transitions",
        "",
        f"- total_transitions: {report['total_transitions']}",
        "",
        "| from \\ to | " + " | ".join(VALID_STATUSES) + " |",
        "|---|" + "|".join(["---:"] * len(VALID_STATUSES)) + "|",
    ]
    for frm in VALID_STATUSES:
        row = " | ".join(
            str(report["matrix"][frm][to]) for to in VALID_STATUSES
        )
        lines.append(f"| {frm} | {row} |")
    lines.append("")
    return "\n".join(lines) + "\n"

# F-V6-A1.1 (2026-05-02): bootstrap root logging so the logger.info(...)
# progress messages this entry point emits actually surface in CI logs
# (default WARNING-only handler would drop them). Extends F-V5-A1-2 / #2012
# from the priority entry-point set to plan_2_8 aggregators + showcase.
try:
    from scripts._logging_init import init_cli_logging
except ImportError:  # script-style invocation: `python scripts/X.py`
    import sys as _v6a11_sys
    from pathlib import Path as _v6a11_Path

    _v6a11_sys.path.insert(0, str(_v6a11_Path(__file__).resolve().parents[1]))
    from scripts._logging_init import init_cli_logging  # type: ignore[no-redef]




def main(argv: list[str] | None = None) -> int:
    init_cli_logging()  # F-V6-A1.1 (2026-05-02)
    parser = argparse.ArgumentParser(
        description="Compute NxN status transition matrix.",
    )
    parser.add_argument("--ledger", type=Path, required=True)
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
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

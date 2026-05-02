"""Plan 2.8 status-ledger transition matrix.

Walks the ledger in captured order and builds a ``from\u2192to``
transition matrix over the allowed statuses. Useful for pattern
analysis (e.g. how often green\u2192amber vs green\u2192red).
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


def _norm(status: Any) -> str | None:
    if not isinstance(status, str):
        return None
    norm = status.strip().lower()
    if norm not in VALID_STATUSES:
        return None
    return norm


def build_matrix(records: list[dict[str, Any]]) -> dict[str, Any]:
    matrix: dict[str, dict[str, int]] = {
        a: {b: 0 for b in VALID_STATUSES} for a in VALID_STATUSES
    }
    prev: str | None = None
    total_transitions = 0
    for rec in records:
        curr = _norm(rec.get("status"))
        if curr is None:
            prev = None
            continue
        if prev is not None:
            matrix[prev][curr] += 1
            total_transitions += 1
        prev = curr
    return {
        "schema_version": 1,
        "statuses":       list(VALID_STATUSES),
        "counts":         {"transitions": total_transitions},
        "matrix":         matrix,
    }


def render_markdown(report: dict[str, Any]) -> str:
    statuses = report["statuses"]
    matrix = report["matrix"]
    lines = [
        "# Plan 2.8 status transition matrix",
        "",
        f"- transitions: {report['counts']['transitions']}",
        "",
    ]
    header = "| from \\\\ to | " + " | ".join(statuses) + " |"
    sep = "| --- | " + " | ".join(["---"] * len(statuses)) + " |"
    lines.append(header)
    lines.append(sep)
    for a in statuses:
        row = [f"**{a}**"]
        for b in statuses:
            row.append(str(matrix[a][b]))
        lines.append("| " + " | ".join(row) + " |")
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
        description="Build a status transition matrix from a ledger.",
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="json")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.ledger.exists():
        print(f"ERROR: ledger not found: {args.ledger}", file=sys.stderr)
        return 1

    records = _iter_records(args.ledger)
    report = build_matrix(records)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

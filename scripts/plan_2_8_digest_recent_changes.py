"""Plan 2.8 digest recent-changes emitter.

Walks the ledger in order and keeps only the records where the
status changed from the previous one. Emits the last ``--limit``
such changes (default 10) as md or json — a compact "what has
actually changed lately" view distinct from the full ledger.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

VALID_STATUSES = frozenset({"green", "amber", "red", "unknown"})


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


def extract(records: list[dict[str, Any]], *,
            limit: int) -> dict[str, Any]:
    if limit < 1:
        raise ValueError("limit must be >= 1")
    changes: list[dict[str, Any]] = []
    prev: str | None = None
    for rec in records:
        raw = rec.get("status")
        if not isinstance(raw, str):
            continue
        s = raw.strip().lower()
        if s not in VALID_STATUSES:
            continue
        if s != prev:
            changes.append({
                "from":        prev,
                "to":          s,
                "captured_at": rec.get("captured_at"),
                "run_url":     rec.get("run_url"),
            })
            prev = s
    # drop the synthetic initial entry (``from = None``) so the
    # result only contains real *transitions* when there are any.
    transitions = [c for c in changes if c["from"] is not None]
    recent = transitions[-limit:]
    return {
        "schema_version": 1,
        "total_changes":  len(transitions),
        "returned":       len(recent),
        "changes":        recent,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 recent status changes",
        "",
        f"- total changes: {report['total_changes']}",
        f"- shown:         {report['returned']}",
        "",
    ]
    if report["changes"]:
        lines.append("| captured_at | from | to | run |")
        lines.append("|---|---|---|---|")
        for c in report["changes"]:
            run = c["run_url"] or ""
            link = f"[run]({run})" if run else "-"
            lines.append(
                f"| {c['captured_at'] or 'n/a'} | {c['from']} "
                f"| {c['to']} | {link} |"
            )
    else:
        lines.append("_No status changes recorded._")
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
        description="Emit the last N ledger status changes.",
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.ledger.exists():
        print(f"ERROR: ledger not found: {args.ledger}", file=sys.stderr)
        return 1
    if args.limit < 1:
        print("ERROR: --limit must be >= 1", file=sys.stderr)
        return 1

    report = extract(_iter_records(args.ledger), limit=args.limit)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

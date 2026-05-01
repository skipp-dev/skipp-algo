"""Plan 2.8 ledger distinct days.

Counts how many distinct UTC calendar days are represented in
the ledger's ``captured_at`` timestamps. Invalid records and
malformed timestamps are silently skipped.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
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


def _day(ts: Any) -> str | None:
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts).date().isoformat()
    except ValueError:
        return None


def compute(records: list[dict[str, Any]]) -> dict[str, Any]:
    days: set[str] = set()
    for rec in records:
        raw = rec.get("status")
        if not isinstance(raw, str):
            continue
        if raw.strip().lower() not in VALID_STATUSES:
            continue
        d = _day(rec.get("captured_at"))
        if d is not None:
            days.add(d)
    return {
        "schema_version": 1,
        "distinct_days":  len(days),
        "days":           sorted(days),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 ledger distinct days",
        "",
        f"- distinct_days: {report['distinct_days']}",
    ]
    if report["days"]:
        lines.append("")
        for d in report["days"]:
            lines.append(f"  - {d}")
    lines.append("")
    return "\n".join(lines)

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
        description="Count distinct UTC days in the ledger.",
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--fail-below-days", type=int, default=None)
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
    if (args.fail_below_days is not None
            and report["distinct_days"] < args.fail_below_days):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

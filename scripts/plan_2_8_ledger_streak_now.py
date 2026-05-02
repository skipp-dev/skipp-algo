"""Plan 2.8 current-streak calculator.

Returns the current (trailing) streak of the latest status:

- status: the latest valid status
- length: number of consecutive records that share it
- started_at: captured_at of the first record in the trailing run
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


def compute(records: list[dict[str, Any]]) -> dict[str, Any]:
    cleaned: list[tuple[str, str | None]] = []
    for rec in records:
        raw = rec.get("status")
        if not isinstance(raw, str):
            continue
        s = raw.strip().lower()
        if s not in VALID_STATUSES:
            continue
        ts = rec.get("captured_at")
        cleaned.append((s, ts if isinstance(ts, str) else None))
    if not cleaned:
        return {
            "schema_version": 1,
            "status":         None,
            "length":         0,
            "started_at":     None,
        }
    latest_status = cleaned[-1][0]
    length = 0
    started_at: str | None = None
    for status, ts in reversed(cleaned):
        if status != latest_status:
            break
        length += 1
        started_at = ts
    return {
        "schema_version": 1,
        "status":         latest_status,
        "length":         length,
        "started_at":     started_at,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 current streak\n\n"
        f"- status:     {report['status'] or 'n/a'}\n"
        f"- length:     {report['length']}\n"
        f"- started_at: {report['started_at'] or 'n/a'}\n"
    )

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
        description="Compute the current streak of the latest status.",
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

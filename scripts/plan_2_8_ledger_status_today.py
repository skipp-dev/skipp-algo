"""Plan 2.8 ledger today-status emitter.

Returns the latest ledger record whose ``captured_at`` falls on
the target UTC date (defaults to today). Emits md or json.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

VALID_STATUSES = frozenset({"green", "amber", "red", "unknown"})


def _parse_ts(raw: Any) -> _dt.datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        return _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


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


def find_today(
    records: list[dict[str, Any]], *,
    target: _dt.date,
) -> dict[str, Any]:
    match: dict[str, Any] | None = None
    for rec in records:
        ts = _parse_ts(rec.get("captured_at"))
        raw = rec.get("status")
        if ts is None or not isinstance(raw, str):
            continue
        s = raw.strip().lower()
        if s not in VALID_STATUSES:
            continue
        if ts.astimezone(_dt.UTC).date() != target:
            continue
        match = {
            "schema_version": 1,
            "date":           target.isoformat(),
            "status":         s,
            "captured_at":    rec.get("captured_at"),
            "run_url":        rec.get("run_url"),
            "found":          True,
        }
    if match is not None:
        return match
    return {
        "schema_version": 1,
        "date":           target.isoformat(),
        "status":         None,
        "captured_at":    None,
        "run_url":        None,
        "found":          False,
    }


def render_markdown(report: dict[str, Any]) -> str:
    if not report["found"]:
        return (
            f"# Plan 2.8 status on {report['date']}\n\n"
            "_No ledger record captured today._\n"
        )
    return (
        f"# Plan 2.8 status on {report['date']}\n\n"
        f"- status:      {report['status']}\n"
        f"- captured_at: {report['captured_at']}\n"
        f"- run_url:     {report['run_url'] or 'n/a'}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Show the ledger record for a given UTC date.",
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--date", default=None,
                        help="ISO UTC date (default: today)")
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.ledger.exists():
        print(f"ERROR: ledger not found: {args.ledger}", file=sys.stderr)
        return 1

    if args.date is None:
        target = _dt.datetime.now(tz=_dt.UTC).date()
    else:
        try:
            target = _dt.date.fromisoformat(args.date)
        except ValueError:
            print(f"ERROR: invalid --date: {args.date}", file=sys.stderr)
            return 1

    report = find_today(_iter_records(args.ledger), target=target)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

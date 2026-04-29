"""Plan 2.8 ledger latest captured_at.

Reports the most recent ``captured_at`` timestamp from any
record in the ledger (valid JSON only). Status validity is
not enforced here -- this helper answers "how stale is the
ledger?" even when the tail record has a malformed status.
Returns ``{"found": false}`` when no usable timestamp exists.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


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


def compute(
    records: list[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    if now is None:
        now = datetime.now(UTC)
    for rec in reversed(records):
        ts = rec.get("captured_at")
        if not isinstance(ts, str):
            continue
        try:
            parsed = datetime.fromisoformat(ts)
        except ValueError:
            continue
        age_h = round((now - parsed).total_seconds() / 3600.0, 4)
        return {
            "schema_version":  1,
            "found":           True,
            "captured_at":     ts,
            "age_hours":       age_h,
        }
    return {"schema_version": 1, "found": False}


def render_markdown(report: dict[str, Any]) -> str:
    if not report.get("found"):
        return (
            "# Plan 2.8 ledger latest captured_at\n"
            "\n"
            "- _none_\n"
        )
    return (
        "# Plan 2.8 ledger latest captured_at\n"
        "\n"
        f"- captured_at: {report['captured_at']}\n"
        f"- age_hours: {report['age_hours']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Most recent ledger captured_at and its age.",
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--now", type=str, default=None)
    parser.add_argument("--fail-above-hours", type=float, default=None)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.ledger.exists():
        print(f"ERROR: ledger not found: {args.ledger}", file=sys.stderr)
        return 1

    now: datetime | None = None
    if args.now is not None:
        try:
            now = datetime.fromisoformat(args.now)
        except ValueError:
            print(f"ERROR: bad --now: {args.now}", file=sys.stderr)
            return 1

    report = compute(_iter_records(args.ledger), now=now)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if (args.fail_above_hours is not None
            and report.get("found")
            and report["age_hours"] > args.fail_above_hours):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

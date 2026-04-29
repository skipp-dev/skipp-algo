"""Plan 2.8 ledger green ratio.

Reports the share of valid observations recorded as
``green``. Result in ``[0.0, 1.0]``.
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
    total = 0
    green = 0
    for rec in records:
        raw = rec.get("status")
        if not isinstance(raw, str):
            continue
        status = raw.strip().lower()
        if status not in VALID_STATUSES:
            continue
        total += 1
        if status == "green":
            green += 1
    ratio = (green / total) if total else 0.0
    return {
        "schema_version":    1,
        "observation_count": total,
        "green_ratio":       round(ratio, 4),
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 ledger green ratio\n"
        "\n"
        f"- observation_count: {report['observation_count']}\n"
        f"- green_ratio: {report['green_ratio']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Green ratio.")
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

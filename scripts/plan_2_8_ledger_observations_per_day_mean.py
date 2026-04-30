"""Plan 2.8 ledger observations per day mean.

Mean number of valid observations per distinct day.
Empty ledger yields 0.0.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
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
    per_day: Counter[str] = Counter()
    for rec in records:
        raw = rec.get("status")
        cap = rec.get("captured_at")
        if not isinstance(raw, str) or not isinstance(cap, str):
            continue
        if raw.strip().lower() not in VALID_STATUSES:
            continue
        if len(cap) < 10:
            continue
        per_day[cap[:10]] += 1
    if per_day:
        total = sum(per_day.values())
        mean = total / len(per_day)
    else:
        mean = 0.0
    return {
        "schema_version":          1,
        "unique_day_count":        len(per_day),
        "observations_per_day_mean": round(mean, 4),
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 ledger observations per day mean\n"
        "\n"
        f"- unique_day_count: {report['unique_day_count']}\n"
        "- observations_per_day_mean: "
        f"{report['observations_per_day_mean']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Obs per day.")
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

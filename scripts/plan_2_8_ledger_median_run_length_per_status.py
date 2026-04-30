"""Plan 2.8 ledger median run length per status.

Reports the median consecutive-same-status run length for
each of the four canonical statuses. Statuses that never
appear yield 0.0. Even counts use linear interpolation and
round to two decimals.
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


def _median(vals: list[int]) -> float:
    n = len(vals)
    if n == 0:
        return 0.0
    ordered = sorted(vals)
    if n % 2 == 1:
        return float(ordered[n // 2])
    return round((ordered[n // 2 - 1] + ordered[n // 2]) / 2, 2)


def compute(records: list[dict[str, Any]]) -> dict[str, Any]:
    per: dict[str, list[int]] = {s: [] for s in VALID_STATUSES}
    cur_status: str | None = None
    cur_length = 0
    for rec in records:
        raw = rec.get("status")
        if not isinstance(raw, str):
            continue
        status = raw.strip().lower()
        if status not in VALID_STATUSES:
            continue
        if cur_status != status:
            if cur_status is not None:
                per[cur_status].append(cur_length)
            cur_status = status
            cur_length = 1
        else:
            cur_length += 1
    if cur_status is not None:
        per[cur_status].append(cur_length)
    return {
        "schema_version":   1,
        "median_by_status": {s: _median(v) for s, v in per.items()},
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Plan 2.8 ledger median run length per status", ""]
    for s in VALID_STATUSES:
        lines.append(f"- {s}: {report['median_by_status'][s]}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Median run length per status.",
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

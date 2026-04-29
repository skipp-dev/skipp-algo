"""Plan 2.8 ledger unknown ratio.

Mirror of the red/amber/green ratio helpers for ``unknown``
records. Reports the share of ``unknown`` records within the
trailing N entries; ``ratio`` is ``None`` when the window is
empty; ``--last-n 0`` means all records.
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


def compute(records: list[dict[str, Any]], last_n: int) -> dict[str, Any]:
    cleaned: list[str] = []
    for rec in records:
        raw = rec.get("status")
        if not isinstance(raw, str):
            continue
        s = raw.strip().lower()
        if s in VALID_STATUSES:
            cleaned.append(s)
    window = cleaned if last_n <= 0 else cleaned[-last_n:]
    unknown = sum(1 for s in window if s == "unknown")
    ratio: float | None
    ratio = round(unknown / len(window), 4) if window else None
    return {
        "schema_version": 1,
        "last_n":         last_n,
        "window_size":    len(window),
        "unknown_count":  unknown,
        "ratio":          ratio,
    }


def render_markdown(report: dict[str, Any]) -> str:
    ratio = report["ratio"]
    ratio_s = f"{ratio}" if ratio is not None else "n/a"
    return (
        "# Plan 2.8 recent unknown ratio\n"
        "\n"
        f"- last_n: {report['last_n']}\n"
        f"- window_size: {report['window_size']}\n"
        f"- unknown_count: {report['unknown_count']}\n"
        f"- ratio: {ratio_s}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Unknown share over the last N ledger records.",
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--last-n", type=int, default=10)
    parser.add_argument(
        "--fail-above-ratio", type=float, default=None,
        help="Exit 1 if ratio exceeds this value (ignored when n/a).",
    )
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.ledger.exists():
        print(f"ERROR: ledger not found: {args.ledger}", file=sys.stderr)
        return 1

    report = compute(_iter_records(args.ledger), args.last_n)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if (args.fail_above_ratio is not None
            and report["ratio"] is not None
            and report["ratio"] > args.fail_above_ratio):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

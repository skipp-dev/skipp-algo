"""Plan 2.8 ledger status-run min.

Reports the shortest consecutive status run. Ties resolve to
the first occurrence. Records with invalid statuses are
skipped.
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
    best_status: str | None = None
    best_length: int | None = None
    best_start: str | None = None
    best_end: str | None = None
    cur_status: str | None = None
    cur_length = 0
    cur_start: str | None = None
    cur_end: str | None = None

    def _commit() -> None:
        nonlocal best_status, best_length, best_start, best_end
        if cur_status is None:
            return
        if best_length is None or cur_length < best_length:
            best_status = cur_status
            best_length = cur_length
            best_start = cur_start
            best_end = cur_end

    for rec in records:
        raw = rec.get("status")
        if not isinstance(raw, str):
            continue
        status = raw.strip().lower()
        if status not in VALID_STATUSES:
            continue
        ts = rec.get("captured_at")
        ts_val = ts if isinstance(ts, str) and ts else None
        if cur_status != status:
            _commit()
            cur_status = status
            cur_length = 1
            cur_start = ts_val
            cur_end = ts_val
        else:
            cur_length += 1
            if ts_val is not None:
                cur_end = ts_val
                if cur_start is None:
                    cur_start = ts_val
    _commit()
    if best_status is None:
        return {"schema_version": 1, "found": False}
    return {
        "schema_version": 1,
        "found":          True,
        "status":         best_status,
        "length":         best_length,
        "start":          best_start,
        "end":            best_end,
    }


def render_markdown(report: dict[str, Any]) -> str:
    if not report.get("found"):
        return "# Plan 2.8 ledger status-run min\n\n_none_\n"
    start = report["start"] if report["start"] is not None else "_unknown_"
    end = report["end"] if report["end"] is not None else "_unknown_"
    return (
        "# Plan 2.8 ledger status-run min\n"
        "\n"
        f"- status: {report['status']}\n"
        f"- length: {report['length']}\n"
        f"- start: {start}\n"
        f"- end: {end}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Shortest consecutive status run.",
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

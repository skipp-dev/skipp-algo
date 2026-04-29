"""Plan 2.8 ledger status-flip alert.

Reads a Plan 2.8 status ledger (JSONL) and reports *flips* \u2014
points where consecutive valid records have a different status.
Only records within the last ``--weeks`` weeks are considered.

Emits markdown (default) or JSON. Exit code is ``1`` when
``--fail-on-flip`` is set and at least one flip was found.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from itertools import pairwise
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

VALID_STATUSES = frozenset({"green", "amber", "red", "unknown"})


def _parse_ts(raw: str) -> _dt.datetime | None:
    try:
        # tolerate trailing 'Z' or offset
        return _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
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


def detect_flips(
    records: list[dict[str, Any]], *,
    weeks: int, now: _dt.datetime | None = None,
) -> list[dict[str, Any]]:
    if weeks < 0:
        raise ValueError("weeks must be non-negative")
    now_ = now or _dt.datetime.now(tz=_dt.UTC)
    cutoff = now_ - _dt.timedelta(weeks=weeks) if weeks > 0 else None
    in_window: list[dict[str, Any]] = []
    for rec in records:
        raw_status = rec.get("status")
        if not isinstance(raw_status, str):
            continue
        status = raw_status.strip().lower()
        if status not in VALID_STATUSES:
            continue
        if cutoff is not None:
            ts_raw = rec.get("captured_at")
            ts = _parse_ts(ts_raw) if isinstance(ts_raw, str) else None
            if ts is None or ts < cutoff:
                continue
        in_window.append({**rec, "status": status})
    flips: list[dict[str, Any]] = []
    for prev, curr in pairwise(in_window):
        if prev["status"] != curr["status"]:
            flips.append({
                "from":        prev["status"],
                "to":          curr["status"],
                "from_at":     prev.get("captured_at"),
                "to_at":       curr.get("captured_at"),
                "to_run_url":  curr.get("run_url"),
            })
    return flips


def render_markdown(
    flips: list[dict[str, Any]], *, weeks: int,
) -> str:
    lines = [
        f"# Plan 2.8 status flips (last {weeks} wk)",
        "",
        f"- flips: {len(flips)}",
        "",
    ]
    if not flips:
        lines.append("_No status flips detected in the window._")
        return "\n".join(lines) + "\n"
    lines.append("| from | to | at | run |")
    lines.append("| --- | --- | --- | --- |")
    for f in flips:
        run = f.get("to_run_url") or ""
        run_cell = f"[run]({run})" if run else ""
        at = f.get("to_at") or ""
        lines.append(f"| {f['from']} | {f['to']} | {at} | {run_cell} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report Plan 2.8 status-ledger flips.",
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--weeks", type=int, default=12,
                        help="window size (0 = all records)")
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-flip", action="store_true")
    args = parser.parse_args(argv)

    if not args.ledger.exists():
        print(f"ERROR: ledger not found: {args.ledger}", file=sys.stderr)
        return 1
    if args.weeks < 0:
        print("ERROR: --weeks must be non-negative", file=sys.stderr)
        return 1

    records = _iter_records(args.ledger)
    flips = detect_flips(records, weeks=args.weeks)
    if args.format == "md":
        body = render_markdown(flips, weeks=args.weeks)
    else:
        body = json.dumps({
            "schema_version": 1,
            "weeks":          args.weeks,
            "counts":         {"flips": len(flips)},
            "flips":          flips,
        }, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_flip and flips:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

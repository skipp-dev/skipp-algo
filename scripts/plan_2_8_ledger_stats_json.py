"""Plan 2.8 ledger per-period stats.

Buckets ledger records by ISO year-week (default) or by calendar
month and reports status counts per bucket. Pure stdlib, JSON-first.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

VALID_STATUSES = ("green", "amber", "red", "unknown")


def _parse_ts(raw: Any) -> _dt.datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        return _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _bucket_key(ts: _dt.datetime, *, period: str) -> str:
    if period == "month":
        return ts.strftime("%Y-%m")
    if period == "week":
        iso = ts.isocalendar()
        return f"{iso.year:04d}-W{iso.week:02d}"
    raise ValueError(f"unknown period: {period}")


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


def bucket(
    records: list[dict[str, Any]], *, period: str = "week",
) -> dict[str, Any]:
    buckets: OrderedDict[str, dict[str, int]] = OrderedDict()
    skipped = 0
    for rec in records:
        ts = _parse_ts(rec.get("captured_at"))
        raw_status = rec.get("status")
        if ts is None or not isinstance(raw_status, str):
            skipped += 1
            continue
        status = raw_status.strip().lower()
        if status not in VALID_STATUSES:
            status = "unknown"
        key = _bucket_key(ts, period=period)
        slot = buckets.setdefault(key, {s: 0 for s in VALID_STATUSES})
        slot[status] += 1
    # keep deterministic sort
    ordered = OrderedDict(sorted(buckets.items()))
    return {
        "schema_version": 1,
        "period":         period,
        "counts":         {"buckets": len(ordered), "skipped": skipped},
        "buckets":        ordered,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Plan 2.8 ledger stats ({report['period']})",
        "",
        f"- buckets: {report['counts']['buckets']}",
        f"- skipped: {report['counts']['skipped']}",
        "",
    ]
    if not report["buckets"]:
        lines.append("_No bucketed records._")
        return "\n".join(lines) + "\n"
    lines.append("| bucket | green | amber | red | unknown |")
    lines.append("| --- | --- | --- | --- | --- |")
    for key, slot in report["buckets"].items():
        lines.append(
            f"| {key} | {slot['green']} | {slot['amber']} "
            f"| {slot['red']} | {slot['unknown']} |",
        )
    return "\n".join(lines) + "\n"

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
        description="Bucket Plan 2.8 ledger records per week or month.",
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--period", choices=("week", "month"),
                        default="week")
    parser.add_argument("--format", choices=("md", "json"), default="json")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.ledger.exists():
        print(f"ERROR: ledger not found: {args.ledger}", file=sys.stderr)
        return 1

    records = _iter_records(args.ledger)
    report = bucket(records, period=args.period)
    body = render_markdown(report) if args.format == "md" else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

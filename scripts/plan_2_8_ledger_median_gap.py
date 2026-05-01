"""Plan 2.8 ledger median gap.

Reports the median gap (in hours) between consecutive
``captured_at`` timestamps in the ledger. Statistics follow
the standard library (``statistics.median``). Records missing
or with malformed timestamps are skipped. ``median_hours`` is
``None`` when fewer than two usable timestamps exist.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime
from itertools import pairwise
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


def _ts(rec: dict[str, Any]) -> datetime | None:
    raw = rec.get("status")
    if not isinstance(raw, str) or raw.strip().lower() not in VALID_STATUSES:
        return None
    v = rec.get("captured_at")
    if not isinstance(v, str):
        return None
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        return None


def compute(records: list[dict[str, Any]]) -> dict[str, Any]:
    times: list[datetime] = [t for t in (_ts(r) for r in records) if t]
    gaps_h: list[float] = []
    for a, b in pairwise(times):
        delta = (b - a).total_seconds() / 3600.0
        gaps_h.append(delta)
    median_h: float | None
    median_h = round(float(statistics.median(gaps_h)), 4) if gaps_h else None
    return {
        "schema_version":  1,
        "records":         len(times),
        "gaps":            len(gaps_h),
        "median_hours":    median_h,
    }


def render_markdown(report: dict[str, Any]) -> str:
    m = report["median_hours"]
    m_s = f"{m}" if m is not None else "n/a"
    return (
        "# Plan 2.8 ledger median gap\n"
        "\n"
        f"- records: {report['records']}\n"
        f"- gaps: {report['gaps']}\n"
        f"- median_hours: {m_s}\n"
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
        description="Median inter-record gap (hours) in the ledger.",
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument(
        "--fail-above-hours", type=float, default=None,
        help="Exit 1 if median_hours exceeds this value (ignored when n/a).",
    )
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
    if (args.fail_above_hours is not None
            and report["median_hours"] is not None
            and report["median_hours"] > args.fail_above_hours):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

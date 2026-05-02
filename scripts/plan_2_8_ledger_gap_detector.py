"""Plan 2.8 ledger gap-detector.

Walks ledger records in order and reports every gap between
consecutive ``captured_at`` timestamps that exceeds a threshold
in hours. Useful for catching ingestion gaps the uptime/hour
histogram would average away.
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


def compute(
    records: list[dict[str, Any]], *,
    threshold_hours: float,
) -> dict[str, Any]:
    timestamps: list[_dt.datetime] = []
    for rec in records:
        ts = _parse_ts(rec.get("captured_at"))
        if ts is not None:
            timestamps.append(ts.astimezone(_dt.UTC))
    timestamps.sort()
    gaps: list[dict[str, Any]] = []
    for a, b in pairwise(timestamps):
        hours = (b - a).total_seconds() / 3600.0
        if hours > threshold_hours:
            gaps.append({
                "from":  a.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "to":    b.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "hours": round(hours, 2),
            })
    return {
        "schema_version":  1,
        "threshold_hours": threshold_hours,
        "record_count":    len(timestamps),
        "gap_count":       len(gaps),
        "gaps":            gaps,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 ledger gaps",
        "",
        f"- threshold:    {report['threshold_hours']}h",
        f"- record_count: {report['record_count']}",
        f"- gap_count:    {report['gap_count']}",
        "",
        "| from | to | hours |",
        "|---|---|---:|",
    ]
    if report["gaps"]:
        for g in report["gaps"]:
            lines.append(
                f"| {g['from']} | {g['to']} | {g['hours']:.2f} |"
            )
    else:
        lines.append("| _(none)_ | - | 0.00 |")
    lines.append("")
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
        description="Report captured_at gaps exceeding N hours.",
    )
    parser.add_argument("--ledger",          type=Path, required=True)
    parser.add_argument("--threshold-hours", type=float, default=24.0)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-gaps", action="store_true")
    args = parser.parse_args(argv)

    if not args.ledger.exists():
        print(f"ERROR: ledger not found: {args.ledger}", file=sys.stderr)
        return 1

    report = compute(
        _iter_records(args.ledger),
        threshold_hours=args.threshold_hours,
    )
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_gaps and report["gap_count"] > 0:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

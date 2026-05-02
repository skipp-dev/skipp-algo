"""Plan 2.8 uptime-percent calculator.

Uptime is the fraction of time green between consecutive records
in the ledger, over the last ``--weeks`` weeks. Records outside
the window are clipped. Pure stdlib.
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
    weeks: int,
    now: _dt.datetime | None = None,
) -> dict[str, Any]:
    if weeks < 1:
        raise ValueError("weeks must be >= 1")
    now_ = now or _dt.datetime.now(tz=_dt.UTC)
    cutoff = now_ - _dt.timedelta(weeks=weeks)
    clean: list[tuple[_dt.datetime, str]] = []
    for rec in records:
        ts = _parse_ts(rec.get("captured_at"))
        raw = rec.get("status")
        if ts is None or not isinstance(raw, str):
            continue
        status = raw.strip().lower()
        if status not in ("green", "amber", "red", "unknown"):
            continue
        clean.append((ts, status))
    # clip to window by dropping points strictly before the cutoff,
    # but keep the most-recent point before cutoff as the starting
    # anchor (clipped to cutoff) so we don't under-count.
    anchor: tuple[_dt.datetime, str] | None = None
    windowed: list[tuple[_dt.datetime, str]] = []
    for point in clean:
        if point[0] < cutoff:
            anchor = point
            continue
        windowed.append(point)
    if anchor is not None:
        windowed.insert(0, (cutoff, anchor[1]))
    total_seconds = 0.0
    green_seconds = 0.0
    for (t0, s0), (t1, _) in pairwise(windowed):
        span = (t1 - t0).total_seconds()
        if span < 0:
            span = 0.0
        total_seconds += span
        if s0 == "green":
            green_seconds += span
    pct = (green_seconds / total_seconds * 100.0) \
        if total_seconds > 0 else 0.0
    return {
        "schema_version": 1,
        "weeks":           weeks,
        "total_seconds":   total_seconds,
        "green_seconds":   green_seconds,
        "uptime_pct":      round(pct, 2),
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        f"# Plan 2.8 uptime (last {report['weeks']} wk)\n\n"
        f"- uptime:        {report['uptime_pct']:.2f}%\n"
        f"- total seconds: {report['total_seconds']:.0f}\n"
        f"- green seconds: {report['green_seconds']:.0f}\n"
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
        description="Compute green-uptime % over the last N weeks.",
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--weeks", type=int, default=4)
    parser.add_argument("--format", choices=("md", "json"), default="json")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-below", type=float, default=None,
                        help="fail with rc=1 if uptime%% < this value")
    args = parser.parse_args(argv)

    if not args.ledger.exists():
        print(f"ERROR: ledger not found: {args.ledger}", file=sys.stderr)
        return 1
    if args.weeks < 1:
        print("ERROR: --weeks must be >= 1", file=sys.stderr)
        return 1

    records = _iter_records(args.ledger)
    report = compute(records, weeks=args.weeks)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_below is not None \
            and report["uptime_pct"] < args.fail_below:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

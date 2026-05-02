"""Plan 2.8 alert-history heatmap.

Reads ``alert_history.jsonl`` and collapses it into a weekday x
(tf/family) grid, showing where drift alerts concentrate over the
lookback window. Weekdays use ``Mon..Sun`` labels; unknown or
unparseable timestamps are dropped.

Output shapes:

  - markdown: grid with totals per weekday and per tf/family
  - json:     {grid: {"Mon": {"5m/HR": n, ...}, ...},
               tf_family_totals: {...},
               weekday_totals:   {...},
               total: n,
               lookback_days: k or null}

Pure stdlib.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _parse_ts(s: Any) -> _dt.datetime | None:
    if not isinstance(s, str) or not s:
        return None
    try:
        return _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _iter_records(log: Path) -> Iterable[dict[str, Any]]:
    for raw in log.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            yield obj


def heatmap(
    records: Iterable[dict[str, Any]],
    *,
    lookback_days: int | None = None,
    now: _dt.datetime | None = None,
) -> dict[str, Any]:
    now_ = now or _dt.datetime.now(tz=_dt.UTC)
    floor = (now_ - _dt.timedelta(days=lookback_days)
             if lookback_days is not None else None)

    grid: dict[str, dict[str, int]] = {d: {} for d in WEEKDAYS}
    tf_family_totals: dict[str, int] = {}
    weekday_totals: dict[str, int] = {d: 0 for d in WEEKDAYS}
    total = 0

    for rec in records:
        ts = _parse_ts(rec.get("captured_at"))
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=_dt.UTC)
        if floor is not None and ts < floor:
            continue
        tf = str(rec.get("tf", "")).strip()
        fam = str(rec.get("family", "")).strip()
        if not tf or not fam:
            continue
        wd = WEEKDAYS[ts.weekday()]
        key = f"{tf}/{fam}"
        grid[wd][key] = grid[wd].get(key, 0) + 1
        tf_family_totals[key] = tf_family_totals.get(key, 0) + 1
        weekday_totals[wd] += 1
        total += 1

    return {
        "schema_version":   1,
        "lookback_days":    lookback_days,
        "total":            total,
        "grid":             grid,
        "weekday_totals":   weekday_totals,
        "tf_family_totals": tf_family_totals,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Plan 2.8 alert-history heatmap"]
    lb = report["lookback_days"]
    window = f"last {lb} days" if lb is not None else "all time"
    lines.append(f"_window:_ {window}  |  _total:_ {report['total']}")
    lines.append("")
    keys = sorted(report["tf_family_totals"].keys())
    if not keys:
        lines.append("_No alerts in window._")
        return "\n".join(lines) + "\n"
    header = ["weekday", *keys, "total"]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join(["---"] * len(header)) + " |")
    for wd in WEEKDAYS:
        row = [wd]
        for k in keys:
            row.append(str(report["grid"].get(wd, {}).get(k, 0)))
        row.append(str(report["weekday_totals"].get(wd, 0)))
        lines.append("| " + " | ".join(row) + " |")
    # footer totals
    totals_row = ["total"] + [str(report["tf_family_totals"][k]) for k in keys] \
        + [str(report["total"])]
    lines.append("| " + " | ".join(totals_row) + " |")
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
        description="Render a weekday x tf/family heatmap from alert history.",
    )
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--lookback-days", type=int, default=None)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.log.exists():
        print(f"ERROR: alert history log not found: {args.log}",
              file=sys.stderr)
        return 1
    report = heatmap(
        list(_iter_records(args.log)),
        lookback_days=args.lookback_days,
    )
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

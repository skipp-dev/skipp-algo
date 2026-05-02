"""Plan 2.8 N-week rolling HR trend per slice.

Given the long-running history JSONL, for each TF×family slice emit a
compact sparkline-style record showing the HR over the most recent
N week-aligned buckets. Useful for quick "is this slice improving or
degrading?" reads in the monthly digest.

Bucketing uses ISO week (Mon–Sun) in UTC on ``captured_at``. Within a
week the latest snapshot wins. Weeks with no comparable sample
(``n_events < min_events``) are emitted as null.

Pure stdlib, read-only.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def _parse_iso(ts: str) -> _dt.datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return _dt.datetime.fromisoformat(ts)


def _iso_week_monday(ts: _dt.datetime) -> _dt.date:
    # Monday of the ISO week containing `ts` (UTC).
    d = ts.astimezone(_dt.UTC).date()
    return d - _dt.timedelta(days=d.weekday())


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise ValueError(f"history not found: {path}")
    out: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def rollup(
    snapshots: list[dict[str, Any]],
    *,
    weeks: int = 8,
    min_events: int = 30,
) -> dict[str, Any]:
    if not snapshots:
        return {
            "schema_version": 1,
            "status": "empty",
            "weeks": weeks,
            "min_events": min_events,
            "week_keys": [],
            "slices": [],
        }

    # Index snapshots by week-monday → (datetime, snapshot).
    by_week: dict[_dt.date, tuple[_dt.datetime, dict[str, Any]]] = {}
    for s in snapshots:
        try:
            ts = _parse_iso(s["captured_at"])
        except (KeyError, ValueError):
            continue
        wk = _iso_week_monday(ts)
        prev = by_week.get(wk)
        if prev is None or ts > prev[0]:
            by_week[wk] = (ts, s)

    if not by_week:
        return {
            "schema_version": 1,
            "status": "empty",
            "weeks": weeks,
            "min_events": min_events,
            "week_keys": [],
            "slices": [],
        }

    week_keys_sorted = sorted(by_week.keys())[-weeks:]

    # Enumerate all (tf, family) pairs that appear in any selected week.
    pairs: set[tuple[str, str]] = set()
    for wk in week_keys_sorted:
        per_tf = (by_week[wk][1].get("per_tf") or {})
        for tf, row in per_tf.items():
            for fam in (row or {}).get("families", {}):
                pairs.add((tf, fam))

    slices: list[dict[str, Any]] = []
    for (tf, fam) in sorted(pairs):
        series: list[float | None] = []
        for wk in week_keys_sorted:
            snap = by_week[wk][1]
            fams = ((snap.get("per_tf") or {}).get(tf) or {}).get("families") or {}
            bucket = fams.get(fam) or {}
            n = bucket.get("n_events") or 0
            hr = bucket.get("hit_rate")
            if hr is None or n < min_events:
                series.append(None)
            else:
                series.append(round(float(hr), 6))
        seen = [x for x in series if x is not None]
        if not seen:
            trend_pp = None
            latest = None
        else:
            trend_pp = round(seen[-1] - seen[0], 6) if len(seen) >= 2 else 0.0
            latest = seen[-1]
        slices.append({
            "tf": tf,
            "family": fam,
            "series": series,
            "observed": len(seen),
            "trend_pp": trend_pp,
            "latest": latest,
        })
    return {
        "schema_version": 1,
        "status": "ok",
        "weeks": weeks,
        "min_events": min_events,
        "week_keys": [wk.isoformat() for wk in week_keys_sorted],
        "slices": slices,
    }


def _sparkline(series: list[float | None]) -> str:
    # 8-level ramp plus '.' for missing weeks.
    ramp = "▁▂▃▄▅▆▇█"
    present = [x for x in series if x is not None]
    if not present:
        return "." * len(series)
    lo = min(present)
    hi = max(present)
    span = hi - lo
    out = []
    for v in series:
        if v is None:
            out.append(".")
        elif span == 0:
            out.append(ramp[len(ramp) // 2])
        else:
            idx = int((v - lo) / span * (len(ramp) - 1))
            out.append(ramp[idx])
    return "".join(out)


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Plan 2.8 rolling HR trend"]
    lines.append("")
    if report["status"] != "ok":
        lines.append(f"_status:_ **{report['status']}**")
        return "\n".join(lines) + "\n"
    lines.append(f"- weeks:      last {report['weeks']} "
                 f"(week keys: {', '.join(report['week_keys'])})")
    lines.append(f"- min_events: {report['min_events']}")
    lines.append("")
    lines.append("| tf | family | trend | latest | trend_pp | series |")
    lines.append("|----|--------|------:|-------:|---------:|--------|")
    for s in report["slices"]:
        trend = _sparkline(s["series"])
        latest = "-" if s["latest"] is None else f"{s['latest']:.4f}"
        trend_pp = "-" if s["trend_pp"] is None else f"{s['trend_pp']:+.4f}"
        lines.append(
            f"| {s['tf']} | {s['family']} | `{trend}` | {latest} | "
            f"{trend_pp} | {s['observed']}/{len(s['series'])} |"
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
        description="Plan 2.8 N-week rolling HR trend per slice.",
    )
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--weeks", type=int, default=8)
    parser.add_argument("--min-events", type=int, default=30)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        snaps = _read_jsonl(args.history)
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    report = rollup(snaps, weeks=args.weeks, min_events=args.min_events)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

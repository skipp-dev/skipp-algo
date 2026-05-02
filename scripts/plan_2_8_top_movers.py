"""Summarize top / bottom HR movers across a Plan 2.8 history JSONL.

For a weekly or monthly retro, it's useful to know which TF×family
slices moved the most HR since the first snapshot in the lookback
window. This helper walks the history, picks the earliest + latest
snapshot inside the window, and ranks slices by ``|delta_pp|``.

Pure stdlib. Read-only.
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


def _endpoints(
    snapshots: list[dict[str, Any]],
    *,
    lookback_days: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Pick (earliest-in-window, latest) by captured_at."""
    if not snapshots:
        return None, None
    parsed: list[tuple[_dt.datetime, dict[str, Any]]] = []
    for s in snapshots:
        try:
            parsed.append((_parse_iso(s["captured_at"]), s))
        except (KeyError, ValueError):
            continue
    if not parsed:
        return None, None
    parsed.sort(key=lambda t: t[0])
    latest_ts, latest = parsed[-1]
    cutoff = latest_ts - _dt.timedelta(days=lookback_days)
    in_window = [(t, s) for (t, s) in parsed if t >= cutoff]
    if len(in_window) < 2:
        return None, latest
    earliest = in_window[0][1]
    return earliest, latest


def _gather_slices(snap: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """Return ``{(tf, family): {n_events, hit_rate}}``."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    per_tf = snap.get("per_tf") or {}
    for tf, row in per_tf.items():
        for fam, fam_row in (row.get("families") or {}).items():
            out[(tf, fam)] = {
                "n_events": fam_row.get("n_events"),
                "hit_rate": fam_row.get("hit_rate"),
            }
    return out


def top_movers(
    snapshots: list[dict[str, Any]],
    *,
    lookback_days: int = 30,
    min_events: int = 30,
    top_n: int = 5,
) -> dict[str, Any]:
    earliest, latest = _endpoints(snapshots, lookback_days=lookback_days)
    if earliest is None or latest is None:
        return {
            "schema_version": 1,
            "status": "empty" if latest is None else "warmup",
            "lookback_days": lookback_days,
            "min_events": min_events,
            "top_n": top_n,
            "earliest_captured_at": earliest["captured_at"] if earliest else None,
            "latest_captured_at":   latest["captured_at"]   if latest   else None,
            "gainers": [],
            "losers": [],
        }
    prev_slices   = _gather_slices(earliest)
    latest_slices = _gather_slices(latest)
    rows: list[dict[str, Any]] = []
    for key in sorted(set(prev_slices) | set(latest_slices)):
        p = prev_slices.get(key) or {}
        lat = latest_slices.get(key) or {}
        hr_p, hr_l = p.get("hit_rate"), lat.get("hit_rate")
        n_p, n_l = p.get("n_events") or 0, lat.get("n_events") or 0
        if hr_p is None or hr_l is None:
            continue
        comparable = n_p >= min_events and n_l >= min_events
        rows.append({
            "tf": key[0], "family": key[1],
            "hr_prev": hr_p, "hr_latest": hr_l,
            "delta_pp": hr_l - hr_p,
            "n_prev": n_p, "n_latest": n_l,
            "comparable": comparable,
        })
    comparable_rows = [r for r in rows if r["comparable"]]
    gainers = sorted(comparable_rows, key=lambda r: r["delta_pp"], reverse=True)[:top_n]
    losers  = sorted(comparable_rows, key=lambda r: r["delta_pp"])[:top_n]
    return {
        "schema_version": 1,
        "status": "ok",
        "lookback_days": lookback_days,
        "min_events": min_events,
        "top_n": top_n,
        "earliest_captured_at": earliest["captured_at"],
        "latest_captured_at":   latest["captured_at"],
        "gainers": gainers,
        "losers":  losers,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Plan 2.8 top movers"]
    lines.append("")
    if report["status"] != "ok":
        lines.append(f"_status:_ **{report['status']}** "
                     f"(lookback={report['lookback_days']}d)")
        return "\n".join(lines) + "\n"
    lines.append(f"- window: `{report['earliest_captured_at']}` .. "
                 f"`{report['latest_captured_at']}`")
    lines.append(f"- lookback_days: {report['lookback_days']}")
    lines.append(f"- min_events:    {report['min_events']}")
    lines.append("")
    for title, rows in (("Gainers", report["gainers"]),
                         ("Losers",  report["losers"])):
        lines.append(f"## {title}")
        lines.append("")
        if not rows:
            lines.append("- _none (no comparable slices)_")
            lines.append("")
            continue
        lines.append("| tf | family | hr_prev | hr_latest | delta_pp | n_prev | n_latest |")
        lines.append("|----|--------|--------:|----------:|---------:|-------:|---------:|")
        for r in rows:
            lines.append(
                f"| {r['tf']} | {r['family']} | {r['hr_prev']:.3f} | "
                f"{r['hr_latest']:.3f} | {r['delta_pp']:+.3f} | "
                f"{r['n_prev']} | {r['n_latest']} |"
            )
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
        description="Rank top / bottom HR movers in a Plan 2.8 history JSONL.",
    )
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--min-events",    type=int, default=30)
    parser.add_argument("--top-n",         type=int, default=5)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        snapshots = _read_jsonl(args.history)
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    report = top_movers(
        snapshots,
        lookback_days=args.lookback_days,
        min_events=args.min_events,
        top_n=args.top_n,
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

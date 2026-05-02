"""Summarize Plan 2.8 slice coverage against a ``min_events`` floor.

For a given history JSONL, look at the **latest** snapshot and
enumerate every TF×family bucket, flagging which ones are below a
configurable events floor. Output is designed to feed into onboarding
checks ("am I capturing enough signal for a valid verdict?") and into
the weekly digest as a sanity sidebar.

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


def _latest(snapshots: list[dict[str, Any]]) -> dict[str, Any] | None:
    parsed: list[tuple[_dt.datetime, dict[str, Any]]] = []
    for s in snapshots:
        try:
            parsed.append((_parse_iso(s["captured_at"]), s))
        except (KeyError, ValueError):
            continue
    if not parsed:
        return None
    parsed.sort(key=lambda t: t[0])
    return parsed[-1][1]


def coverage_report(
    snapshots: list[dict[str, Any]],
    *,
    min_events: int = 30,
) -> dict[str, Any]:
    latest = _latest(snapshots)
    if latest is None:
        return {
            "schema_version": 1,
            "status": "empty",
            "min_events": min_events,
            "latest_captured_at": None,
            "slices": [],
            "under_threshold": [],
            "counts": {"total": 0, "ok": 0, "under": 0},
        }
    slices: list[dict[str, Any]] = []
    under: list[dict[str, Any]] = []
    per_tf = latest.get("per_tf") or {}
    for tf in sorted(per_tf):
        row = per_tf[tf] or {}
        fams = row.get("families") or {}
        for fam in sorted(fams):
            n = (fams[fam] or {}).get("n_events") or 0
            ok = n >= min_events
            entry = {"tf": tf, "family": fam, "n_events": n, "ok": ok}
            slices.append(entry)
            if not ok:
                under.append(entry)
    return {
        "schema_version": 1,
        "status": "ok",
        "min_events": min_events,
        "latest_captured_at": latest.get("captured_at"),
        "slices": slices,
        "under_threshold": under,
        "counts": {
            "total": len(slices),
            "ok": sum(1 for s in slices if s["ok"]),
            "under": len(under),
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Plan 2.8 slice coverage"]
    lines.append("")
    if report["status"] != "ok":
        lines.append(f"_status:_ **{report['status']}**")
        return "\n".join(lines) + "\n"
    c = report["counts"]
    lines.append(f"- latest snapshot: `{report['latest_captured_at']}`")
    lines.append(f"- min_events:      {report['min_events']}")
    lines.append(f"- slices:          total={c['total']}, ok={c['ok']}, "
                 f"under={c['under']}")
    lines.append("")
    if report["under_threshold"]:
        lines.append("## Under threshold")
        lines.append("")
        lines.append("| tf | family | n_events |")
        lines.append("|----|--------|---------:|")
        for s in report["under_threshold"]:
            lines.append(f"| {s['tf']} | {s['family']} | {s['n_events']} |")
    else:
        lines.append("All slices at or above `min_events`. No action needed.")
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
        description="Summarize Plan 2.8 slice coverage in a history JSONL.",
    )
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--min-events", type=int, default=30)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-under", action="store_true",
                        help="Exit 1 when any slice is under the floor.")
    args = parser.parse_args(argv)

    try:
        snapshots = _read_jsonl(args.history)
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    report = coverage_report(snapshots, min_events=args.min_events)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_under and report["counts"].get("under", 0):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

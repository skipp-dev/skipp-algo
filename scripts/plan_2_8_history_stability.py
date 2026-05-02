"""Plan 2.8 slice stability metric — HR variability over the last N snapshots.

For each TF×family slice, look back over the last ``--window`` snapshots
and compute:
  - `n`:         how many comparable snapshots contributed (n_events >= floor)
  - `hr_mean`:   simple mean of `hit_rate`
  - `hr_stddev`: population stddev of `hit_rate`
  - `hr_range`:  max-min of `hit_rate`
  - `stable`:    True when n >= ``--min-samples`` and hr_stddev <= ``--stddev-threshold``

Stability reports help surface slices whose calibration jumps week to
week even when no single alert fires. Pure stdlib, read-only.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import statistics
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


def _sorted_recent(
    snapshots: list[dict[str, Any]], window: int,
) -> list[dict[str, Any]]:
    parsed: list[tuple[_dt.datetime, dict[str, Any]]] = []
    for s in snapshots:
        try:
            parsed.append((_parse_iso(s["captured_at"]), s))
        except (KeyError, ValueError):
            continue
    parsed.sort(key=lambda t: t[0])
    return [s for _, s in parsed[-window:]]


def stability_report(
    snapshots: list[dict[str, Any]],
    *,
    window: int = 8,
    min_events: int = 30,
    min_samples: int = 3,
    stddev_threshold: float = 0.03,
) -> dict[str, Any]:
    recent = _sorted_recent(snapshots, window)
    if not recent:
        return {
            "schema_version": 1,
            "status": "empty",
            "window": window,
            "min_events": min_events,
            "min_samples": min_samples,
            "stddev_threshold": stddev_threshold,
            "slices": [],
            "unstable": [],
            "counts": {"total": 0, "stable": 0, "unstable": 0, "warmup": 0},
        }
    # Per-(tf,family) HR series across recent snapshots.
    series: dict[tuple[str, str], list[float]] = {}
    for snap in recent:
        per_tf = snap.get("per_tf") or {}
        for tf, row in per_tf.items():
            fams = (row or {}).get("families") or {}
            for fam, bucket in fams.items():
                bucket = bucket or {}
                if (bucket.get("n_events") or 0) < min_events:
                    continue
                hr = bucket.get("hit_rate")
                if hr is None:
                    continue
                series.setdefault((tf, fam), []).append(float(hr))

    slices: list[dict[str, Any]] = []
    unstable: list[dict[str, Any]] = []
    warmup_count = 0
    for (tf, fam), hrs in sorted(series.items()):
        n = len(hrs)
        hr_mean = statistics.fmean(hrs) if hrs else 0.0
        hr_stddev = statistics.pstdev(hrs) if n >= 2 else 0.0
        hr_range = (max(hrs) - min(hrs)) if hrs else 0.0
        if n < min_samples:
            warmup_count += 1
            stable = None
        else:
            stable = hr_stddev <= stddev_threshold
        entry = {
            "tf": tf,
            "family": fam,
            "n": n,
            "hr_mean": round(hr_mean, 6),
            "hr_stddev": round(hr_stddev, 6),
            "hr_range": round(hr_range, 6),
            "stable": stable,
        }
        slices.append(entry)
        if stable is False:
            unstable.append(entry)
    return {
        "schema_version": 1,
        "status": "ok",
        "window": window,
        "min_events": min_events,
        "min_samples": min_samples,
        "stddev_threshold": stddev_threshold,
        "snapshots_seen": len(recent),
        "slices": slices,
        "unstable": unstable,
        "counts": {
            "total": len(slices),
            "stable": sum(1 for s in slices if s["stable"] is True),
            "unstable": len(unstable),
            "warmup": warmup_count,
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Plan 2.8 slice stability"]
    lines.append("")
    if report["status"] != "ok":
        lines.append(f"_status:_ **{report['status']}**")
        return "\n".join(lines) + "\n"
    c = report["counts"]
    lines.append(f"- window:           last {report['window']} snapshots "
                 f"(seen: {report['snapshots_seen']})")
    lines.append(f"- min_events floor: {report['min_events']}")
    lines.append(f"- min_samples:      {report['min_samples']}")
    lines.append(f"- stddev threshold: {report['stddev_threshold']}")
    lines.append(f"- slices:           total={c['total']}, "
                 f"stable={c['stable']}, unstable={c['unstable']}, "
                 f"warmup={c['warmup']}")
    lines.append("")
    if report["unstable"]:
        lines.append("## Unstable slices")
        lines.append("")
        lines.append("| tf | family | n | hr_mean | hr_stddev | hr_range |")
        lines.append("|----|--------|--:|--------:|----------:|---------:|")
        for s in report["unstable"]:
            lines.append(
                f"| {s['tf']} | {s['family']} | {s['n']} | "
                f"{s['hr_mean']:.4f} | {s['hr_stddev']:.4f} | "
                f"{s['hr_range']:.4f} |"
            )
    else:
        lines.append("No slices exceed the stddev threshold. All calm.")
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
        description="Compute Plan 2.8 slice stability over recent snapshots.",
    )
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--window", type=int, default=8)
    parser.add_argument("--min-events", type=int, default=30)
    parser.add_argument("--min-samples", type=int, default=3)
    parser.add_argument("--stddev-threshold", type=float, default=0.03)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-unstable", action="store_true")
    args = parser.parse_args(argv)

    try:
        snapshots = _read_jsonl(args.history)
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    report = stability_report(
        snapshots,
        window=args.window,
        min_events=args.min_events,
        min_samples=args.min_samples,
        stddev_threshold=args.stddev_threshold,
    )
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    if args.fail_on_unstable and report["counts"].get("unstable", 0):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

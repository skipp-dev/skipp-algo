"""Diagnose session-bucket integrity for FVG events emitted by the
measurement benchmark.

Closes the deferred ASIA-inversion ToDo from
``docs/FVG_LABEL_AUDIT_Q3.md`` §5b.2 by quantifying *what* the ASIA
sample actually contains. The benchmark's ASIA bucket comes from
session-classifying each FVG event's anchor timestamp; if every "ASIA"
event happens to fall on a synthetic resampled bar at exactly midnight
UTC, the bucket is a session-misclassification artifact rather than a
real ASIA-session signal.

Usage::

    python scripts/fvg_session_artifact_diagnosis.py \
        --root artifacts/ci/measurement_benchmark_2026-04-22_partial50_v3

Reports per-session counts, the share of events whose anchor timestamp
is exactly 00:00:00 UTC ("midnight artifact"), and per-timeframe
breakouts so the source of any inversion is visible.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_ROOT = Path("artifacts/ci/measurement_benchmark_2026-04-22_partial50_v3")


def _iter_events(root: Path) -> Iterable[dict]:
    for fp in sorted(root.glob("*/*/events_*.jsonl")):
        for line in fp.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _is_midnight_utc(ts_epoch: float) -> bool:
    dt = datetime.fromtimestamp(float(ts_epoch), tz=UTC)
    return (dt.hour, dt.minute, dt.second) == (0, 0, 0)


def diagnose(root: Path) -> dict:
    by_session: Counter = Counter()
    by_session_midnight: Counter = Counter()
    by_session_tf: defaultdict = defaultdict(Counter)

    for event in _iter_events(root):
        if event.get("family") != "FVG":
            continue
        ctx = event.get("context") or {}
        session = str(ctx.get("session", "?"))
        tf = str(event.get("timeframe", "?"))
        ts = event.get("timestamp")
        by_session[session] += 1
        by_session_tf[session][tf] += 1
        if ts is not None and _is_midnight_utc(ts):
            by_session_midnight[session] += 1

    sessions = sorted(by_session)
    total = sum(by_session.values())
    rows = []
    for session in sessions:
        n = by_session[session]
        midnight = by_session_midnight[session]
        midnight_pct = midnight / n if n else 0.0
        artifact_flag = (
            "ARTIFACT" if n > 0 and midnight_pct >= 0.95 else "ok"
        )
        rows.append(
            {
                "session": session,
                "n_events": n,
                "midnight_utc_n": midnight,
                "midnight_utc_pct": round(midnight_pct, 4),
                "tf_breakout": dict(by_session_tf[session]),
                "verdict": artifact_flag,
            }
        )

    return {
        "source_root": str(root),
        "n_fvg_events_total": total,
        "per_session": rows,
    }


def _print_md(report: dict) -> None:
    print("# FVG session-bucket integrity\n")
    print(f"Source: `{report['source_root']}`")
    print(f"Total FVG events: {report['n_fvg_events_total']}\n")
    print("| Session | n | midnight-UTC n | midnight-UTC % | TF breakout | Verdict |")
    print("|---|---:|---:|---:|---|---|")
    for row in report["per_session"]:
        tf_str = ", ".join(
            f"{tf}:{c}" for tf, c in sorted(row["tf_breakout"].items())
        )
        print(
            f"| {row['session']} | {row['n_events']} | "
            f"{row['midnight_utc_n']} | "
            f"{row['midnight_utc_pct'] * 100:.1f}% | "
            f"{tf_str} | {row['verdict']} |"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--format", choices=["json", "md"], default="md")
    args = parser.parse_args(argv)

    if not args.root.exists():
        print(f"ERROR: root not found: {args.root}")
        return 1

    report = diagnose(args.root)
    if args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        _print_md(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Aggregate the §15 regime-weight shadow so the wire-or-not decision has data.

`open_prep/regime_shadow.py` (#4106) stamps ``regime_weight_shadow`` /
``symbol_regime_at_scoring`` onto every ranked row — but until this reader no
process ever consumed them (verified 2026-07-28): the measurement existed with
no operating lever. This CLI folds any number of run payloads into the summary
the decision needs: how often the measured regime is non-NEUTRAL, and how much
score would have moved had §15 been live.

Read-only; consumes ``artifacts/open_prep/runs/run_*.json`` and/or
``artifacts/open_prep/latest/latest_open_prep_run.json`` (both carry
``ranked_v2`` rows). Exit 0 always — it is a report, not a gate.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path
from typing import Any

DEFAULT_GLOBS = (
    "artifacts/open_prep/runs/run_*.json",
    "artifacts/open_prep/latest/latest_open_prep_run.json",
)


def _rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    rows = payload.get("ranked_v2")
    if not isinstance(rows, list):
        rows = payload.get("ranked") if isinstance(payload.get("ranked"), list) else []
    return [r for r in rows if isinstance(r, dict) and isinstance(r.get("regime_weight_shadow"), dict)]


def summarize(paths: list[Path]) -> dict[str, Any]:
    regimes: dict[str, int] = {}
    deltas: list[float] = []
    movers: list[tuple[float, str, str]] = []
    files_with_rows = 0
    total_rows = 0
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows = _rows_from_payload(payload)
        if not rows:
            continue
        files_with_rows += 1
        for row in rows:
            shadow = row["regime_weight_shadow"]
            total_rows += 1
            regime = str(shadow.get("measured_regime") or "?")
            regimes[regime] = regimes.get(regime, 0) + 1
            delta = shadow.get("score_delta")
            if isinstance(delta, (int, float)):
                deltas.append(float(delta))
                if delta:
                    movers.append((abs(float(delta)), str(row.get("symbol") or "?"), regime))
    movers.sort(reverse=True)
    non_neutral = total_rows - regimes.get("NEUTRAL", 0)
    return {
        "files_scanned": len(paths),
        "files_with_shadow_rows": files_with_rows,
        "rows": total_rows,
        "measured_regime_counts": dict(sorted(regimes.items())),
        "non_neutral_share": round(non_neutral / total_rows, 4) if total_rows else None,
        "would_change_share": (
            round(sum(1 for d in deltas if d) / total_rows, 4) if total_rows else None
        ),
        "mean_abs_score_delta": (
            round(sum(abs(d) for d in deltas) / len(deltas), 4) if deltas else None
        ),
        "max_abs_score_delta": round(max((abs(d) for d in deltas), default=0.0), 4),
        "top_movers": [
            {"symbol": s, "regime": r, "abs_score_delta": round(a, 4)}
            for a, s, r in movers[:10]
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "paths", nargs="*",
        help=f"Run-payload JSON files/globs (default: {', '.join(DEFAULT_GLOBS)})",
    )
    args = parser.parse_args(argv)
    patterns = args.paths or list(DEFAULT_GLOBS)
    files = sorted({Path(p) for pat in patterns for p in glob.glob(pat)})
    summary = summarize(files)
    json.dump(summary, sys.stdout, indent=2)
    print()
    if summary["rows"] == 0:
        print(
            "No shadow rows found — either no run payloads at the given paths, "
            "or they predate the #4106 shadow fields.", file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

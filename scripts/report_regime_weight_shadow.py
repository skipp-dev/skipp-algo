"""Aggregate exact §15 scorer replays for the wire-or-not decision.

Read-only; consumes open-prep run payloads. Exit 0 always because this is a
report, never an activation gate.
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
    summary = payload.get("regime_weight_shadow_summary")
    if isinstance(summary, dict) and isinstance(summary.get("comparisons"), list):
        return [
            {
                "symbol": comparison.get("symbol"),
                "regime_weight_shadow": comparison,
            }
            for comparison in summary["comparisons"]
            if isinstance(comparison, dict)
        ]
    rows = payload.get("ranked_v2")
    if not isinstance(rows, list):
        rows = payload.get("ranked") if isinstance(payload.get("ranked"), list) else []
    return [
        row for row in rows
        if isinstance(row, dict) and isinstance(row.get("regime_weight_shadow"), dict)
    ]


def summarize(paths: list[Path]) -> dict[str, Any]:
    regimes: dict[str, int] = {}
    deltas: list[float] = []
    movers: list[tuple[float, str, str]] = []
    files_with_rows = 0
    total_rows = 0
    exact_rows = 0
    unresolved_rows = 0
    rank_changed_rows = 0
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
            if shadow.get("exact_second_scorer_pass") is not True:
                unresolved_rows += 1
                continue
            exact_rows += 1
            rank_delta = shadow.get("rank_delta")
            if isinstance(rank_delta, int) and rank_delta != 0:
                rank_changed_rows += 1
            regime = str(shadow.get("measured_regime") or "?")
            regimes[regime] = regimes.get(regime, 0) + 1
            delta = shadow.get("score_delta")
            if isinstance(delta, (int, float)):
                deltas.append(float(delta))
                if delta:
                    movers.append((abs(float(delta)), str(row.get("symbol") or "?"), regime))
    movers.sort(reverse=True)
    non_neutral = exact_rows - regimes.get("NEUTRAL", 0)
    return {
        "files_scanned": len(paths),
        "files_with_shadow_rows": files_with_rows,
        "rows": total_rows,
        "exact_rows": exact_rows,
        "unresolved_rows": unresolved_rows,
        "rank_changed_rows": rank_changed_rows,
        "measured_regime_counts": dict(sorted(regimes.items())),
        "non_neutral_share": round(non_neutral / exact_rows, 4) if exact_rows else None,
        "would_change_share": (
            round(sum(1 for delta in deltas if delta) / exact_rows, 4)
            if exact_rows else None
        ),
        "mean_abs_score_delta": (
            round(sum(abs(delta) for delta in deltas) / len(deltas), 4)
            if deltas else None
        ),
        "max_abs_score_delta": round(max((abs(delta) for delta in deltas), default=0.0), 4),
        "top_movers": [
            {"symbol": symbol, "regime": regime, "abs_score_delta": round(delta, 4)}
            for delta, symbol, regime in movers[:10]
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
    files = sorted({Path(path) for pattern in patterns for path in glob.glob(pattern)})
    summary = summarize(files)
    json.dump(summary, sys.stdout, indent=2)  # ATOMIC-WRITE-EXEMPT: stdout report
    print()
    if summary["rows"] == 0:
        print("No exact shadow rows found.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

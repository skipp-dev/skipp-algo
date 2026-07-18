"""Evaluate the private OPRA shadow ledger without treating missing evidence as zero."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

_US_EASTERN = ZoneInfo("America/New_York")


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float] | None:
    if total <= 0:
        return None
    p = successes / total
    denominator = 1.0 + z * z / total
    center = (p + z * z / (2.0 * total)) / denominator
    radius = z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * total)) / total) / denominator
    return max(0.0, center - radius), min(1.0, center + radius)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile
    low = math.floor(index)
    high = math.ceil(index)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - index) + ordered[high] * (index - low)


def _time_slice(row: dict[str, Any]) -> str:
    raw = str(row.get("observed_at") or "")
    try:
        observed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if observed.tzinfo is None:
            return "unknown"
        local = observed.astimezone(_US_EASTERN)
    except ValueError:
        return "unknown"
    if local.hour < 12:
        return "open"
    if local.hour < 15:
        return "midday"
    return "close"


def load_ledger(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return rows
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("shadow_only") is True:
            rows.append(value)
    return rows


def evaluate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    sessions = sorted({str(row.get("session")) for row in rows if row.get("session")})
    latencies = [
        max(0.0, float(row["data_age_seconds"]))
        for row in rows
        if row.get("data_age_seconds") is not None
    ]
    known_definitions = sum(row.get("definition_known") is True for row in rows)
    unknown_definitions = sum(row.get("definition_known") is False for row in rows)
    outcomes = [row for row in rows if isinstance(row.get("outcome_success"), bool)]
    ablations: dict[str, dict[str, Any]] = {}
    for name in ("premium", "aggressor", "cluster", "full"):
        selected = [row for row in outcomes if (row.get("ablation") or {}).get(name) is True]
        successes = sum(row["outcome_success"] is True for row in selected)
        interval = wilson_interval(successes, len(selected))
        ablations[name] = {
            "observations": len(selected),
            "successes": successes,
            "success_rate": successes / len(selected) if selected else None,
            "confidence_interval_95": list(interval) if interval else None,
        }
    slices: dict[str, int] = defaultdict(int)
    for row in rows:
        slices[_time_slice(row)] += 1
    session_gate = len(sessions) >= 7
    outcome_gate = bool(outcomes)
    return {
        "version": "opra-shadow-evaluation/v1",
        "decision": "insufficient_evidence"
        if not (session_gate and outcome_gate)
        else "ready_for_human_review",
        "sessions": sessions,
        "session_count": len(sessions),
        "minimum_session_gate_met": session_gate,
        "records": len(rows),
        "latency_seconds": {
            "p50": median(latencies) if latencies else None,
            "p95": _percentile(latencies, 0.95),
            "p99": _percentile(latencies, 0.99),
        },
        "definition_coverage": (
            known_definitions / (known_definitions + unknown_definitions)
            if known_definitions + unknown_definitions
            else None
        ),
        "duplicates": sum(row.get("duplicate") is True for row in rows),
        "unclassified_gaps": sum(row.get("gap") is True for row in rows),
        "aggressor_signed_share": (
            sum(row.get("aggressor_signed") is True for row in rows) / len(rows)
            if rows
            else None
        ),
        "time_slices": dict(sorted(slices.items())),
        "outcome_observations": len(outcomes),
        "ablations": ablations,
        "gates": {
            "sessions_7_to_10": session_gate,
            "p95_latency_lte_3s": _percentile(latencies, 0.95) <= 3.0 if latencies else None,
            "p99_latency_lte_8s": _percentile(latencies, 0.99) <= 8.0 if latencies else None,
            "definition_coverage_gte_99_5pct": (
                known_definitions / (known_definitions + unknown_definitions) >= 0.995
                if known_definitions + unknown_definitions
                else None
            ),
            "unclassified_gaps_zero": not any(row.get("gap") is True for row in rows)
            if rows
            else None,
            "outcomes_available": outcome_gate,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ledger",
        type=Path,
        default=Path("artifacts/monitoring/opra_shadow_ledger.jsonl"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/monitoring/opra_shadow_summary.json"),
    )
    args = parser.parse_args()
    report = evaluate(load_ledger(args.ledger))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

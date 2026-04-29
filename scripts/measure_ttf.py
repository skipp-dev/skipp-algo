"""Plan §2.1 D3 — FVG time-to-fill measurement (skeleton).

Measures how long (in bars) it takes an FVG event to become fully
mitigated relative to its anchor. The purpose is a one-off empirical
study to decide whether the project-wide ``lookahead_bars`` of 10 is
too tight for the FVG family specifically.

This module is intentionally pure and side-effect free so the business
logic can be unit-tested with synthetic fixtures. The CLI wrapper at
the bottom is a thin I/O shim that reads evaluated FVG events from a
JSON file and writes a distribution summary back out.

Design notes
------------

- A full-mitigation event is defined as the bar index at which price
  fully fills the FVG zone. An event that was never mitigated within
  the provided window is reported with ``time_to_fill = None`` so the
  caller cannot confuse "never filled" with "filled on bar 0".
- The distribution summary intentionally uses simple percentiles
  (``P25 / median / P75 / P90``) rather than a parametric fit —
  percentiles are robust to the small-sample regime we operate in
  (cf. ``smc_core.benchmark._FVG_BUCKET_MIN_EVENTS``).
- The lookahead sensitivity sweep walks the candidate set
  ``{5, 10, 20, 40}`` and reports, for each, how many previously-miss
  events flip to hit. This is the plan's go/no-go gate for raising
  ``lookahead_bars_fvg`` from 10 to something larger.
- Deterministic order: the output preserves the input event order so
  a callsite can join the results back to the original ledger by row
  index. Aggregated counts are sorted by lookahead value ascending.
"""

from __future__ import annotations

import json
from pathlib import Path
from statistics import median
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

DEFAULT_LOOKAHEAD_SWEEP: tuple[int, ...] = (5, 10, 20, 40)


def _percentile(sorted_values: list[int], pct: float) -> int | None:
    """Linear-interpolation percentile on a pre-sorted int list.

    Returns ``None`` for an empty list rather than raising — the
    caller is expected to skip the percentile instead of dying on a
    zero-event symbol.
    """
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = pct * (len(sorted_values) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = rank - lo
    return round(sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac)


def time_to_fill(event: dict[str, Any]) -> int | None:
    """Extract the bar-index offset at which an FVG event was fully filled.

    Accepts the same event shape produced by the measurement-evidence
    pipeline: a dict with at least ``anchor_idx`` (int, anchor bar
    index) and ``mitigation_idx`` (int, bar at which mitigation
    completed; ``None`` if never mitigated within the measurement
    window). Returns the non-negative offset in bars, or ``None`` if
    the event never fully mitigated.
    """
    anchor = event.get("anchor_idx")
    mitigation = event.get("mitigation_idx")
    if mitigation is None:
        return None
    if not isinstance(anchor, (int, float)) or not isinstance(mitigation, (int, float)):
        return None
    offset = int(mitigation) - int(anchor)
    if offset < 0:
        # Corrupted input — treat as unknown rather than silently
        # producing a negative TTF which would poison the distribution.
        return None
    return offset


def distribution_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a P25 / median / P75 / P90 summary of time-to-fill values.

    Buckets ``mitigated_events`` and ``never_filled_events`` counts so
    the operator can always recover the denominator. A symbol with
    zero mitigated events returns ``None`` for every percentile — this
    mirrors the insufficient-bucket convention in ``benchmark.py``.
    """
    ttfs: list[int] = []
    never_filled = 0
    corrupted = 0
    for event in events:
        if not isinstance(event, dict):
            corrupted += 1
            continue
        value = time_to_fill(event)
        if value is None:
            # Either event had no mitigation or the anchor/mitigation
            # indices were unusable. The former is the interesting
            # denominator; the latter is a pipeline bug. Split them.
            if event.get("mitigation_idx") is None:
                never_filled += 1
            else:
                corrupted += 1
            continue
        ttfs.append(value)

    ttfs.sort()
    total_events = len(events)
    return {
        "total_events": total_events,
        "mitigated_events": len(ttfs),
        "never_filled_events": never_filled,
        "corrupted_events": corrupted,
        "p25": _percentile(ttfs, 0.25),
        "median": int(median(ttfs)) if ttfs else None,
        "p75": _percentile(ttfs, 0.75),
        "p90": _percentile(ttfs, 0.90),
        "min": ttfs[0] if ttfs else None,
        "max": ttfs[-1] if ttfs else None,
    }


def lookahead_sensitivity(
    events: list[dict[str, Any]],
    lookaheads: tuple[int, ...] = DEFAULT_LOOKAHEAD_SWEEP,
) -> dict[str, Any]:
    """For each lookahead in the sweep, count how many events would be
    labelled ``hit=True``.

    The current project default is ``lookahead=10``. The D3 gate in
    the plan asks whether raising this threshold *for FVG only* lifts
    the hit rate by more than +5 percentage points. The caller must
    compare the resulting hit rates to make that decision — this
    function only produces the raw counts so the decision stays
    auditable in the calibration report.
    """
    total = len(events)
    per_lookahead: list[dict[str, Any]] = []
    for lookahead in sorted(set(lookaheads)):
        hits = 0
        for event in events:
            if not isinstance(event, dict):
                continue
            ttf = time_to_fill(event)
            if ttf is not None and ttf <= lookahead:
                hits += 1
        hit_rate = round(hits / total, 4) if total else None
        per_lookahead.append(
            {"lookahead": lookahead, "hits": hits, "hit_rate": hit_rate}
        )

    default_rate = next(
        (row["hit_rate"] for row in per_lookahead if row["lookahead"] == 10),
        None,
    )
    return {
        "total_events": total,
        "default_lookahead": 10,
        "default_hit_rate": default_rate,
        "per_lookahead": per_lookahead,
    }


def measure(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Combined entry point — distribution + lookahead sensitivity."""
    return {
        "distribution": distribution_summary(events),
        "lookahead_sensitivity": lookahead_sensitivity(events),
    }


# --- CLI ---


def _load_events(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        # Accept both a bare list and a {"events": [...]} wrapper so
        # this script can be pointed at whatever format a future
        # producer emits without a breaking change.
        payload = payload.get("events", [])
    if not isinstance(payload, list):
        raise ValueError(
            f"Expected a list of FVG events in {path}, got {type(payload).__name__}"
        )
    return payload


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--events", required=True, type=Path, help="Path to JSON file with FVG events"
    )
    parser.add_argument(
        "--output", required=False, type=Path, help="Optional path to write the summary"
    )
    args = parser.parse_args(argv)

    events = _load_events(args.events)
    summary = measure(events)
    text = json.dumps(summary, indent=2, sort_keys=True)
    if args.output:
        atomic_write_text(text + "\n", args.output)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())

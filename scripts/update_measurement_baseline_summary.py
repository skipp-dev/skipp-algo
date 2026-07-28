#!/usr/bin/env python3
"""Roll the deeper-gates evidence summary into the committed measurement baseline.

Wired 2026-07-28 (B-sweep): ``run_smc_release_gates --measurement-baseline-summary``
has existed since the shadow-governance sprint, but NO invocation ever passed it
and evidence summaries lived only as per-run workflow artifacts — so the
regression half of the measurement-shadow governance (the four
``MEASUREMENT_*_REGRESSION`` codes and the history-tightened calibrated
ceilings) was constructively dead while ``docs/MEASUREMENT_LANE.md`` described
it as running "automatically". This script is the missing persistence edge:
the *scheduled* ``smc-deeper-integration-gates`` run merges its fresh evidence
summary into ``reports/smc_measurement_baseline_summary.json`` (committed via
the standard bot-branch auto-merge PR), and every gate invocation reads that
file back through the pre-existing flag.

Merge semantics: per pair, newest-first by ``checked_at``, deduped on
``(checked_at, commit)`` with the current run's version winning, capped at
``--max-rows-per-pair`` so the committed file stays bounded. The output carries
exactly what ``run_smc_release_gates._load_measurement_history_rows`` reads
(``measurement_history.history_by_pair``) plus provenance fields.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from scripts._logging_init import init_cli_logging
from scripts.smc_atomic_write import atomic_write_text

logger = logging.getLogger("scripts.update_measurement_baseline_summary")

DEFAULT_MAX_ROWS_PER_PAIR = 30


def _history_by_pair(payload: Any) -> dict[str, list[dict[str, Any]]]:
    """Extract history_by_pair from a summary payload (lenient, dict rows only)."""
    history = payload.get("measurement_history") if isinstance(payload, dict) else None
    by_pair = history.get("history_by_pair") if isinstance(history, dict) else None
    if not isinstance(by_pair, dict):
        return {}
    extracted: dict[str, list[dict[str, Any]]] = {}
    for pair, rows in by_pair.items():
        if isinstance(rows, list):
            extracted[str(pair)] = [row for row in rows if isinstance(row, dict)]
    return extracted


def _row_key(row: dict[str, Any]) -> tuple[Any, Any]:
    commit = row.get("commit")
    if commit is None:  # synonym key some collectors emit instead of "commit"
        commit = row.get("git_commit")
    return (row.get("checked_at"), commit)


def merge_history(
    current: dict[str, list[dict[str, Any]]],
    baseline: dict[str, list[dict[str, Any]]],
    *,
    max_rows_per_pair: int = DEFAULT_MAX_ROWS_PER_PAIR,
) -> dict[str, list[dict[str, Any]]]:
    """Merge current-run rows over the rolling baseline, newest-first, capped."""
    merged: dict[str, list[dict[str, Any]]] = {}
    for pair in sorted(set(current) | set(baseline)):
        rows: list[dict[str, Any]] = []
        seen: set[tuple[Any, Any]] = set()
        # Current first so a re-extracted row wins over its baseline copy.
        for row in list(current.get(pair, [])) + list(baseline.get(pair, [])):
            key = _row_key(row)
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
        rows.sort(key=lambda r: float(r.get("checked_at") or 0.0), reverse=True)
        merged[pair] = rows[: max(int(max_rows_per_pair), 1)]
    return merged


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--current", required=True, type=Path, help="Fresh evidence summary from this run (required, must parse).")
    parser.add_argument("--baseline", required=True, type=Path, help="Committed rolling baseline (missing/broken -> bootstrap from current).")
    parser.add_argument("--out", required=True, type=Path, help="Output path (atomic write; may equal --baseline).")
    parser.add_argument("--max-rows-per-pair", type=int, default=DEFAULT_MAX_ROWS_PER_PAIR)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        current_payload = json.loads(args.current.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.error("current evidence summary unusable (%s): %s", args.current, exc)
        return 2
    current = _history_by_pair(current_payload)
    if not isinstance(current_payload, dict) or "measurement_history" not in current_payload:
        logger.error("current evidence summary missing measurement_history: %s", args.current)
        return 2

    try:
        baseline_payload = json.loads(args.baseline.read_text(encoding="utf-8"))
        baseline = _history_by_pair(baseline_payload)
    except (OSError, ValueError) as exc:
        # Bootstrap path: first run (or a corrupt committed file) must not
        # block the roll-up — the whole point is to CREATE the history.
        logger.warning("baseline unusable, bootstrapping from current (%s): %s", args.baseline, exc)
        baseline = {}

    merged = merge_history(current, baseline, max_rows_per_pair=args.max_rows_per_pair)
    payload = {
        "report_kind": "measurement_baseline_summary",
        "generated_at_iso": (
            current_payload.get("generated_at_iso") if isinstance(current_payload, dict) else None
        ),
        "updated_from": str(args.current),
        "max_rows_per_pair": int(args.max_rows_per_pair),
        "pairs": sorted(merged),
        "rows_total": sum(len(rows) for rows in merged.values()),
        "measurement_history": {"history_by_pair": merged},
    }
    atomic_write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", args.out)
    logger.info(
        "measurement baseline rolled: %d pair(s), %d row(s) -> %s",
        len(merged), payload["rows_total"], args.out,
    )
    return 0


if __name__ == "__main__":
    init_cli_logging()
    sys.exit(main())

#!/usr/bin/env python3
"""Build one deterministic daily A0-Fast versus FMP parity report."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from open_prep.a0_parity import (
    ShadowDecision,
    build_parity_report,
    match_shadow_decisions,
)
from open_prep.a0_parity_store import load_shadow_decisions
from scripts.smc_atomic_write import atomic_write_json


def build_daily_report(
    *,
    session_date: str,
    fast_paths: list[Path],
    fmp_paths: list[Path],
    matching_window_seconds: float,
    stream_health_by_symbol: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Load, filter and match a single session without wall-clock inputs."""
    date.fromisoformat(session_date)
    fast = _for_session(
        load_shadow_decisions(fast_paths, expected_source="databento"),
        session_date,
        label="Fast",
    )
    fmp = _for_session(
        load_shadow_decisions(fmp_paths, include_core_a0=True),
        session_date,
        label="FMP",
        source_prefix="fmp",
    )
    matches = match_shadow_decisions(
        fast,
        fmp,
        matching_window_seconds=matching_window_seconds,
        stream_health_by_symbol=stream_health_by_symbol,
    )
    return {
        "schema_version": 1,
        "session_date": session_date,
        "matching_window_seconds": float(matching_window_seconds),
        "input_counts": {"fast": len(fast), "fmp": len(fmp)},
        **build_parity_report(matches),
    }


def _for_session(
    decisions: list[ShadowDecision],
    session_date: str,
    *,
    label: str,
    source_prefix: str | None = None,
) -> list[ShadowDecision]:
    missing = [item.decision_id for item in decisions if not item.session_date]
    if missing:
        raise ValueError(f"{label} decision missing session_date: {missing[0]}")
    wrong_source = [
        item.source for item in decisions
        if source_prefix and not item.source.startswith(source_prefix)
    ]
    if wrong_source:
        raise ValueError(f"{label} decision has unexpected source: {wrong_source[0]}")
    return [item for item in decisions if item.session_date == session_date]


def _load_health(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("stream-health file must contain an object")
    return {
        str(symbol).strip().upper(): str(status)
        for symbol, status in payload.items()
        if str(symbol).strip()
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-date", required=True, help="ET session date YYYY-MM-DD")
    parser.add_argument("--fast", required=True, nargs="+", type=Path)
    parser.add_argument("--fmp", required=True, nargs="+", type=Path)
    parser.add_argument("--stream-health", type=Path)
    parser.add_argument("--matching-window-seconds", type=float, default=60.0)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_daily_report(
        session_date=args.session_date,
        fast_paths=args.fast,
        fmp_paths=args.fmp,
        matching_window_seconds=args.matching_window_seconds,
        stream_health_by_symbol=_load_health(args.stream_health),
    )
    atomic_write_json(report, args.output, indent=2, sort_keys=True, fsync=True)
    print(
        f"A0 parity {report['session_date']}: "
        f"{report['matched_same_direction']}/{report['total']} matched"
    )


if __name__ == "__main__":
    main()

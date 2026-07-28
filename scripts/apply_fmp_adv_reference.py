#!/usr/bin/env python3
"""Embed an explicit FMP 15-session ADV into the realtime watchlist snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_json

_ROW_SECTIONS = ("ranked_v2", "filtered_out_v2", "enriched_quotes")


def apply_fmp_adv_reference(
    snapshot: dict[str, Any],
    reference: dict[str, Any],
) -> dict[str, int]:
    """Stamp provider-defined 15-session ADV fields on every candidate row.

    Missing reference rows are represented explicitly with ``None``. The live
    producer treats an explicit missing value fail-closed and never falls back
    to FMP profile ``averageVolume`` with its opaque lookback window.
    """
    seen: set[str] = set()
    covered: set[str] = set()
    for section in _ROW_SECTIONS:
        rows = snapshot.get(section)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            seen.add(symbol)
            ref = reference.get(symbol)
            if isinstance(ref, dict):
                try:
                    adv = float(ref.get("average_daily_volume"))
                except (TypeError, ValueError, OverflowError):
                    adv = 0.0
                if adv >= 1000.0:
                    row["avg_volume_15_session"] = adv
                    row["avg_volume_15_session_as_of"] = str(ref.get("as_of_session") or "")
                    row["avg_volume_15_session_source"] = str(ref.get("source") or "fmp:eod")
                    covered.add(symbol)
                    continue
            row["avg_volume_15_session"] = None
            row["avg_volume_15_session_as_of"] = None
            row["avg_volume_15_session_source"] = "missing:fmp-15-session-eod"
    return {
        "symbols_seen": len(seen),
        "symbols_covered": len(covered),
        "symbols_missing": len(seen - covered),
    }


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    snapshot = _load_object(args.snapshot)
    reference = _load_object(args.reference)
    stats = apply_fmp_adv_reference(snapshot, reference)
    output = args.output or args.snapshot
    atomic_write_json(snapshot, output, indent=2, sort_keys=True, fsync=True)
    print(json.dumps({"output": str(output), **stats}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

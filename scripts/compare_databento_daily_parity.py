"""Compare two daily-bar extracts before retiring a legacy source."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

KEYS = ("symbol", "trade_date")
VALUES = ("open", "high", "low", "close", "volume")


def compare(reference: pd.DataFrame, candidate: pd.DataFrame) -> dict:
    """Return exact coverage plus numeric deltas for a 10x10 parity sample."""
    for name, frame in (("reference", reference), ("candidate", candidate)):
        missing = [column for column in (*KEYS, *VALUES) if column not in frame.columns]
        if missing:
            raise ValueError(f"{name} missing columns: {missing}")
        if frame.duplicated(list(KEYS)).any():
            raise ValueError(f"{name} contains duplicate symbol/trade_date keys")
    merged = reference[list((*KEYS, *VALUES))].merge(
        candidate[list((*KEYS, *VALUES))],
        on=list(KEYS),
        how="outer",
        suffixes=("_reference", "_candidate"),
        indicator=True,
    )
    matched = merged[merged["_merge"] == "both"].copy()
    deltas: dict[str, dict[str, float | None]] = {}
    for column in VALUES:
        left = pd.to_numeric(matched[f"{column}_reference"], errors="coerce")
        right = pd.to_numeric(matched[f"{column}_candidate"], errors="coerce")
        absolute = (right - left).abs()
        denominator = left.abs().replace(0, pd.NA)
        relative = absolute / denominator
        deltas[column] = {
            "max_absolute": float(absolute.max()) if absolute.notna().any() else None,
            "max_relative": float(relative.max()) if relative.notna().any() else None,
            "mean_absolute": float(absolute.mean()) if absolute.notna().any() else None,
        }
    symbols = sorted(set(reference["symbol"].astype(str)) | set(candidate["symbol"].astype(str)))
    dates = sorted(set(reference["trade_date"].astype(str)) | set(candidate["trade_date"].astype(str)))
    dimensions_met = len(symbols) >= 10 and len(dates) >= 10
    matched_sample_met = (
        dimensions_met
        and len(matched) >= 100
        and len(reference) >= 100
        and len(candidate) >= 100
    )
    complete_coverage = matched_sample_met and not (
        (merged["_merge"] != "both").any()
    )
    return {
        "version": "databento-daily-parity/v1",
        "sample": {"symbols": len(symbols), "trade_dates": len(dates)},
        "minimum_10x10_met": dimensions_met,
        "matched_10x10_met": matched_sample_met,
        "complete_coverage": complete_coverage,
        "reference_rows": len(reference),
        "candidate_rows": len(candidate),
        "matched_rows": len(matched),
        "reference_only_rows": int((merged["_merge"] == "left_only").sum()),
        "candidate_only_rows": int((merged["_merge"] == "right_only").sum()),
        "deltas": deltas,
        "status": "ready_for_review" if complete_coverage else "insufficient_evidence",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path, help="legacy daily CSV")
    parser.add_argument("candidate", type=Path, help="EQUS.SUMMARY daily CSV")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = compare(pd.read_csv(args.reference), pd.read_csv(args.candidate))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

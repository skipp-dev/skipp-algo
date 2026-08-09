"""Produce an auditable portfolio position-reconciliation report."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from governance.portfolio_contract import PortfolioSnapshotV1
from governance.portfolio_reconciliation import PortfolioFill, reconcile_portfolio_positions
from scripts.smc_atomic_write import atomic_write_text

PORTFOLIO_RECONCILIATION_SCHEMA_VERSION = "1.0"


def monitoring_report(report: dict) -> dict:
    """Return the non-sensitive reconciliation fields safe for monitoring."""
    return {
        "schema_version": PORTFOLIO_RECONCILIATION_SCHEMA_VERSION,
        "before_captured_at": report["before_captured_at"],
        "after_captured_at": report["after_captured_at"],
        "fill_count": report["fill_count"],
        "duplicate_fill_count": len(report["duplicate_fill_ids"]),
        "max_abs_quantity_delta": report["max_abs_quantity_delta"],
        "reconciled": report["reconciled"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reconcile portfolio snapshots against fills.")
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--fills", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--monitoring-output", type=Path)
    parser.add_argument("--quantity-tolerance", type=float, default=1e-9)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    before = PortfolioSnapshotV1.from_dict(json.loads(args.before.read_text(encoding="utf-8")))
    after = PortfolioSnapshotV1.from_dict(json.loads(args.after.read_text(encoding="utf-8")))
    raw_fills = json.loads(args.fills.read_text(encoding="utf-8"))
    if not isinstance(raw_fills, list):
        raise ValueError("fills input must be a JSON list")
    fills = tuple(PortfolioFill(**row) for row in raw_fills)
    reconciliation = reconcile_portfolio_positions(
        before,
        after,
        fills,
        quantity_tolerance=args.quantity_tolerance,
    )
    report = {
        "schema_version": PORTFOLIO_RECONCILIATION_SCHEMA_VERSION,
        **reconciliation.to_dict(),
    }
    atomic_write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n",
        args.output,
        fsync=True,
    )
    if args.monitoring_output is not None:
        atomic_write_text(
            json.dumps(monitoring_report(report), sort_keys=True, indent=2) + "\n",
            args.monitoring_output,
            fsync=True,
        )
    print(json.dumps(report, sort_keys=True))
    return 0 if reconciliation.reconciled else 2


if __name__ == "__main__":
    raise SystemExit(main())

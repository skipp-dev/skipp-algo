"""Produce ``regime_stratified_<date>.json`` from the persisted returns series.

ADR-0031: first production caller of the Sprint-C5 inference layer.
Consumes the ``trades`` block written by
:mod:`scripts.build_returns_series` (Variant-A net returns given a
triggered setup, tagged with the point-in-time TRENDING/RANGING/NEUTRAL
regime) and assembles the per-regime report the C5 plan (§T7) specified,
using only the tested library:

* per-regime blocks — :func:`scripts.regime_stratification.compute_regime_conditional_metrics`
  (sharpe / max_dd / win_rate / profit_factor, ``regime_frequency_pct``,
  honest ``skipped_reason: insufficient_n`` below the 30-trade floor);
* frequency-weighted aggregate — :func:`scripts.regime_stratification.compute_regime_aware_aggregate`;
* concentration warning — :func:`scripts.regime_stratification.detect_regime_concentration`;
* composition-preserving bootstrap CI of the mean net return —
  :func:`scripts.regime_stratified_inference.regime_stratified_bootstrap`
  (fixed seed → deterministic report).

The two-sample :func:`regime_stratified_permutation` needs a second arm
and stays out of this single-series report by design.

The output is surfaced in the public calibration report via
``emit_public_calibration_report`` (additive ``regime_stratified`` key,
schema 1.2.0). Empty/regime-less series yield an honest
``status: "insufficient_data"`` report rather than no file.

Usage::

    python -m scripts.build_regime_stratified_report \\
        --series docs/calibration/gates/returns_series_2026-07-29.json \\
        --date 2026-07-29 \\
        --output docs/calibration/gates/regime_stratified_2026-07-29.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from scripts.regime_stratification import (
    compute_regime_aware_aggregate,
    compute_regime_conditional_metrics,
    detect_regime_concentration,
    stratify_trades_by_regime,
)
from scripts.regime_stratified_inference import regime_stratified_bootstrap
from scripts.smc_atomic_write import atomic_write_json

SCHEMA_VERSION = 1
BOOTSTRAP_SEED = 0
BOOTSTRAP_RESAMPLES = 1000


def _mean(pnls: np.ndarray) -> float:
    return float(np.mean(pnls))


def build_regime_report(
    trades: list[dict[str, Any]],
    *,
    date: str,
    measurement: dict[str, Any] | None,
    n_trades_total: int | None = None,
) -> dict[str, Any]:
    """Assemble the C5 report; honest shell when the sample cannot stratify.

    ``n_trades_total`` is the full triggered-trade count of the series
    (including trades WITHOUT a regime tag, which never reach this
    report); it feeds the aggregate's ``unknown_share`` warning so a
    clean-looking stratification can't hide an untagged majority.
    """
    out: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "date": date,
        "n_trades_with_regime": len(trades),
        "n_trades_total": n_trades_total,
        "measurement": measurement or {},
    }
    if not trades:
        out["status"] = "insufficient_data"
        return out

    unknown_share: float | None = None
    if n_trades_total and n_trades_total > 0:
        unknown_share = max(0.0, 1.0 - len(trades) / n_trades_total)

    buckets = stratify_trades_by_regime(trades)
    per_regime = compute_regime_conditional_metrics(buckets)
    aggregate = compute_regime_aware_aggregate(per_regime, unknown_share=unknown_share)
    concentration = detect_regime_concentration(buckets)
    boot = regime_stratified_bootstrap(
        trades,
        _mean,
        B=BOOTSTRAP_RESAMPLES,
        seed=BOOTSTRAP_SEED,
    )

    active = [r for r, block in per_regime.items() if "skipped_reason" not in block]
    out.update(
        {
            "status": "ok" if active else "insufficient_data",
            "per_regime": per_regime,
            "aggregate": aggregate,
            "concentration": concentration,
            "stratified_bootstrap": {
                "statistic": "mean_net_return",
                "observed": boot.get("statistic_observed"),
                "ci_lower": boot.get("ci_lower"),
                "ci_upper": boot.get("ci_upper"),
                "n_resamples": boot.get("n_resamples"),
                "per_regime_n": boot.get("per_regime_n"),
                "skipped_regimes": boot.get("skipped_regimes"),
                "seed": BOOTSTRAP_SEED,
            },
        }
    )
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Build regime_stratified_<date>.json from the returns series (ADR-0031)."
    )
    p.add_argument("--series", type=Path, required=True, help="returns_series_<date>.json")
    p.add_argument("--date", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv)

    series = json.loads(args.series.read_text(encoding="utf-8"))
    if not isinstance(series, dict):
        raise ValueError(f"{args.series}: expected a JSON object")
    trades = series.get("trades") or []
    if not isinstance(trades, list):
        raise ValueError(f"{args.series}: 'trades' must be a list")

    n_total = series.get("n_trades")
    report = build_regime_report(
        trades,
        date=args.date,
        measurement=series.get("measurement") if isinstance(series.get("measurement"), dict) else None,
        n_trades_total=int(n_total) if isinstance(n_total, int) else None,
    )
    atomic_write_json(report, args.output)
    print(
        f"wrote {args.output} (status={report['status']}, "
        f"n_trades_with_regime={report['n_trades_with_regime']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

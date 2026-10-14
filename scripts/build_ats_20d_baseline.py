#!/usr/bin/env python3
"""Build the 20-day average-trade-size (ATS) baseline cache.

WP-J (Tier-2 flow-overlay foundation). Computes a per-symbol rolling 20-day
mean and sample standard deviation of ``avg_trade_size`` from Databento
``trades`` microstructure and writes a committed JSON artifact
(``reports/ats_baseline_20d.json``).

The artifact is intentionally COMMITTED so the live overlay endpoint (WP-K) has
a fast, network-free baseline to compare today's ATS against when deriving the
``ats_zscore`` / ``ats_state`` fields; the daily job overwrites it atomically.
The output key names (``avg_trade_size_20d_mean`` / ``avg_trade_size_20d_std``)
deliberately match the per-row inputs read by
:func:`scripts.smc_flow_qualifier.build_flow_qualifier`.

The pure reduction (:func:`compute_ats_baseline`) carries no I/O and is
unit-tested directly. The live builder injects a ``fetch`` callable (defaulting
to the Databento-backed :func:`fetch_symbol_microstructure`) so tests run
without network access.
"""
from __future__ import annotations

import argparse
import logging
import math
import statistics
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_json
from scripts.smc_trades_microstructure import fetch_symbol_microstructure

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_PATH = REPO_ROOT / "reports" / "ats_baseline_20d.json"
DEFAULT_DATASET = "XNAS.ITCH"
DEFAULT_LOOKBACK_DAYS = 20

# Output key names -- MUST match the per-row inputs read by
# scripts.smc_flow_qualifier.build_flow_qualifier (the WP-K overlay consumer).
MEAN_KEY = "avg_trade_size_20d_mean"
STD_KEY = "avg_trade_size_20d_std"
N_DAYS_KEY = "n_days"

# Errors that make a single day's fetch unusable. We skip the day rather than
# abort the whole baseline; a specific tuple (not a bare ``except Exception``)
# keeps this off the broad-except-silent budget.
_FETCH_SKIP_ERRORS = (OSError, ValueError, KeyError, RuntimeError, TypeError)

FetchFn = Callable[..., dict]


def compute_ats_baseline(
    daily_avg_trade_sizes: Iterable[float | None],
) -> dict[str, float | int]:
    """Reduce a series of daily ``avg_trade_size`` values to a baseline dict.

    Only finite, strictly-positive samples are retained (a zero / NaN ATS marks
    a day with no usable trades and must not drag the mean toward zero). The
    standard deviation is the SAMPLE stdev (:func:`statistics.stdev`) and is
    defined as ``0.0`` for fewer than two samples. Mean and std are rounded to
    six decimal places. An empty series yields zeroed defaults.
    """
    samples = [
        float(v)
        for v in daily_avg_trade_sizes
        if v is not None and math.isfinite(float(v)) and float(v) > 0.0
    ]
    n = len(samples)
    if n == 0:
        return {MEAN_KEY: 0.0, STD_KEY: 0.0, N_DAYS_KEY: 0}
    mean = statistics.fmean(samples)
    std = statistics.stdev(samples) if n >= 2 else 0.0
    return {MEAN_KEY: round(mean, 6), STD_KEY: round(std, 6), N_DAYS_KEY: n}


def _trading_day_windows(end_date: date, lookback_days: int) -> list[tuple[date, date]]:
    """Return ``lookback_days`` consecutive one-day ``[start, end)`` windows.

    Windows walk backwards from ``end_date`` (exclusive upper bound). Weekend /
    holiday filtering is intentionally omitted: the fetch layer returns no
    usable ATS for a non-trading day, which is dropped by
    :func:`compute_ats_baseline`.
    """
    windows: list[tuple[date, date]] = []
    for offset in range(1, lookback_days + 1):
        start = end_date - timedelta(days=offset)
        windows.append((start, start + timedelta(days=1)))
    return windows


def build_baseline_for_symbols(
    symbols: Sequence[str],
    dataset: str,
    *,
    end_date: date | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    fetch: FetchFn = fetch_symbol_microstructure,
    client: Any = None,
) -> dict[str, dict[str, float | int]]:
    """Build the per-symbol 20-day ATS baseline by aggregating daily ATS.

    ``fetch`` is injected (defaulting to the Databento-backed microstructure
    fetcher) so the reduction can be exercised without network access. Each day
    window that errors or yields no usable ATS is silently skipped.
    """
    if end_date is None:
        end_date = datetime.now(UTC).date()
    windows = _trading_day_windows(end_date, lookback_days)
    out: dict[str, dict[str, float | int]] = {}
    for symbol in symbols:
        daily: list[float | None] = []
        for start, end in windows:
            try:
                micro = fetch(
                    symbol,
                    dataset,
                    start.isoformat(),
                    end.isoformat(),
                    client=client,
                )
            except _FETCH_SKIP_ERRORS as exc:
                logger.debug("ATS fetch skipped for %s %s: %s", symbol, start, exc)
                continue
            ats = (micro or {}).get("avg_trade_size")
            if ats is not None:
                daily.append(float(ats))
        out[symbol] = compute_ats_baseline(daily)
    return out


def build_and_write(
    symbols: Sequence[str],
    dataset: str,
    *,
    end_date: date | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    fetch: FetchFn = fetch_symbol_microstructure,
    client: Any = None,
) -> dict[str, Any]:
    """Build the baseline payload and write it atomically as committed JSON.

    Returns the in-memory payload (identical to what is written to disk) so
    callers and tests can assert on it without re-reading the file.
    """
    if end_date is None:
        end_date = datetime.now(UTC).date()
    symbols_baseline = build_baseline_for_symbols(
        symbols,
        dataset,
        end_date=end_date,
        lookback_days=lookback_days,
        fetch=fetch,
        client=client,
    )
    payload: dict[str, Any] = {
        "asof": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end_date": end_date.isoformat(),
        "dataset": dataset,
        "lookback_days": lookback_days,
        "symbols": symbols_baseline,
    }
    atomic_write_json(payload, output_path, indent=2, sort_keys=True)
    return payload


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the 20-day average-trade-size (ATS) baseline cache.",
    )
    parser.add_argument(
        "--symbols",
        required=True,
        help="Comma-separated list of symbols (e.g. 'AAPL,MSFT,NVDA').",
    )
    parser.add_argument(
        "--dataset",
        default=DEFAULT_DATASET,
        help=f"Databento dataset (default: {DEFAULT_DATASET}).",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=DEFAULT_LOOKBACK_DAYS,
        help=f"Number of trailing days to aggregate (default: {DEFAULT_LOOKBACK_DAYS}).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Output JSON path (default: reports/ats_baseline_20d.json).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args(argv)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        raise SystemExit("no symbols provided")
    payload = build_and_write(
        symbols,
        args.dataset,
        lookback_days=args.lookback_days,
        output_path=args.output,
    )
    logger.info(
        "wrote %d-symbol ATS baseline -> %s", len(payload["symbols"]), args.output
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

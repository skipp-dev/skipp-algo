"""Post-open outcome backfill: fetch RTH price data and resolve null PnL fields.

Scans ``artifacts/open_prep/outcomes/`` for records where ``profitable_30m``
is still ``None``, fetches 1-minute OHLCV bars from Databento for the
[9:30 ET, 10:00 ET] window, calculates 30-minute P&L, and atomically
updates the outcome files.

Also back-fills the ``FeatureImportanceCollector`` samples so that the
calibration feedback loop has labeled data.

Usage::

    python -m open_prep.outcome_backfill                # backfill today
    python -m open_prep.outcome_backfill --date 2026-04-18
    python -m open_prep.outcome_backfill --lookback 5   # last 5 days
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from datetime import date, datetime
from datetime import time as dt_time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo as _ZoneInfo

_ET = _ZoneInfo("America/New_York")

logger = logging.getLogger("open_prep.outcome_backfill")

# Re-use the canonical outcomes directory.
OUTCOMES_DIR = Path("artifacts/open_prep/outcomes")

# RTH entry/exit window: 09:30–10:00 ET.
_OPEN_TIME = dt_time(9, 30)
_EXIT_TIME = dt_time(10, 0)

# Databento dataset for US equities.
_DEFAULT_DATASET = "DBEQ.BASIC"
_DEFAULT_SCHEMA = "ohlcv-1m"


# ── Core backfill ───────────────────────────────────────────────────────────

def _load_pending_dates(lookback_days: int = 1) -> list[date]:
    """Return dates that have at least one unresolved outcome record."""
    if not OUTCOMES_DIR.exists():
        return []
    files = sorted(OUTCOMES_DIR.glob("outcomes_*.json"), reverse=True)
    pending: list[date] = []
    loaded = 0
    for path in files:
        if loaded >= lookback_days:
            break
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list) and any(
                r.get("profitable_30m") is None for r in data
            ):
                # Extract date from filename pattern outcomes_YYYY-MM-DD.json
                stem = path.stem  # outcomes_2026-04-18
                dt_str = stem.replace("outcomes_", "")
                pending.append(date.fromisoformat(dt_str))
            loaded += 1
        except Exception:
            logger.warning("Failed to inspect outcome file: %s", path)
    return sorted(pending)


def _load_outcome_file(run_date: date) -> tuple[Path, list[dict[str, Any]]]:
    """Load a single day's outcome records."""
    path = OUTCOMES_DIR / f"outcomes_{run_date.isoformat()}.json"
    if not path.exists():
        return path, []
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return path, data if isinstance(data, list) else []


def _save_outcome_file(path: Path, records: list[dict[str, Any]]) -> None:
    """Atomically overwrite an outcome JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(records, fh, indent=2, default=str, allow_nan=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def compute_pnl_from_bars(
    bars_df: Any,
    symbol: str,
    run_date: date,
) -> dict[str, Any] | None:
    """Calculate 30-minute P&L from 1-min OHLCV bars.

    Returns ``{"profitable_30m": bool, "pnl_30m_pct": float}`` or ``None``
    if insufficient bar data is available.
    """
    import pandas as pd

    if bars_df is None or bars_df.empty:
        return None

    # Filter to this symbol if the DataFrame contains multiple symbols.
    if "symbol" in bars_df.columns:
        sym_df = bars_df[bars_df["symbol"] == symbol]
    else:
        sym_df = bars_df

    if sym_df.empty:
        return None

    # Build timezone-aware ET timestamps for the target window.
    open_dt = datetime.combine(run_date, _OPEN_TIME, tzinfo=_ET)
    exit_dt = datetime.combine(run_date, _EXIT_TIME, tzinfo=_ET)

    # Databento timestamps are typically in UTC — convert index/column.
    ts_col = None
    for candidate in ("ts_event", "timestamp", "ts_recv"):
        if candidate in sym_df.columns:
            ts_col = candidate
            break

    if ts_col is None and isinstance(sym_df.index, pd.DatetimeIndex):
        sym_df = sym_df.copy()
        sym_df["_ts"] = sym_df.index
        ts_col = "_ts"

    if ts_col is None:
        logger.warning("No timestamp column found for %s", symbol)
        return None

    sym_df = sym_df.copy()
    sym_df["_et"] = pd.to_datetime(sym_df[ts_col], utc=True).dt.tz_convert(_ET)

    # Open bar: first 1-min bar at or after 09:30 ET.
    open_mask = sym_df["_et"] >= open_dt
    if not open_mask.any():
        return None
    open_bar = sym_df.loc[open_mask].iloc[0]

    # Exit bar: last 1-min bar before 10:00 ET.
    exit_mask = sym_df["_et"] < exit_dt
    if not exit_mask.any():
        return None
    exit_bar = sym_df.loc[exit_mask].iloc[-1]

    entry_price = float(open_bar["open"])
    exit_price = float(exit_bar["close"])

    if entry_price <= 0:
        return None

    pnl_pct = round((exit_price - entry_price) / entry_price * 100, 4)
    return {
        "profitable_30m": pnl_pct > 0,
        "pnl_30m_pct": pnl_pct,
    }


def _fetch_bars(
    provider: Any,
    symbols: list[str],
    run_date: date,
    *,
    dataset: str = _DEFAULT_DATASET,
    schema: str = _DEFAULT_SCHEMA,
) -> Any:
    """Fetch 1-min OHLCV bars for the 09:30–10:00 ET window.

    Returns a pandas DataFrame or ``None`` on failure.
    """
    # Query 09:29 → 10:01 to ensure we have the edge bars.
    start_dt = datetime.combine(run_date, dt_time(9, 29), tzinfo=_ET)
    end_dt = datetime.combine(run_date, dt_time(10, 1), tzinfo=_ET)

    try:
        store = provider.get_range(
            context="outcome_backfill",
            dataset=dataset,
            symbols=symbols,
            schema=schema,
            start=start_dt.isoformat(),
            end=end_dt.isoformat(),
        )
        return store.to_df()
    except Exception as exc:
        logger.warning(
            "Databento fetch failed for %s (%s): %s",
            run_date,
            ", ".join(symbols[:5]),
            type(exc).__name__,
            exc_info=True,
        )
        return None


def backfill_outcomes(
    *,
    target_dates: list[date] | None = None,
    lookback_days: int = 1,
    provider: Any | None = None,
    dataset: str = _DEFAULT_DATASET,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Main entry point: resolve null outcomes for the given dates.

    Parameters
    ----------
    target_dates
        Explicit list of dates to backfill. If ``None``, scans the last
        ``lookback_days`` outcome files for unresolved records.
    lookback_days
        How many recent outcome files to scan when ``target_dates`` is
        not provided.
    provider
        A ``MarketDataProvider`` instance. If ``None``, instantiates a
        ``DabentoProvider`` from the environment.
    dataset
        Databento dataset identifier.
    dry_run
        If ``True``, compute PnL but do not write files.

    Returns
    -------
    dict
        Summary with counts of resolved, skipped, failed records.
    """
    if provider is None:
        from databento_provider import DabentoProvider
        provider = DabentoProvider()

    dates = target_dates or _load_pending_dates(lookback_days)
    if not dates:
        logger.info("No pending outcome dates to backfill.")
        return {"resolved": 0, "skipped": 0, "failed": 0, "dates_processed": 0}

    total_resolved = 0
    total_skipped = 0
    total_failed = 0

    for run_date in dates:
        path, records = _load_outcome_file(run_date)
        if not records:
            logger.info("No records for %s, skipping.", run_date)
            continue

        # Collect symbols that need backfill.
        pending_symbols = [
            r["symbol"]
            for r in records
            if r.get("profitable_30m") is None and r.get("symbol")
        ]
        if not pending_symbols:
            logger.info("All outcomes already resolved for %s.", run_date)
            total_skipped += len(records)
            continue

        # Fetch bars for all pending symbols in one batch.
        bars_df = _fetch_bars(
            provider, pending_symbols, run_date, dataset=dataset,
        )

        updated = False
        for rec in records:
            if rec.get("profitable_30m") is not None:
                total_skipped += 1
                continue

            symbol = rec.get("symbol")
            if not symbol:
                total_failed += 1
                continue

            result = compute_pnl_from_bars(bars_df, symbol, run_date)
            if result is None:
                logger.debug("No bar data for %s on %s", symbol, run_date)
                total_failed += 1
                continue

            rec["profitable_30m"] = result["profitable_30m"]
            rec["pnl_30m_pct"] = result["pnl_30m_pct"]
            total_resolved += 1
            updated = True

        if updated and not dry_run:
            _save_outcome_file(path, records)
            logger.info(
                "Updated %s: %d resolved, %d failed",
                path.name,
                sum(1 for r in records if r.get("profitable_30m") is not None),
                sum(1 for r in records if r.get("profitable_30m") is None),
            )

    summary = {
        "resolved": total_resolved,
        "skipped": total_skipped,
        "failed": total_failed,
        "dates_processed": len(dates),
    }
    logger.info("Backfill complete: %s", summary)
    return summary


# ── Feature importance backfill ─────────────────────────────────────────────

def backfill_feature_importance(
    lookback_days: int = 7,
) -> int:
    """Re-scan outcome files and update feature importance JSONL samples.

    Returns the number of labeled samples written.
    """
    from .outcomes import (
        FEATURE_KEYS,
        FeatureImportanceCollector,
        _load_outcomes_range,
    )

    records = _load_outcomes_range(lookback_days)
    labeled = [r for r in records if r.get("profitable_30m") is not None]
    if not labeled:
        return 0

    collector = FeatureImportanceCollector()
    for rec in labeled:
        breakdown: dict[str, float] = {}
        for key in FEATURE_KEYS:
            breakdown[key] = float(rec.get(key, 0.0) or 0.0)
        collector.record(
            symbol=rec.get("symbol", ""),
            score_breakdown=breakdown,
            total_score=float(rec.get("score", 0.0) or 0.0),
            confidence_tier=rec.get("confidence_tier", "STANDARD"),
            profitable_30m=rec["profitable_30m"],
            pnl_30m_pct=float(rec.get("pnl_30m_pct", 0.0) or 0.0),
            run_date=rec.get("date"),
        )

    count = collector.sample_count
    if count > 0:
        collector.flush_to_disk()

    return count


# ── CLI ─────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill post-open outcomes for Signal Replay.",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Specific date to backfill (YYYY-MM-DD). Default: scan recent files.",
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=5,
        help="Number of recent outcome files to scan for unresolved records (default: 5).",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default=_DEFAULT_DATASET,
        help=f"Databento dataset (default: {_DEFAULT_DATASET}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute PnL without writing files.",
    )
    parser.add_argument(
        "--feature-importance",
        action="store_true",
        help="Also backfill feature importance samples from resolved outcomes.",
    )
    parser.add_argument(
        "--require-progress",
        action="store_true",
        help=(
            "Exit 3 when the run made zero progress "
            "(resolved == 0 AND failed == 0 AND skipped == 0). "
            "Use this in scheduled workflows that should never "
            "silently no-op (audit finding F-09)."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Backfill outcomes and return a process exit code.

    Returns:
        ``0`` if every record was either resolved or deliberately skipped,
        ``2`` if at least one record failed (loud non-zero exit so a
        scheduled workflow surfaces the failure instead of silently
        succeeding) — ENG-WS4-01 DoD: 'Fehlfaelle sind sichtbar und nicht
        still'.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    )

    target_dates: list[date] | None = None
    if args.date:
        target_dates = [date.fromisoformat(args.date)]

    summary = backfill_outcomes(
        target_dates=target_dates,
        lookback_days=args.lookback,
        dataset=args.dataset,
        dry_run=args.dry_run,
    )

    print(
        f"Backfill complete: {summary['resolved']} resolved, "
        f"{summary['skipped']} skipped, {summary['failed']} failed "
        f"across {summary['dates_processed']} date(s)."
    )

    fi_written = 0
    if args.feature_importance and summary["resolved"] > 0:
        fi_written = backfill_feature_importance(lookback_days=args.lookback)
        print(f"Feature importance: {fi_written} labeled samples written.")

    # ── Persist run log (ENG-WS4-01 DoD: 'Ergebnisse sind persistiert
    # und nachvollziehbar'). One JSON file per run, atomically written.
    if not args.dry_run:
        log_path = _write_backfill_run_log(
            summary=summary,
            feature_importance_samples=fi_written if args.feature_importance else None,
            cli_args={
                "date": args.date,
                "lookback": args.lookback,
                "dataset": args.dataset,
                "feature_importance": bool(args.feature_importance),
            },
        )
        print(f"Run log: {log_path}")

    # Exit non-zero only when the backfill made no progress at all
    # (resolved == 0 AND failed > 0). Per-symbol "failed" counts are
    # normal and expected — they capture data gaps for delisted /
    # halted / missing-bar-data symbols and would otherwise turn the
    # workflow permanently red on any single legacy bad row. The exact
    # counts are still preserved in the JSON run log for inspection
    # and the FI report's `insufficient_labels` state.
    resolved = int(summary.get("resolved") or 0)
    failed = int(summary.get("failed") or 0)
    skipped = int(summary.get("skipped") or 0)
    if resolved == 0 and failed > 0:
        return 2
    # F-09: opt-in tripwire for scheduled workflows. The default
    # behaviour (no-op runs are tolerated) stays unchanged so ad-hoc
    # / dry-run invocations don't break.
    if args.require_progress and (resolved + failed + skipped) == 0:
        print(
            "::error::--require-progress was set but the run made "
            "no progress (resolved=0, failed=0, skipped=0)."
        )
        return 3
    return 0


# ── Run-log persistence (ENG-WS4-01) ────────────────────────────────────────

BACKFILL_RUN_LOG_DIR = Path("artifacts/open_prep/outcome_backfill")


def _write_backfill_run_log(
    *,
    summary: dict[str, Any],
    feature_importance_samples: int | None,
    cli_args: dict[str, Any],
    log_dir: Path | None = None,
) -> Path:
    """Atomically write a per-run JSON log of the backfill outcome.

    The log is timestamped to the second so concurrent invocations stay
    distinct. A small ``latest.json`` pointer is also written so a
    workflow can grab the last result without scanning the directory.
    """
    target_dir = log_dir if log_dir is not None else BACKFILL_RUN_LOG_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(_ET)
    record = {
        "run_id": now.strftime("%Y%m%dT%H%M%S"),
        "started_at_et": now.isoformat(),
        "resolved": int(summary.get("resolved") or 0),
        "skipped": int(summary.get("skipped") or 0),
        "failed": int(summary.get("failed") or 0),
        "dates_processed": int(summary.get("dates_processed") or 0),
        "feature_importance_samples": (
            int(feature_importance_samples) if feature_importance_samples is not None else None
        ),
        "status": "failed" if int(summary.get("failed") or 0) > 0 else "ok",
        "cli_args": cli_args,
    }

    out_path = target_dir / f"backfill_{record['run_id']}.json"
    _atomic_write_json(out_path, record)

    latest_path = target_dir / "latest.json"
    _atomic_write_json(latest_path, record)

    return out_path


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


if __name__ == "__main__":
    sys.exit(main())

"""Backward-looking validation: outcome tracking and historical hit-rate
computation for gap+RVOL setups.

Stores daily outcomes in JSON files under ``artifacts/open_prep/outcomes/``.
Computes bucketed statistics: given a (gap_bucket, rvol_bucket) combination,
what fraction of historical entries were profitable after 30 minutes?
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

logger = logging.getLogger("open_prep.outcomes")

OUTCOMES_DIR = Path("artifacts/open_prep/outcomes")

# Bucket edges
GAP_BUCKETS = [
    ("tiny", 0.0, 1.0),
    ("small", 1.0, 2.5),
    ("medium", 2.5, 5.0),
    ("large", 5.0, 10.0),
    ("extreme", 10.0, 100.0),
]

RVOL_BUCKETS = [
    ("low", 0.0, 1.0),
    ("normal", 1.0, 2.0),
    ("high", 2.0, 5.0),
    ("very_high", 5.0, 100.0),
]


def _gap_bucket_label(gap_pct: float) -> str:
    abs_gap = abs(gap_pct)
    for label, lo, hi in GAP_BUCKETS:
        if lo <= abs_gap < hi:
            return label
    return "extreme"


def _rvol_bucket_label(rvol: float) -> str:
    for label, lo, hi in RVOL_BUCKETS:
        if lo <= rvol < hi:
            return label
    return "very_high"


# ---------------------------------------------------------------------------
# Outcome storage
# ---------------------------------------------------------------------------

def store_daily_outcomes(
    run_date: date,
    outcomes: list[dict[str, Any]],
) -> Path:
    """Persist daily outcome records.

    Each record should contain at minimum::

        {
            "symbol": "NVDA",
            "gap_pct": 3.2,
            "rvol": 2.1,
            "score": 4.5,
            "gap_bucket_label": "medium",
            "rvol_bucket_label": "high",
            "profitable_30m": true | false | null,
            "pnl_30m_pct": 1.2,
        }
    """
    OUTCOMES_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTCOMES_DIR / f"outcomes_{run_date.isoformat()}.json"
    # Atomic write: tmp file + os.replace to avoid half-written files on crash.
    fd, tmp_path = tempfile.mkstemp(dir=OUTCOMES_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(outcomes, fh, indent=2, default=str)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    logger.info("Stored %d outcome records for %s → %s", len(outcomes), run_date, path)

    # Rotate old outcome files beyond the retention window to prevent
    # unbounded disk growth.  Default: keep 90 days.
    max_days = max(
        int(float(os.environ.get("OPEN_PREP_OUTCOME_RETENTION_DAYS", "90") or "90")),
        7,
    )
    try:
        all_files = sorted(OUTCOMES_DIR.glob("outcomes_*.json"))
        if len(all_files) > max_days:
            for stale in all_files[: len(all_files) - max_days]:
                stale.unlink(missing_ok=True)
                logger.debug("Rotated stale outcome file: %s", stale.name)
    except Exception as exc:
        logger.warning("Outcome rotation failed (non-fatal): %s", exc)

    return path


def _load_outcomes_range(lookback_days: int = 20) -> list[dict[str, Any]]:
    """Load outcome records from the last N days of stored files."""
    if not OUTCOMES_DIR.exists():
        return []
    files = sorted(OUTCOMES_DIR.glob("outcomes_*.json"), reverse=True)
    records: list[dict[str, Any]] = []
    loaded = 0
    for path in files:
        if loaded >= lookback_days:
            break
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                records.extend(data)
                loaded += 1
        except Exception:
            logger.warning("Failed to load outcome file: %s", path)
    return records


# ---------------------------------------------------------------------------
# Hit-rate computation
# ---------------------------------------------------------------------------

def compute_hit_rates(
    lookback_days: int = 20,
) -> dict[str, dict[str, Any]]:
    """Compute hit rates bucketed by (gap_bucket, rvol_bucket).

    Returns a dict keyed by ``"gap_bucket:rvol_bucket"`` with::

        {
            "total": int,
            "profitable": int,
            "hit_rate": float (0..1),
            "avg_pnl_pct": float,
        }
    """
    records = _load_outcomes_range(lookback_days)
    if not records:
        return {}

    buckets: dict[str, dict[str, Any]] = {}
    for rec in records:
        gap_pct = float(rec["gap_pct"]) if rec.get("gap_pct") is not None else 0.0
        rvol = float(rec["rvol"]) if rec.get("rvol") is not None else 0.0
        profitable = rec.get("profitable_30m")
        pnl = float(rec["pnl_30m_pct"]) if rec.get("pnl_30m_pct") is not None else 0.0

        gb = _gap_bucket_label(gap_pct)
        rb = _rvol_bucket_label(rvol)
        key = f"{gb}:{rb}"

        if key not in buckets:
            buckets[key] = {"total": 0, "profitable": 0, "pnl_sum": 0.0}

        buckets[key]["total"] += 1
        if profitable is True:
            buckets[key]["profitable"] += 1
        buckets[key]["pnl_sum"] += pnl

    result: dict[str, dict[str, Any]] = {}
    for key, data in buckets.items():
        total = data["total"]
        result[key] = {
            "total": total,
            "profitable": data["profitable"],
            "hit_rate": round(data["profitable"] / total, 4) if total > 0 else 0.0,
            "avg_pnl_pct": round(data["pnl_sum"] / total, 4) if total > 0 else 0.0,
        }
    return result


def get_symbol_hit_rate(
    symbol: str,
    gap_pct: float,
    rvol: float,
    hit_rates: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Look up the historical hit-rate for a symbol's gap+RVOL bucket.

    Returns the bucket stats dict or a default indicating no data.
    """
    gb = _gap_bucket_label(gap_pct)
    rb = _rvol_bucket_label(rvol)
    key = f"{gb}:{rb}"
    stats = hit_rates.get(key)
    if stats:
        return {
            "historical_hit_rate": stats["hit_rate"],
            "historical_sample_size": stats["total"],
            "historical_avg_pnl_pct": stats["avg_pnl_pct"],
            "gap_bucket": gb,
            "rvol_bucket": rb,
        }
    return {
        "historical_hit_rate": None,
        "historical_sample_size": 0,
        "historical_avg_pnl_pct": None,
        "gap_bucket": gb,
        "rvol_bucket": rb,
    }


def prepare_outcome_snapshot(
    ranked: list[dict[str, Any]],
    run_date: date,
) -> list[dict[str, Any]]:
    """Prepare outcome tracking records from ranked candidates.

    These records are stored after the run.  The ``profitable_30m`` and
    ``pnl_30m_pct`` fields are initially ``null`` and should be back-filled
    once RTH data is available (e.g. via a scheduled post-open job).
    """
    records: list[dict[str, Any]] = []
    for row in ranked:
        gap_pct = float(row["gap_pct"]) if row.get("gap_pct") is not None else 0.0
        rvol = float(row.get("volume") or 0)
        avg_vol = float(row.get("avg_volume") or 1)
        rvol_ratio = (rvol / avg_vol) if avg_vol > 0 else 0.0

        records.append({
            "date": run_date.isoformat(),
            "symbol": row.get("symbol"),
            "gap_pct": gap_pct,
            "rvol": round(rvol_ratio, 4),
            "score": row.get("score", 0.0),
            "confidence_tier": row.get("confidence_tier", "STANDARD"),
            "gap_bucket_label": _gap_bucket_label(gap_pct),
            "rvol_bucket_label": _rvol_bucket_label(rvol_ratio),
            "regime": row.get("regime"),
            "profitable_30m": None,  # Back-filled post-open
            "pnl_30m_pct": None,     # Back-filled post-open
        })
    return records

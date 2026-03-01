"""Backward-looking validation: outcome tracking, historical hit-rate
computation for gap+RVOL setups, and feature importance analysis.

Stores daily outcomes in JSON files under ``artifacts/open_prep/outcomes/``.
Computes bucketed statistics: given a (gap_bucket, rvol_bucket) combination,
what fraction of historical entries were profitable after 30 minutes?

Feature Importance (#3):
  - ``FeatureImportanceCollector`` accumulates per-run scoring component
    values alongside binary outcomes (profitable_30m).
  - ``compute_feature_importance()`` runs Pearson correlation and mean-
    separation importance to identify which score weights are predictive
    and which are dead weight, closing the calibration feedback loop.
"""
from __future__ import annotations

import json
import logging
import math
import os
import tempfile
from collections import deque
from datetime import date
from pathlib import Path
from typing import Any

from .utils import to_float as _safe_float

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
            json.dump(outcomes, fh, indent=2, default=str, allow_nan=False)
            fh.flush()
            os.fsync(fh.fileno())
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
    try:
        max_days = max(
            int(float(os.environ.get("OPEN_PREP_OUTCOME_RETENTION_DAYS", "90") or "90")),
            7,
        )
    except (ValueError, TypeError):
        max_days = 90
    try:
        all_files = sorted(OUTCOMES_DIR.glob("outcomes_*.json"))
        if len(all_files) > max_days:
            for stale in all_files[: len(all_files) - max_days]:
                stale.unlink(missing_ok=True)
                logger.debug("Rotated stale outcome file: %s", stale.name)
    except Exception as exc:
        logger.warning("Outcome rotation failed (non-fatal): %s", type(exc).__name__, exc_info=True)

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
        gap_pct = _safe_float(rec.get("gap_pct"))
        rvol = _safe_float(rec.get("rvol"))
        profitable = rec.get("profitable_30m")
        pnl = _safe_float(rec.get("pnl_30m_pct"))

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
        gap_pct = _safe_float(row.get("gap_pct"))
        rvol = _safe_float(row.get("volume"))
        avg_vol = _safe_float(row.get("avg_volume"), default=1.0)
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


# ═══════════════════════════════════════════════════════════════════════════
# #3  Feature Importance Collector — closes the calibration feedback loop
# ═══════════════════════════════════════════════════════════════════════════

# The score breakdown keys from scorer.py that form the feature vector.
FEATURE_KEYS: list[str] = [
    "gap_component",
    "gap_sector_rel_component",
    "rvol_component",
    "macro_component",
    "momentum_component",
    "hvb_component",
    "earnings_bmo_component",
    "news_component",
    "ext_hours_component",
    "analyst_catalyst_component",
    "vwap_distance_component",
    "freshness_component",
    "institutional_component",
    "estimate_revision_component",
]

FEATURE_IMPORTANCE_DIR = OUTCOMES_DIR / "feature_importance"
_MAX_RING_BUFFER = 100_000


class FeatureImportanceCollector:
    """Accumulates scoring-component samples for offline analysis.

    Call ``record()`` once per scored candidate with the ``score_breakdown``
    dict from ``score_candidate()`` plus the eventual outcome (which may
    be ``None`` initially and back-filled later).

    Data is persisted to JSONL files per day.  Use
    ``compute_feature_importance()`` for the offline report.
    """

    def __init__(self, max_samples: int = _MAX_RING_BUFFER) -> None:
        self._buffer: deque[dict[str, Any]] = deque(maxlen=max_samples)

    def record(
        self,
        symbol: str,
        score_breakdown: dict[str, float],
        *,
        total_score: float = 0.0,
        confidence_tier: str = "STANDARD",
        profitable_30m: bool | None = None,
        pnl_30m_pct: float | None = None,
        run_date: str | None = None,
    ) -> None:
        """Add a single sample to the ring buffer."""
        sample: dict[str, Any] = {
            "symbol": symbol,
            "date": run_date or date.today().isoformat(),
            "total_score": total_score,
            "confidence_tier": confidence_tier,
            "profitable_30m": profitable_30m,
            "pnl_30m_pct": pnl_30m_pct,
        }
        for key in FEATURE_KEYS:
            sample[key] = _safe_float(score_breakdown.get(key))
        self._buffer.append(sample)

    def flush_to_disk(self, run_date: date | None = None) -> Path | None:
        """Persist collected samples as JSONL and clear the buffer."""
        if not self._buffer:
            return None
        FEATURE_IMPORTANCE_DIR.mkdir(parents=True, exist_ok=True)
        rd = run_date or date.today()
        path = FEATURE_IMPORTANCE_DIR / f"fi_samples_{rd.isoformat()}.jsonl"
        fd, tmp_path = tempfile.mkstemp(
            dir=FEATURE_IMPORTANCE_DIR, suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                for sample in self._buffer:
                    fh.write(json.dumps(sample, default=str, allow_nan=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        count = len(self._buffer)
        self._buffer.clear()
        logger.info("Feature importance: flushed %d samples → %s", count, path)
        return path

    @property
    def sample_count(self) -> int:
        return len(self._buffer)


def _pearson_r(xs: list[float], ys: list[float]) -> float:
    """Pearson correlation coefficient for two equal-length lists."""
    n = len(xs)
    if n < 3:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return 0.0
    return cov / (sx * sy)


def compute_feature_importance(
    lookback_days: int = 30,
) -> dict[str, Any]:
    """Offline report: which score components predict profitable_30m?

    Loads JSONL samples from the last ``lookback_days`` days and computes:
      - Pearson correlation between each feature component and the binary
        ``profitable_30m`` outcome.
      - Mean-separation importance: ``|mean_win − mean_loss| / std_win``
        per feature, normalized to [0, 1].

    Returns a dict with per-feature stats + calibration recommendations.
    """
    if not FEATURE_IMPORTANCE_DIR.exists():
        return {"error": "no feature importance data found"}

    files = sorted(FEATURE_IMPORTANCE_DIR.glob("fi_samples_*.jsonl"), reverse=True)
    samples: list[dict[str, Any]] = []
    loaded = 0
    for path in files:
        if loaded >= lookback_days:
            break
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        samples.append(json.loads(line))
            loaded += 1
        except Exception:
            logger.warning("Failed to load FI file: %s", path)

    # Filter to samples with known outcome
    labeled = [s for s in samples if s.get("profitable_30m") is not None]
    if len(labeled) < 10:
        return {
            "error": "insufficient labeled samples",
            "total_samples": len(samples),
            "labeled_samples": len(labeled),
        }

    outcomes = [1.0 if s["profitable_30m"] else 0.0 for s in labeled]

    report: dict[str, Any] = {
        "total_samples": len(samples),
        "labeled_samples": len(labeled),
        "features": {},
        "recommendations": [],
    }

    importance_scores: dict[str, float] = {}

    for key in FEATURE_KEYS:
        vals = [_safe_float(s.get(key)) for s in labeled]

        # Pearson correlation with binary outcome
        r = _pearson_r(vals, outcomes)

        # Mean-separation importance
        wins = [v for v, o in zip(vals, outcomes) if o > 0.5]
        losses = [v for v, o in zip(vals, outcomes) if o <= 0.5]
        mean_win = (sum(wins) / len(wins)) if wins else 0.0
        mean_loss = (sum(losses) / len(losses)) if losses else 0.0
        std_win = (
            math.sqrt(sum((x - mean_win) ** 2 for x in wins) / max(len(wins) - 1, 1))
            if len(wins) > 1
            else 0.001
        )
        separation = abs(mean_win - mean_loss) / max(std_win, 0.001)

        report["features"][key] = {
            "pearson_r": round(r, 4),
            "mean_separation": round(separation, 4),
            "mean_win": round(mean_win, 4),
            "mean_loss": round(mean_loss, 4),
        }
        importance_scores[key] = separation

    # Normalize importance to [0, 1]
    max_imp = max(importance_scores.values()) if importance_scores else 1.0
    if max_imp > 0:
        for key in FEATURE_KEYS:
            report["features"][key]["importance_normalized"] = round(
                importance_scores[key] / max_imp, 4,
            )

    # Generate recommendations
    for key in FEATURE_KEYS:
        feat = report["features"][key]
        r = feat["pearson_r"]
        imp = feat.get("importance_normalized", 0)
        if abs(r) > 0.5:
            report["recommendations"].append(
                f"🟢 {key}: strong predictor (r={r:.2f}). Consider increasing weight."
            )
        elif imp < 0.2:
            report["recommendations"].append(
                f"🔴 {key}: weak predictor (importance={imp:.2f}). Consider reducing weight."
            )

    return report

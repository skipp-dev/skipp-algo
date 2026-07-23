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

import contextlib
import json
import logging
import math
import os
import tempfile
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo as _ZoneInfo

import numpy as np

cp: Any | None
try:
    import cupy as cp
except Exception:  # pragma: no cover - optional GPU dependency
    cp = None

from smc_core._pytest_canonical_write_guard import (
    guard_against_canonical_repo_write_under_pytest,
)

from .utils import to_float as _safe_float

logger = logging.getLogger("open_prep.outcomes")

_ET = _ZoneInfo("America/New_York")

OUTCOMES_DIR = Path("artifacts/open_prep/outcomes")


def _outcomes_dir() -> Path:
    """Effective outcomes dir, resolved at call time (not import).

    Local ``run_open_prep`` runs set ``OPEN_PREP_OUTCOMES_DIR`` (a gitignored
    shadow dir) so they stop writing the CI-committed canonical
    ``artifacts/open_prep/outcomes/``: that dir is UN-ignored in .gitignore and
    committed daily by CI, so a local write leaves an untracked ``outcomes_<date>.json``
    that collides with the incoming CI commit on the next ``git pull``. CI leaves
    the var unset and keeps the canonical dir. Resolved at call time because
    run_open_prep loads ``.env`` only after importing this module."""
    override = os.environ.get("OPEN_PREP_OUTCOMES_DIR", "").strip()
    return Path(override) if override else OUTCOMES_DIR


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


def _extract_date_from_stem(stem: str, *, prefix: str) -> date | None:
    if not stem.startswith(prefix):
        return None
    try:
        return date.fromisoformat(stem[len(prefix):])
    except ValueError:
        return None


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

def _null_non_finite_floats(records: list[Any]) -> int:
    """Replace NaN/inf float field values with None in-place; return the count.

    Outcome records are flat dicts of scalars; a single non-finite float (e.g. a
    ``gap_pct`` computed from a zero prev-close) would make ``json.dump`` raise
    under ``allow_nan=False`` and lose the entire day's outcomes.
    """
    nulled = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        for key, value in record.items():
            if isinstance(value, float) and not math.isfinite(value):
                record[key] = None
                nulled += 1
    return nulled


def store_daily_outcomes(
    run_date: date,
    outcomes: list[dict[str, Any]],
    *,
    universe_source: str | None = None,
) -> Path:
    """Persist daily outcome records as the *full* daily aggregate.

    ``universe_source`` stamps every record with the producing universe
    (e.g. ``fmp_us_mid_large``) so consumers can tell which pipeline wrote
    the file. The single-writer contract below holds *per environment*:
    the CI daily cron and a local run write the SAME filename from
    different universes (found 2026-07-09 — bot file: screener small caps;
    local file: mega caps), and without the stamp that shadowing is
    invisible to consumers (it silently emptied the panel's setups join).

    .. warning::
        This function performs an **atomic overwrite** of the per-day
        artefact ``artifacts/open_prep/outcomes/outcomes_<date>.json``,
        not an append. The caller is responsible for assembling the
        *complete* list of records for ``run_date`` before invoking
        this function — calling it twice on the same day with disjoint
        record sets clobbers the first run.

        The outcome ledger therefore assumes a **single writer per
        day**: the daily ``open_prep`` cron is the sole producer.
        Sprint-Plan-Wording "Live-Outcome-Stream" notwithstanding, this
        is a daily-aggregate writer, not a streaming append. A future
        truly-streaming variant must use either (a) JSONL append with
        per-record dedup keys ``(symbol, gap_bucket_label,
        rvol_bucket_label, ts)`` (matching the field names used in the
        record schema below) or (b) a file-lock around a read-merge-
        replace cycle.

        Tests:
        - ``tests/test_open_prep.py`` pins the atomic-overwrite
          invariant (second write wins).
        - ``tests/test_outcomes_single_writer.py`` documents the
          single-writer contract with an explicit regression
          assertion (overwrite-second-wins + atomic-on-failure).
        - ``tests/test_outcomes_pytest_write_guard.py`` pins the
          canonical-write guard below: tests that forget to redirect
          ``OUTCOMES_DIR`` fail loudly instead of silently rewriting
          the tracked ``artifacts/open_prep/outcomes/`` artefacts
          (the pollution shipped to main in PRs #2687/#2688).

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
    outcomes_dir = _outcomes_dir()
    guard_against_canonical_repo_write_under_pytest(
        outcomes_dir,
        canonical_relative_paths=("artifacts/open_prep/outcomes",),
        caller="store_daily_outcomes",
    )
    # Provenance stamp (setdefault: a record that already carries its origin
    # is never clobbered — e.g. replayed/merged historical rows).
    if universe_source:
        for record in outcomes:
            if isinstance(record, dict):
                record.setdefault("universe_source", universe_source)
    # NaN/inf from bad upstream data would make json.dump(allow_nan=False) raise
    # and lose the whole day's outcomes. Null them so the write still succeeds,
    # and warn so the upstream issue stays visible.
    n_nulled = _null_non_finite_floats(outcomes)
    if n_nulled:
        logger.warning("Nulled %d non-finite float field(s) in outcome records before save", n_nulled)
    outcomes_dir.mkdir(parents=True, exist_ok=True)
    path = outcomes_dir / f"outcomes_{run_date.isoformat()}.json"
    # Atomic write: tmp file + os.replace to avoid half-written files on crash.
    fd, tmp_path = tempfile.mkstemp(dir=outcomes_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(outcomes, fh, indent=2, default=str, allow_nan=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise
    logger.info("Stored %d outcome records for %s → %s", len(outcomes), run_date, path)

    # Rotate old outcome files beyond the retention window to prevent
    # unbounded disk growth.  Default: keep the 90 lexicographically-newest
    # FILES (≈ days for the daily single-writer; a non-dated stray like
    # ``outcomes_backup.json`` sorts after all dates and survives rotation).
    try:
        # OverflowError: int(float("INF")) / int(float("1e309")) overflow and were
        # NOT caught by the old (ValueError, TypeError) clause — that crashed the
        # call AFTER the file had already been written.
        requested_days = int(float(os.environ.get("OPEN_PREP_OUTCOME_RETENTION_DAYS", "90") or "90"))
    except (ValueError, TypeError, OverflowError):
        requested_days = 90
    max_days = max(requested_days, 7)
    if requested_days < 7:
        logger.warning(
            "OPEN_PREP_OUTCOME_RETENTION_DAYS=%d is below the 7-day floor; keeping 7 days",
            requested_days,
        )
    try:
        all_files = sorted(outcomes_dir.glob("outcomes_*.json"))
        if len(all_files) > max_days:
            for stale in all_files[: len(all_files) - max_days]:
                stale.unlink(missing_ok=True)
                logger.debug("Rotated stale outcome file: %s", stale.name)
    except Exception as exc:
        logger.warning("Outcome rotation failed (non-fatal): %s", type(exc).__name__, exc_info=True)

    return path


def _load_outcomes_range(lookback_days: int = 20) -> list[dict[str, Any]]:
    """Load outcome records from the last N days of stored files."""
    outcomes_dir = _outcomes_dir()
    if not outcomes_dir.exists():
        return []
    files = sorted(outcomes_dir.glob("outcomes_*.json"), reverse=True)
    records: list[dict[str, Any]] = []
    loaded_dates: set[date] = set()
    for path in files:
        file_date = _extract_date_from_stem(path.stem, prefix="outcomes_")
        if file_date is None:
            # A non-dated ``outcomes_*.json`` (e.g. a stray backup) is not a daily
            # outcomes file. The old code loaded it in full AND never counted it
            # toward loaded_dates, so it silently bypassed lookback_days (a single
            # huge backup could blow up memory / skew hit-rates). Skip it.
            logger.warning("Skipping non-dated outcome file: %s", path.name)
            continue
        if file_date not in loaded_dates and len(loaded_dates) >= lookback_days:
            break
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                records.extend(data)
                loaded_dates.add(file_date)
            else:
                logger.warning(
                    "Outcome file %s contains %s, expected list — skipped",
                    path,
                    type(data).__name__,
                )
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
            "profitable": int, "unresolved": int,
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
        # rvol is None when the ratio was unavailable at scoring time (RVOL
        # fix 2026-07-23). Skip the record — _safe_float's 0.0 default would
        # silently pool it into the "low" bucket, mixing missing-data records
        # with genuine low-RVOL signals and inflating the apparent edge of
        # the high buckets. Legacy records always carry a numeric rvol.
        if rec.get("rvol") is None:
            continue
        rvol = _safe_float(rec.get("rvol"))
        # Direction-signed label when present, falling back to the legacy
        # long-only label for old records (eval-findings C3a). Label and PnL
        # fall back AS A PAIR (like compute_gap_playbook_report) so a
        # directional hit-rate is never averaged with long-only PnL when a
        # field-level null desyncs the two.
        profitable = rec.get("profitable_30m_directional")
        pnl_raw = rec.get("pnl_30m_pct_signed")
        if profitable is None or pnl_raw is None:
            profitable = rec.get("profitable_30m")
            pnl_raw = rec.get("pnl_30m_pct")
        pnl = _safe_float(pnl_raw, default=0.0)

        gb = _gap_bucket_label(gap_pct)
        rb = _rvol_bucket_label(rvol)
        key = f"{gb}:{rb}"

        if key not in buckets:
            buckets[key] = {"total": 0, "profitable": 0, "pnl_sum": 0.0, "unresolved": 0}

        # Unresolved (profitable is None) must not dilute the denominator —
        # 32/140 unresolved dragged the rate from 0.722 down to 0.557
        # (eval-findings B1). Track them separately so survivorship is visible.
        if profitable is None:
            buckets[key]["unresolved"] += 1
            continue
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
            "unresolved": data.get("unresolved", 0),
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
            "historical_unresolved": stats.get("unresolved", 0),
            "historical_avg_pnl_pct": stats["avg_pnl_pct"],
            "gap_bucket": gb,
            "rvol_bucket": rb,
        }
    return {
        "historical_hit_rate": None,
        "historical_sample_size": 0,
        "historical_unresolved": 0,
        "historical_avg_pnl_pct": None,
        "gap_bucket": gb,
        "rvol_bucket": rb,
    }


def compute_gap_playbook_report(
    records: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Hit-rate per ``gap_bucket × playbook`` over resolved outcome records.

    The scorer's gap component is monotonic-linear while the GAP_FADE
    playbook treats large gaps as fade candidates — an internal
    contradiction (eval-findings B5, 2026-06-11). This report measures the
    actual win-rate per gap-size bucket conditioned on the assigned
    playbook so the gap component can be re-shaped on evidence, not
    opinion. Uses the direction-signed label when present, falling back to
    the legacy long-only ``profitable_30m``.
    """
    buckets: dict[str, dict[str, Any]] = {}
    for rec in records:
        profitable = rec.get("profitable_30m_directional")
        pnl = rec.get("pnl_30m_pct_signed")
        if profitable is None:
            profitable = rec.get("profitable_30m")
            pnl = rec.get("pnl_30m_pct")
        if profitable is None:
            continue
        gb = rec.get("gap_bucket_label") or _gap_bucket_label(_safe_float(rec.get("gap_pct")))
        pb = rec.get("playbook_name") or "UNKNOWN"
        key = f"{gb}:{pb}"
        entry = buckets.setdefault(key, {"total": 0, "profitable": 0, "pnl_sum": 0.0})
        entry["total"] += 1
        if profitable is True:
            entry["profitable"] += 1
        entry["pnl_sum"] += _safe_float(pnl)

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


def infer_trade_direction(row: dict[str, Any]) -> str:
    """Infer the intended trade direction for a ranked candidate.

    The legacy ``profitable_30m`` label was long-only, which mislabels
    short-side setups (GAP_FADE) — eval-findings B1 (2026-06-11).

    Rules:
      • GAP_FADE playbook → fade the gap (gap up → short, gap down → long).
      • All other playbooks → continuation of the gap sign.
      • Missing/zero gap → "long" (conservative default).
    """
    gap_pct = _safe_float(row.get("gap_pct"))
    playbook = row.get("playbook")
    playbook_name = str(playbook.get("playbook", "")) if isinstance(playbook, dict) else str(playbook or "")
    if playbook_name == "GAP_FADE":
        return "short" if gap_pct > 0 else "long"
    return "short" if gap_pct < 0 else "long"


def _component_fields(row: dict[str, Any]) -> dict[str, float | None]:
    """Flatten the weighted ``score_breakdown`` components for persistence.

    c10b producer-bug fix (2026-06-11): ``outcomes_<date>.json`` records
    never carried the per-component values, so
    ``backfill_feature_importance()`` defaulted every component to 0.0 and
    every FI report since 2026-04-30 was built on all-zero feature
    vectors. Emits ``None`` (not 0.0) when the breakdown is absent so the
    backfill era-gate can tell "legacy record" apart from "component
    genuinely zero".
    """
    sb = row.get("score_breakdown")
    if not isinstance(sb, dict):
        return {key: None for key in FEATURE_TO_WEIGHT_KEY}
    return {
        key: (_safe_float(sb.get(key)) if key in sb else None)
        for key in FEATURE_TO_WEIGHT_KEY
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
        # RVOL fix (2026-07-23): read the scorer's ``volume_ratio`` (emitted on
        # every ranked row; the get_symbol_hit_rate lookup side already keys on
        # it) instead of re-deriving volume/avg_volume here. When the ratio is
        # missing or non-positive (the scorer emits 0.0 when the provider has
        # no volume/avg_volume data), record None — the old fabricated 0.0
        # pooled every missing-data record into the "low" rvol bucket of
        # compute_hit_rates(), contaminating "low" and leaving the higher
        # buckets a positively-selected remnant. The volume/avg_volume
        # fallback keeps rows from callers that don't carry volume_ratio;
        # missing avg_volume must still not masquerade as rvol=raw_volume
        # (WP-D7), so it degrades to 0.0 → None, never to a huge ratio.
        rvol_ratio = _safe_float(row.get("volume_ratio"), default=0.0)
        if rvol_ratio <= 0.0:
            avg_vol = _safe_float(row.get("avg_volume"), default=0.0)
            rvol_ratio = (_safe_float(row.get("volume")) / avg_vol) if avg_vol > 0 else 0.0
        has_rvol = rvol_ratio > 0.0

        records.append({
            "date": run_date.isoformat(),
            "symbol": row.get("symbol"),
            "gap_pct": gap_pct,
            "rvol": round(rvol_ratio, 4) if has_rvol else None,
            "score": row.get("score", 0.0),
            "confidence_tier": row.get("confidence_tier", "STANDARD"),
            "gap_bucket_label": _gap_bucket_label(gap_pct),
            "rvol_bucket_label": _rvol_bucket_label(rvol_ratio) if has_rvol else None,
            "regime": row.get("regime"),
            # Sprint C1: explicit alias consumed by the C5 regime
            # stratification + C9 drift watchdog. We emit BOTH keys so
            # legacy tooling that reads ``regime`` keeps working.
            "regime_at_entry": row.get("regime"),
            "zone_priority_rank": row.get("zone_priority_rank"),
            "zone_priority_score": row.get("zone_priority_score"),
            # Trend-state features (observe-only pass-throughs; no scorer
            # weight until FI evidence supports one).
            "trend_alignment": row.get("trend_alignment"),
            "dist_to_ema20_pct": row.get("dist_to_ema20_pct"),
            "ema50_slope_pct": row.get("ema50_slope_pct"),
            # Gap position vs prior-day H/L range (observe-only; eval C4).
            "gap_range_pos": row.get("gap_range_pos"),
            # Earnings-surprise magnitude for PEAD (observe-only; eval C2b — the
            # surprise of the most-recent REPORTED earnings, which HAS actuals,
            # paired with days_since_last_earnings for the drift window). No
            # scorer weight until FI evidence supports one. Replaces the retired
            # today's-earnings ``eps_surprise_pct`` (removed 2026-07-10 — it was
            # always 0: today's earnings are unreported at pre-open scoring time,
            # FI ledger confirmed 0 across all samples).
            "recent_eps_surprise_pct": row.get("recent_eps_surprise_pct"),
            "days_since_last_earnings": row.get("days_since_last_earnings"),
            # Signed news score: mention intensity × avg sentiment
            # (observe-only; audit 2026-07-07 — the weighted `news`
            # component is direction-blind by contract until c10b ends;
            # this column collects the FI evidence for a directional
            # variant BEFORE any weight moves).
            "news_directional_score": row.get("news_directional_score"),
            # VIX 9-day / 30-day term-structure ratio (observe-only;
            # eval D5). > 1 ⇒ inverted short-term structure ⇒ imminent
            # event risk priced in. Market-wide (same for all rows).
            "vix9d_vix_ratio": row.get("vix9d_vix_ratio"),
            # Market-microstructure context (observe-only; regime-study
            # plan 2026-07): do moves run, do stocks differentiate, how
            # much lockstep? Market-wide (same for all rows in a run).
            "market_efficiency_ratio": row.get("market_efficiency_ratio"),
            "intraday_efficiency_ratio": row.get("intraday_efficiency_ratio"),
            "cs_dispersion": row.get("cs_dispersion"),
            "avg_pair_correlation": row.get("avg_pair_correlation"),
            "market_weather": row.get("market_weather"),
            # Direction-aware labeling inputs (eval-findings B1/B2):
            # ``direction`` signs the PnL during backfill; ``atr_pct``
            # scales the triple-barrier levels; ``playbook`` enables
            # gap×playbook bucket reports.
            "direction": infer_trade_direction(row),
            "atr_pct": _safe_float(row.get("atr_pct_computed") or row.get("atr_pct")),
            "playbook_name": (
                row["playbook"].get("playbook")
                if isinstance(row.get("playbook"), dict)
                else None
            ),
            "profitable_30m": None,  # Back-filled post-open
            "pnl_30m_pct": None,     # Back-filled post-open
            # Direction-signed + triple-barrier labels (back-filled; B1/B2).
            "pnl_30m_pct_signed": None,
            "profitable_30m_directional": None,
            "label_tb": None,
            "profitable_tb": None,
            # Weighted score components (c10b producer-bug fix): persisted
            # flat so backfill_feature_importance() reads real values
            # instead of defaulting every component to 0.0.
            **_component_fields(row),
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
    "analyst_catalyst_component",  # legacy name; measures analyst COVERAGE breadth (see config_validation.py)
    "vwap_distance_component",
    "freshness_component",
    "institutional_component",
    "estimate_revision_component",
    "zone_priority_score",
    "trend_alignment",
    "dist_to_ema20_pct",
    "ema50_slope_pct",
    "gap_range_pos",
    "recent_eps_surprise_pct",
    "days_since_last_earnings",
    "vix9d_vix_ratio",
    "market_efficiency_ratio",
    "intraday_efficiency_ratio",
    "cs_dispersion",
    "avg_pair_correlation",
    "news_directional_score",
]

# Observe-only features: recorded in outcome records + FI samples but
# intentionally NOT mapped to a scorer weight.  Promotion to a weighted
# component requires feature-importance evidence first.
PASS_THROUGH_FEATURE_KEYS: frozenset[str] = frozenset({
    "news_directional_score",
    "zone_priority_score",
    "trend_alignment",
    "dist_to_ema20_pct",
    "ema50_slope_pct",
    "gap_range_pos",
    "recent_eps_surprise_pct",
    "days_since_last_earnings",
    "vix9d_vix_ratio",
    "market_efficiency_ratio",
    "intraday_efficiency_ratio",
    "cs_dispersion",
    "avg_pair_correlation",
})

# G1: Explicit mapping from feature importance keys → scorer weight keys.
# PASS_THROUGH_FEATURE_KEYS entries are intentionally absent here.
FEATURE_TO_WEIGHT_KEY: dict[str, str] = {
    "gap_component": "gap",
    "gap_sector_rel_component": "gap_sector_relative",
    "rvol_component": "rvol",
    "macro_component": "macro",
    "momentum_component": "momentum_z",
    "hvb_component": "hvb",
    "earnings_bmo_component": "earnings_bmo",
    "news_component": "news",
    "ext_hours_component": "ext_hours",
    "analyst_catalyst_component": "analyst_catalyst",  # feature measures coverage breadth, NOT a rating action
    "vwap_distance_component": "vwap_distance",
    "freshness_component": "freshness_decay",
    "institutional_component": "institutional_quality",
    "estimate_revision_component": "estimate_revision",
    # PASS_THROUGH_FEATURE_KEYS are not weighted components; omitted intentionally.
}

FEATURE_IMPORTANCE_DIR = OUTCOMES_DIR / "feature_importance"
_MAX_RING_BUFFER = 100_000

# Formula-era gate (2026-07-02, PR #3114): the component-cap rewrite rescaled
# concentration-dominant components (e.g. gap_component ~0.1 -> ~6.0 for the
# same archetype, because the old loop crushed lone components to raw*0.40**5).
# Pooling pre/post-rewrite samples into one Pearson/Cohen's-d window mixes two
# non-stationary feature scales, so drop pre-rewrite rows — same pattern as the
# 2026-06-11 all-zero legacy gate below.
_SCORE_FORMULA_ERA_CUTOFF = date(2026, 7, 2)
# Directional-label era (2026-07-13): from this date the backfill feeds the
# DIRECTION-SIGNED outcome (profitable_30m_directional, B1 parity with
# compute_hit_rates) into the FI samples. Earlier fi_samples rows carry the
# long-only label (sign-inverted for short setups like GAP_FADE), so pooling
# them would mix two label semantics in one training set — drop pre-cutover
# rows, same pattern as the formula-era gate above.
_DIRECTIONAL_LABEL_ERA_CUTOFF = date(2026, 7, 14)
FI_BACKEND_AUTO = "auto"
FI_BACKEND_CPU = "cpu"
FI_BACKEND_GPU = "gpu"
_FI_BACKEND_CHOICES = frozenset({FI_BACKEND_AUTO, FI_BACKEND_CPU, FI_BACKEND_GPU})


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
        # C-sprint deep-review C1: track how many times the ring buffer
        # has been flushed-and-cleared so observability/tests can detect
        # in-process flush churn without scraping log lines. NOTE: in-process
        # only — a hot-restart constructs a fresh collector with count 0, so
        # cross-restart buffer wipes are NOT observable here.
        self._reset_count: int = 0

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
            "date": run_date or datetime.now(_ET).date().isoformat(),
            "total_score": total_score,
            "confidence_tier": confidence_tier,
            "profitable_30m": profitable_30m,
            "pnl_30m_pct": pnl_30m_pct,
        }
        for key in FEATURE_KEYS:
            sample[key] = _safe_float(score_breakdown[key]) if key in score_breakdown else None  # None = not measured
        self._buffer.append(sample)

    def flush_to_disk(self, run_date: date | None = None) -> Path | None:
        """Persist collected samples as JSONL and clear the buffer."""
        if not self._buffer:
            return None
        FEATURE_IMPORTANCE_DIR.mkdir(parents=True, exist_ok=True)
        rd = run_date or datetime.now(_ET).date()
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
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise
        count = len(self._buffer)
        self._buffer.clear()
        self._reset_count += 1
        logger.info("Feature importance: flushed %d samples → %s", count, path)
        return path

    @property
    def sample_count(self) -> int:
        return len(self._buffer)

    @property
    def reset_count(self) -> int:
        """Number of successful ``flush_to_disk`` calls since construction.

        C-sprint deep-review C1: exposed so callers can detect ring-buffer
        churn (e.g., repeated hot-restarts wiping samples before any
        meaningful aggregation could happen).
        """

        return self._reset_count


def _normalize_fi_backend_name(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in _FI_BACKEND_CHOICES:
        return normalized
    return FI_BACKEND_AUTO


def _to_python_float(value: Any) -> float:
    with contextlib.suppress(TypeError, ValueError, AttributeError):
        return float(value.item())
    with contextlib.suppress(TypeError, ValueError, AttributeError):
        return float(value.get())
    return float(value)


def _decode_cuda_device_name(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        with contextlib.suppress(UnicodeDecodeError):
            return raw.decode("utf-8")
        return raw.decode("utf-8", errors="replace")
    return str(raw)


def _resolve_feature_importance_backend(requested_backend: str | None = None) -> dict[str, Any]:
    requested = _normalize_fi_backend_name(
        requested_backend or os.getenv("OPEN_PREP_FI_BACKEND", FI_BACKEND_AUTO),
    )
    device_raw = str(os.getenv("OPEN_PREP_FI_GPU_DEVICE", "0") or "0").strip()
    try:
        device_id = int(device_raw)
    except ValueError as exc:
        if requested == FI_BACKEND_GPU:
            raise RuntimeError(
                f"OPEN_PREP_FI_GPU_DEVICE must be an integer, got {device_raw!r}",
            ) from exc
        return {
            "requested": requested,
            "used": FI_BACKEND_CPU,
            "reason": f"invalid_gpu_device:{device_raw}",
            "device_id": None,
            "device_name": None,
        }

    if requested == FI_BACKEND_CPU:
        return {
            "requested": requested,
            "used": FI_BACKEND_CPU,
            "reason": "requested_cpu",
            "device_id": None,
            "device_name": None,
        }

    if cp is None:
        if requested == FI_BACKEND_GPU:
            raise RuntimeError(
                "OPEN_PREP_FI_BACKEND=gpu requested but CuPy is not installed. "
                "Install requirements-gpu.txt on the GPU runner.",
            )
        return {
            "requested": requested,
            "used": FI_BACKEND_CPU,
            "reason": "cupy_unavailable",
            "device_id": None,
            "device_name": None,
        }

    try:
        device_count = int(cp.cuda.runtime.getDeviceCount())
        if device_count <= 0:
            raise RuntimeError("no CUDA devices detected")
        if device_id < 0 or device_id >= device_count:
            raise RuntimeError(
                f"GPU device index {device_id} is out of range for {device_count} device(s)",
            )

        with cp.cuda.Device(device_id):
            probe = cp.asarray([1.0, 2.0, 3.0], dtype=cp.float64)
            float(cp.sum(probe * probe).item())
            properties = cp.cuda.runtime.getDeviceProperties(device_id)

        device_name_raw = properties.get("name") if isinstance(properties, dict) else None
        device_name = _decode_cuda_device_name(device_name_raw)
        return {
            "requested": requested,
            "used": FI_BACKEND_GPU,
            "reason": f"cuda_device:{device_id}",
            "device_id": device_id,
            "device_name": device_name,
        }
    except Exception as exc:
        if requested == FI_BACKEND_GPU:
            raise RuntimeError(f"GPU backend requested but unavailable: {exc}") from exc
        return {
            "requested": requested,
            "used": FI_BACKEND_CPU,
            "reason": f"gpu_probe_failed:{type(exc).__name__}",
            "device_id": None,
            "device_name": None,
        }


def _build_feature_importance_arrays(
    labeled: list[dict[str, Any]],
) -> tuple[np.ndarray, np.ndarray]:
    feature_matrix = np.asarray(
        # None/absent = "not measured" (a pass-through feature that did not
        # exist when the sample was written, e.g. news_directional_score
        # pre-2026-07-08). Encode as NaN so the per-feature statistics mask
        # those rows — coercing to 0.0 laundered absence into a block of
        # fabricated neutral measurements that diluted the FI evidence.
        [
            [
                float("nan") if sample.get(key) is None else _safe_float(sample.get(key))
                for key in FEATURE_KEYS
            ]
            for sample in labeled
        ],
        dtype=np.float64,
    )
    outcomes = np.asarray(
        [1.0 if sample["profitable_30m"] else 0.0 for sample in labeled],
        dtype=np.float64,
    )
    return feature_matrix, outcomes


def _normalize_sample_dates(sample_dates: Iterable[str | date] | None) -> set[str] | None:
    if sample_dates is None:
        return None
    normalized: set[str] = set()
    for raw in sample_dates:
        if raw is None:
            continue
        if isinstance(raw, date):
            normalized.add(raw.isoformat())
            continue
        text = str(raw).strip()
        if not text:
            continue
        try:
            normalized.add(date.fromisoformat(text[:10]).isoformat())
        except ValueError:
            continue
    return normalized


def _compute_feature_statistics(
    feature_matrix: Any,
    outcomes: Any,
    *,
    xp: Any,
) -> dict[str, dict[str, float]]:
    stats: dict[str, dict[str, float]] = {}
    outcomes = outcomes.astype(xp.float64, copy=False)
    win_mask = outcomes > 0.5
    loss_mask = ~win_mask

    for index, key in enumerate(FEATURE_KEYS):
        vals = feature_matrix[:, index].astype(xp.float64, copy=False)

        # NaN = "not measured": the feature did not exist when the sample was
        # written (era-gated pass-throughs, e.g. news_directional_score
        # pre-2026-07-08). Mask those rows for THIS feature only — the sample
        # still contributes to every feature it actually measured. Works for
        # both backends (xp is numpy or cupy).
        measured = ~xp.isnan(vals)
        vals = vals[measured]
        feature_outcomes = outcomes[measured]
        feature_win_mask = win_mask[measured]
        feature_loss_mask = loss_mask[measured]

        centered_vals = vals - xp.mean(vals) if vals.size else vals
        centered_outcomes = (
            feature_outcomes - xp.mean(feature_outcomes) if vals.size else feature_outcomes
        )
        denom = xp.sqrt(xp.sum(centered_vals * centered_vals)) * xp.sqrt(
            xp.sum(centered_outcomes * centered_outcomes),
        )
        denom_value = _to_python_float(denom) if vals.size >= 3 else 0.0
        pearson = (
            _to_python_float(xp.sum(centered_vals * centered_outcomes)) / denom_value
            if vals.size >= 3 and denom_value > 0.0
            else 0.0
        )

        wins = vals[feature_win_mask]
        losses = vals[feature_loss_mask]
        n_win = int(wins.size)
        n_loss = int(losses.size)
        mean_win = _to_python_float(xp.mean(wins)) if n_win else 0.0
        mean_loss = _to_python_float(xp.mean(losses)) if n_loss else 0.0
        var_win = (
            _to_python_float(xp.sum((wins - mean_win) ** 2)) / (n_win - 1)
            if n_win > 1 else 0.0
        )
        var_loss = (
            _to_python_float(xp.sum((losses - mean_loss) ** 2)) / (n_loss - 1)
            if n_loss > 1 else 0.0
        )
        # Cohen's d denominator: POOLED std across both classes
        # (eval-findings B3, 2026-06-11). The previous σ_win-only
        # denominator inflated separation whenever winners clustered.
        if n_win + n_loss > 2:
            pooled_var = (
                (max(n_win - 1, 0) * var_win + max(n_loss - 1, 0) * var_loss)
                / (n_win + n_loss - 2)
            )
            pooled_std = max(math.sqrt(pooled_var), 0.001)
        else:
            pooled_std = 0.001
        separation = abs(mean_win - mean_loss) / pooled_std

        # Welch's t-test (normal approximation for the two-sided p-value;
        # adequate at the n ≥ 200 tuning gate). p = 1.0 (no evidence) when
        # either class is too small or variance degenerates.
        se_sq = (var_win / n_win if n_win else 0.0) + (var_loss / n_loss if n_loss else 0.0)
        if n_win >= 2 and n_loss >= 2 and se_sq > 0:
            t_stat = (mean_win - mean_loss) / math.sqrt(se_sq)
            p_value = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(t_stat) / math.sqrt(2.0))))
        else:
            p_value = 1.0

        stats[key] = {
            "pearson_r": round(float(pearson), 4),
            "mean_separation": round(float(separation), 4),
            "mean_win": round(float(mean_win), 4),
            "mean_loss": round(float(mean_loss), 4),
            "p_value": round(float(p_value), 6),
        }

    return stats


def _compute_feature_statistics_cpu(
    feature_matrix: np.ndarray,
    outcomes: np.ndarray,
) -> dict[str, dict[str, float]]:
    return _compute_feature_statistics(feature_matrix, outcomes, xp=np)


def _compute_feature_statistics_gpu(
    feature_matrix: np.ndarray,
    outcomes: np.ndarray,
    *,
    device_id: int,
) -> dict[str, dict[str, float]]:
    if cp is None:  # pragma: no cover - guarded by backend resolution
        raise RuntimeError("CuPy is unavailable")
    with cp.cuda.Device(device_id):
        gpu_features = cp.asarray(feature_matrix, dtype=cp.float64)
        gpu_outcomes = cp.asarray(outcomes, dtype=cp.float64)
        return _compute_feature_statistics(gpu_features, gpu_outcomes, xp=cp)


def compute_feature_importance(
    lookback_days: int = 30,
    sample_dates: Iterable[str | date] | None = None,
) -> dict[str, Any]:
    """Offline report: which score components predict profitable_30m?

    Loads JSONL samples from the last ``lookback_days`` days and computes:
      - Pearson correlation between each feature component and the binary
        ``profitable_30m`` outcome.
      - Mean-separation importance: ``|mean_win − mean_loss| / pooled_std``
        per feature, normalized to [0, 1].

    Returns a dict with per-feature stats + calibration recommendations.
    """
    backend = _resolve_feature_importance_backend()
    if not FEATURE_IMPORTANCE_DIR.exists():
        return {
            "error": "no feature importance data found",
            "backend": backend,
        }

    files = sorted(FEATURE_IMPORTANCE_DIR.glob("fi_samples_*.jsonl"), reverse=True)
    samples: list[dict[str, Any]] = []
    selected_dates = _normalize_sample_dates(sample_dates)
    loaded_dates: set[date] = set()
    for path in files:
        file_date = _extract_date_from_stem(path.stem, prefix="fi_samples_")
        if file_date is None:
            # A non-dated ``fi_samples_*.jsonl`` (e.g. a stray backup) bypasses
            # the lookback count AND — sorting after all dated stems in the
            # reverse sort — would be read FIRST, so its stale rows win the
            # (symbol, date) dedup over genuinely fresh files. Skip it (same
            # fix as _load_outcomes_range).
            logger.warning("Skipping non-dated FI samples file: %s", path.name)
            continue
        if file_date not in loaded_dates and len(loaded_dates) >= lookback_days:
            break
        try:
            with open(path, encoding="utf-8") as fh:
                for line_no, line in enumerate(fh, start=1):
                    line = line.strip()
                    if line:
                        try:
                            samples.append(json.loads(line))
                        except json.JSONDecodeError as exc:
                            logger.warning(
                                "Failed to parse FI line %s:%d (%s)",
                                path,
                                line_no,
                                exc,
                            )
                            continue
            if file_date is not None:
                loaded_dates.add(file_date)
        except Exception:
            logger.warning("Failed to load FI file: %s", path, exc_info=True)

    # (symbol, date) dedup (2026-06-11): the daily backfill re-emits its
    # full lookback window into each day's fi_samples file, so the same
    # candidate-row appears in up to `lookback` consecutive files.
    # Counting those copies as independent observations inflated n — and
    # the Welch t-statistics feeding the BH-FDR gate — by roughly the
    # overlap factor (~3× observed). Files are iterated newest-first, so
    # the first occurrence (freshest labels) wins. Samples without both
    # keys (synthetic/legacy) are kept as-is.
    deduped: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    duplicate_samples_dropped = 0
    for sample in samples:
        sym = sample.get("symbol")
        run_d = sample.get("date")
        if sym and run_d:
            dedup_key = (str(sym), str(run_d))
            if dedup_key in seen_keys:
                duplicate_samples_dropped += 1
                continue
            seen_keys.add(dedup_key)
        deduped.append(sample)
    samples = deduped

    if selected_dates is not None:
        scoped: list[dict[str, Any]] = []
        for sample in samples:
            raw_d = sample.get("date")
            if not raw_d:
                continue
            try:
                sample_date = date.fromisoformat(str(raw_d)[:10]).isoformat()
            except ValueError:
                continue
            if sample_date in selected_dates:
                scoped.append(sample)
        samples = scoped

    # Filter to samples with known outcome
    labeled = [s for s in samples if s.get("profitable_30m") is not None]

    # Reader-side era-gate (audit D-2, 2026-06-12): fi_samples files
    # written before the 2026-06-11 component-persistence fix carry the
    # weighted components as literal 0.0 (the collector defaulted absent
    # breakdown keys to zero). The 2026-06-11 era-gate only fixed the
    # WRITER; this reader kept mixing those poisoned rows into the
    # matrix, so reports stayed vacuous (every importance = 0.00) for a
    # full lookback window after the fix. A genuine sample never has ALL
    # 14 weighted components at exactly 0.0, so an all-zero weighted
    # vector identifies a pre-fix row.
    era_gated_samples_dropped = 0
    component_complete: list[dict[str, Any]] = []
    for s in labeled:
        vals = [_safe_float(s.get(k)) for k in FEATURE_TO_WEIGHT_KEY]
        if all(v == 0.0 for v in vals):
            era_gated_samples_dropped += 1
            continue
        component_complete.append(s)
    if era_gated_samples_dropped:
        logger.warning(
            "FI report: dropped %d/%d labeled samples with all-zero weighted "
            "component vectors (legacy pre-2026-06-11 fi_samples rows)",
            era_gated_samples_dropped,
            len(labeled),
        )
    labeled = component_complete

    # Formula-era gate (2026-07-02, PR #3114): drop rows scored before the
    # component-cap rewrite. Their concentration-dominant components live on a
    # different scale (crushed to raw*0.40**5), so pooling them with post-rewrite
    # rows mixes two non-stationary feature scales and poisons the statistics.
    # A sample whose ``date`` is absent or unparseable is kept (conservative,
    # mirrors the dedup path that keeps synthetic/legacy rows).
    formula_era_samples_dropped = 0
    post_rewrite: list[dict[str, Any]] = []
    for s in labeled:
        raw_d = s.get("date")
        sample_date: date | None = None
        if raw_d:
            try:
                sample_date = date.fromisoformat(str(raw_d)[:10])
            except ValueError:
                sample_date = None
        if sample_date is not None and sample_date < _SCORE_FORMULA_ERA_CUTOFF:
            formula_era_samples_dropped += 1
            continue
        post_rewrite.append(s)
    if formula_era_samples_dropped:
        logger.warning(
            "FI report: dropped %d/%d labeled samples scored before the "
            "2026-07-02 component-cap rewrite (pre-rewrite feature scale)",
            formula_era_samples_dropped,
            len(labeled),
        )
    labeled = post_rewrite

    # Directional-label era gate (2026-07-13): fi_samples rows written before
    # _DIRECTIONAL_LABEL_ERA_CUTOFF carry the legacy LONG-ONLY outcome label
    # (sign-inverted for short setups such as GAP_FADE); from the cutover the
    # backfill feeds the direction-signed label. Pooling both would mix two
    # label semantics in one training set, so drop pre-cutover rows — same
    # pattern (and same conservative keep-on-unparseable-date rule) as the
    # formula-era gate above.
    directional_era_samples_dropped = 0
    directional_era: list[dict[str, Any]] = []
    for s in labeled:
        raw_d = s.get("date")
        sample_date = None
        if raw_d:
            try:
                sample_date = date.fromisoformat(str(raw_d)[:10])
            except ValueError:
                sample_date = None
        if sample_date is not None and sample_date < _DIRECTIONAL_LABEL_ERA_CUTOFF:
            directional_era_samples_dropped += 1
            continue
        directional_era.append(s)
    if directional_era_samples_dropped:
        logger.warning(
            "FI report: dropped %d/%d labeled samples from before the "
            "2026-07-14 directional-label cutover (legacy long-only labels)",
            directional_era_samples_dropped,
            len(labeled),
        )
    labeled = directional_era

    if len(labeled) < 10:
        return {
            "error": "insufficient labeled samples",
            "total_samples": len(samples),
            "labeled_samples": len(labeled),
            "duplicate_samples_dropped": duplicate_samples_dropped,
            "era_gated_samples_dropped": era_gated_samples_dropped,
            "formula_era_samples_dropped": formula_era_samples_dropped,
            "directional_era_samples_dropped": directional_era_samples_dropped,
            "sample_dates_filter": sorted(selected_dates) if selected_dates is not None else None,
            "backend": backend,
        }

    feature_matrix, outcomes = _build_feature_importance_arrays(labeled)

    report: dict[str, Any] = {
        "total_samples": len(samples),
        "labeled_samples": len(labeled),
        "duplicate_samples_dropped": duplicate_samples_dropped,
        "era_gated_samples_dropped": era_gated_samples_dropped,
        "formula_era_samples_dropped": formula_era_samples_dropped,
        "directional_era_samples_dropped": directional_era_samples_dropped,
        "sample_dates_filter": sorted(selected_dates) if selected_dates is not None else None,
        "features": {},
        "recommendations": [],
        "backend": backend,
    }

    if backend["used"] == FI_BACKEND_GPU:
        feature_stats = _compute_feature_statistics_gpu(
            feature_matrix,
            outcomes,
            device_id=int(backend["device_id"] or 0),
        )
    else:
        feature_stats = _compute_feature_statistics_cpu(feature_matrix, outcomes)

    importance_scores = {
        key: float(stats["mean_separation"])
        for key, stats in feature_stats.items()
    }
    report["features"] = feature_stats

    # BH-FDR gate (eval-findings B3): stamp ``fdr_significant`` onto every
    # feature so downstream consumers (compute_weight_adjustments,
    # recommendations) can distinguish evidence from noise. Without this
    # wiring the q=0.05 gate would silently neutralize ALL features
    # (fail-closed default) and auto-tuning would never move a weight.
    fdr_flags = _benjamini_hochberg(
        {key: float(stats["p_value"]) for key, stats in feature_stats.items()},
    )
    for key, stats in feature_stats.items():
        stats["fdr_significant"] = bool(fdr_flags.get(key, False))

    # Normalize importance to [0, 1]
    max_imp = max(importance_scores.values()) if importance_scores else 1.0
    if max_imp > 0:
        for key in FEATURE_KEYS:
            report["features"][key]["importance_normalized"] = round(
                importance_scores[key] / max_imp, 4,
            )

    # Generate recommendations — only for features that pass the FDR gate
    # (eval-findings B3): a strong-looking r without significance is noise.
    for key in FEATURE_KEYS:
        feat = report["features"][key]
        r = feat["pearson_r"]
        imp = feat.get("importance_normalized", 0)
        if abs(r) > 0.5 and feat.get("fdr_significant", False):
            report["recommendations"].append(
                f"🟢 {key}: strong predictor (r={r:.2f}). Consider increasing weight."
            )
        elif imp < 0.2:
            report["recommendations"].append(
                f"🔴 {key}: weak predictor (importance={imp:.2f}). Consider reducing weight."
            )

    return report


# ═══════════════════════════════════════════════════════════════════════════
# #4  G2 — Automated Scorer Weight Tuning
# ═══════════════════════════════════════════════════════════════════════════

# Bayesian smoothing factor for weight updates (same philosophy as zone
# priority calibration): ``(1 - smoothing) × data_weight + smoothing × prior``.
_SCORER_SMOOTHING = 0.3

# Minimum labeled samples to attempt auto-tuning.
# 2026-06-11 (eval-findings B3): raised 30 → 200. With ~19 features, n=30
# gives correlation-estimate σ ≈ 0.19 — weight updates at that sample size
# are noise-fitting. 200 matches the governance-layer MIN_OOS philosophy.
_MIN_TUNING_SAMPLES = 200

# BH-FDR level for feature-importance significance gating (mirrors the
# promotion-gate FDR-q ≤ 0.05 used in governance/promotion_gate.py).
_FDR_Q = 0.05


def _benjamini_hochberg(p_values: dict[str, float], q: float = _FDR_Q) -> dict[str, bool]:
    """Benjamini–Hochberg step-up: ``{key: significant}`` at FDR level *q*."""
    if not p_values:
        return {}
    ordered = sorted(p_values.items(), key=lambda kv: kv[1])
    m = len(ordered)
    cutoff_rank = 0
    for rank, (_, p) in enumerate(ordered, start=1):
        if p <= q * rank / m:
            cutoff_rank = rank
    return {
        key: rank <= cutoff_rank
        for rank, (key, _) in enumerate(ordered, start=1)
    }


# Maximum weight drift allowed from DEFAULT_WEIGHTS before CI gate trips.
_MAX_SCORER_DRIFT = 0.50  # absolute


@dataclass
class ScorerWeightUpdate:
    """Result of a single weight auto-tuning run."""

    updated_weights: dict[str, float]
    prior_weights: dict[str, float]
    deltas: dict[str, float]
    feature_report: dict[str, Any]
    labeled_samples: int
    smoothing: float


def compute_weight_adjustments(
    feature_report: dict[str, Any],
    current_weights: dict[str, float],
    *,
    smoothing: float = _SCORER_SMOOTHING,
) -> ScorerWeightUpdate:
    """Translate feature-importance rankings into Bayesian weight updates.

    For each feature that maps to a scorer weight key:

    1. Extract ``importance_normalized`` from the feature report (0–1).
    2. Compute ``data_weight = current_weight × (0.5 + importance_normalized)``.
       - Importance 1.0 → 50% upward scaling.
       - Importance 0.0 → 50% downward scaling.
    3. Bayesian blend: ``new = (1 - smoothing) × data_weight + smoothing × prior``.

    Features without a weight mapping (``PASS_THROUGH_FEATURE_KEYS``) are
    skipped.  Weights not covered by FEATURE_TO_WEIGHT_KEY (penalties, ewma)
    are passed through unchanged.
    """
    if "error" in feature_report:
        raise ValueError(
            f"Cannot tune weights: {feature_report['error']} "
            f"(labeled={feature_report.get('labeled_samples', 0)})"
        )

    from open_prep.scorer import DEFAULT_WEIGHTS

    prior = dict(DEFAULT_WEIGHTS)
    updated = dict(current_weights)
    deltas: dict[str, float] = {}

    features = feature_report.get("features", {})

    for feat_key, weight_key in FEATURE_TO_WEIGHT_KEY.items():
        feat = features.get(feat_key)
        if feat is None:
            continue
        # eval-findings B3: features that fail the BH-FDR gate carry NO
        # statistical evidence — force a neutral importance (0.5) so the
        # data_weight equals the current weight and only the prior pull
        # applies (no noise-driven boost/cut).
        if not feat.get("fdr_significant", False):
            imp = 0.5
        else:
            imp = feat.get("importance_normalized", 0.5)
        cur = current_weights.get(weight_key, prior.get(weight_key, 0.5))
        p = prior.get(weight_key, cur)

        # Scale current weight by importance: range [0.5×, 1.5×].
        data_weight = cur * (0.5 + imp)

        # Bayesian blend with prior.
        new_weight = (1 - smoothing) * data_weight + smoothing * p
        new_weight = round(max(new_weight, 0.01), 4)  # floor at 0.01

        updated[weight_key] = new_weight
        deltas[weight_key] = round(new_weight - cur, 4)

    return ScorerWeightUpdate(
        updated_weights=updated,
        prior_weights=prior,
        deltas=deltas,
        feature_report=feature_report,
        labeled_samples=feature_report.get("labeled_samples", 0),
        smoothing=smoothing,
    )


def check_scorer_drift(
    weights: dict[str, float],
    *,
    max_drift: float = _MAX_SCORER_DRIFT,
) -> list[str]:
    """Return human-readable violation strings for excessive weight drift.

    Compares *weights* against ``DEFAULT_WEIGHTS`` from scorer.py.
    Each weight that drifts more than *max_drift* generates a violation.
    """
    from open_prep.scorer import DEFAULT_WEIGHTS

    violations: list[str] = []
    for key, default in DEFAULT_WEIGHTS.items():
        current = weights.get(key, default)
        drift = abs(current - default)
        if drift > max_drift:
            violations.append(
                f"{key}: drift={drift:.4f} (default={default}, current={current})"
            )
    return violations


def scorer_update_to_json(update: ScorerWeightUpdate) -> dict[str, Any]:
    """Serialize a ScorerWeightUpdate for artifact persistence."""
    return {
        "updated_weights": update.updated_weights,
        "prior_weights": update.prior_weights,
        "deltas": {k: v for k, v in update.deltas.items() if abs(v) > 1e-6},
        "labeled_samples": update.labeled_samples,
        "smoothing": update.smoothing,
    }

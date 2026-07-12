"""Candidate weight-set production with drift-gate (ENG-WS4-03).

Realises ticket ``ENG-WS4-03`` from
``docs/engineering-program/smc_deep_review_2026-04-20_engineering_backlog.md``.

The pieces — feature-importance computation
(:mod:`open_prep.outcomes`.compute_feature_importance), Bayesian weight
adjustment (compute_weight_adjustments), drift detection
(check_scorer_drift), and weight persistence
(:mod:`open_prep.scorer`.save_weight_set) — already exist. This module
wires them into one deterministic CLI so a candidate weight set can be
produced automatically, gated against extreme drift, and versioned
distinctly from the default weights.

Run-log layout::

    artifacts/open_prep/candidate_weights/
        candidate_<run_id>.json   # full record per run
        latest.json               # pointer to the last record

Status values:

* ``ok``                — weights regenerated, drift gate clean, saved
                          as ``weights_candidate.json`` via scorer.
* ``insufficient_data`` — FI report below threshold, no candidate
                          produced; default keeps serving.
* ``drift_blocked``     — weights computed but drift-gate fired; the
                          candidate file is *not* written so the next
                          loader call still resolves to default.
  (No ``error`` record is written: an unexpected failure logs + exits 2 below.)

Exit codes:

* ``0`` for ok / insufficient_data / drift_blocked (state is the
  product output).
* ``2`` only on internal error.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import logging
import math
import os
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo as _ZoneInfo

from open_prep import scorer as scorer_mod
from open_prep.outcomes import (
    _MIN_TUNING_SAMPLES,
    FEATURE_IMPORTANCE_DIR,
    check_scorer_drift,
    compute_feature_importance,
    compute_weight_adjustments,
    scorer_update_to_json,
)
from open_prep.scorer import DEFAULT_WEIGHTS, save_weight_set

logger = logging.getLogger("open_prep.candidate_weights")

_ET = _ZoneInfo("America/New_York")

CANDIDATE_RUN_LOG_DIR = Path("artifacts/open_prep/candidate_weights")
CANDIDATE_LABEL = "candidate"
# Align with the governance tuning gate (eval-findings B3): n=30 gives
# correlation-estimate σ ≈ 0.19 with ~19 features — weight updates at that
# sample size are noise-fitting. Reference the single source of truth.
DEFAULT_MIN_SAMPLES = _MIN_TUNING_SAMPLES
DEFAULT_MAX_DRIFT = 0.50
DEFAULT_HOLDOUT_FRACTION = 0.20


def _normalize_iso_date(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw.isoformat()
    text = str(raw).strip()
    if not text:
        return None
    with contextlib.suppress(ValueError):
        return date.fromisoformat(text[:10]).isoformat()
    return None


def _collect_fi_sample_dates(*, lookback_days: int) -> list[str]:  # NOTE (2026-07-08): lookback_days caps the NUMBER of most-recent sample DATES (one per trading-day file), not a calendar window — 30 "days" ≈ 30 trading days ≈ 6 calendar weeks
    if not FEATURE_IMPORTANCE_DIR.exists():
        return []
    files = sorted(FEATURE_IMPORTANCE_DIR.glob("fi_samples_*.jsonl"), reverse=True)
    loaded_dates: set[str] = set()
    ordered: list[str] = []
    for path in files:
        iso = _normalize_iso_date(path.stem.replace("fi_samples_", ""))
        if iso is None or iso in loaded_dates:
            continue
        loaded_dates.add(iso)
        ordered.append(iso)
        if len(ordered) >= max(int(lookback_days), 1):
            break
    ordered.sort()
    return ordered


def _split_train_holdout_dates(
    all_dates: list[str],
    *,
    holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION,
) -> tuple[list[str], list[str]]:
    uniq = sorted({d for d in all_dates if d})
    if len(uniq) <= 1:
        return uniq, []
    holdout_n = max(1, round(len(uniq) * max(min(holdout_fraction, 0.9), 0.1)))
    holdout_n = min(holdout_n, len(uniq) - 1)
    return uniq[:-holdout_n], uniq[-holdout_n:]


def _load_fi_holdout_samples(sample_dates: list[str]) -> list[dict[str, Any]]:
    selected = set(sample_dates)
    if not selected or not FEATURE_IMPORTANCE_DIR.exists():
        return []
    samples: list[dict[str, Any]] = []
    for path in sorted(FEATURE_IMPORTANCE_DIR.glob("fi_samples_*.jsonl"), reverse=True):
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    text = line.strip()
                    if not text:
                        continue
                    with contextlib.suppress(json.JSONDecodeError):
                        sample = json.loads(text)
                        iso = _normalize_iso_date(sample.get("date"))
                        if iso in selected and sample.get("profitable_30m") is not None:
                            samples.append(sample)
        except Exception:
            logger.warning("Failed to load holdout FI samples from %s", path, exc_info=True)
    # Match FI report semantics: newest file wins for duplicate (symbol, date)
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for sample in samples:
        sym = str(sample.get("symbol") or "").strip().upper()
        iso = _normalize_iso_date(sample.get("date"))
        if sym and iso:
            key = (sym, iso)
            if key in seen:
                continue
            seen.add(key)
        deduped.append(sample)
    return deduped


def _invert_sqrt_component(component: float, weight: float) -> float:
    if weight <= 0:
        return 0.0
    ratio = max(component / weight, 0.0)
    return max(0.0, min(ratio * ratio, 1.0))


def _build_filter_result_from_fi_sample(sample: dict[str, Any]) -> scorer_mod.FilterResult:
    # Reconstruct a score_candidate input from persisted FI components.
    # The inversion keeps the full scorer path (caps + penalties + gates)
    # active for holdout evaluation instead of linear component arithmetic.
    gap_component = float(sample.get("gap_component") or 0.0)
    gap_sector_component = float(sample.get("gap_sector_rel_component") or 0.0)
    rvol_component = float(sample.get("rvol_component") or 0.0)
    momentum_component = float(sample.get("momentum_component") or 0.0)
    hvb_component = float(sample.get("hvb_component") or 0.0)
    earnings_bmo_component = float(sample.get("earnings_bmo_component") or 0.0)
    news_component = float(sample.get("news_component") or 0.0)
    ext_component = float(sample.get("ext_hours_component") or 0.0)
    analyst_component = float(sample.get("analyst_catalyst_component") or 0.0)  # coverage breadth (legacy key name)
    vwap_component = float(sample.get("vwap_distance_component") or 0.0)
    freshness_component = float(sample.get("freshness_component") or 0.0)
    institutional_component = float(sample.get("institutional_component") or 0.0)
    estimate_component = float(sample.get("estimate_revision_component") or 0.0)

    gap_raw = gap_component / DEFAULT_WEIGHTS["gap"] if DEFAULT_WEIGHTS["gap"] else 0.0
    gap_sector_raw = (
        gap_sector_component / DEFAULT_WEIGHTS["gap_sector_relative"]
        if DEFAULT_WEIGHTS["gap_sector_relative"] else 0.0
    )
    rvol_norm = _invert_sqrt_component(rvol_component, DEFAULT_WEIGHTS["rvol"])
    rel_vol_capped = rvol_norm * max(float(scorer_mod.RVOL_CAP), 1e-9)
    news_norm = _invert_sqrt_component(news_component, DEFAULT_WEIGHTS["news"])
    ext_norm = _invert_sqrt_component(ext_component, DEFAULT_WEIGHTS["ext_hours"])
    ewma_norm = 0.5

    features: dict[str, Any] = {
        "price": 100.0,
        "gap_pct": gap_raw,
        "gap_available": True,
        "gap_pct_for_scoring": gap_raw,
        "sector_relative_gap": gap_sector_raw,
        "sector_change_pct": 0.0,
        "symbol_sector": "",
        "volume": max(rel_vol_capped, 0.0),
        "avg_volume": 1.0,
        "avg_volume_baseline_missing": False,
        "rel_vol": rel_vol_capped,
        "rel_vol_capped": rel_vol_capped,
        "atr": 0.0,
        "momentum_z": momentum_component / DEFAULT_WEIGHTS["momentum_z"] if DEFAULT_WEIGHTS["momentum_z"] else 0.0,
        "is_hvb": hvb_component > 0.0,
        "earnings_today": earnings_bmo_component > 0.0,
        "earnings_timing": "bmo" if earnings_bmo_component > 0.0 else "",
        "earnings_bmo": earnings_bmo_component > 0.0,
        "earnings_risk_window": False,
        "is_premarket_mover": False,
        "ext_hours_score": ext_norm,
        "ext_volume_ratio": 0.0,
        "premarket_stale": False,
        "premarket_spread_bps": None,
        "premarket_change_pct": None,
        "corporate_action_penalty": 0.0,
        "analyst_catalyst_score": (
            analyst_component / DEFAULT_WEIGHTS["analyst_catalyst"]
            if DEFAULT_WEIGHTS["analyst_catalyst"] else 0.0
        ),
        # FI holdout samples carry no analyst price-target data; None mirrors
        # the scorer's "no consensus available" value (#3261 added the field
        # to the scorer's row output, which reads it with a hard key).
        "analyst_implied_upside_pct": None,
        # Weight-0 evaluation pass-through (#3269); 0.0 is the scorer's own
        # default when no news metrics are present.
        "news_directional_score": 0.0,
        "split_today": False,
        "dividend_today": False,
        "ipo_window": False,
        "news_score": news_norm,
        "news_metrics": {},
        "vwap_distance_pct": (
            vwap_component / DEFAULT_WEIGHTS["vwap_distance"]
            if DEFAULT_WEIGHTS["vwap_distance"] else 0.0
        ),
        "freshness_decay": (
            freshness_component / DEFAULT_WEIGHTS["freshness_decay"]
            if DEFAULT_WEIGHTS["freshness_decay"] else 0.0
        ),
        "freshness_half_life_s": 600.0,
        "institutional_quality": (
            institutional_component / DEFAULT_WEIGHTS["institutional_quality"]
            if DEFAULT_WEIGHTS["institutional_quality"] else 0.0
        ),
        "estimate_revision_score": (
            estimate_component / DEFAULT_WEIGHTS["estimate_revision"]
            if DEFAULT_WEIGHTS["estimate_revision"] else 0.0
        ),
        "data_sufficiency_low": False,
        "gap_type": None,
        "gap_scope": None,
        "gap_from_ts": None,
        "gap_to_ts": None,
        "gap_reason": None,
        "gap_bucket": None,
        "gap_grade": None,
        "warn_flags": "",
        "atr_pct": None,
        "pdh": None,
        "pdl": None,
        "pdh_source": None,
        "pdl_source": None,
        "dist_to_pdh_atr": None,
        "dist_to_pdl_atr": None,
        "premarket_high": None,
        "premarket_low": None,
        "upgrade_downgrade_emoji": "",
        "upgrade_downgrade_label": "",
        "upgrade_downgrade_action": "",
        "upgrade_downgrade_firm": "",
        "upgrade_downgrade_date": None,
        "news_event_class": "UNKNOWN",
        "news_event_label": "generic",
        "news_event_labels_all": [],
        "news_materiality": "LOW",
        "news_recency_bucket": "UNKNOWN",
        "news_age_minutes": None,
        "news_is_actionable": False,
        "news_source_tier": "TIER_1",
        "news_source_rank": 1,
        "instrument_class": "mid_cap",
        "atr_pct_computed": 0.0,
        "spread_pct": 0.0,
        "data_quality_issues": [],
        "ewma_score": ewma_norm,
        "symbol_regime": "NEUTRAL",
        "name": "",
        "change": 0.0,
        "changesPercentage": 0.0,
        "pe": None,
        # Pass-through features recorded for FI visibility
        "zone_priority_score": float(sample.get("zone_priority_score") or 0.0),
        "trend_alignment": float(sample.get("trend_alignment") or 0.0),
        "dist_to_ema20_pct": float(sample.get("dist_to_ema20_pct") or 0.0),
        "ema50_slope_pct": float(sample.get("ema50_slope_pct") or 0.0),
        "gap_range_pos": float(sample.get("gap_range_pos") or 0.0),
        "recent_eps_surprise_pct": float(sample.get("recent_eps_surprise_pct") or 0.0),
        "days_since_last_earnings": float(sample.get("days_since_last_earnings") or 0.0),
        "vix9d_vix_ratio": float(sample.get("vix9d_vix_ratio") or 0.0),
    }
    return scorer_mod.FilterResult(
        symbol=str(sample.get("symbol") or ""),
        passed=True,
        filter_reasons=[],
        allowed_setups=[],
        max_trades=0,
        long_allowed=True,
        features=features,
    )


def _rescore_sample_with_weights(sample: dict[str, Any], weights: dict[str, float]) -> float:
    fr = _build_filter_result_from_fi_sample(sample)
    macro_weight = float(DEFAULT_WEIGHTS.get("macro") or 0.0)
    macro_component = float(sample.get("macro_component") or 0.0)
    bias = (macro_component / macro_weight) if macro_weight > 0.0 else 0.0
    rescored = scorer_mod.score_candidate(fr, bias=bias, weights=weights)
    score = rescored.get("score")
    if isinstance(score, (int, float)) and math.isfinite(float(score)):
        return float(score)
    return 0.0


def _compute_holdout_hit_rate(samples: list[dict[str, Any]], weights: dict[str, float]) -> dict[str, Any]:
    if not samples:
        return {
            "labeled_samples": 0,
            "evaluated_samples": 0,
            "top_n_per_day": 0,
            "hit_rate": None,
        }
    grouped: dict[str, list[tuple[float, bool]]] = {}
    evaluated = 0
    for sample in samples:
        iso = _normalize_iso_date(sample.get("date"))
        lbl = sample.get("profitable_30m")
        if iso is None or lbl is None:
            continue
        score = _rescore_sample_with_weights(sample, weights)
        grouped.setdefault(iso, []).append((score, bool(lbl)))
        evaluated += 1

    total_hits = 0
    total_picks = 0
    top_n_per_day = 0
    for rows in grouped.values():
        if not rows:
            continue
        ranked = sorted(rows, key=lambda it: it[0], reverse=True)
        top_n = max(1, min(5, len(ranked)))
        top_n_per_day = max(top_n_per_day, top_n)
        chosen = ranked[:top_n]
        total_hits += sum(1 for _, hit in chosen if hit)
        total_picks += len(chosen)

    hit_rate = (total_hits / total_picks) if total_picks > 0 else None
    return {
        "labeled_samples": len(samples),
        "evaluated_samples": evaluated,
        "top_n_per_day": top_n_per_day,
        "hit_rate": round(float(hit_rate), 4) if hit_rate is not None else None,
    }


# ── Generation ────────────────────────────────────────────────────────


def _now_run_id() -> tuple[str, str]:
    now = datetime.now(_ET)
    return now.strftime("%Y%m%dT%H%M%S"), now.isoformat()


def generate_candidate(
    *,
    lookback_days: int = 30,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    max_drift: float = DEFAULT_MAX_DRIFT,
) -> dict[str, Any]:
    """Compute a candidate weight set, gated against drift.

    Returns a serialisable record with status + payload; never raises
    for known states (insufficient data, drift block).
    """
    run_id, started_at = _now_run_id()
    base: dict[str, Any] = {
        "run_id": run_id,
        "generated_at_et": started_at,
        "lookback_days": int(lookback_days),
        "min_samples_threshold": int(min_samples),
        "max_drift_threshold": float(max_drift),
    }

    all_dates = _collect_fi_sample_dates(lookback_days=lookback_days)
    train_dates, holdout_dates = _split_train_holdout_dates(all_dates)
    fi_report = compute_feature_importance(
        lookback_days=lookback_days,
        sample_dates=train_dates or None,
    )
    labeled = int(fi_report.get("labeled_samples") or 0)

    if "error" in fi_report or labeled < min_samples:
        return {
            **base,
            "status": "insufficient_data",
            "labeled_samples": labeled,
            "shortfall": max(0, int(min_samples) - labeled),
            "candidate_label": None,
            "drift_violations": [],
            "weights": None,
            "fi_error": fi_report.get("error"),
            "train_dates": train_dates,
            "holdout_dates": holdout_dates,
            "holdout": None,
        }

    update = compute_weight_adjustments(fi_report, current_weights=dict(DEFAULT_WEIGHTS))
    candidate = update.updated_weights
    violations = check_scorer_drift(candidate, max_drift=max_drift)

    if violations:
        holdout_samples = _load_fi_holdout_samples(holdout_dates)
        holdout_default = _compute_holdout_hit_rate(holdout_samples, dict(DEFAULT_WEIGHTS))
        holdout_candidate = _compute_holdout_hit_rate(holdout_samples, candidate)
        holdout_delta: float | None = None
        if holdout_default["hit_rate"] is not None and holdout_candidate["hit_rate"] is not None:
            holdout_delta = round(float(holdout_candidate["hit_rate"] - holdout_default["hit_rate"]), 4)
        return {
            **base,
            "status": "drift_blocked",
            "labeled_samples": labeled,
            "shortfall": 0,
            "candidate_label": None,
            "drift_violations": violations,
            "weights": candidate,
            "weight_update": scorer_update_to_json(update),
            "train_dates": train_dates,
            "holdout_dates": holdout_dates,
            "holdout": {
                "default": holdout_default,
                "candidate": holdout_candidate,
                "hit_rate_delta": holdout_delta,
            },
        }

    holdout_samples = _load_fi_holdout_samples(holdout_dates)
    holdout_default = _compute_holdout_hit_rate(holdout_samples, dict(DEFAULT_WEIGHTS))
    holdout_candidate = _compute_holdout_hit_rate(holdout_samples, candidate)
    holdout_delta: float | None = None
    if holdout_default["hit_rate"] is not None and holdout_candidate["hit_rate"] is not None:
        holdout_delta = round(float(holdout_candidate["hit_rate"] - holdout_default["hit_rate"]), 4)

    return {
        **base,
        "status": "ok",
        "labeled_samples": labeled,
        "shortfall": 0,
        "candidate_label": CANDIDATE_LABEL,
        "drift_violations": [],
        "weights": candidate,
        "weight_update": scorer_update_to_json(update),
        "train_dates": train_dates,
        "holdout_dates": holdout_dates,
        "holdout": {
            "default": holdout_default,
            "candidate": holdout_candidate,
            "hit_rate_delta": holdout_delta,
        },
    }


# ── Persistence ──────────────────────────────────────────────────────


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def write_run_log(
    record: dict[str, Any],
    *,
    log_dir: Path | None = None,
) -> Path:
    target_dir = log_dir if log_dir is not None else CANDIDATE_RUN_LOG_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_dir / f"candidate_{record['run_id']}.json"
    _atomic_write_json(out_path, record)
    _atomic_write_json(target_dir / "latest.json", record)
    return out_path


def persist_candidate(record: dict[str, Any]) -> bool:
    """Save the candidate weight set to disk if status==ok.

    Returns True if a candidate file was written, False otherwise. The
    drift gate (status=='drift_blocked') is the explicit reason this
    function refuses to write — DoD: 'Drift-Gate blockiert extreme
    Spruenge'.
    """
    if record.get("status") != "ok":
        return False
    weights = record.get("weights")
    if not isinstance(weights, dict):
        return False
    save_weight_set(CANDIDATE_LABEL, weights)
    return True


# ── CLI ──────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Produce candidate scorer weights with drift-gate (ENG-WS4-03).",
    )
    parser.add_argument("--lookback", type=int, default=30)
    parser.add_argument("--min-samples", type=int, default=DEFAULT_MIN_SAMPLES)
    parser.add_argument("--max-drift", type=float, default=DEFAULT_MAX_DRIFT)
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute the record without writing to disk.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    )

    try:
        record = generate_candidate(
            lookback_days=args.lookback,
            min_samples=args.min_samples,
            max_drift=args.max_drift,
        )
    except Exception:
        logger.exception("Candidate weight generation failed unexpectedly.")
        return 2

    print(
        f"Candidate weights status={record['status']} "
        f"labeled={record['labeled_samples']} "
        f"violations={len(record.get('drift_violations') or [])}"
    )

    if not args.dry_run:
        log_path = write_run_log(record)
        print(f"Run log: {log_path}")
        if persist_candidate(record):
            print(f"Saved candidate weight set as label={CANDIDATE_LABEL!r}")
        elif record.get("status") == "drift_blocked":
            print("Candidate NOT saved — drift gate blocked the update.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

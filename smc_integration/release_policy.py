from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass
from statistics import median
import subprocess
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Operational release baseline: representative liquid US equities across
# sectors (Tech, Healthcare, Finance, Energy, Consumer, Industrials,
# Communication, Materials, Real-Estate, Utilities).  The set is intentionally
# broad so release gates exercise the full provider/artifact/smoke stack
# across realistic market-structure conditions.
# ---------------------------------------------------------------------------
RELEASE_REFERENCE_SYMBOLS: tuple[str, ...] = (
    "AAPL",   # Tech / mega-cap
    "MSFT",   # Tech / mega-cap
    "AMZN",   # Consumer / Tech
    "JPM",    # Financials
    "JNJ",    # Healthcare
    "XOM",    # Energy
    "CAT",    # Industrials
    "PG",     # Consumer Staples
    "NEE",    # Utilities
    "AMT",    # Real-Estate / REIT
    "META",   # Communication
    "LIN",    # Materials
)
RELEASE_REFERENCE_TIMEFRAMES: tuple[str, ...] = ("5m", "15m", "1H", "4H")

# 7-day freshness: artifacts older than one trading week are considered stale
# for active signal release purposes.
RELEASE_STALE_AFTER_SECONDS: int = 7 * 24 * 60 * 60

# Evidence policy used for GELB->GRUEN release decisions.
EVIDENCE_LOOKBACK_DAYS: int = 14
EVIDENCE_MIN_DEEPER_OK_RUNS: int = 3
EVIDENCE_MIN_RELEASE_OK_RUNS: int = 2

# Minimum coverage thresholds for release evidence.
EVIDENCE_MIN_SYMBOL_COVERAGE: int = 5
EVIDENCE_MIN_TIMEFRAME_COVERAGE: int = 2

# ---------------------------------------------------------------------------
# Environment variable names for config-driven overrides.
# ---------------------------------------------------------------------------
_ENV_SYMBOLS = "SMC_RELEASE_SYMBOLS"
_ENV_TIMEFRAMES = "SMC_RELEASE_TIMEFRAMES"
_ENV_STALE_SECONDS = "SMC_RELEASE_STALE_SECONDS"

# ---------------------------------------------------------------------------
# Structured failure-reason codes emitted by release gates.
# ---------------------------------------------------------------------------
REASON_STALE_DATA = "STALE_DATA"
REASON_INSUFFICIENT_SYMBOLS = "INSUFFICIENT_SYMBOL_BREADTH"
REASON_INSUFFICIENT_TIMEFRAMES = "INSUFFICIENT_TIMEFRAME_BREADTH"
REASON_INSUFFICIENT_RUNS = "INSUFFICIENT_SUCCESSFUL_RUNS"
REASON_PROVIDER_FAILURE = "PROVIDER_FAILURE"
REASON_SMOKE_FAILURE = "SMOKE_FAILURE"
REASON_MISSING_ARTIFACT = "MISSING_ARTIFACT"
REASON_MEASUREMENT_QUALITY = "MEASUREMENT_QUALITY_REGRESSION"


@dataclass(slots=True, frozen=True)
class MeasurementShadowThresholds:
    """Warn-only measurement governance thresholds.

    The defaults are deliberately conservative so the shadow lane remains
    additive until operators have sufficient history to tighten them.
    """

    max_brier_score: float = 0.60
    max_log_score: float = 1.20
    max_calibrated_brier_score: float = 0.60
    max_calibrated_ece: float = 0.30
    min_scoring_events: int = 1
    min_populated_stratification_buckets: int = 1
    min_history_runs: int = 2
    max_brier_regression_abs: float = 0.08
    max_log_regression_abs: float = 0.20
    max_calibrated_brier_regression_abs: float = 0.08
    max_calibrated_ece_regression_abs: float = 0.10
    min_event_coverage_ratio: float = 0.50
    min_stratification_coverage_ratio: float = 0.50


@dataclass(slots=True, frozen=True)
class ContextualCalibrationRecommendationPolicy:
    """Eligibility floor for recommending a preferred contextual dimension."""

    min_scoring_events: int = 8
    min_coverage_ratio: float = 0.60
    min_populated_groups: int = 1
    min_delta_brier_score: float = 0.001
    min_delta_ece: float = 0.002
    max_fallback_event_ratio: float = 0.40


@dataclass(slots=True, frozen=True)
class ContextualCalibrationPromotionPolicy:
    """Stability rules for promoting a contextual recommendation to governance relevance."""

    min_history_runs: int = 3
    min_recommended_run_ratio: float = 0.67
    require_metric_consensus: bool = True


MEASUREMENT_SHADOW_THRESHOLDS = MeasurementShadowThresholds()
CONTEXTUAL_CALIBRATION_RECOMMENDATION_POLICY = ContextualCalibrationRecommendationPolicy()
CONTEXTUAL_CALIBRATION_PROMOTION_POLICY = ContextualCalibrationPromotionPolicy()


def get_measurement_shadow_thresholds() -> MeasurementShadowThresholds:
    return MEASUREMENT_SHADOW_THRESHOLDS


def get_contextual_calibration_recommendation_policy() -> ContextualCalibrationRecommendationPolicy:
    return CONTEXTUAL_CALIBRATION_RECOMMENDATION_POLICY


def get_contextual_calibration_promotion_policy() -> ContextualCalibrationPromotionPolicy:
    return CONTEXTUAL_CALIBRATION_PROMOTION_POLICY


def serialize_measurement_shadow_thresholds(
    thresholds: MeasurementShadowThresholds | None = None,
) -> dict[str, float | int]:
    return asdict(thresholds or MEASUREMENT_SHADOW_THRESHOLDS)


def serialize_contextual_calibration_recommendation_policy(
    policy: ContextualCalibrationRecommendationPolicy | None = None,
) -> dict[str, float | int]:
    return asdict(policy or CONTEXTUAL_CALIBRATION_RECOMMENDATION_POLICY)


def serialize_contextual_calibration_promotion_policy(
    policy: ContextualCalibrationPromotionPolicy | None = None,
) -> dict[str, float | int | bool]:
    return asdict(policy or CONTEXTUAL_CALIBRATION_PROMOTION_POLICY)


def _finite_metric(value: Any) -> float | None:
    try:
        metric = float(value)
    except (TypeError, ValueError):
        return None
    return metric if math.isfinite(metric) else None


def _int_metric(value: Any) -> int | None:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return None


def _populated_bucket_count(entry: dict[str, Any]) -> int | None:
    raw = entry.get("stratification_coverage")
    if not isinstance(raw, dict):
        return None
    return _int_metric(raw.get("populated_bucket_count", 0))


def _median_metric(values: list[float]) -> float | None:
    if not values:
        return None
    return float(median(values))


def _median_int_metric(values: list[int]) -> int | None:
    if not values:
        return None
    return int(round(float(median(values))))


def _optional_stripped_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_contextual_calibration_dimensions(raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}

    dimensions_raw = raw.get("dimensions") if isinstance(raw.get("dimensions"), dict) else None
    source = dimensions_raw if dimensions_raw is not None else raw
    if dimensions_raw is None and "dimensions_present" in raw:
        return {}

    dimensions: dict[str, dict[str, Any]] = {}
    for dimension, item in sorted(source.items()):
        if not isinstance(item, dict):
            continue
        dimensions[str(dimension)] = item
    return dimensions


def _best_contextual_dimension(raw: Any, dimensions: dict[str, dict[str, Any]], *, metric_name: str) -> str | None:
    if isinstance(raw, dict):
        direct = _optional_stripped_string(raw.get(metric_name))
        if direct is not None:
            return direct

    best_dimension = None
    best_value = None
    value_key = "adjusted_brier_score" if metric_name.endswith("brier") else "adjusted_ece"
    for dimension, item in sorted(dimensions.items()):
        value = _finite_metric(item.get(value_key))
        if value is None:
            continue
        if best_value is None or value < best_value:
            best_dimension = dimension
            best_value = value
    return best_dimension


def recommend_contextual_calibration(
    entry: dict[str, Any],
    *,
    policy: ContextualCalibrationRecommendationPolicy | None = None,
) -> dict[str, Any]:
    resolved = policy or CONTEXTUAL_CALIBRATION_RECOMMENDATION_POLICY
    dimensions = _coerce_contextual_calibration_dimensions(entry.get("contextual_calibration"))
    best_dimension_by_adjusted_brier = _best_contextual_dimension(
        entry.get("contextual_calibration"),
        dimensions,
        metric_name="best_dimension_by_adjusted_brier",
    )
    best_dimension_by_adjusted_ece = _best_contextual_dimension(
        entry.get("contextual_calibration"),
        dimensions,
        metric_name="best_dimension_by_adjusted_ece",
    )

    if not dimensions:
        return {
            "available": False,
            "recommended_dimension": None,
            "basis": None,
            "metric_consensus": False,
            "best_dimension_by_adjusted_brier": best_dimension_by_adjusted_brier,
            "best_dimension_by_adjusted_ece": best_dimension_by_adjusted_ece,
            "candidate_dimensions": [],
            "eligible_dimensions": [],
            "reason": "no_contextual_calibration_dimensions",
        }

    eligible: dict[str, dict[str, Any]] = {}
    candidates: dict[str, dict[str, Any]] = {}
    for dimension, item in dimensions.items():
        n_events = _int_metric(item.get("n_events")) or _int_metric(entry.get("n_events")) or 0
        covered_events = _int_metric(item.get("covered_events"))
        coverage_ratio = _finite_metric(item.get("coverage_ratio"))
        if coverage_ratio is None and covered_events is not None and n_events > 0:
            coverage_ratio = covered_events / float(n_events)
        populated_groups = _int_metric(item.get("populated_groups")) or 0
        delta_brier_score = _finite_metric(item.get("delta_brier_score"))
        delta_ece = _finite_metric(item.get("delta_ece"))
        fallback_event_count = _int_metric(item.get("fallback_event_count"))
        if fallback_event_count is None and covered_events is not None:
            fallback_event_count = max(0, n_events - covered_events)
        fallback_event_count = fallback_event_count or 0
        fallback_event_ratio = (fallback_event_count / float(n_events)) if n_events > 0 else 1.0
        best_metric_votes = int(dimension == best_dimension_by_adjusted_brier) + int(dimension == best_dimension_by_adjusted_ece)
        improves_metric = (
            (delta_brier_score is not None and delta_brier_score >= resolved.min_delta_brier_score)
            or (delta_ece is not None and delta_ece >= resolved.min_delta_ece)
        )
        meets_support = (
            n_events >= resolved.min_scoring_events
            and (coverage_ratio or 0.0) >= resolved.min_coverage_ratio
            and populated_groups >= resolved.min_populated_groups
            and fallback_event_ratio <= resolved.max_fallback_event_ratio
        )

        candidate = {
            "dimension": dimension,
            "n_events": n_events,
            "covered_events": covered_events,
            "coverage_ratio": round(float(coverage_ratio or 0.0), 6),
            "populated_groups": populated_groups,
            "delta_brier_score": round(float(delta_brier_score), 6) if delta_brier_score is not None else None,
            "delta_ece": round(float(delta_ece), 6) if delta_ece is not None else None,
            "fallback_event_count": fallback_event_count,
            "fallback_event_ratio": round(float(fallback_event_ratio), 6),
            "best_metric_votes": best_metric_votes,
            "improves_metric": improves_metric,
            "meets_support": meets_support,
            "ranking": (
                best_metric_votes,
                float(delta_brier_score) if delta_brier_score is not None else -1.0,
                float(delta_ece) if delta_ece is not None else -1.0,
                float(coverage_ratio or 0.0),
                float(populated_groups),
                -float(fallback_event_ratio),
            ),
        }
        candidates[dimension] = candidate
        if meets_support and improves_metric:
            eligible[dimension] = candidate

    if not eligible:
        return {
            "available": False,
            "recommended_dimension": None,
            "basis": None,
            "metric_consensus": False,
            "best_dimension_by_adjusted_brier": best_dimension_by_adjusted_brier,
            "best_dimension_by_adjusted_ece": best_dimension_by_adjusted_ece,
            "candidate_dimensions": sorted(candidates.keys()),
            "eligible_dimensions": [],
            "reason": "no_dimension_met_recommendation_policy",
        }

    recommended_dimension, recommended = max(
        sorted(eligible.items()),
        key=lambda item: item[1]["ranking"],
    )
    metric_consensus = bool(
        recommended_dimension
        and recommended_dimension == best_dimension_by_adjusted_brier
        and recommended_dimension == best_dimension_by_adjusted_ece
    )
    basis = "metric_consensus" if metric_consensus else "combined_improvement_ranking"
    return {
        "available": True,
        "recommended_dimension": recommended_dimension,
        "basis": basis,
        "metric_consensus": metric_consensus,
        "best_dimension_by_adjusted_brier": best_dimension_by_adjusted_brier,
        "best_dimension_by_adjusted_ece": best_dimension_by_adjusted_ece,
        "candidate_dimensions": sorted(candidates.keys()),
        "eligible_dimensions": sorted(eligible.keys()),
        "n_events": recommended["n_events"],
        "coverage_ratio": recommended["coverage_ratio"],
        "populated_groups": recommended["populated_groups"],
        "delta_brier_score": recommended["delta_brier_score"],
        "delta_ece": recommended["delta_ece"],
        "fallback_event_count": recommended["fallback_event_count"],
        "fallback_event_ratio": recommended["fallback_event_ratio"],
        "best_metric_votes": recommended["best_metric_votes"],
        "reason": None,
    }


def assess_contextual_calibration_promotion(
    current_entry: dict[str, Any],
    history_entries: list[dict[str, Any]],
    *,
    recommendation_policy: ContextualCalibrationRecommendationPolicy | None = None,
    promotion_policy: ContextualCalibrationPromotionPolicy | None = None,
) -> dict[str, Any]:
    resolved_recommendation = recommendation_policy or CONTEXTUAL_CALIBRATION_RECOMMENDATION_POLICY
    resolved_promotion = promotion_policy or CONTEXTUAL_CALIBRATION_PROMOTION_POLICY

    current_recommendation = recommend_contextual_calibration(current_entry, policy=resolved_recommendation)
    historical_rows = [row for row in history_entries if isinstance(row, dict)]
    all_rows = [current_entry, *historical_rows]
    all_recommendations = [recommend_contextual_calibration(row, policy=resolved_recommendation) for row in all_rows]
    eligible_recommendations = [
        item
        for item in all_recommendations
        if bool(item.get("available")) and _optional_stripped_string(item.get("recommended_dimension")) is not None
    ]

    recommended_dimension = _optional_stripped_string(current_recommendation.get("recommended_dimension"))
    recommended_run_count = (
        sum(1 for item in eligible_recommendations if item.get("recommended_dimension") == recommended_dimension)
        if recommended_dimension is not None
        else 0
    )
    eligible_run_count = len(eligible_recommendations)
    recommended_run_ratio = (
        recommended_run_count / float(eligible_run_count)
        if eligible_run_count > 0
        else float("nan")
    )

    reasons: list[str] = []
    if not current_recommendation.get("available"):
        reasons.append("current_run_has_no_contextual_recommendation")
    if len(all_rows) < resolved_promotion.min_history_runs:
        reasons.append("insufficient_history_runs")
    if eligible_run_count < resolved_promotion.min_history_runs:
        reasons.append("insufficient_recommendation_history")
    if resolved_promotion.require_metric_consensus and not bool(current_recommendation.get("metric_consensus")):
        reasons.append("recommended_dimension_lacks_metric_consensus")
    if (
        recommended_dimension is not None
        and eligible_run_count > 0
        and recommended_run_ratio < resolved_promotion.min_recommended_run_ratio
    ):
        reasons.append("recommended_dimension_not_stable_across_history")

    return {
        "available": bool(current_recommendation.get("available")),
        "promotion_ready": len(reasons) == 0 and recommended_dimension is not None,
        "recommended_dimension": recommended_dimension,
        "current_recommendation": current_recommendation,
        "history_runs": len(all_rows),
        "required_history_runs": resolved_promotion.min_history_runs,
        "eligible_recommendation_runs": eligible_run_count,
        "recommended_run_count": recommended_run_count,
        "recommended_run_ratio": round(float(recommended_run_ratio), 6) if math.isfinite(recommended_run_ratio) else None,
        "required_recommended_run_ratio": round(float(resolved_promotion.min_recommended_run_ratio), 6),
        "metric_consensus_required": bool(resolved_promotion.require_metric_consensus),
        "reasons": reasons,
    }


def _effective_shadow_thresholds(
    baseline: dict[str, Any],
    *,
    thresholds: MeasurementShadowThresholds,
) -> tuple[dict[str, float | int], list[str]]:
    effective = serialize_measurement_shadow_thresholds(thresholds)
    tightened_metrics: list[str] = []

    baseline_calibrated_brier = _finite_metric(baseline.get("calibrated_brier_score"))
    if baseline.get("available") and baseline_calibrated_brier is not None:
        tightened_brier = min(
            float(thresholds.max_calibrated_brier_score),
            float(baseline_calibrated_brier + thresholds.max_calibrated_brier_regression_abs),
        )
        if tightened_brier < float(thresholds.max_calibrated_brier_score):
            effective["max_calibrated_brier_score"] = round(tightened_brier, 6)
            tightened_metrics.append("calibrated_brier_score")

    baseline_calibrated_ece = _finite_metric(baseline.get("calibrated_ece"))
    if baseline.get("available") and baseline_calibrated_ece is not None:
        tightened_ece = min(
            float(thresholds.max_calibrated_ece),
            float(baseline_calibrated_ece + thresholds.max_calibrated_ece_regression_abs),
        )
        if tightened_ece < float(thresholds.max_calibrated_ece):
            effective["max_calibrated_ece"] = round(tightened_ece, 6)
            tightened_metrics.append("calibrated_ece")

    return effective, tightened_metrics


def build_measurement_shadow_baseline(
    history_entries: list[dict[str, Any]],
    *,
    thresholds: MeasurementShadowThresholds | None = None,
) -> dict[str, Any]:
    resolved = thresholds or MEASUREMENT_SHADOW_THRESHOLDS
    history_rows = [row for row in history_entries if isinstance(row, dict)]

    brier_values = [value for value in (_finite_metric(row.get("brier_score")) for row in history_rows) if value is not None]
    log_values = [value for value in (_finite_metric(row.get("log_score")) for row in history_rows) if value is not None]
    calibrated_brier_values = [
        value for value in (_finite_metric(row.get("calibrated_brier_score")) for row in history_rows) if value is not None
    ]
    calibrated_ece_values = [
        value for value in (_finite_metric(row.get("calibrated_ece")) for row in history_rows) if value is not None
    ]
    event_values = [value for value in (_int_metric(row.get("n_events")) for row in history_rows) if value is not None]
    bucket_values = [value for value in (_populated_bucket_count(row) for row in history_rows) if value is not None]

    return {
        "available": len(history_rows) >= resolved.min_history_runs,
        "history_runs": len(history_rows),
        "required_history_runs": resolved.min_history_runs,
        "brier_score": _median_metric(brier_values),
        "log_score": _median_metric(log_values),
        "calibrated_brier_score": _median_metric(calibrated_brier_values),
        "calibrated_ece": _median_metric(calibrated_ece_values),
        "n_events": _median_int_metric(event_values),
        "populated_bucket_count": _median_int_metric(bucket_values),
        "effective_thresholds": {},
        "history_tightened_metrics": [],
    }


def assess_measurement_shadow_degradations(
    current_entry: dict[str, Any],
    history_entries: list[dict[str, Any]],
    *,
    thresholds: MeasurementShadowThresholds | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Compare a current measurement row against static and historical baselines."""

    resolved = thresholds or MEASUREMENT_SHADOW_THRESHOLDS
    degradations: list[dict[str, Any]] = []
    baseline = build_measurement_shadow_baseline(history_entries, thresholds=resolved)
    effective_thresholds, tightened_metrics = _effective_shadow_thresholds(baseline, thresholds=resolved)
    baseline["effective_thresholds"] = effective_thresholds
    baseline["history_tightened_metrics"] = tightened_metrics

    current_brier = _finite_metric(current_entry.get("brier_score"))
    current_log = _finite_metric(current_entry.get("log_score"))
    current_calibrated_brier = _finite_metric(current_entry.get("calibrated_brier_score"))
    current_calibrated_ece = _finite_metric(current_entry.get("calibrated_ece"))
    current_events = _int_metric(current_entry.get("n_events"))
    current_buckets = _populated_bucket_count(current_entry)
    calibrated_thresholds_eligible = current_events is not None and current_events >= resolved.min_history_runs

    if current_brier is not None and current_brier > resolved.max_brier_score:
        degradations.append(
            {
                "code": "MEASUREMENT_BRIER_ABOVE_THRESHOLD",
                "basis": "absolute_threshold",
                "metric": "brier_score",
                "current_value": round(current_brier, 6),
                "threshold_value": round(resolved.max_brier_score, 6),
                "detail": f"brier_score {current_brier:.6f} exceeds warn threshold {resolved.max_brier_score:.6f}",
            }
        )

    if current_log is not None and current_log > resolved.max_log_score:
        degradations.append(
            {
                "code": "MEASUREMENT_LOG_SCORE_ABOVE_THRESHOLD",
                "basis": "absolute_threshold",
                "metric": "log_score",
                "current_value": round(current_log, 6),
                "threshold_value": round(resolved.max_log_score, 6),
                "detail": f"log_score {current_log:.6f} exceeds warn threshold {resolved.max_log_score:.6f}",
            }
        )

    effective_calibrated_brier_threshold = _finite_metric(
        effective_thresholds.get("max_calibrated_brier_score", resolved.max_calibrated_brier_score)
    )
    if (
        calibrated_thresholds_eligible
        and
        current_calibrated_brier is not None
        and effective_calibrated_brier_threshold is not None
        and current_calibrated_brier > effective_calibrated_brier_threshold
    ):
        degradations.append(
            {
                "code": "MEASUREMENT_CALIBRATED_BRIER_ABOVE_THRESHOLD",
                "basis": "history_tightened_threshold" if "calibrated_brier_score" in tightened_metrics else "absolute_threshold",
                "metric": "calibrated_brier_score",
                "current_value": round(current_calibrated_brier, 6),
                "threshold_value": round(effective_calibrated_brier_threshold, 6),
                "detail": (
                    f"calibrated_brier_score {current_calibrated_brier:.6f} exceeds warn threshold "
                    f"{effective_calibrated_brier_threshold:.6f}"
                ),
            }
        )

    effective_calibrated_ece_threshold = _finite_metric(
        effective_thresholds.get("max_calibrated_ece", resolved.max_calibrated_ece)
    )
    if (
        calibrated_thresholds_eligible
        and
        current_calibrated_ece is not None
        and effective_calibrated_ece_threshold is not None
        and current_calibrated_ece > effective_calibrated_ece_threshold
    ):
        degradations.append(
            {
                "code": "MEASUREMENT_CALIBRATED_ECE_ABOVE_THRESHOLD",
                "basis": "history_tightened_threshold" if "calibrated_ece" in tightened_metrics else "absolute_threshold",
                "metric": "calibrated_ece",
                "current_value": round(current_calibrated_ece, 6),
                "threshold_value": round(effective_calibrated_ece_threshold, 6),
                "detail": (
                    f"calibrated_ece {current_calibrated_ece:.6f} exceeds warn threshold "
                    f"{effective_calibrated_ece_threshold:.6f}"
                ),
            }
        )

    if current_events is not None and current_events < resolved.min_scoring_events:
        degradations.append(
            {
                "code": "MEASUREMENT_EVENT_COVERAGE_LOW",
                "basis": "absolute_threshold",
                "metric": "n_events",
                "current_value": current_events,
                "threshold_value": resolved.min_scoring_events,
                "detail": f"n_events {current_events} below warn floor {resolved.min_scoring_events}",
            }
        )

    if current_buckets is not None and current_buckets < resolved.min_populated_stratification_buckets:
        degradations.append(
            {
                "code": "MEASUREMENT_STRATIFICATION_COVERAGE_LOW",
                "basis": "absolute_threshold",
                "metric": "populated_bucket_count",
                "current_value": current_buckets,
                "threshold_value": resolved.min_populated_stratification_buckets,
                "detail": (
                    f"populated stratification buckets {current_buckets} below warn floor "
                    f"{resolved.min_populated_stratification_buckets}"
                ),
            }
        )

    if not baseline["available"]:
        return degradations, baseline

    baseline_brier = _finite_metric(baseline.get("brier_score"))
    if current_brier is not None and baseline_brier is not None:
        delta = current_brier - baseline_brier
        if delta > resolved.max_brier_regression_abs:
            degradations.append(
                {
                    "code": "MEASUREMENT_BRIER_REGRESSION",
                    "basis": "history_baseline",
                    "metric": "brier_score",
                    "current_value": round(current_brier, 6),
                    "baseline_value": round(baseline_brier, 6),
                    "delta_value": round(delta, 6),
                    "threshold_value": round(resolved.max_brier_regression_abs, 6),
                    "detail": f"brier_score regressed by {delta:.6f} versus historical median",
                }
            )

    baseline_log = _finite_metric(baseline.get("log_score"))
    if current_log is not None and baseline_log is not None:
        delta = current_log - baseline_log
        if delta > resolved.max_log_regression_abs:
            degradations.append(
                {
                    "code": "MEASUREMENT_LOG_SCORE_REGRESSION",
                    "basis": "history_baseline",
                    "metric": "log_score",
                    "current_value": round(current_log, 6),
                    "baseline_value": round(baseline_log, 6),
                    "delta_value": round(delta, 6),
                    "threshold_value": round(resolved.max_log_regression_abs, 6),
                    "detail": f"log_score regressed by {delta:.6f} versus historical median",
                }
            )

    baseline_calibrated_brier = _finite_metric(baseline.get("calibrated_brier_score"))
    if current_calibrated_brier is not None and baseline_calibrated_brier is not None:
        delta = current_calibrated_brier - baseline_calibrated_brier
        if delta > resolved.max_calibrated_brier_regression_abs:
            degradations.append(
                {
                    "code": "MEASUREMENT_CALIBRATED_BRIER_REGRESSION",
                    "basis": "history_baseline",
                    "metric": "calibrated_brier_score",
                    "current_value": round(current_calibrated_brier, 6),
                    "baseline_value": round(baseline_calibrated_brier, 6),
                    "delta_value": round(delta, 6),
                    "threshold_value": round(resolved.max_calibrated_brier_regression_abs, 6),
                    "detail": "calibrated_brier_score regressed versus historical median",
                }
            )

    baseline_calibrated_ece = _finite_metric(baseline.get("calibrated_ece"))
    if current_calibrated_ece is not None and baseline_calibrated_ece is not None:
        delta = current_calibrated_ece - baseline_calibrated_ece
        if delta > resolved.max_calibrated_ece_regression_abs:
            degradations.append(
                {
                    "code": "MEASUREMENT_CALIBRATED_ECE_REGRESSION",
                    "basis": "history_baseline",
                    "metric": "calibrated_ece",
                    "current_value": round(current_calibrated_ece, 6),
                    "baseline_value": round(baseline_calibrated_ece, 6),
                    "delta_value": round(delta, 6),
                    "threshold_value": round(resolved.max_calibrated_ece_regression_abs, 6),
                    "detail": "calibrated_ece regressed versus historical median",
                }
            )

    baseline_events = _int_metric(baseline.get("n_events"))
    if current_events is not None and baseline_events is not None and baseline_events > 0:
        ratio = current_events / float(baseline_events)
        if ratio < resolved.min_event_coverage_ratio:
            degradations.append(
                {
                    "code": "MEASUREMENT_EVENT_COVERAGE_REGRESSION",
                    "basis": "history_baseline",
                    "metric": "n_events",
                    "current_value": current_events,
                    "baseline_value": baseline_events,
                    "ratio_value": round(ratio, 6),
                    "threshold_value": round(resolved.min_event_coverage_ratio, 6),
                    "detail": f"n_events ratio {ratio:.6f} below historical coverage floor",
                }
            )

    baseline_buckets = _int_metric(baseline.get("populated_bucket_count"))
    if current_buckets is not None and baseline_buckets is not None and baseline_buckets > 0:
        ratio = current_buckets / float(baseline_buckets)
        if ratio < resolved.min_stratification_coverage_ratio:
            degradations.append(
                {
                    "code": "MEASUREMENT_STRATIFICATION_COVERAGE_REGRESSION",
                    "basis": "history_baseline",
                    "metric": "populated_bucket_count",
                    "current_value": current_buckets,
                    "baseline_value": baseline_buckets,
                    "ratio_value": round(ratio, 6),
                    "threshold_value": round(resolved.min_stratification_coverage_ratio, 6),
                    "detail": "populated stratification coverage regressed versus historical median",
                }
            )

    return degradations, baseline


def csv_from_values(values: Iterable[str]) -> str:
    items: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw).strip()
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        items.append(value)
    return ",".join(items)


def parse_csv(raw: str, *, normalize_upper: bool = False) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for token in str(raw).split(","):
        value = token.strip()
        if normalize_upper:
            value = value.upper()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def resolve_git_commit() -> str | None:
    env_sha = str(os.environ.get("GITHUB_SHA", "")).strip()
    if env_sha:
        return env_sha
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    value = str(result.stdout).strip()
    return value or None


def runtime_metadata() -> dict[str, object]:
    return {
        "git_commit": resolve_git_commit(),
        "github_workflow": str(os.environ.get("GITHUB_WORKFLOW", "")).strip() or None,
        "github_run_id": str(os.environ.get("GITHUB_RUN_ID", "")).strip() or None,
        "github_run_number": str(os.environ.get("GITHUB_RUN_NUMBER", "")).strip() or None,
        "github_event_name": str(os.environ.get("GITHUB_EVENT_NAME", "")).strip() or None,
        "github_ref": str(os.environ.get("GITHUB_REF", "")).strip() or None,
        "github_ref_name": str(os.environ.get("GITHUB_REF_NAME", "")).strip() or None,
    }


# ---------------------------------------------------------------------------
# Config-driven policy resolution
# ---------------------------------------------------------------------------

def resolve_release_policy(
    *,
    symbols: str | None = None,
    timeframes: str | None = None,
    stale_after_seconds: int | None = None,
) -> dict[str, Any]:
    """Resolve the effective release policy by merging explicit values > env vars > defaults."""
    # Symbols: explicit arg > env > default
    if symbols:
        resolved_symbols = parse_csv(symbols, normalize_upper=True)
    else:
        env_sym = os.environ.get(_ENV_SYMBOLS, "").strip()
        resolved_symbols = parse_csv(env_sym, normalize_upper=True) if env_sym else list(RELEASE_REFERENCE_SYMBOLS)

    # Timeframes: explicit arg > env > default
    if timeframes:
        resolved_timeframes = parse_csv(timeframes, normalize_upper=False)
    else:
        env_tf = os.environ.get(_ENV_TIMEFRAMES, "").strip()
        resolved_timeframes = parse_csv(env_tf, normalize_upper=False) if env_tf else list(RELEASE_REFERENCE_TIMEFRAMES)

    # Stale threshold: explicit arg > env > default
    if stale_after_seconds is not None:
        resolved_stale = int(stale_after_seconds)
    else:
        env_stale = os.environ.get(_ENV_STALE_SECONDS, "").strip()
        resolved_stale = int(env_stale) if env_stale else RELEASE_STALE_AFTER_SECONDS

    return {
        "symbols": resolved_symbols,
        "timeframes": resolved_timeframes,
        "stale_after_seconds": resolved_stale,
    }


# ---------------------------------------------------------------------------
# Failure diagnosis helpers
# ---------------------------------------------------------------------------

def diagnose_gate_failure(report: dict[str, Any]) -> list[dict[str, str]]:
    """Extract structured failure reasons from a release-gate or provider-health report.

    Returns a list of ``{"reason": REASON_*, "detail": "..."}`` dicts so operators
    can immediately see *why* a gate failed without parsing raw failure codes.
    """
    reasons: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(reason: str, detail: str) -> None:
        key = f"{reason}:{detail}"
        if key not in seen:
            seen.add(key)
            reasons.append({"reason": reason, "detail": detail})

    # Scan top-level failures/warnings/degradations.
    for row in _iter_code_rows(report.get("failures")):
        code = str(row.get("code", ""))
        _classify_code(code, row, _add)

    for row in _iter_code_rows(report.get("degradations_detected")):
        code = str(row.get("code", ""))
        _classify_code(code, row, _add)

    # Scan gates list (release-gate reports).
    for gate in _iter_code_rows(report.get("gates")):
        details = gate.get("details")
        if not isinstance(details, dict):
            continue
        for key in ("failures", "warnings", "degradations_detected", "missing_smoke_failures"):
            for row in _iter_code_rows(details.get(key)):
                code = str(row.get("code", ""))
                _classify_code(code, row, _add)

    # Coverage breadth checks.
    ref_symbols = report.get("reference_symbols", [])
    ref_timeframes = report.get("reference_timeframes", [])
    if isinstance(ref_symbols, list) and len(ref_symbols) < EVIDENCE_MIN_SYMBOL_COVERAGE:
        _add(REASON_INSUFFICIENT_SYMBOLS, f"only {len(ref_symbols)} symbol(s), need >= {EVIDENCE_MIN_SYMBOL_COVERAGE}")
    if isinstance(ref_timeframes, list) and len(ref_timeframes) < EVIDENCE_MIN_TIMEFRAME_COVERAGE:
        _add(REASON_INSUFFICIENT_TIMEFRAMES, f"only {len(ref_timeframes)} timeframe(s), need >= {EVIDENCE_MIN_TIMEFRAME_COVERAGE}")

    return reasons


def _iter_code_rows(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _classify_code(code: str, row: dict[str, Any], add_fn: Any) -> None:
    upper = code.upper()
    if not upper:
        return
    if "STALE" in upper:
        detail = code
        symbol = row.get("symbol", "")
        if symbol:
            detail = f"{code} ({symbol})"
        add_fn(REASON_STALE_DATA, detail)
    elif "MISSING_ARTIFACT" in upper:
        add_fn(REASON_MISSING_ARTIFACT, code)
    elif upper.startswith("MEASUREMENT_"):
        add_fn(REASON_MEASUREMENT_QUALITY, code)
    elif "MISSING_SMOKE" in upper or "SMOKE" in upper:
        detail = code
        symbol = row.get("symbol", "")
        tf = row.get("timeframe", "")
        if symbol and tf:
            detail = f"{code} ({symbol}/{tf})"
        add_fn(REASON_SMOKE_FAILURE, detail)
    elif "MISSING" in upper:
        add_fn(REASON_MISSING_ARTIFACT, code)
    elif "PROVIDER" in upper or "BUNDLE" in upper or "REFRESH" in upper:
        add_fn(REASON_PROVIDER_FAILURE, code)

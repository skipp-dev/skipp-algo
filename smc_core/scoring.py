"""Probabilistic scoring and calibration for SMC events.

Implements proper scoring rules plus a Python-only calibration lane for
predicted probabilities. The calibration lane stays additive to the
existing lean surface: it improves measurement artifacts without changing
Pine runtime behavior.

Current scope covers the four core SMC families with deterministic labels:
    - BOS follow-through
    - OB mitigation
    - FVG mitigation / fill
    - Sweep reversal

Calibration scope:
    - aggregate probability calibration with a Platt-scaling preferred path
    - beta-bin fallback when class balance or sample size is insufficient
    - stratified calibration summaries by session, HTF bias, and vol regime

Integration:
    - Consumed by benchmark scripts, measurement evidence, and CI gates.
    - Produces versionable JSON artifacts per symbol+timeframe.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

EventFamily = Literal["BOS", "OB", "FVG", "SWEEP"]
_FAMILY_ORDER: tuple[EventFamily, ...] = ("BOS", "OB", "FVG", "SWEEP")
CalibrationMethod = Literal["platt_scaling", "beta_bin", "identity"]
_CALIBRATION_DIMENSIONS: tuple[str, ...] = ("session", "htf_bias", "vol_regime")
_DEFAULT_BIN_COUNT = 10
_MIN_PLATT_EVENTS = 20
_BETA_PRIOR_ALPHA = 1.0
_BETA_PRIOR_BETA = 1.0


@dataclass(slots=True, frozen=True)
class ScoredEvent:
    """A single scored prediction."""

    event_id: str
    family: EventFamily
    predicted_prob: float  # model's predicted probability of outcome
    outcome: bool          # True = event realized (e.g., sweep led to reversal)
    timestamp: float
    context: dict[str, str] = field(default_factory=dict)
    raw_score: float | None = None
    raw_score_name: str | None = None


@dataclass(slots=True)
class FamilyScoringMetrics:
    """Family-level probabilistic scoring summary."""

    family: EventFamily
    n_events: int = 0
    brier_score: float = float("nan")
    log_score: float = float("nan")
    hit_rate: float = float("nan")


@dataclass(slots=True)
class CalibrationBin:
    """Reliability-bin summary for raw and calibrated probabilities."""

    bin_index: int
    lower_bound: float
    upper_bound: float
    predicted_mean: float
    observed_rate: float
    calibrated_mean: float
    n_events: int


@dataclass(slots=True)
class CalibrationSummary:
    """Aggregate calibration summary for a scored event set."""

    method: CalibrationMethod = "identity"
    applied: bool = False
    input_kind: str = "predicted_prob"
    source_name: str = "predicted_prob"
    n_events: int = 0
    positive_rate: float = float("nan")
    raw_brier_score: float = float("nan")
    calibrated_brier_score: float = float("nan")
    raw_log_score: float = float("nan")
    calibrated_log_score: float = float("nan")
    raw_ece: float = float("nan")
    calibrated_ece: float = float("nan")
    delta_brier_score: float = float("nan")
    delta_log_score: float = float("nan")
    delta_ece: float = float("nan")
    bins: list[CalibrationBin] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CalibrationDimensionSummary:
    """Grouped calibration summaries for a context dimension."""

    dimension: str
    total_groups: int = 0
    populated_groups: int = 0
    groups: dict[str, CalibrationSummary] = field(default_factory=dict)


@dataclass(slots=True)
class ContextualCalibrationSummary:
    """Aggregate summary for calibration adjusted by a context dimension."""

    dimension: str
    input_kind: str = "predicted_prob"
    source_name: str = "predicted_prob"
    n_events: int = 0
    covered_events: int = 0
    coverage_ratio: float = float("nan")
    total_groups: int = 0
    populated_groups: int = 0
    raw_brier_score: float = float("nan")
    adjusted_brier_score: float = float("nan")
    raw_log_score: float = float("nan")
    adjusted_log_score: float = float("nan")
    raw_ece: float = float("nan")
    adjusted_ece: float = float("nan")
    delta_brier_score: float = float("nan")
    delta_log_score: float = float("nan")
    delta_ece: float = float("nan")
    group_method_counts: dict[str, int] = field(default_factory=dict)
    fallback_event_count: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ScoringResult:
    """Aggregate scoring result for a set of predictions."""

    generated_at: float = field(default_factory=time.time)
    n_events: int = 0
    brier_score: float = float("nan")
    log_score: float = float("nan")
    hit_rate: float = float("nan")
    family_metrics: dict[EventFamily, FamilyScoringMetrics] = field(default_factory=dict)
    calibration: CalibrationSummary = field(default_factory=CalibrationSummary)
    stratified_calibration: dict[str, CalibrationDimensionSummary] = field(default_factory=dict)
    contextual_calibration: dict[str, ContextualCalibrationSummary] = field(default_factory=dict)
    events: list[ScoredEvent] = field(default_factory=list)


def _normalize_market_direction(raw: str) -> str:
    normalized = str(raw).strip().upper()
    if normalized in {"UP", "BULL", "BULLISH"}:
        return "BULLISH"
    if normalized in {"DOWN", "BEAR", "BEARISH"}:
        return "BEARISH"
    return "NEUTRAL"


def _clip_probability(value: float, *, eps: float = 1e-6) -> float:
    return max(eps, min(1.0 - eps, float(value)))


def _sigmoid(value: float) -> float:
    if value >= 0:
        exp_value = math.exp(-value)
        return 1.0 / (1.0 + exp_value)
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)


def _logit(probability: float) -> float:
    clipped = _clip_probability(probability)
    return math.log(clipped / (1.0 - clipped))


def _event_outcome_value(outcome: bool) -> float:
    return 1.0 if outcome else 0.0


def _bucket_index(probability: float, *, bin_count: int) -> int:
    clipped = min(max(float(probability), 0.0), 1.0)
    if clipped >= 1.0:
        return bin_count - 1
    return min(bin_count - 1, int(math.floor(clipped * bin_count)))


def brier_score(predictions: list[tuple[float, bool]]) -> float:
    """Compute Brier Score: mean squared error of probabilities vs outcomes.

    Lower is better.  Range: [0, 1].
    """
    if not predictions:
        return float("nan")
    total = sum((p - (1.0 if o else 0.0)) ** 2 for p, o in predictions)
    return total / len(predictions)


def log_score(predictions: list[tuple[float, bool]]) -> float:
    """Compute Log Score (negative log-likelihood per prediction).

    Lower is better (less negative).
    Clips probabilities to [1e-15, 1-1e-15] to avoid -inf.
    """
    if not predictions:
        return float("nan")
    eps = 1e-15
    total = 0.0
    for p, o in predictions:
        p_clipped = max(eps, min(1 - eps, p))
        if o:
            total += math.log(p_clipped)
        else:
            total += math.log(1 - p_clipped)
    return -total / len(predictions)


def expected_calibration_error(
    predictions: list[tuple[float, bool]],
    *,
    bin_count: int = _DEFAULT_BIN_COUNT,
) -> float:
    """Compute expected calibration error over equal-width probability bins."""
    if not predictions:
        return float("nan")

    buckets: dict[int, list[tuple[float, bool]]] = {}
    for probability, outcome in predictions:
        buckets.setdefault(_bucket_index(probability, bin_count=bin_count), []).append((float(probability), bool(outcome)))

    total_events = len(predictions)
    total_error = 0.0
    for bucket_events in buckets.values():
        n_events = len(bucket_events)
        predicted_mean = sum(event[0] for event in bucket_events) / n_events
        observed_rate = sum(1.0 if event[1] else 0.0 for event in bucket_events) / n_events
        total_error += (n_events / total_events) * abs(predicted_mean - observed_rate)
    return total_error


def _calibration_bins(
    raw_probabilities: list[float],
    outcomes: list[bool],
    calibrated_probabilities: list[float],
    *,
    bin_count: int,
) -> list[CalibrationBin]:
    if not raw_probabilities:
        return []

    buckets: dict[int, list[int]] = {}
    for idx, probability in enumerate(raw_probabilities):
        buckets.setdefault(_bucket_index(probability, bin_count=bin_count), []).append(idx)

    bins: list[CalibrationBin] = []
    for bucket_idx in sorted(buckets):
        indices = buckets[bucket_idx]
        n_events = len(indices)
        predicted_mean = sum(raw_probabilities[idx] for idx in indices) / n_events
        observed_rate = sum(_event_outcome_value(outcomes[idx]) for idx in indices) / n_events
        calibrated_mean = sum(calibrated_probabilities[idx] for idx in indices) / n_events
        bins.append(
            CalibrationBin(
                bin_index=bucket_idx,
                lower_bound=round(bucket_idx / bin_count, 6),
                upper_bound=round((bucket_idx + 1) / bin_count, 6),
                predicted_mean=round(predicted_mean, 6),
                observed_rate=round(observed_rate, 6),
                calibrated_mean=round(calibrated_mean, 6),
                n_events=n_events,
            )
        )
    return bins


def _ece_from_bins(bins: list[CalibrationBin], *, field_name: str) -> float:
    total_events = sum(int(item.n_events or 0) for item in bins)
    if total_events <= 0:
        return float("nan")

    total_error = 0.0
    for item in bins:
        bucket_weight = float(item.n_events) / float(total_events)
        predicted = float(getattr(item, field_name))
        total_error += bucket_weight * abs(predicted - float(item.observed_rate))
    return total_error


def _platt_loss(
    features: list[float],
    outcomes: list[float],
    *,
    slope: float,
    intercept: float,
    l2_penalty: float,
) -> float:
    eps = 1e-12
    total = 0.0
    for feature, outcome in zip(features, outcomes, strict=True):
        calibrated = _sigmoid(slope * feature + intercept)
        clipped = max(eps, min(1.0 - eps, calibrated))
        total += -(outcome * math.log(clipped) + (1.0 - outcome) * math.log(1.0 - clipped))
    total /= float(len(features))
    total += l2_penalty * ((slope - 1.0) ** 2 + intercept ** 2)
    return total


def _fit_platt_scaler(raw_probabilities: list[float], outcomes: list[bool]) -> tuple[dict[str, float], list[float]] | None:
    if len(raw_probabilities) < _MIN_PLATT_EVENTS:
        return None

    labels = [_event_outcome_value(item) for item in outcomes]
    if min(labels) == max(labels):
        return None

    features = [_logit(probability) for probability in raw_probabilities]
    if max(features) - min(features) < 1e-6:
        return None

    slope = 1.0
    intercept = 0.0
    l2_penalty = 0.01
    current_loss = _platt_loss(features, labels, slope=slope, intercept=intercept, l2_penalty=l2_penalty)

    for _ in range(600):
        calibrated = [_sigmoid(slope * feature + intercept) for feature in features]
        grad_slope = sum((prediction - label) * feature for prediction, label, feature in zip(calibrated, labels, features, strict=True))
        grad_intercept = sum(prediction - label for prediction, label in zip(calibrated, labels, strict=True))
        grad_slope = grad_slope / float(len(features)) + (2.0 * l2_penalty * (slope - 1.0))
        grad_intercept = grad_intercept / float(len(features)) + (2.0 * l2_penalty * intercept)

        learning_rate = 0.5
        improved = False
        next_slope = slope
        next_intercept = intercept
        next_loss = current_loss
        while learning_rate >= 1e-5:
            candidate_slope = slope - learning_rate * grad_slope
            candidate_intercept = intercept - learning_rate * grad_intercept
            candidate_loss = _platt_loss(
                features,
                labels,
                slope=candidate_slope,
                intercept=candidate_intercept,
                l2_penalty=l2_penalty,
            )
            if candidate_loss <= current_loss + 1e-10:
                next_slope = candidate_slope
                next_intercept = candidate_intercept
                next_loss = candidate_loss
                improved = True
                break
            learning_rate *= 0.5

        if not improved:
            break

        slope = next_slope
        intercept = next_intercept
        if abs(current_loss - next_loss) <= 1e-9:
            current_loss = next_loss
            break
        current_loss = next_loss

    calibrated_probabilities = [round(_clip_probability(_sigmoid(slope * feature + intercept)), 6) for feature in features]
    return {
        "slope": round(slope, 6),
        "intercept": round(intercept, 6),
        "l2_penalty": round(l2_penalty, 6),
        "loss": round(current_loss, 6),
    }, calibrated_probabilities


def _beta_bin_calibration(
    raw_probabilities: list[float],
    outcomes: list[bool],
    *,
    bin_count: int,
) -> tuple[dict[str, float | int], list[float]]:
    bucket_indices = [_bucket_index(probability, bin_count=bin_count) for probability in raw_probabilities]
    bucket_stats: dict[int, tuple[int, int]] = {}
    for bucket_idx, outcome in zip(bucket_indices, outcomes, strict=True):
        hits, total = bucket_stats.get(bucket_idx, (0, 0))
        bucket_stats[bucket_idx] = (hits + (1 if outcome else 0), total + 1)

    calibrated_probabilities: list[float] = []
    for bucket_idx in bucket_indices:
        hits, total = bucket_stats[bucket_idx]
        posterior = (hits + _BETA_PRIOR_ALPHA) / (total + _BETA_PRIOR_ALPHA + _BETA_PRIOR_BETA)
        calibrated_probabilities.append(round(_clip_probability(posterior), 6))

    return {
        "bin_count": bin_count,
        "alpha": _BETA_PRIOR_ALPHA,
        "beta": _BETA_PRIOR_BETA,
    }, calibrated_probabilities


def _fit_calibration_mapping(
    raw_probabilities: list[float],
    outcomes: list[bool],
    *,
    bin_count: int,
) -> tuple[CalibrationMethod, dict[str, Any], list[float], list[str]]:
    warnings: list[str] = []
    parameters: dict[str, Any] = {"bin_count": int(bin_count)}
    method: CalibrationMethod = "identity"
    calibrated_probabilities = list(raw_probabilities)

    fitted = _fit_platt_scaler(raw_probabilities, outcomes)
    if fitted is not None:
        method = "platt_scaling"
        platt_parameters, calibrated_probabilities = fitted
        parameters.update(platt_parameters)
        return method, parameters, calibrated_probabilities, warnings

    method = "beta_bin"
    beta_parameters, calibrated_probabilities = _beta_bin_calibration(
        raw_probabilities,
        outcomes,
        bin_count=bin_count,
    )
    parameters.update(beta_parameters)
    if len(raw_probabilities) < _MIN_PLATT_EVENTS:
        warnings.append("insufficient_events_for_platt_scaling")
    outcome_values = {_event_outcome_value(item) for item in outcomes}
    if len(outcome_values) <= 1:
        warnings.append("single_class_outcomes_used_beta_bin_fallback")
    return method, parameters, calibrated_probabilities, warnings


def _resolve_calibration_input(events: list[ScoredEvent]) -> tuple[list[float], str, str, list[str]]:
    warnings: list[str] = []
    if events and all(event.raw_score is not None for event in events):
        names = {str(event.raw_score_name or "raw_score_0_100") for event in events}
        source_name = next(iter(names)) if len(names) == 1 else "raw_score_0_100"
        probabilities = [_clip_probability(float(event.raw_score or 0.0) / 100.0) for event in events]
        return probabilities, "raw_score_0_100", source_name, warnings

    if any(event.raw_score is not None for event in events):
        warnings.append("partial_raw_score_coverage_fell_back_to_predicted_prob")

    probabilities = [_clip_probability(float(event.predicted_prob)) for event in events]
    return probabilities, "predicted_prob", "predicted_prob", warnings


def _build_calibration_summary_from_probabilities(
    raw_probabilities: list[float],
    outcomes: list[bool],
    calibrated_probabilities: list[float],
    *,
    input_kind: str,
    source_name: str,
    method: CalibrationMethod,
    parameters: dict[str, Any],
    warnings: list[str],
    bin_count: int,
) -> CalibrationSummary:
    if not raw_probabilities:
        return CalibrationSummary()

    raw_predictions = list(zip(raw_probabilities, outcomes, strict=True))
    raw_brier = brier_score(raw_predictions)
    raw_log = log_score(raw_predictions)
    calibrated_predictions = list(zip(calibrated_probabilities, outcomes, strict=True))
    calibrated_brier = brier_score(calibrated_predictions)
    calibrated_log = log_score(calibrated_predictions)
    bins = _calibration_bins(raw_probabilities, outcomes, calibrated_probabilities, bin_count=bin_count)
    raw_ece = _ece_from_bins(bins, field_name="predicted_mean")
    calibrated_ece = _ece_from_bins(bins, field_name="calibrated_mean")
    positive_rate = sum(_event_outcome_value(item) for item in outcomes) / float(len(outcomes))

    return CalibrationSummary(
        method=method,
        applied=method != "identity",
        input_kind=input_kind,
        source_name=source_name,
        n_events=len(raw_probabilities),
        positive_rate=round(positive_rate, 6),
        raw_brier_score=round(raw_brier, 6),
        calibrated_brier_score=round(calibrated_brier, 6),
        raw_log_score=round(raw_log, 6),
        calibrated_log_score=round(calibrated_log, 6),
        raw_ece=round(raw_ece, 6),
        calibrated_ece=round(calibrated_ece, 6),
        delta_brier_score=round(raw_brier - calibrated_brier, 6),
        delta_log_score=round(raw_log - calibrated_log, 6),
        delta_ece=round(raw_ece - calibrated_ece, 6),
        bins=bins,
        parameters=parameters,
        warnings=warnings,
    )


def _build_calibration_summary_with_probabilities(
    events: list[ScoredEvent],
    *,
    bin_count: int = _DEFAULT_BIN_COUNT,
) -> tuple[CalibrationSummary, list[float]]:
    if not events:
        return CalibrationSummary(), []

    raw_probabilities, input_kind, source_name, warnings = _resolve_calibration_input(events)
    outcomes = [bool(event.outcome) for event in events]
    method, parameters, calibrated_probabilities, fit_warnings = _fit_calibration_mapping(
        raw_probabilities,
        outcomes,
        bin_count=bin_count,
    )
    summary = _build_calibration_summary_from_probabilities(
        raw_probabilities,
        outcomes,
        calibrated_probabilities,
        input_kind=input_kind,
        source_name=source_name,
        method=method,
        parameters=parameters,
        warnings=[*warnings, *fit_warnings],
        bin_count=bin_count,
    )
    return summary, calibrated_probabilities


def build_calibration_summary(
    events: list[ScoredEvent],
    *,
    bin_count: int = _DEFAULT_BIN_COUNT,
) -> CalibrationSummary:
    """Build an aggregate calibration summary for scored events."""
    summary, _ = _build_calibration_summary_with_probabilities(events, bin_count=bin_count)
    return summary


def _build_stratified_calibration(
    events: list[ScoredEvent],
    *,
    dimensions: tuple[str, ...] = _CALIBRATION_DIMENSIONS,
    bin_count: int = _DEFAULT_BIN_COUNT,
) -> dict[str, CalibrationDimensionSummary]:
    stratified: dict[str, CalibrationDimensionSummary] = {}
    for dimension in dimensions:
        grouped_events: dict[str, list[ScoredEvent]] = {}
        for event in events:
            raw_context = event.context if isinstance(event.context, dict) else {}
            group_key = str(raw_context.get(dimension, "")).strip()
            if not group_key:
                continue
            grouped_events.setdefault(group_key, []).append(event)
        if not grouped_events:
            continue

        groups = {
            group_key: build_calibration_summary(group_events, bin_count=bin_count)
            for group_key, group_events in sorted(grouped_events.items())
        }
        stratified[dimension] = CalibrationDimensionSummary(
            dimension=dimension,
            total_groups=len(groups),
            populated_groups=sum(1 for summary in groups.values() if summary.n_events > 0),
            groups=groups,
        )
    return stratified


def _build_contextual_calibration(
    events: list[ScoredEvent],
    *,
    dimensions: tuple[str, ...] = _CALIBRATION_DIMENSIONS,
    bin_count: int = _DEFAULT_BIN_COUNT,
) -> dict[str, ContextualCalibrationSummary]:
    if not events:
        return {}

    raw_probabilities, input_kind, source_name, input_warnings = _resolve_calibration_input(events)
    outcomes = [bool(event.outcome) for event in events]
    raw_predictions = list(zip(raw_probabilities, outcomes, strict=True))
    raw_brier = brier_score(raw_predictions)
    raw_log = log_score(raw_predictions)
    raw_bins = _calibration_bins(raw_probabilities, outcomes, raw_probabilities, bin_count=bin_count)
    raw_ece = _ece_from_bins(raw_bins, field_name="predicted_mean")

    contextual: dict[str, ContextualCalibrationSummary] = {}
    for dimension in dimensions:
        grouped_indices: dict[str, list[int]] = {}
        for idx, event in enumerate(events):
            raw_context = event.context if isinstance(event.context, dict) else {}
            group_key = str(raw_context.get(dimension, "")).strip()
            if not group_key:
                continue
            grouped_indices.setdefault(group_key, []).append(idx)
        if not grouped_indices:
            continue

        adjusted_probabilities = list(raw_probabilities)
        covered_events = 0
        group_method_counts: dict[str, int] = {}
        warnings = list(input_warnings)

        for group_key, indices in sorted(grouped_indices.items()):
            group_raw = [raw_probabilities[idx] for idx in indices]
            group_outcomes = [outcomes[idx] for idx in indices]
            method, _parameters, group_calibrated, group_warnings = _fit_calibration_mapping(
                group_raw,
                group_outcomes,
                bin_count=bin_count,
            )
            covered_events += len(indices)
            group_method_counts[method] = int(group_method_counts.get(method, 0) or 0) + 1
            for local_idx, event_idx in enumerate(indices):
                adjusted_probabilities[event_idx] = group_calibrated[local_idx]
            warnings.extend(group_warnings)

        fallback_event_count = max(0, len(events) - covered_events)
        if fallback_event_count > 0:
            warnings.append(f"{dimension}_partial_coverage_used_raw_fallback")

        bins = _calibration_bins(raw_probabilities, outcomes, adjusted_probabilities, bin_count=bin_count)
        adjusted_predictions = list(zip(adjusted_probabilities, outcomes, strict=True))
        adjusted_brier = brier_score(adjusted_predictions)
        adjusted_log = log_score(adjusted_predictions)
        adjusted_ece = _ece_from_bins(bins, field_name="calibrated_mean")
        coverage_ratio = covered_events / float(len(events)) if events else float("nan")

        contextual[dimension] = ContextualCalibrationSummary(
            dimension=dimension,
            input_kind=input_kind,
            source_name=source_name,
            n_events=len(events),
            covered_events=covered_events,
            coverage_ratio=round(coverage_ratio, 6),
            total_groups=len(grouped_indices),
            populated_groups=sum(1 for indices in grouped_indices.values() if indices),
            raw_brier_score=round(raw_brier, 6),
            adjusted_brier_score=round(adjusted_brier, 6),
            raw_log_score=round(raw_log, 6),
            adjusted_log_score=round(adjusted_log, 6),
            raw_ece=round(raw_ece, 6),
            adjusted_ece=round(adjusted_ece, 6),
            delta_brier_score=round(raw_brier - adjusted_brier, 6),
            delta_log_score=round(raw_log - adjusted_log, 6),
            delta_ece=round(raw_ece - adjusted_ece, 6),
            group_method_counts={
                method_name: int(count)
                for method_name, count in sorted(group_method_counts.items())
            },
            fallback_event_count=fallback_event_count,
            warnings=sorted({warning for warning in warnings if warning}),
        )

    return contextual


def serialize_calibration_summary(summary: CalibrationSummary | None) -> dict[str, Any]:
    if summary is None:
        return {}
    return {
        "method": summary.method,
        "applied": bool(summary.applied),
        "input_kind": summary.input_kind,
        "source_name": summary.source_name,
        "n_events": int(summary.n_events),
        "positive_rate": float(summary.positive_rate) if math.isfinite(summary.positive_rate) else None,
        "raw_brier_score": float(summary.raw_brier_score) if math.isfinite(summary.raw_brier_score) else None,
        "calibrated_brier_score": float(summary.calibrated_brier_score) if math.isfinite(summary.calibrated_brier_score) else None,
        "raw_log_score": float(summary.raw_log_score) if math.isfinite(summary.raw_log_score) else None,
        "calibrated_log_score": float(summary.calibrated_log_score) if math.isfinite(summary.calibrated_log_score) else None,
        "raw_ece": float(summary.raw_ece) if math.isfinite(summary.raw_ece) else None,
        "calibrated_ece": float(summary.calibrated_ece) if math.isfinite(summary.calibrated_ece) else None,
        "delta_brier_score": float(summary.delta_brier_score) if math.isfinite(summary.delta_brier_score) else None,
        "delta_log_score": float(summary.delta_log_score) if math.isfinite(summary.delta_log_score) else None,
        "delta_ece": float(summary.delta_ece) if math.isfinite(summary.delta_ece) else None,
        "bins": [asdict(item) for item in summary.bins],
        "parameters": dict(summary.parameters),
        "warnings": list(summary.warnings),
    }


def serialize_stratified_calibration(
    summaries: dict[str, CalibrationDimensionSummary],
) -> dict[str, dict[str, Any]]:
    return {
        dimension: {
            "dimension": item.dimension,
            "total_groups": int(item.total_groups),
            "populated_groups": int(item.populated_groups),
            "groups": {
                group_key: serialize_calibration_summary(group_summary)
                for group_key, group_summary in sorted(item.groups.items())
            },
        }
        for dimension, item in sorted(summaries.items())
    }


def serialize_contextual_calibration(
    summaries: dict[str, ContextualCalibrationSummary],
) -> dict[str, dict[str, Any]]:
    return {
        dimension: {
            "dimension": item.dimension,
            "input_kind": item.input_kind,
            "source_name": item.source_name,
            "n_events": int(item.n_events),
            "covered_events": int(item.covered_events),
            "coverage_ratio": float(item.coverage_ratio) if math.isfinite(item.coverage_ratio) else None,
            "total_groups": int(item.total_groups),
            "populated_groups": int(item.populated_groups),
            "raw_brier_score": float(item.raw_brier_score) if math.isfinite(item.raw_brier_score) else None,
            "adjusted_brier_score": float(item.adjusted_brier_score) if math.isfinite(item.adjusted_brier_score) else None,
            "raw_log_score": float(item.raw_log_score) if math.isfinite(item.raw_log_score) else None,
            "adjusted_log_score": float(item.adjusted_log_score) if math.isfinite(item.adjusted_log_score) else None,
            "raw_ece": float(item.raw_ece) if math.isfinite(item.raw_ece) else None,
            "adjusted_ece": float(item.adjusted_ece) if math.isfinite(item.adjusted_ece) else None,
            "delta_brier_score": float(item.delta_brier_score) if math.isfinite(item.delta_brier_score) else None,
            "delta_log_score": float(item.delta_log_score) if math.isfinite(item.delta_log_score) else None,
            "delta_ece": float(item.delta_ece) if math.isfinite(item.delta_ece) else None,
            "group_method_counts": dict(item.group_method_counts),
            "fallback_event_count": int(item.fallback_event_count),
            "warnings": list(item.warnings),
        }
        for dimension, item in sorted(summaries.items())
    }


def summarize_stratified_calibration(
    summaries: dict[str, CalibrationDimensionSummary],
) -> dict[str, Any]:
    return {
        "dimensions_present": sorted(summaries.keys()),
        "dimension_group_counts": {
            dimension: int(item.total_groups)
            for dimension, item in sorted(summaries.items())
        },
        "dimension_populated_groups": {
            dimension: int(item.populated_groups)
            for dimension, item in sorted(summaries.items())
        },
    }


def summarize_contextual_calibration(
    summaries: dict[str, ContextualCalibrationSummary],
) -> dict[str, Any]:
    best_brier_dimension = None
    best_ece_dimension = None

    finite_brier = [
        (dimension, item.adjusted_brier_score)
        for dimension, item in sorted(summaries.items())
        if math.isfinite(item.adjusted_brier_score)
    ]
    if finite_brier:
        best_brier_dimension = min(finite_brier, key=lambda item: item[1])[0]

    finite_ece = [
        (dimension, item.adjusted_ece)
        for dimension, item in sorted(summaries.items())
        if math.isfinite(item.adjusted_ece)
    ]
    if finite_ece:
        best_ece_dimension = min(finite_ece, key=lambda item: item[1])[0]

    return {
        "dimensions_present": sorted(summaries.keys()),
        "improved_dimensions": sorted(
            dimension
            for dimension, item in summaries.items()
            if (math.isfinite(item.delta_brier_score) and item.delta_brier_score > 0)
            or (math.isfinite(item.delta_ece) and item.delta_ece > 0)
        ),
        "best_dimension_by_adjusted_brier": best_brier_dimension,
        "best_dimension_by_adjusted_ece": best_ece_dimension,
    }


def label_sweep_reversal(
    sweep_price: float,
    sweep_side: str,
    subsequent_closes: list[float],
    *,
    threshold_pct: float = 0.005,
) -> bool:
    """Label whether a sweep led to a reversal.

    Parameters
    ----------
    sweep_price:
        Price at the sweep event.
    sweep_side:
        ``"BUY_SIDE"`` or ``"SELL_SIDE"``.
    subsequent_closes:
        Close prices of the *N* bars after the sweep.
    threshold_pct:
        Minimum price movement required to count as reversal.
    """
    if not subsequent_closes:
        return False

    if sweep_side == "SELL_SIDE":
        # Sell-side sweep → reversal = price moves UP
        return any((c - sweep_price) / sweep_price >= threshold_pct for c in subsequent_closes)
    else:
        # Buy-side sweep → reversal = price moves DOWN
        return any((sweep_price - c) / sweep_price >= threshold_pct for c in subsequent_closes)


def label_bos_follow_through(
    bos_price: float,
    direction: str,
    subsequent_highs: list[float],
    subsequent_lows: list[float],
    *,
    threshold_pct: float = 0.003,
) -> bool:
    """Label whether a BOS produced directional follow-through.

    ``direction`` may be ``UP``/``DOWN`` or any bullish/bearish synonym.
    """
    if bos_price <= 0:
        return False

    normalized_direction = _normalize_market_direction(direction)
    if normalized_direction == "BULLISH":
        return any((high - bos_price) / bos_price >= threshold_pct for high in subsequent_highs)
    if normalized_direction == "BEARISH":
        return any((bos_price - low) / bos_price >= threshold_pct for low in subsequent_lows)
    return False


def _zone_touch_before_invalidation(
    zone_low: float,
    zone_high: float,
    direction: str,
    subsequent_highs: list[float],
    subsequent_lows: list[float],
    subsequent_closes: list[float],
) -> bool:
    if zone_low <= 0 or zone_high <= 0 or zone_high < zone_low:
        return False

    normalized_direction = _normalize_market_direction(direction)
    if normalized_direction not in {"BULLISH", "BEARISH"}:
        return False

    bar_count = max(len(subsequent_closes), len(subsequent_highs), len(subsequent_lows))
    if bar_count == 0:
        return False

    touch_idx: int | None = None
    invalid_idx: int | None = None
    for idx in range(bar_count):
        close = subsequent_closes[idx] if idx < len(subsequent_closes) else None
        high = subsequent_highs[idx] if idx < len(subsequent_highs) else None
        low = subsequent_lows[idx] if idx < len(subsequent_lows) else None

        if normalized_direction == "BEARISH":
            if touch_idx is None and high is not None and zone_low <= high <= zone_high:
                touch_idx = idx
            if invalid_idx is None and close is not None and close > zone_high:
                invalid_idx = idx
        else:
            if touch_idx is None and low is not None and zone_low <= low <= zone_high:
                touch_idx = idx
            if invalid_idx is None and close is not None and close < zone_low:
                invalid_idx = idx

    return touch_idx is not None and (invalid_idx is None or touch_idx <= invalid_idx)


def label_orderblock_mitigation(
    zone_low: float,
    zone_high: float,
    direction: str,
    subsequent_highs: list[float],
    subsequent_lows: list[float],
    subsequent_closes: list[float],
) -> bool:
    """Label whether an order block was mitigated before invalidation."""
    return _zone_touch_before_invalidation(
        zone_low,
        zone_high,
        direction,
        subsequent_highs,
        subsequent_lows,
        subsequent_closes,
    )


def label_fvg_mitigation(
    zone_low: float,
    zone_high: float,
    direction: str,
    subsequent_highs: list[float],
    subsequent_lows: list[float],
    subsequent_closes: list[float],
) -> bool:
    """Label whether an FVG was tagged/filled before invalidation."""
    return _zone_touch_before_invalidation(
        zone_low,
        zone_high,
        direction,
        subsequent_highs,
        subsequent_lows,
        subsequent_closes,
    )


def _summarize_scored_events(events: list[ScoredEvent]) -> tuple[int, float, float, float]:
    if not events:
        return 0, float("nan"), float("nan"), float("nan")

    predictions = [(e.predicted_prob, e.outcome) for e in events]
    hits = sum(1 for _, outcome in predictions if outcome)
    return (
        len(events),
        round(brier_score(predictions), 6),
        round(log_score(predictions), 6),
        round(hits / len(events), 4),
    )


def score_events(events: list[ScoredEvent]) -> ScoringResult:
    """Score a list of predicted events."""
    if not events:
        return ScoringResult()

    family_metrics: dict[EventFamily, FamilyScoringMetrics] = {}
    for family in _FAMILY_ORDER:
        family_events = [event for event in events if event.family == family]
        if not family_events:
            continue
        n_events, family_brier, family_log, family_hit_rate = _summarize_scored_events(family_events)
        family_metrics[family] = FamilyScoringMetrics(
            family=family,
            n_events=n_events,
            brier_score=family_brier,
            log_score=family_log,
            hit_rate=family_hit_rate,
        )

    n_events, aggregate_brier, aggregate_log, aggregate_hit_rate = _summarize_scored_events(events)
    calibration = build_calibration_summary(events)
    stratified_calibration = _build_stratified_calibration(events)
    contextual_calibration = _build_contextual_calibration(events)

    return ScoringResult(
        n_events=n_events,
        brier_score=aggregate_brier,
        log_score=aggregate_log,
        hit_rate=aggregate_hit_rate,
        family_metrics=family_metrics,
        calibration=calibration,
        stratified_calibration=stratified_calibration,
        contextual_calibration=contextual_calibration,
        events=list(events),
    )


def export_scoring_artifact(
    result: ScoringResult,
    *,
    symbol: str,
    timeframe: str,
    output_dir: Path,
    schema_version: str,
) -> Path:
    """Write a versionable scoring artifact to *output_dir*.

    Returns the path to the written JSON file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema_version": schema_version,
        "symbol": symbol,
        "timeframe": timeframe,
        "generated_at": result.generated_at,
        "n_events": result.n_events,
        "brier_score": result.brier_score,
        "log_score": result.log_score,
        "hit_rate": result.hit_rate,
        "aggregate": {
            "n_events": result.n_events,
            "brier_score": result.brier_score,
            "log_score": result.log_score,
            "hit_rate": result.hit_rate,
        },
        "calibration": serialize_calibration_summary(result.calibration),
        "stratified_calibration": serialize_stratified_calibration(result.stratified_calibration),
        "contextual_calibration": serialize_contextual_calibration(result.contextual_calibration),
        "family_metrics": {
            family: asdict(metrics)
            for family, metrics in result.family_metrics.items()
        },
    }
    filename = f"scoring_{symbol}_{timeframe}.json"
    path = output_dir / filename
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path

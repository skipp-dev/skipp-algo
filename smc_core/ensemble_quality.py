"""Explicit Python-side ensemble quality scoring for the SMC stack."""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import median
from typing import Any, Literal

from smc_core.schema_version import SCHEMA_VERSION
from smc_core.scoring import ScoringResult


QualityTier = Literal["low", "ok", "good", "high"]


@dataclass(slots=True)
class EnsembleQualityResult:
    generated_at: float = field(default_factory=time.time)
    score: float = 0.0
    tier: QualityTier = "low"
    available_components: list[str] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)
    contributions: dict[str, dict[str, Any]] = field(default_factory=dict)


_DEFAULT_WEIGHTS: dict[str, float] = {
    "heuristic": 0.30,
    "bias": 0.20,
    "vol_regime": 0.15,
    "scoring": 0.25,
    "history": 0.10,
}

_VOL_REGIME_BASE_SCORES: dict[str, float] = {
    "LOW_VOL": 0.55,
    "NORMAL": 0.75,
    "HIGH_VOL": 0.45,
    "EXTREME": 0.25,
}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _finite_metric(value: Any) -> float | None:
    try:
        metric = float(value)
    except (TypeError, ValueError):
        return None
    return metric if math.isfinite(metric) else None


def _median_metric(values: list[float]) -> float | None:
    if not values:
        return None
    return float(median(values))


def _tier_from_score(score: float) -> QualityTier:
    if score < 0.25:
        return "low"
    if score < 0.50:
        return "ok"
    if score < 0.75:
        return "good"
    return "high"


def _bias_component(direction: str | None, confidence: float | None) -> tuple[float | None, dict[str, Any]]:
    normalized_direction = str(direction or "").strip().upper() or "NEUTRAL"
    bias_confidence = _clamp(_finite_metric(confidence) or 0.0)
    if normalized_direction == "NEUTRAL":
        return 0.5, {"direction": normalized_direction, "confidence": bias_confidence}
    value = _clamp(0.4 + 0.6 * bias_confidence)
    return value, {"direction": normalized_direction, "confidence": bias_confidence}


def _vol_regime_component(label: str | None, confidence: float | None) -> tuple[float | None, dict[str, Any]]:
    normalized_label = str(label or "").strip().upper()
    if not normalized_label:
        return None, {"label": None, "confidence": None}
    base = _VOL_REGIME_BASE_SCORES.get(normalized_label, 0.5)
    regime_confidence = _clamp(_finite_metric(confidence) or 0.0)
    value = _clamp(0.5 + (base - 0.5) * regime_confidence)
    return value, {"label": normalized_label, "confidence": regime_confidence}


def _scoring_component(scoring_result: ScoringResult | None) -> tuple[float | None, dict[str, Any]]:
    if scoring_result is None or int(scoring_result.n_events or 0) <= 0:
        return None, {"n_events": 0}

    brier_quality = 1.0 - _clamp(float(scoring_result.brier_score), 0.0, 1.0)
    log_quality = 1.0 - _clamp(float(scoring_result.log_score) / 1.5, 0.0, 1.0)
    hit_rate = _clamp(_finite_metric(scoring_result.hit_rate) or 0.0)
    family_coverage = _clamp(len(scoring_result.family_metrics) / 4.0)
    value = _clamp(0.4 * brier_quality + 0.3 * log_quality + 0.2 * hit_rate + 0.1 * family_coverage)
    return value, {
        "n_events": int(scoring_result.n_events or 0),
        "brier_score": float(scoring_result.brier_score),
        "log_score": float(scoring_result.log_score),
        "hit_rate": float(scoring_result.hit_rate),
        "family_count": len(scoring_result.family_metrics),
    }


def _history_component(
    scoring_result: ScoringResult | None,
    history_rows: list[dict[str, Any]] | None,
) -> tuple[float | None, dict[str, Any]]:
    rows = [row for row in history_rows or [] if isinstance(row, dict)]
    if scoring_result is None or int(scoring_result.n_events or 0) <= 0 or not rows:
        return None, {"history_runs": len(rows)}

    baseline_brier = _median_metric([value for value in (_finite_metric(row.get("brier_score")) for row in rows) if value is not None])
    baseline_log = _median_metric([value for value in (_finite_metric(row.get("log_score")) for row in rows) if value is not None])
    baseline_events = _median_metric([value for value in (_finite_metric(row.get("n_events")) for row in rows) if value is not None])

    sub_scores: list[float] = []
    if baseline_brier is not None:
        sub_scores.append(_clamp(1.0 - max(0.0, float(scoring_result.brier_score) - baseline_brier) / 0.25))
    if baseline_log is not None:
        sub_scores.append(_clamp(1.0 - max(0.0, float(scoring_result.log_score) - baseline_log) / 0.75))
    if baseline_events is not None and baseline_events > 0:
        sub_scores.append(_clamp(float(scoring_result.n_events) / baseline_events))

    if not sub_scores:
        return None, {
            "history_runs": len(rows),
            "baseline_brier_score": baseline_brier,
            "baseline_log_score": baseline_log,
            "baseline_n_events": baseline_events,
        }

    return _clamp(sum(sub_scores) / len(sub_scores)), {
        "history_runs": len(rows),
        "baseline_brier_score": baseline_brier,
        "baseline_log_score": baseline_log,
        "baseline_n_events": baseline_events,
    }


def serialize_ensemble_quality(result: EnsembleQualityResult) -> dict[str, Any]:
    return asdict(result)


def build_ensemble_quality(
    *,
    generated_at: float | None = None,
    heuristic_quality: float | None = None,
    bias_direction: str | None = None,
    bias_confidence: float | None = None,
    vol_regime_label: str | None = None,
    vol_regime_confidence: float | None = None,
    scoring_result: ScoringResult | None = None,
    history_rows: list[dict[str, Any]] | None = None,
    weights: dict[str, float] | None = None,
) -> EnsembleQualityResult:
    resolved_weights = dict(_DEFAULT_WEIGHTS)
    if weights:
        resolved_weights.update({key: float(value) for key, value in weights.items()})

    contributions: dict[str, dict[str, Any]] = {}
    weighted_total = 0.0
    active_weight = 0.0

    def _add_component(name: str, value: float | None, detail: dict[str, Any]) -> None:
        nonlocal weighted_total, active_weight
        if value is None:
            return
        weight = float(resolved_weights.get(name, 0.0))
        if weight <= 0:
            return
        clamped_value = _clamp(value)
        weighted_total += clamped_value * weight
        active_weight += weight
        contributions[name] = {
            "value": round(clamped_value, 6),
            "weight": round(weight, 6),
            "weighted_value": round(clamped_value * weight, 6),
            "detail": detail,
        }

    heuristic_metric = _finite_metric(heuristic_quality)
    _add_component("heuristic", heuristic_metric if heuristic_metric is None else _clamp(heuristic_metric), {"source": "heuristic_quality"})

    bias_value, bias_detail = _bias_component(bias_direction, bias_confidence)
    _add_component("bias", bias_value, bias_detail)

    vol_value, vol_detail = _vol_regime_component(vol_regime_label, vol_regime_confidence)
    _add_component("vol_regime", vol_value, vol_detail)

    scoring_value, scoring_detail = _scoring_component(scoring_result)
    _add_component("scoring", scoring_value, scoring_detail)

    history_value, history_detail = _history_component(scoring_result, history_rows)
    _add_component("history", history_value, history_detail)

    score = 0.0 if active_weight <= 0 else _clamp(weighted_total / active_weight)
    return EnsembleQualityResult(
        generated_at=float(generated_at) if generated_at is not None else time.time(),
        score=round(score, 6),
        tier=_tier_from_score(score),
        available_components=sorted(contributions),
        weights={key: round(float(value), 6) for key, value in sorted(resolved_weights.items())},
        contributions=contributions,
    )


def export_ensemble_quality_artifact(
    result: EnsembleQualityResult,
    *,
    symbol: str,
    timeframe: str,
    output_dir: Path,
    schema_version: str = SCHEMA_VERSION,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"ensemble_quality_{symbol}_{timeframe}.json"
    payload = {
        "schema_version": schema_version,
        "symbol": symbol,
        "timeframe": timeframe,
        **serialize_ensemble_quality(result),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
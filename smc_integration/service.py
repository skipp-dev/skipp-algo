from __future__ import annotations

import math
from typing import Any
from pathlib import Path

import pandas as pd

from smc_adapters import (
    build_meta_from_raw,
    build_structure_from_raw,
    snapshot_to_dashboard_payload,
    snapshot_to_pine_payload,
)
from smc_core import apply_layering, derive_base_signals, normalize_meta, snapshot_to_dict
from smc_core.benchmark import BenchmarkResult, build_benchmark
from smc_core.bias_merge import merge_bias
from smc_core.ensemble_quality import build_ensemble_quality, serialize_ensemble_quality
from smc_core.scoring import (
    score_events,
    serialize_calibration_summary,
    summarize_contextual_calibration,
    summarize_stratified_calibration,
)
from smc_core.vol_regime import compute_vol_regime
from smc_core.types import SmcSnapshot
from scripts.load_databento_export_bundle import load_export_bundle
from scripts.smc_htf_context import build_htf_bias_context
from scripts.smc_session_context import build_session_liquidity_context
from scripts.smc_structure_qualifiers import build_structure_qualifiers
from smc_integration.sources import structure_artifact_json
from smc_integration.measurement_evidence import build_measurement_evidence

from .repo_sources import (
    discover_composite_source_plan,
    discover_structure_source_status,
    load_raw_meta_input_composite,
    load_raw_structure_input,
    select_best_structure_source,
)


_DEFAULT_EXPORT_DIR = Path("artifacts") / "smc_microstructure_exports"


def _safe_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _serialize_bias_verdict(bias_verdict: Any) -> dict[str, Any]:
    return {
        "direction": bias_verdict.direction,
        "confidence": bias_verdict.confidence,
        "htf_direction": bias_verdict.htf_direction,
        "session_direction": bias_verdict.session_direction,
        "conflict": bias_verdict.conflict,
        "source": bias_verdict.source,
    }


def _serialize_vol_regime(vol_regime_result: Any) -> dict[str, Any]:
    return {
        "label": vol_regime_result.label,
        "raw_atr_ratio": vol_regime_result.raw_atr_ratio,
        "confidence": vol_regime_result.confidence,
        "bars_used": vol_regime_result.bars_used,
        "model_source": vol_regime_result.model_source,
        "fallback_reason": vol_regime_result.fallback_reason,
        "forecast_volatility": vol_regime_result.forecast_volatility,
        "baseline_volatility": vol_regime_result.baseline_volatility,
        "forecast_ratio": vol_regime_result.forecast_ratio,
    }


def _serialize_scoring_family_metrics(scoring_result: Any) -> dict[str, dict[str, Any]]:
    raw_metrics = getattr(scoring_result, "family_metrics", None)
    if not isinstance(raw_metrics, dict):
        return {}

    metrics: dict[str, dict[str, Any]] = {}
    for family, item in sorted(raw_metrics.items()):
        metrics[str(family)] = {
            "n_events": int(getattr(item, "n_events", 0) or 0),
            "brier_score": _safe_float(getattr(item, "brier_score", None)),
            "log_score": _safe_float(getattr(item, "log_score", None)),
            "hit_rate": _safe_float(getattr(item, "hit_rate", None)),
        }
    return metrics


def _summarize_stratification(benchmark_result: BenchmarkResult) -> dict[str, Any]:
    bucket_event_counts: dict[str, int] = {}
    dimensions_present: set[str] = set()
    populated_bucket_count = 0

    for bucket_key, bucket_kpis in sorted(benchmark_result.stratified.items()):
        dimension = str(bucket_key).split(":", 1)[0]
        dimensions_present.add(dimension)
        event_count = sum(int(kpi.n_events or 0) for kpi in bucket_kpis)
        bucket_event_counts[str(bucket_key)] = event_count
        if event_count > 0:
            populated_bucket_count += 1

    return {
        "bucket_count": len(bucket_event_counts),
        "populated_bucket_count": populated_bucket_count,
        "dimensions_present": sorted(dimensions_present),
        "bucket_event_counts": bucket_event_counts,
    }


def _benchmark_event_counts(benchmark_result: BenchmarkResult) -> dict[str, int]:
    return {
        kpi.family: int(kpi.n_events or 0)
        for kpi in benchmark_result.kpis
    }


def _build_measurement_summary(symbol: str, timeframe: str) -> dict[str, Any]:
    empty_summary = {
        "available": False,
        "status": "unavailable",
        "measurement_evidence_present": False,
        "bars_source_mode": None,
        "evaluated_event_counts": {},
        "benchmark_event_counts": {},
        "stratification_coverage": {
            "bucket_count": 0,
            "populated_bucket_count": 0,
            "dimensions_present": [],
            "bucket_event_counts": {},
        },
        "scoring": {
            "n_events": 0,
            "brier_score": None,
            "log_score": None,
            "hit_rate": None,
            "families_present": [],
            "family_metrics": {},
            "calibration": {},
            "stratified_calibration": {
                "dimensions_present": [],
                "dimension_group_counts": {},
                "dimension_populated_groups": {},
            },
        },
        "ensemble_quality": {},
        "warnings": [],
    }
    try:
        evidence = build_measurement_evidence(symbol, timeframe)
    except Exception as exc:
        return {
            **empty_summary,
            "status": "error",
            "warnings": [f"measurement summary unavailable: {exc}"],
        }

    benchmark_result = build_benchmark(
        str(symbol).strip().upper(),
        str(timeframe).strip(),
        events_by_family=evidence.events_by_family,
        stratified_events=evidence.stratified_events,
    )
    scoring_result = score_events(evidence.scored_events)
    scoring_family_metrics = _serialize_scoring_family_metrics(scoring_result)
    calibration = serialize_calibration_summary(getattr(scoring_result, "calibration", None))
    stratified_calibration = summarize_stratified_calibration(
        getattr(scoring_result, "stratified_calibration", {}) or {}
    )
    contextual_calibration = summarize_contextual_calibration(
        getattr(scoring_result, "contextual_calibration", {}) or {}
    )
    available = bool(evidence.details.get("measurement_evidence_present"))

    return {
        "available": available,
        "status": "available" if available else "unavailable",
        "measurement_evidence_present": available,
        "bars_source_mode": evidence.details.get("bars_source_mode"),
        "evaluated_event_counts": dict(evidence.details.get("evaluated_event_counts", {})),
        "benchmark_event_counts": _benchmark_event_counts(benchmark_result),
        "stratification_coverage": _summarize_stratification(benchmark_result),
        "scoring": {
            "n_events": int(getattr(scoring_result, "n_events", 0) or 0),
            "brier_score": _safe_float(getattr(scoring_result, "brier_score", None)),
            "log_score": _safe_float(getattr(scoring_result, "log_score", None)),
            "hit_rate": _safe_float(getattr(scoring_result, "hit_rate", None)),
            "families_present": sorted(scoring_family_metrics.keys()),
            "family_metrics": scoring_family_metrics,
            "calibration": calibration,
            "stratified_calibration": stratified_calibration,
            "contextual_calibration": contextual_calibration,
        },
        "ensemble_quality": dict(evidence.details.get("ensemble_quality", {})),
        "warnings": list(evidence.warnings),
    }


def _load_symbol_bars_for_context(symbol: str, timeframe: str) -> pd.DataFrame:
    try:
        bundle = load_export_bundle(_DEFAULT_EXPORT_DIR, manifest_prefix="databento_volatility_production_")
    except Exception:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "symbol"]) 

    frames = bundle.get("frames", {})
    symbol_name = str(symbol).strip().upper()
    tf = str(timeframe).strip()

    if tf == "1D":
        daily = frames.get("daily_bars")
        if isinstance(daily, pd.DataFrame) and not daily.empty:
            bars = daily.copy()
            bars["symbol"] = bars.get("symbol", "").astype(str).str.strip().str.upper()
            bars = bars.loc[bars["symbol"].eq(symbol_name)].copy()
            if bars.empty:
                return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "symbol"])
            bars["timestamp"] = pd.to_datetime(bars.get("trade_date"), utc=True, errors="coerce").astype("int64") // 10**9
            for col in ("open", "high", "low", "close"):
                bars[col] = pd.to_numeric(bars.get(col), errors="coerce")
            bars["volume"] = pd.to_numeric(bars.get("volume", 0.0), errors="coerce").fillna(0.0)
            return bars[["timestamp", "open", "high", "low", "close", "volume", "symbol"]].dropna().reset_index(drop=True)

    intraday = frames.get("full_universe_second_detail_open")
    if isinstance(intraday, pd.DataFrame) and not intraday.empty:
        bars = intraday.copy()
        bars["symbol"] = bars.get("symbol", "").astype(str).str.strip().str.upper()
        bars = bars.loc[bars["symbol"].eq(symbol_name)].copy()
        if bars.empty:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "symbol"])
        bars["timestamp"] = pd.to_datetime(bars.get("timestamp"), utc=True, errors="coerce").astype("int64") // 10**9
        for col in ("open", "high", "low", "close"):
            bars[col] = pd.to_numeric(bars.get(col), errors="coerce")
        bars["volume"] = pd.to_numeric(bars.get("volume", 0.0), errors="coerce").fillna(0.0)
        return bars[["timestamp", "open", "high", "low", "close", "volume", "symbol"]].dropna().reset_index(drop=True)

    return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "symbol"])


def _build_snapshot_from_loaded_raw(
    raw_structure: dict[str, Any],
    raw_meta: dict[str, Any],
    *,
    generated_at: float | None = None,
) -> SmcSnapshot:
    structure = build_structure_from_raw(raw_structure)
    meta = build_meta_from_raw(raw_meta)
    return apply_layering(structure, meta, generated_at=generated_at)


def _load_structure_input_and_context(
    symbol: str,
    timeframe: str,
    *,
    source: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    composite = discover_composite_source_plan(source=source, symbol=symbol, timeframe=timeframe)
    structure_source = composite["structure"]
    structure_load_source = "auto" if source.strip().lower() == "auto" else structure_source

    raw_structure = load_raw_structure_input(
        symbol,
        timeframe,
        source=structure_load_source,
    )

    if structure_source == "structure_artifact_json":
        structure_context = structure_artifact_json.load_structure_context_input(symbol, timeframe)
        return raw_structure, structure_context

    return raw_structure, None


def build_snapshot_for_symbol_timeframe(
    symbol: str,
    timeframe: str,
    *,
    source: str = "auto",
    generated_at: float | None = None,
) -> SmcSnapshot:
    raw_structure, _ = _load_structure_input_and_context(symbol, timeframe, source=source)
    raw_meta = load_raw_meta_input_composite(
        symbol,
        timeframe,
        source=source,
        reference_time=generated_at,
    )
    return _build_snapshot_from_loaded_raw(raw_structure, raw_meta, generated_at=generated_at)


def build_dashboard_payload_for_symbol_timeframe(
    symbol: str,
    timeframe: str,
    *,
    source: str = "auto",
    generated_at: float | None = None,
) -> dict:
    source_plan = discover_composite_source_plan(source=source, symbol=symbol, timeframe=timeframe)
    structure_status = discover_structure_source_status(source=source, symbol=symbol, timeframe=timeframe)
    snapshot = build_snapshot_for_symbol_timeframe(
        symbol,
        timeframe,
        source=source,
        generated_at=generated_at,
    )
    return snapshot_to_dashboard_payload(
        snapshot,
        source_plan=source_plan,
        structure_status=structure_status,
    )


def build_pine_payload_for_symbol_timeframe(
    symbol: str,
    timeframe: str,
    *,
    source: str = "auto",
    generated_at: float | None = None,
) -> dict:
    source_plan = discover_composite_source_plan(source=source, symbol=symbol, timeframe=timeframe)
    structure_status = discover_structure_source_status(source=source, symbol=symbol, timeframe=timeframe)
    snapshot = build_snapshot_for_symbol_timeframe(
        symbol,
        timeframe,
        source=source,
        generated_at=generated_at,
    )
    return snapshot_to_pine_payload(
        snapshot,
        source_plan=source_plan,
        structure_status=structure_status,
    )


def build_snapshot_bundle_for_symbol_timeframe(
    symbol: str,
    timeframe: str,
    *,
    source: str = "auto",
    generated_at: float | None = None,
) -> dict:
    selected = select_best_structure_source() if source.strip().lower() == "auto" else None
    composite = discover_composite_source_plan(source=source, symbol=symbol, timeframe=timeframe)
    structure_status = discover_structure_source_status(source=source, symbol=symbol, timeframe=timeframe)
    raw_structure, normalized_structure_context = _load_structure_input_and_context(symbol, timeframe, source=source)
    raw_meta = load_raw_meta_input_composite(
        symbol,
        timeframe,
        source=source,
        reference_time=generated_at,
    )
    snapshot = _build_snapshot_from_loaded_raw(raw_structure, raw_meta, generated_at=generated_at)
    dashboard_payload = snapshot_to_dashboard_payload(
        snapshot,
        source_plan=composite,
        structure_status=structure_status,
    )
    pine_payload = snapshot_to_pine_payload(
        snapshot,
        source_plan=composite,
        structure_status=structure_status,
    )

    source_descriptor = selected if selected is not None else None
    if source_descriptor is None:
        from .repo_sources import discover_repo_sources

        by_name = {item.name: item for item in discover_repo_sources()}
        source_key = source.strip().lower()
        if source_key not in by_name:
            known = ", ".join(sorted(by_name))
            raise ValueError(f"unknown source {source}; expected one of: {known}, auto")
        source_descriptor = by_name[source_key]

    bars = _load_symbol_bars_for_context(symbol, timeframe)
    if bars.empty:
        structure_qualifiers: dict[str, Any] = {}
        session_context: dict[str, Any] = {}
        htf_context: dict[str, Any] = {}
    else:
        structure_qualifiers = build_structure_qualifiers(bars, pivot_lookup=1)
        session_context = build_session_liquidity_context(bars, tz="America/New_York")
        htf_context = build_htf_bias_context(bars, timeframe=timeframe, htf_frames=None)

    bias_verdict = merge_bias(htf_context or None, session_context or None)

    # Vol-regime classification (additive, degrades to NORMAL on empty bars)
    vol_regime_result = compute_vol_regime(bars)
    heuristic_quality = derive_base_signals(normalize_meta(snapshot.meta))["global_strength"]
    ensemble_quality = build_ensemble_quality(
        generated_at=float(snapshot.generated_at),
        heuristic_quality=heuristic_quality,
        bias_direction=bias_verdict.direction,
        bias_confidence=bias_verdict.confidence,
        vol_regime_label=vol_regime_result.label,
        vol_regime_confidence=vol_regime_result.confidence,
    )

    structure_context = normalized_structure_context
    bias_payload = _serialize_bias_verdict(bias_verdict)
    vol_regime_payload = _serialize_vol_regime(vol_regime_result)
    measurement_summary = _build_measurement_summary(symbol, timeframe)
    measurement_refs = {
        "artifact_dir": f"measurement/{symbol}/{timeframe}",
        "benchmark_artifact": f"benchmark_{symbol}_{timeframe}.json",
        "scoring_artifact": f"scoring_{symbol}_{timeframe}.json",
        "summary_artifact": f"measurement_summary_{symbol}_{timeframe}.json",
        "status": measurement_summary["status"],
    }

    out = {
        "source_plan": composite,
        "structure_status": structure_status,
        "source": source_descriptor.to_dict(),
        "snapshot": snapshot_to_dict(snapshot),
        "dashboard_payload": dashboard_payload,
        "pine_payload": pine_payload,
        "structure_qualifiers": structure_qualifiers,
        "session_context": session_context,
        "htf_context": htf_context,
        "bias_verdict": bias_payload,
        "vol_regime": vol_regime_payload,
        "ensemble_quality": serialize_ensemble_quality(ensemble_quality),
        "measurement_refs": measurement_refs,
        "measurement_summary": measurement_summary,
        "market_context": {
            "bias_direction": bias_payload["direction"],
            "bias_confidence": bias_payload["confidence"],
            "vol_regime_label": vol_regime_payload["label"],
            "vol_regime_confidence": vol_regime_payload["confidence"],
            "measurement_status": measurement_summary["status"],
            "measurement_events": measurement_summary["scoring"]["n_events"],
            "measurement_brier_score": measurement_summary["scoring"]["brier_score"],
            "measurement_log_score": measurement_summary["scoring"]["log_score"],
        },
        "meta_domains_present": raw_meta.get("meta_domains_present", []),
        "meta_domains_missing": raw_meta.get("meta_domains_missing", []),
        "meta_domain_diagnostics": raw_meta.get("meta_domain_diagnostics", {}),
    }
    if structure_context is not None:
        out["structure_context"] = structure_context

    return out

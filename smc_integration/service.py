from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any, cast

import pandas as pd

from scripts.load_databento_export_bundle import load_export_bundle
from scripts.smc_bus_manifest import build_product_cut_manifest_payload
from scripts.smc_structure_qualifiers import build_structure_qualifiers
from smc_adapters import (
    build_meta_from_raw,
    build_structure_from_raw,
    build_volume_provenance_from_raw,
    snapshot_to_dashboard_payload,
    snapshot_to_pine_payload,
)
from smc_core import apply_layering, derive_base_signals, normalize_meta, snapshot_to_dict
from smc_core.benchmark import BenchmarkResult, build_benchmark
from smc_core.bias_merge import merge_bias
from smc_core.ensemble_quality import build_ensemble_quality, serialize_ensemble_quality
from smc_core.htf_context import build_htf_bias_context
from smc_core.scoring import (
    score_events,
    serialize_calibration_summary,
    summarize_contextual_calibration,
    summarize_stratified_calibration,
)
from smc_core.session_context import build_session_liquidity_context
from smc_core.types import SmcSnapshot
from smc_core.vol_regime import compute_vol_regime
from smc_integration.measurement_evidence import build_measurement_evidence
from smc_integration.sources import structure_artifact_json

from .repo_sources import (
    discover_composite_source_plan,
    discover_structure_source_status,
    load_raw_meta_input_composite,
    load_raw_meta_input_composite_for_release_reference,
    load_raw_structure_input,
    select_best_structure_source,
)
from .trust_tier import (
    derive_quality_recommendation as _derive_quality_recommendation,
)
from .trust_tier import (
    resolve_provider_state,
    resolve_trust_main_blocker,
    resolve_trust_tier,
)

_DEFAULT_EXPORT_DIR = Path("artifacts") / "smc_microstructure_exports"
logger = logging.getLogger(__name__)


def _to_epoch_seconds(series: Any) -> pd.Series:
    timestamp = pd.to_datetime(series, utc=True, errors="coerce")
    epoch = pd.Timestamp("1970-01-01", tz="UTC")
    return ((timestamp - epoch) // pd.Timedelta(seconds=1)).astype("int64")


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


def _serialize_vol_regime(vol_regime_result: Any, *, bars_available: bool) -> dict[str, Any]:
    payload = {
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
    if not bars_available and str(vol_regime_result.fallback_reason or "").strip().lower() == "empty_bars":
        payload["raw_label"] = payload["label"]
        payload["label"] = "UNKNOWN"
        payload["confidence"] = 0.0
        payload["service_override_reason"] = "empty_bars"
    return payload


def _context_diagnostics_for_bars(bars: pd.DataFrame) -> dict[str, Any]:
    bar_count = len(bars)
    bars_available = bar_count > 0
    diagnostics: dict[str, Any] = {
        "bars_available": bars_available,
        "bar_count": bar_count,
        "structure_qualifiers_available": bars_available,
        "session_context_available": bars_available,
        "htf_context_available": bars_available,
    }
    if not bars_available:
        diagnostics["reason"] = "empty_bars"
    return diagnostics


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
    except Exception as exc:
        logger.warning(
            "Failed to load export bundle for context bars (%s, %s): %s",
            symbol,
            timeframe,
            exc,
            exc_info=True,
        )
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
            bars["timestamp"] = _to_epoch_seconds(bars.get("trade_date"))
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
        bars["timestamp"] = _to_epoch_seconds(bars.get("timestamp"))
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


def _resolve_source_descriptor(*, source: str, selected: Any) -> Any:
    if selected is not None:
        return selected

    from .repo_sources import discover_repo_sources

    by_name = {item.name: item for item in discover_repo_sources()}
    source_key = source.strip().lower()
    if source_key not in by_name:
        known = ", ".join(sorted(by_name))
        raise ValueError(f"unknown source {source}; expected one of: {known}, auto")
    return by_name[source_key]


def _load_snapshot_projection_inputs(
    symbol: str,
    timeframe: str,
    *,
    source: str,
    generated_at: float | None,
    allow_release_reference_meta_fallback: bool = False,
) -> dict[str, Any]:
    selected = select_best_structure_source() if source.strip().lower() == "auto" else None
    source_plan = discover_composite_source_plan(source=source, symbol=symbol, timeframe=timeframe)
    structure_status = discover_structure_source_status(source=source, symbol=symbol, timeframe=timeframe)
    product_cut = build_product_cut_manifest_payload()
    raw_structure, structure_context = _load_structure_input_and_context(symbol, timeframe, source=source)
    if allow_release_reference_meta_fallback:
        raw_meta = load_raw_meta_input_composite_for_release_reference(
            symbol,
            timeframe,
            source=source,
            reference_time=generated_at,
        )
    else:
        raw_meta = load_raw_meta_input_composite(
            symbol,
            timeframe,
            source=source,
            reference_time=generated_at,
        )
    snapshot = _build_snapshot_from_loaded_raw(raw_structure, raw_meta, generated_at=generated_at)
    return {
        "selected": selected,
        "source_plan": source_plan,
        "structure_status": structure_status,
        "product_cut": product_cut,
        "raw_meta": raw_meta,
        "snapshot": snapshot,
        "structure_context": structure_context,
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def _resolve_structure_state(structure_status: dict[str, Any] | None) -> str:
    if not isinstance(structure_status, dict):
        return "unknown"

    raw_state = str(
        structure_status.get("selected_structure_mode")
        or structure_status.get("coverage")
        or structure_status.get("selected")
        or ""
    ).strip().lower()
    if raw_state in {"full", "partial", "none"}:
        return raw_state
    if raw_state in {"ok", "healthy", "ready", "available", "structure_artifact_json"}:
        return "full"
    if raw_state in {"missing", "unavailable", "failed"}:
        return "none"

    selected_category_coverage = structure_status.get("selected_category_coverage")
    if isinstance(selected_category_coverage, dict) and selected_category_coverage:
        values = [bool(value) for value in selected_category_coverage.values()]
        if values and all(values):
            return "full"
        if values and any(values):
            return "partial"
        return "none"

    return "unknown"


def _missing_meta_domains(raw_meta: dict[str, Any]) -> list[str]:
    missing = set(_string_list(raw_meta.get("meta_domains_missing")))
    diagnostics = raw_meta.get("meta_domain_diagnostics")
    if isinstance(diagnostics, dict):
        for domain in ("volume", "technical", "news"):
            status = str(diagnostics.get(domain) or "").strip().lower()
            if status and status not in {"present", "synthetic_fallback"}:
                missing.add(domain)
    return sorted(missing)


def _stale_meta_domains(raw_meta: dict[str, Any]) -> list[str]:
    stale: set[str] = set()
    diagnostics = raw_meta.get("meta_domain_diagnostics")
    if isinstance(diagnostics, dict):
        for domain in ("volume", "technical", "news"):
            if diagnostics.get(f"{domain}_stale") is True:
                stale.add(domain)
            status = str(diagnostics.get(domain) or "").strip().lower()
            if status == "stale":
                stale.add(domain)

    volume = raw_meta.get("volume")
    if isinstance(volume, dict) and volume.get("stale") is True:
        stale.add("volume")

    return sorted(stale)


def _measurement_quality_tier(measurement_summary: dict[str, Any]) -> str:
    ensemble_quality = measurement_summary.get("ensemble_quality")
    if not isinstance(ensemble_quality, dict):
        return "unknown"

    tier = str(ensemble_quality.get("tier") or "").strip().lower()
    if tier in {"low", "ok", "good", "high"}:
        return tier

    score = _safe_float(ensemble_quality.get("score"))
    if score is None:
        return "unknown"
    if score >= 0.75:
        return "high"
    if score >= 0.50:
        return "good"
    if score >= 0.25:
        return "ok"
    return "low"


def _measurement_quality_score(measurement_summary: dict[str, Any]) -> float | None:
    ensemble_quality = measurement_summary.get("ensemble_quality")
    if not isinstance(ensemble_quality, dict):
        return None
    return _safe_float(ensemble_quality.get("score"))


def _measurement_warning_messages(measurement_summary: dict[str, Any]) -> list[str]:
    return _string_list(measurement_summary.get("warnings"))


def _resolve_provider_state(
    *,
    structure_state: str,
    missing_domains: list[str],
    stale_domains: list[str],
    provider_health_issue_count: int,
) -> str:
    return resolve_provider_state(
        structure_state=structure_state,
        missing_domains=missing_domains,
        stale_domains=stale_domains,
        provider_health_issue_count=provider_health_issue_count,
    )


def _resolve_trust_state(
    *,
    provider_state: str,
    measurement_status: str,
    measurement_available: bool,
    measurement_events: int,
    measurement_family_count: int,
    measurement_quality_tier: str,
    measurement_warning_count: int,
) -> str:
    return resolve_trust_tier(
        provider_state=provider_state,
        measurement_status=measurement_status,
        measurement_available=measurement_available,
        measurement_events=measurement_events,
        measurement_family_count=measurement_family_count,
        measurement_quality_tier=measurement_quality_tier,
        measurement_warning_count=measurement_warning_count,
    )


def _resolve_trust_main_blocker(
    *,
    structure_state: str,
    missing_domains: list[str],
    stale_domains: list[str],
    provider_health_issue_count: int,
    measurement_status: str,
    measurement_available: bool,
    measurement_events: int,
    measurement_family_count: int,
    measurement_quality_tier: str,
    measurement_warnings: list[str],
) -> str:
    return resolve_trust_main_blocker(
        structure_state=structure_state,
        missing_domains=missing_domains,
        stale_domains=stale_domains,
        provider_health_issue_count=provider_health_issue_count,
        measurement_status=measurement_status,
        measurement_available=measurement_available,
        measurement_events=measurement_events,
        measurement_family_count=measurement_family_count,
        measurement_quality_tier=measurement_quality_tier,
        measurement_warnings=measurement_warnings,
    )


def _build_trust_summary(
    *,
    raw_meta: dict[str, Any],
    structure_status: dict[str, Any] | None,
    measurement_summary: dict[str, Any],
) -> dict[str, Any]:
    structure_state = _resolve_structure_state(structure_status)
    structure_missing_categories = _string_list((structure_status or {}).get("selected_missing_categories"))
    missing_domains = _missing_meta_domains(raw_meta)
    stale_domains = _stale_meta_domains(raw_meta)
    provider_health_issue_count = int((structure_status or {}).get("selected_health_issue_count") or 0)

    measurement_status = str(measurement_summary.get("status") or "unavailable").strip().lower()
    scoring = measurement_summary.get("scoring")
    measurement_events = int(scoring.get("n_events") or 0) if isinstance(scoring, dict) else 0
    measurement_family_count = len(_string_list(scoring.get("families_present"))) if isinstance(scoring, dict) else 0
    measurement_available = bool(measurement_summary.get("measurement_evidence_present"))
    measurement_quality_tier = _measurement_quality_tier(measurement_summary)
    measurement_quality_score = _measurement_quality_score(measurement_summary)
    measurement_warnings = _measurement_warning_messages(measurement_summary)
    measurement_warning_count = len(measurement_warnings)

    provider_state = _resolve_provider_state(
        structure_state=structure_state,
        missing_domains=missing_domains,
        stale_domains=stale_domains,
        provider_health_issue_count=provider_health_issue_count,
    )
    trust_state = _resolve_trust_state(
        provider_state=provider_state,
        measurement_status=measurement_status,
        measurement_available=measurement_available,
        measurement_events=measurement_events,
        measurement_family_count=measurement_family_count,
        measurement_quality_tier=measurement_quality_tier,
        measurement_warning_count=measurement_warning_count,
    )
    main_blocker = _resolve_trust_main_blocker(
        structure_state=structure_state,
        missing_domains=missing_domains,
        stale_domains=stale_domains,
        provider_health_issue_count=provider_health_issue_count,
        measurement_status=measurement_status,
        measurement_available=measurement_available,
        measurement_events=measurement_events,
        measurement_family_count=measurement_family_count,
        measurement_quality_tier=measurement_quality_tier,
        measurement_warnings=measurement_warnings,
    )

    quality_rec = _derive_quality_recommendation(
        trust_state=trust_state,
        measurement_quality_tier=measurement_quality_tier,
        measurement_events=measurement_events,
        provider_state=provider_state,
    )

    return {
        "trust_state": trust_state,
        "provider_state": provider_state,
        "main_blocker": main_blocker,
        "measurement_status": measurement_status,
        "measurement_events": measurement_events,
        "measurement_family_count": measurement_family_count,
        "measurement_quality_tier": measurement_quality_tier,
        "measurement_quality_score": measurement_quality_score,
        "measurement_warning_count": measurement_warning_count,
        "provider_health_issue_count": provider_health_issue_count,
        "structure_state": structure_state,
        "structure_missing_categories": structure_missing_categories,
        "missing_domains": missing_domains,
        "stale_domains": stale_domains,
        "quality_recommendation": quality_rec["recommendation"],
        "quality_guardrail": quality_rec["guardrail"],
        "quality_recommendation_reason": quality_rec["reason"],
    }


def _build_projection_payloads(
    snapshot: SmcSnapshot,
    *,
    source_plan: dict[str, Any],
    structure_status: dict[str, Any],
    product_cut: dict[str, Any],
    trust_summary: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    dashboard_payload = snapshot_to_dashboard_payload(
        snapshot,
        source_plan=source_plan,
        structure_status=structure_status,
        product_cut=product_cut,
        trust_summary=trust_summary,
    )
    pine_payload = snapshot_to_pine_payload(
        snapshot,
        source_plan=source_plan,
        structure_status=structure_status,
        product_cut=product_cut,
        trust_summary=trust_summary,
    )
    return dashboard_payload, pine_payload


def _build_context_payloads(symbol: str, timeframe: str, snapshot: SmcSnapshot) -> dict[str, Any]:
    bars = _load_symbol_bars_for_context(symbol, timeframe)
    context_diagnostics = _context_diagnostics_for_bars(bars)
    if not context_diagnostics["bars_available"]:
        structure_qualifiers: dict[str, Any] = {}
        session_context: dict[str, Any] = {}
        htf_context: dict[str, Any] = {}
    else:
        structure_qualifiers = build_structure_qualifiers(bars, pivot_lookup=1)
        session_context = build_session_liquidity_context(bars, tz="America/New_York")
        htf_context = build_htf_bias_context(bars, timeframe=timeframe, htf_frames=None)

    bias_verdict = merge_bias(htf_context or None, session_context or None)
    bias_payload = _serialize_bias_verdict(bias_verdict)

    vol_regime_result = compute_vol_regime(bars)
    vol_regime_payload = _serialize_vol_regime(
        vol_regime_result,
        bars_available=bool(context_diagnostics["bars_available"]),
    )
    heuristic_quality = derive_base_signals(normalize_meta(snapshot.meta))["global_strength"]
    ensemble_quality = build_ensemble_quality(
        generated_at=float(snapshot.generated_at),
        heuristic_quality=heuristic_quality,
        bias_direction=bias_verdict.direction,
        bias_confidence=bias_verdict.confidence,
        vol_regime_label=str(vol_regime_payload["label"]),
        vol_regime_confidence=float(vol_regime_payload["confidence"]),
    )

    return {
        "structure_qualifiers": structure_qualifiers,
        "session_context": session_context,
        "htf_context": htf_context,
        "context_diagnostics": context_diagnostics,
        "bias_verdict": bias_payload,
        "vol_regime": vol_regime_payload,
        "ensemble_quality": serialize_ensemble_quality(ensemble_quality),
    }


def _build_measurement_refs(symbol: str, timeframe: str, measurement_summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_dir": f"measurement/{symbol}/{timeframe}",
        "benchmark_artifact": f"benchmark_{symbol}_{timeframe}.json",
        "scoring_artifact": f"scoring_{symbol}_{timeframe}.json",
        "summary_artifact": f"measurement_summary_{symbol}_{timeframe}.json",
        "status": measurement_summary["status"],
    }


def _build_market_context(*, context_payload: dict[str, Any], measurement_summary: dict[str, Any]) -> dict[str, Any]:
    bias_payload = context_payload["bias_verdict"]
    context_diagnostics = context_payload["context_diagnostics"]
    vol_regime_payload = context_payload["vol_regime"]
    return {
        "bias_direction": bias_payload["direction"],
        "bias_confidence": bias_payload["confidence"],
        "bars_available": context_diagnostics["bars_available"],
        "bar_count": context_diagnostics["bar_count"],
        "vol_regime_label": vol_regime_payload["label"],
        "vol_regime_confidence": vol_regime_payload["confidence"],
        "measurement_status": measurement_summary["status"],
        "measurement_events": measurement_summary["scoring"]["n_events"],
        "measurement_brier_score": measurement_summary["scoring"]["brier_score"],
        "measurement_log_score": measurement_summary["scoring"]["log_score"],
    }


def _build_meta_delivery_payload(raw_meta: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "meta_domains_present": raw_meta.get("meta_domains_present", []),
        "meta_domains_missing": raw_meta.get("meta_domains_missing", []),
        "domain_drop_reasons": raw_meta.get("domain_drop_reasons", {}),
        "domain_drop_providers": raw_meta.get("domain_drop_providers", {}),
        "meta_domain_diagnostics": raw_meta.get("meta_domain_diagnostics", {}),
        "meta_domain_drop_status": {
            domain: raw_meta.get("meta_domain_diagnostics", {}).get(domain)
            for domain in ("volume", "technical", "news")
            if isinstance(raw_meta.get("meta_domain_diagnostics"), dict)
            and raw_meta.get("meta_domain_diagnostics", {}).get(domain) is not None
        },
    }
    volume_provenance = build_volume_provenance_from_raw(raw_meta)
    if volume_provenance:
        payload["volume_provenance"] = volume_provenance
    return payload


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
    inputs = _load_snapshot_projection_inputs(
        symbol,
        timeframe,
        source=source,
        generated_at=generated_at,
    )
    return cast(SmcSnapshot, inputs["snapshot"])


def build_dashboard_payload_for_symbol_timeframe(
    symbol: str,
    timeframe: str,
    *,
    source: str = "auto",
    generated_at: float | None = None,
) -> dict:
    inputs = _load_snapshot_projection_inputs(
        symbol,
        timeframe,
        source=source,
        generated_at=generated_at,
    )
    trust_summary = _build_trust_summary(
        raw_meta=inputs["raw_meta"],
        structure_status=inputs["structure_status"],
        measurement_summary=_build_measurement_summary(symbol, timeframe),
    )
    return snapshot_to_dashboard_payload(
        inputs["snapshot"],
        source_plan=inputs["source_plan"],
        structure_status=inputs["structure_status"],
        product_cut=inputs["product_cut"],
        trust_summary=trust_summary,
    )


def build_pine_payload_for_symbol_timeframe(
    symbol: str,
    timeframe: str,
    *,
    source: str = "auto",
    generated_at: float | None = None,
) -> dict:
    inputs = _load_snapshot_projection_inputs(
        symbol,
        timeframe,
        source=source,
        generated_at=generated_at,
    )
    trust_summary = _build_trust_summary(
        raw_meta=inputs["raw_meta"],
        structure_status=inputs["structure_status"],
        measurement_summary=_build_measurement_summary(symbol, timeframe),
    )
    return snapshot_to_pine_payload(
        inputs["snapshot"],
        source_plan=inputs["source_plan"],
        structure_status=inputs["structure_status"],
        product_cut=inputs["product_cut"],
        trust_summary=trust_summary,
    )


def build_snapshot_bundle_for_symbol_timeframe(
    symbol: str,
    timeframe: str,
    *,
    source: str = "auto",
    generated_at: float | None = None,
    allow_release_reference_meta_fallback: bool = False,
) -> dict:
    inputs = _load_snapshot_projection_inputs(
        symbol,
        timeframe,
        source=source,
        generated_at=generated_at,
        allow_release_reference_meta_fallback=allow_release_reference_meta_fallback,
    )
    measurement_summary = _build_measurement_summary(symbol, timeframe)
    trust_summary = _build_trust_summary(
        raw_meta=inputs["raw_meta"],
        structure_status=inputs["structure_status"],
        measurement_summary=measurement_summary,
    )
    dashboard_payload, pine_payload = _build_projection_payloads(
        inputs["snapshot"],
        source_plan=inputs["source_plan"],
        structure_status=inputs["structure_status"],
        product_cut=inputs["product_cut"],
        trust_summary=trust_summary,
    )

    source_descriptor = _resolve_source_descriptor(source=source, selected=inputs["selected"])
    context_payload = _build_context_payloads(symbol, timeframe, inputs["snapshot"])

    structure_context = inputs["structure_context"]
    measurement_refs = _build_measurement_refs(symbol, timeframe, measurement_summary)

    out = {
        "source_plan": inputs["source_plan"],
        "structure_status": inputs["structure_status"],
        "product_cut": inputs["product_cut"],
        "source": source_descriptor.to_dict(),
        "snapshot": snapshot_to_dict(inputs["snapshot"], product_cut=inputs["product_cut"]),
        "dashboard_payload": dashboard_payload,
        "pine_payload": pine_payload,
        **context_payload,
        "measurement_refs": measurement_refs,
        "measurement_summary": measurement_summary,
        "trust_summary": trust_summary,
        "market_context": _build_market_context(
            context_payload=context_payload,
            measurement_summary=measurement_summary,
        ),
        **_build_meta_delivery_payload(inputs["raw_meta"]),
    }
    if structure_context is not None:
        out["structure_context"] = structure_context

    return out

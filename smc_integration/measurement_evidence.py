from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.explicit_structure_from_bars import build_explicit_structure_from_bars, resample_bars_to_timeframe
from scripts.load_databento_export_bundle import load_export_bundle
from scripts.smc_htf_context import build_htf_bias_context
from scripts.smc_session_context import build_session_liquidity_context
from scripts.smc_session_context_block import build_session_context_block
from smc_core.bias_merge import merge_bias
from smc_core.benchmark import EventFamily
from smc_core.scoring import ScoredEvent, label_sweep_reversal
from smc_core.vol_regime import compute_vol_regime
from smc_integration.artifact_resolution import resolve_structure_artifact_inputs
from smc_integration.sources import structure_artifact_json


_FAMILIES: tuple[EventFamily, ...] = ("BOS", "OB", "FVG", "SWEEP")
_SWEEP_LOOKAHEAD_BARS = 8
_SWEEP_REVERSAL_THRESHOLD_PCT = 0.005


@dataclass(slots=True, frozen=True)
class MeasurementEvidence:
    events_by_family: dict[EventFamily, list[dict[str, Any]]]
    stratified_events: dict[str, dict[EventFamily, list[dict[str, Any]]]]
    scored_events: list[ScoredEvent]
    details: dict[str, Any]
    warnings: list[str]


def _empty_bars() -> pd.DataFrame:
    return pd.DataFrame(columns=["symbol", "timestamp", "open", "high", "low", "close", "volume"])


def _empty_family_map() -> dict[EventFamily, list[dict[str, Any]]]:
    return {family: [] for family in _FAMILIES}


def _normalize_numeric_bars(frame: pd.DataFrame, *, timestamp_column: str) -> pd.DataFrame:
    if frame.empty:
        return _empty_bars()

    bars = frame.copy()
    bars["symbol"] = bars.get("symbol", "").astype(str).str.strip().str.upper()
    for column in ("open", "high", "low", "close"):
        bars[column] = pd.to_numeric(bars.get(column), errors="coerce")
    bars["volume"] = pd.to_numeric(bars.get("volume", 0.0), errors="coerce").fillna(0.0)
    bars["timestamp"] = pd.to_datetime(bars.get(timestamp_column), utc=True, errors="coerce")
    bars = bars.dropna(subset=["timestamp", "open", "high", "low", "close"]).reset_index(drop=True)
    return bars[["symbol", "timestamp", "open", "high", "low", "close", "volume"]]


def _load_source_bars(symbol: str, timeframe: str, resolved_inputs: dict[str, Any] | None = None) -> tuple[pd.DataFrame, str]:
    resolved = resolved_inputs or resolve_structure_artifact_inputs()
    export_bundle_root = resolved.get("export_bundle_root")
    workbook_path = resolved.get("workbook_path")
    symbol_name = str(symbol).strip().upper()
    canonical_tf = str(timeframe).strip()

    if export_bundle_root is not None:
        try:
            bundle = load_export_bundle(export_bundle_root, manifest_prefix="databento_volatility_production_")
        except Exception:
            bundle = None

        if isinstance(bundle, dict):
            frames = bundle.get("frames", {})
            if canonical_tf == "1D":
                daily = frames.get("daily_bars")
                if isinstance(daily, pd.DataFrame) and not daily.empty:
                    filtered = daily.loc[daily.get("symbol", "").astype(str).str.strip().str.upper().eq(symbol_name)].copy()
                    bars = _normalize_numeric_bars(filtered, timestamp_column="trade_date")
                    if not bars.empty:
                        return bars.reset_index(drop=True), "canonical_export_bundle"
            else:
                intraday = frames.get("full_universe_second_detail_open")
                if isinstance(intraday, pd.DataFrame) and not intraday.empty:
                    filtered = intraday.copy()
                    filtered["symbol"] = filtered.get("symbol", "").astype(str).str.strip().str.upper()
                    filtered = filtered.loc[filtered["symbol"].eq(symbol_name)].copy()
                    bars = _normalize_numeric_bars(filtered, timestamp_column="timestamp")
                    if not bars.empty:
                        return bars.reset_index(drop=True), "canonical_export_bundle"

    if canonical_tf == "1D" and isinstance(workbook_path, Path) and workbook_path.exists():
        try:
            daily_bars = pd.read_excel(workbook_path, sheet_name="daily_bars")
        except Exception:
            daily_bars = pd.DataFrame()
        if not daily_bars.empty:
            daily_bars["symbol"] = daily_bars.get("symbol", "").astype(str).str.strip().str.upper()
            filtered = daily_bars.loc[daily_bars["symbol"].eq(symbol_name)].copy()
            bars = _normalize_numeric_bars(filtered, timestamp_column="trade_date")
            if not bars.empty:
                return bars.reset_index(drop=True), "workbook_fallback"

    return _empty_bars(), "none"


def _canonical_event_counts(contract: dict[str, Any]) -> dict[EventFamily, int]:
    structure = contract.get("canonical_structure", {}) if isinstance(contract, dict) else {}
    return {
        "BOS": len(structure.get("bos", [])) if isinstance(structure.get("bos"), list) else 0,
        "OB": len(structure.get("orderblocks", [])) if isinstance(structure.get("orderblocks"), list) else 0,
        "FVG": len(structure.get("fvg", [])) if isinstance(structure.get("fvg"), list) else 0,
        "SWEEP": len(structure.get("liquidity_sweeps", [])) if isinstance(structure.get("liquidity_sweeps"), list) else 0,
    }


def _to_epoch_seconds(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce").astype("int64") // 10**9
    return out.dropna(subset=["timestamp", "open", "high", "low", "close"]).reset_index(drop=True)


def _find_bar_index(bars: pd.DataFrame, event_ts: float) -> int | None:
    matches = bars.index[bars["timestamp"].astype(float) >= float(event_ts)].tolist()
    if not matches:
        return None
    return int(matches[0])


def _find_first_index(future_bars: pd.DataFrame, predicate) -> int | None:
    for idx in range(len(future_bars)):
        if predicate(future_bars.iloc[idx]):
            return idx
    return None


def _directional_excursions(reference_price: float, direction: str, future_bars: pd.DataFrame) -> tuple[float, float]:
    if future_bars.empty or reference_price <= 0:
        return 0.0, 0.0

    max_high = float(pd.to_numeric(future_bars["high"], errors="coerce").max())
    min_low = float(pd.to_numeric(future_bars["low"], errors="coerce").min())
    normalized_direction = str(direction).strip().upper()

    if normalized_direction in {"DOWN", "BEAR", "BEARISH"}:
        mfe = max((reference_price - min_low) / reference_price, 0.0)
        mae = max((max_high - reference_price) / reference_price, 0.0)
        return round(mae, 6), round(mfe, 6)

    mfe = max((max_high - reference_price) / reference_price, 0.0)
    mae = max((reference_price - min_low) / reference_price, 0.0)
    return round(mae, 6), round(mfe, 6)


def _event_session_key(anchor_ts: float, timeframe: str) -> str:
    if str(timeframe).strip().upper() == "1D":
        return "session:NONE"
    session = build_session_context_block(timestamp=datetime.fromtimestamp(float(anchor_ts), tz=UTC))
    return f"session:{session.get('SESSION_CONTEXT', 'NONE')}"


def _append_stratified_event(
    stratified_events: dict[str, dict[EventFamily, list[dict[str, Any]]]],
    key: str,
    family: EventFamily,
    event_payload: dict[str, Any],
) -> None:
    bucket = stratified_events.setdefault(key, _empty_family_map())
    bucket[family].append(dict(event_payload))


def _evaluate_bos_event(event: dict[str, Any], bars: pd.DataFrame) -> dict[str, Any] | None:
    price = float(event.get("price", 0.0) or 0.0)
    anchor_ts = float(event.get("time", event.get("anchor_ts", 0.0)) or 0.0)
    direction = str(event.get("dir", "UP")).upper()
    if price <= 0 or anchor_ts <= 0:
        return None

    anchor_idx = _find_bar_index(bars, anchor_ts)
    if anchor_idx is None or anchor_idx >= len(bars) - 1:
        return None

    future = bars.iloc[anchor_idx + 1 :].reset_index(drop=True)
    if future.empty:
        return None

    if direction == "DOWN":
        touch_idx = _find_first_index(future, lambda row: float(row["high"]) >= price)
        invalid_idx = _find_first_index(future, lambda row: float(row["close"]) > price)
    else:
        touch_idx = _find_first_index(future, lambda row: float(row["low"]) <= price)
        invalid_idx = _find_first_index(future, lambda row: float(row["close"]) < price)

    hit = touch_idx is not None and (invalid_idx is None or touch_idx <= invalid_idx)
    mae, mfe = _directional_excursions(price, direction, future)
    return {
        "hit": hit,
        "time_to_mitigation": float((touch_idx + 1) if hit and touch_idx is not None else 0.0),
        "invalidated": invalid_idx is not None,
        "mae": mae,
        "mfe": mfe,
    }


def _evaluate_zone_event(
    event: dict[str, Any],
    bars: pd.DataFrame,
    *,
    diagnostics_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    low = float(event.get("low", 0.0) or 0.0)
    high = float(event.get("high", 0.0) or 0.0)
    anchor_ts = float(event.get("anchor_ts", event.get("time", 0.0)) or 0.0)
    direction = str(event.get("dir", "BULL")).upper()
    if low <= 0 or high <= 0 or anchor_ts <= 0 or high < low:
        return None

    anchor_idx = _find_bar_index(bars, anchor_ts)
    if anchor_idx is None or anchor_idx >= len(bars) - 1:
        return None

    future = bars.iloc[anchor_idx + 1 :].reset_index(drop=True)
    if future.empty:
        return None

    event_id = str(event.get("id", "")).strip()
    diag = diagnostics_by_id.get(event_id, {})
    mitigated_idx: int | None = None
    mitigated_ts = diag.get("mitigated_ts")
    if diag.get("mitigated") and mitigated_ts is not None:
        absolute_idx = _find_bar_index(bars, float(mitigated_ts))
        if absolute_idx is not None and absolute_idx > anchor_idx:
            mitigated_idx = absolute_idx - anchor_idx - 1

    if direction in {"BEAR", "BEARISH", "DOWN"}:
        if mitigated_idx is None:
            mitigated_idx = _find_first_index(future, lambda row: low <= float(row["high"]) <= high)
        invalid_idx = _find_first_index(future, lambda row: float(row["close"]) > high)
    else:
        if mitigated_idx is None:
            mitigated_idx = _find_first_index(future, lambda row: low <= float(row["low"]) <= high)
        invalid_idx = _find_first_index(future, lambda row: float(row["close"]) < low)

    hit = mitigated_idx is not None and (invalid_idx is None or mitigated_idx <= invalid_idx)
    mae, mfe = _directional_excursions((low + high) / 2.0, direction, future)
    return {
        "hit": hit,
        "time_to_mitigation": float((mitigated_idx + 1) if hit and mitigated_idx is not None else 0.0),
        "invalidated": bool(invalid_idx is not None or not bool(event.get("valid", True))),
        "mae": mae,
        "mfe": mfe,
    }


def _expected_reversal_direction(side: str) -> str:
    return "BULLISH" if str(side).upper() == "SELL_SIDE" else "BEARISH"


def _sweep_probability(side: str, *, bias_direction: str, bias_confidence: float) -> float:
    expected_direction = _expected_reversal_direction(side)
    normalized_bias = str(bias_direction).upper()
    confidence = max(float(bias_confidence), 0.0)
    if normalized_bias == "NEUTRAL":
        return 0.5
    adjustment = min(0.15, 0.15 * max(confidence, 0.5))
    if normalized_bias == expected_direction:
        return round(min(0.95, 0.5 + adjustment), 4)
    return round(max(0.05, 0.5 - adjustment), 4)


def _evaluate_sweep_event(
    event: dict[str, Any],
    bars: pd.DataFrame,
    *,
    bias_direction: str,
    bias_confidence: float,
) -> tuple[dict[str, Any], ScoredEvent] | None:
    price = float(event.get("price", 0.0) or 0.0)
    anchor_ts = float(event.get("time", event.get("anchor_ts", 0.0)) or 0.0)
    side = str(event.get("side", "SELL_SIDE")).upper()
    if price <= 0 or anchor_ts <= 0:
        return None

    anchor_idx = _find_bar_index(bars, anchor_ts)
    if anchor_idx is None or anchor_idx >= len(bars) - 1:
        return None

    future = bars.iloc[anchor_idx + 1 : anchor_idx + 1 + _SWEEP_LOOKAHEAD_BARS].reset_index(drop=True)
    if future.empty:
        return None

    closes = [float(value) for value in pd.to_numeric(future["close"], errors="coerce").dropna().tolist()]
    hit_idx: int | None = None
    for idx in range(len(closes)):
        if label_sweep_reversal(price, side, closes[: idx + 1], threshold_pct=_SWEEP_REVERSAL_THRESHOLD_PCT):
            hit_idx = idx
            break

    if side == "SELL_SIDE":
        invalid_idx = _find_first_index(
            future,
            lambda row: float(row["low"]) <= price * (1.0 - _SWEEP_REVERSAL_THRESHOLD_PCT),
        )
        mae, mfe = _directional_excursions(price, "UP", future)
    else:
        invalid_idx = _find_first_index(
            future,
            lambda row: float(row["high"]) >= price * (1.0 + _SWEEP_REVERSAL_THRESHOLD_PCT),
        )
        mae, mfe = _directional_excursions(price, "DOWN", future)

    outcome = hit_idx is not None
    invalidated = invalid_idx is not None and (hit_idx is None or invalid_idx <= hit_idx)
    scored_event = ScoredEvent(
        event_id=str(event.get("id", "")),
        family="SWEEP",
        predicted_prob=_sweep_probability(side, bias_direction=bias_direction, bias_confidence=bias_confidence),
        outcome=outcome,
        timestamp=float(anchor_ts),
    )
    return {
        "hit": outcome,
        "time_to_mitigation": float((hit_idx + 1) if hit_idx is not None else 0.0),
        "invalidated": invalidated,
        "mae": mae,
        "mfe": mfe,
    }, scored_event


def build_measurement_evidence(symbol: str, timeframe: str) -> MeasurementEvidence:
    warnings: list[str] = []
    resolved_inputs = resolve_structure_artifact_inputs()
    details: dict[str, Any] = {
        "symbol": str(symbol).strip().upper(),
        "timeframe": str(timeframe).strip(),
        "structure_artifact_mode": structure_artifact_json.resolve_artifact_mode(symbol, timeframe),
        "source_resolution_mode": str(resolved_inputs.get("resolution_mode", "missing")),
        "measurement_evidence_present": False,
    }

    contract = structure_artifact_json.load_normalized_structure_contract_input(symbol, timeframe)
    events_by_family = _empty_family_map()
    stratified_events: dict[str, dict[EventFamily, list[dict[str, Any]]]] = {}
    scored_events: list[ScoredEvent] = []

    if contract is None:
        warnings.append("structure artifact unavailable for measurement evidence")
        details["canonical_event_counts"] = {family: 0 for family in _FAMILIES}
        details["evaluated_event_counts"] = {family: 0 for family in _FAMILIES}
        details["warnings"] = list(warnings)
        return MeasurementEvidence(events_by_family, stratified_events, scored_events, details, warnings)

    details["structure_profile_used"] = str(contract.get("structure_profile_used", "hybrid_default"))
    details["canonical_event_counts"] = _canonical_event_counts(contract)

    raw_bars, bars_source_mode = _load_source_bars(symbol, timeframe, resolved_inputs)
    details["bars_source_mode"] = bars_source_mode
    details["raw_bar_rows"] = int(len(raw_bars))
    if raw_bars.empty:
        warnings.append("no bar source available for measurement evidence")
        details["evaluated_event_counts"] = {family: 0 for family in _FAMILIES}
        details["warnings"] = list(warnings)
        return MeasurementEvidence(events_by_family, stratified_events, scored_events, details, warnings)

    resampled_bars = resample_bars_to_timeframe(raw_bars, timeframe)
    if resampled_bars.empty:
        warnings.append("target timeframe bars could not be resampled for measurement evidence")
        details["evaluated_event_counts"] = {family: 0 for family in _FAMILIES}
        details["warnings"] = list(warnings)
        return MeasurementEvidence(events_by_family, stratified_events, scored_events, details, warnings)
    resampled_bars = _to_epoch_seconds(resampled_bars)
    details["resampled_bar_rows"] = int(len(resampled_bars))

    explicit_payload: dict[str, Any] | None = None
    try:
        explicit_payload = build_explicit_structure_from_bars(
            raw_bars,
            symbol=str(symbol).strip().upper(),
            timeframe=timeframe,
            structure_profile=str(contract.get("structure_profile_used", "hybrid_default")),
        )
    except Exception as exc:
        warnings.append(f"explicit structure recompute unavailable for measurement evidence: {exc}")

    details["explicit_recompute_available"] = explicit_payload is not None
    orderblock_diagnostics: dict[str, dict[str, Any]] = {}
    fvg_diagnostics: dict[str, dict[str, Any]] = {}
    if explicit_payload is not None:
        details["recomputed_event_counts"] = {
            "BOS": len(explicit_payload.get("bos", [])),
            "OB": len(explicit_payload.get("orderblocks", [])),
            "FVG": len(explicit_payload.get("fvg", [])),
            "SWEEP": len(explicit_payload.get("liquidity_sweeps", [])),
        }
        diagnostics = explicit_payload.get("diagnostics", {}) if isinstance(explicit_payload.get("diagnostics"), dict) else {}
        orderblock_diagnostics = {
            str(item.get("id", "")).strip(): item
            for item in diagnostics.get("orderblock_diagnostics", [])
            if isinstance(item, dict)
        }
        fvg_diagnostics = {
            str(item.get("id", "")).strip(): item
            for item in diagnostics.get("fvg_diagnostics", [])
            if isinstance(item, dict)
        }

    structure = contract.get("canonical_structure", {}) if isinstance(contract.get("canonical_structure"), dict) else {}
    effective_structure = {
        "bos": list(structure.get("bos", [])) if isinstance(structure.get("bos"), list) else [],
        "orderblocks": list(structure.get("orderblocks", [])) if isinstance(structure.get("orderblocks"), list) else [],
        "fvg": list(structure.get("fvg", [])) if isinstance(structure.get("fvg"), list) else [],
        "liquidity_sweeps": list(structure.get("liquidity_sweeps", [])) if isinstance(structure.get("liquidity_sweeps"), list) else [],
    }
    fallback_families: list[str] = []
    if explicit_payload is not None:
        fallback_map = {
            "bos": "BOS",
            "orderblocks": "OB",
            "fvg": "FVG",
            "liquidity_sweeps": "SWEEP",
        }
        for contract_key, family in fallback_map.items():
            recomputed_family = explicit_payload.get(contract_key, [])
            if effective_structure[contract_key] or not isinstance(recomputed_family, list) or not recomputed_family:
                continue
            effective_structure[contract_key] = list(recomputed_family)
            fallback_families.append(family)
    details["structure_fallback_families"] = fallback_families
    details["effective_event_counts"] = {
        "BOS": len(effective_structure["bos"]),
        "OB": len(effective_structure["orderblocks"]),
        "FVG": len(effective_structure["fvg"]),
        "SWEEP": len(effective_structure["liquidity_sweeps"]),
    }

    try:
        session_context = build_session_liquidity_context(resampled_bars, tz="America/New_York")
    except Exception as exc:
        session_context = {}
        warnings.append(f"session context unavailable for measurement evidence: {exc}")

    try:
        htf_context = build_htf_bias_context(resampled_bars, timeframe=timeframe, htf_frames=None)
    except Exception as exc:
        htf_context = {}
        warnings.append(f"htf bias context unavailable for measurement evidence: {exc}")

    bias_verdict = merge_bias(htf_context or None, session_context or None)
    vol_regime = compute_vol_regime(resampled_bars)
    details["bias_direction"] = bias_verdict.direction
    details["bias_confidence"] = bias_verdict.confidence
    details["vol_regime"] = vol_regime.label
    details["measurement_evidence_present"] = True
    skipped_counts = {family: 0 for family in _FAMILIES}

    for event in effective_structure["bos"]:
        evaluated = _evaluate_bos_event(event, resampled_bars)
        if evaluated is None:
            skipped_counts["BOS"] += 1
            continue
        events_by_family["BOS"].append(evaluated)
        anchor_ts = float(event.get("time", event.get("anchor_ts", 0.0)) or 0.0)
        _append_stratified_event(stratified_events, _event_session_key(anchor_ts, timeframe), "BOS", evaluated)
        _append_stratified_event(stratified_events, f"htf_bias:{bias_verdict.direction}", "BOS", evaluated)
        _append_stratified_event(stratified_events, f"vol_regime:{vol_regime.label}", "BOS", evaluated)

    for event in effective_structure["orderblocks"]:
        evaluated = _evaluate_zone_event(event, resampled_bars, diagnostics_by_id=orderblock_diagnostics)
        if evaluated is None:
            skipped_counts["OB"] += 1
            continue
        events_by_family["OB"].append(evaluated)
        anchor_ts = float(event.get("anchor_ts", event.get("time", 0.0)) or 0.0)
        _append_stratified_event(stratified_events, _event_session_key(anchor_ts, timeframe), "OB", evaluated)
        _append_stratified_event(stratified_events, f"htf_bias:{bias_verdict.direction}", "OB", evaluated)
        _append_stratified_event(stratified_events, f"vol_regime:{vol_regime.label}", "OB", evaluated)

    for event in effective_structure["fvg"]:
        evaluated = _evaluate_zone_event(event, resampled_bars, diagnostics_by_id=fvg_diagnostics)
        if evaluated is None:
            skipped_counts["FVG"] += 1
            continue
        events_by_family["FVG"].append(evaluated)
        anchor_ts = float(event.get("anchor_ts", event.get("time", 0.0)) or 0.0)
        _append_stratified_event(stratified_events, _event_session_key(anchor_ts, timeframe), "FVG", evaluated)
        _append_stratified_event(stratified_events, f"htf_bias:{bias_verdict.direction}", "FVG", evaluated)
        _append_stratified_event(stratified_events, f"vol_regime:{vol_regime.label}", "FVG", evaluated)

    for event in effective_structure["liquidity_sweeps"]:
        sweep_evidence = _evaluate_sweep_event(
            event,
            resampled_bars,
            bias_direction=bias_verdict.direction,
            bias_confidence=bias_verdict.confidence,
        )
        if sweep_evidence is None:
            skipped_counts["SWEEP"] += 1
            continue
        benchmark_event, scored_event = sweep_evidence
        events_by_family["SWEEP"].append(benchmark_event)
        scored_events.append(scored_event)
        anchor_ts = float(event.get("time", event.get("anchor_ts", 0.0)) or 0.0)
        _append_stratified_event(stratified_events, _event_session_key(anchor_ts, timeframe), "SWEEP", benchmark_event)
        _append_stratified_event(stratified_events, f"htf_bias:{bias_verdict.direction}", "SWEEP", benchmark_event)
        _append_stratified_event(stratified_events, f"vol_regime:{vol_regime.label}", "SWEEP", benchmark_event)

    details["evaluated_event_counts"] = {family: len(events_by_family[family]) for family in _FAMILIES}
    details["skipped_event_counts"] = skipped_counts
    details["scoring_event_count"] = len(scored_events)
    details["stratification_keys"] = sorted(stratified_events.keys())
    details["warnings"] = list(warnings)
    return MeasurementEvidence(events_by_family, stratified_events, scored_events, details, warnings)
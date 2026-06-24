from __future__ import annotations

import hashlib
import logging
import math
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from databento_reference import get_reference_event_risk_snapshot

# ADR-0023 §4.1: produce FamilyEvent records alongside measurement evidence
# so the magnitude shadow workflow can consume them without re-running
# the detection pipeline.
from governance.family_event_adapter import family_events_from_structure as _family_events_from_structure
from scripts.explicit_structure_from_bars import build_explicit_structure_from_bars, resample_bars_to_timeframe
from scripts.load_databento_export_bundle import load_export_bundle
from scripts.smc_event_risk_builder import build_event_risk
from scripts.smc_event_risk_light import build_event_risk_light
from scripts.smc_session_context_block import build_session_context_block
from scripts.smc_session_context_light import build_session_context_light
from scripts.smc_signal_quality import (
    _SQ_MODEL_V2,
    _SQ_MODEL_V21,
    build_signal_quality,
    build_signal_quality_v2,
)
from scripts.smc_structure_state import build_structure_state
from scripts.smc_structure_state_light import build_structure_state_light
from smc_core.benchmark import EventFamily
from smc_core.bias_merge import merge_bias
from smc_core.cached_workbook_reader import read_daily_bars
from smc_core.ensemble_quality import build_ensemble_quality, serialize_ensemble_quality
from smc_core.event_freshness import classify_freshness  # Phase A
from smc_core.htf_context import build_htf_bias_context
from smc_core.reaction_zone import compute_reaction_zone  # Phase C
from smc_core.scoring import (
    ScoredEvent,
    compute_fvg_partial_fill,
    label_bos_follow_through,
    label_fvg_mitigation,
    label_fvg_partial_50,
    label_orderblock_mitigation,
    label_sweep_reversal,
    score_events,
)
from smc_core.session_context import build_session_liquidity_context
from smc_core.smc_confluence import compute_confluence  # Phase D
from smc_core.sweep_trap import classify_sweep_trap  # Phase B
from smc_core.vol_regime import compute_vol_regime
from smc_integration.artifact_resolution import resolve_structure_artifact_inputs
from smc_integration.repo_sources import load_raw_meta_input_composite
from smc_integration.sources import structure_artifact_json
from smc_integration.timeframes import is_daily_timeframe

logger = logging.getLogger(__name__)


_FAMILIES: tuple[EventFamily, ...] = ("BOS", "OB", "FVG", "SWEEP")
_BOS_LOOKAHEAD_BARS = 8
_ZONE_LOOKAHEAD_BARS = 12
_FVG_LOOKAHEAD_BARS = 20
_SWEEP_LOOKAHEAD_BARS = 8
_BOS_FOLLOW_THROUGH_THRESHOLD_PCT = 0.003
_SWEEP_REVERSAL_THRESHOLD_PCT = 0.005
_SQ_LOOKBACK_BARS = 64
_SQ_RAW_SCORE_NAME = "SIGNAL_QUALITY_SCORE"


def _bool_env(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).strip() == "1"


def is_freshness_v2_enabled() -> bool:
    return _bool_env("ENABLE_FRESHNESS_V2", "0")


def is_sweep_trap_enabled() -> bool:
    return _bool_env("ENABLE_SWEEP_TRAP", "0")


def is_reaction_zone_enabled() -> bool:
    return _bool_env("ENABLE_REACTION_ZONE", "0")


def is_confluence_score_enabled() -> bool:
    return _bool_env("ENABLE_CONFLUENCE_SCORE", "0")


def signal_quality_model() -> str:
    return os.environ.get("SIGNAL_QUALITY_MODEL", "v1").strip()


def build_evidence_id(
    *,
    symbol: str,
    timeframe: str,
    run_timestamp: float,
    config_fingerprint: str = "",
) -> str:
    """Build a deterministic, stable evidence ID from run parameters.

    The ID is a short hex digest derived from the symbol, timeframe,
    run timestamp (truncated to seconds), and optional config fingerprint.
    Changing any parameter produces a different ID.
    """
    ts_seconds = int(run_timestamp)
    canonical = f"{symbol.strip().upper()}|{timeframe.strip()}|{ts_seconds}|{config_fingerprint.strip()}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


@dataclass(slots=True, frozen=True)
class MeasurementEvidence:
    events_by_family: dict[EventFamily, list[dict[str, Any]]]
    stratified_events: dict[str, dict[EventFamily, list[dict[str, Any]]]]
    scored_events: list[ScoredEvent]
    details: dict[str, Any]
    warnings: list[str]
    # ADR-0023 §4.1: raw FamilyEvent dicts for magnitude-shadow consumption.
    family_events: list[dict[str, Any]] = field(default_factory=list)


def _empty_bars() -> pd.DataFrame:
    return pd.DataFrame(columns=["symbol", "timestamp", "open", "high", "low", "close", "volume"])


def _empty_family_map() -> dict[EventFamily, list[dict[str, Any]]]:
    return {family: [] for family in _FAMILIES}


def _empty_event_risk_light() -> dict[str, Any]:
    return build_event_risk_light(event_risk={"EVENT_PROVIDER_STATUS": "no_data"})


def _event_risk_signal_present(event_risk_light: dict[str, Any]) -> bool:
    level = str(event_risk_light.get("EVENT_RISK_LEVEL", "NONE") or "NONE").strip().upper()
    return bool(
        event_risk_light.get("MARKET_EVENT_BLOCKED")
        or event_risk_light.get("SYMBOL_EVENT_BLOCKED")
        or level != "NONE"
    )


def _resolve_measurement_event_risk_light(symbol: str, timeframe: str) -> tuple[dict[str, Any], dict[str, Any]]:
    raw_meta_lookup_failed = False
    try:
        raw_meta = load_raw_meta_input_composite(symbol, timeframe, source="auto")
    except Exception as exc:
        raw_meta_lookup_failed = True
        logger.warning(
            "event-risk raw_meta lookup failed for %s %s: %s",
            symbol,
            timeframe,
            exc,
            exc_info=True,
        )
        raw_meta = None

    raw_event_risk = raw_meta.get("event_risk") if isinstance(raw_meta, dict) else None
    if isinstance(raw_event_risk, dict) and raw_event_risk:
        event_risk_light = build_event_risk_light(event_risk=dict(raw_event_risk))
        return event_risk_light, {
            "event_risk_source_mode": "raw_meta",
            "event_risk_provider_status": str(event_risk_light.get("EVENT_PROVIDER_STATUS", "no_data") or "no_data"),
            "event_risk_reference_provider_status": None,
            "event_risk_signal_present": _event_risk_signal_present(event_risk_light),
            "event_risk_lookup_failed": raw_meta_lookup_failed,
        }

    reference_lookup_failed = False
    try:
        reference_snapshot = get_reference_event_risk_snapshot([symbol])
    except Exception as exc:
        reference_lookup_failed = True
        logger.warning(
            "event-risk reference snapshot lookup failed for %s: %s",
            symbol,
            exc,
            exc_info=True,
        )
        reference_snapshot = None

    if isinstance(reference_snapshot, dict):
        broad_event_risk = build_event_risk(reference=reference_snapshot)
        event_risk_light = build_event_risk_light(event_risk=broad_event_risk)
        reference_provider_status = str(reference_snapshot.get("provider_status") or "").strip() or None
        return event_risk_light, {
            "event_risk_source_mode": "reference_snapshot",
            "event_risk_provider_status": str(event_risk_light.get("EVENT_PROVIDER_STATUS", "no_data") or "no_data"),
            "event_risk_reference_provider_status": reference_provider_status,
            "event_risk_signal_present": _event_risk_signal_present(event_risk_light),
            "event_risk_lookup_failed": raw_meta_lookup_failed or reference_lookup_failed,
        }

    event_risk_light = _empty_event_risk_light()
    lookup_failed = raw_meta_lookup_failed or reference_lookup_failed
    return event_risk_light, {
        "event_risk_source_mode": "lookup_failed" if lookup_failed else "none",
        "event_risk_provider_status": str(event_risk_light.get("EVENT_PROVIDER_STATUS", "no_data") or "no_data"),
        "event_risk_reference_provider_status": None,
        "event_risk_signal_present": False,
        "event_risk_lookup_failed": lookup_failed,
    }


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
    daily = is_daily_timeframe(canonical_tf)

    bundle_load_failed = False
    if export_bundle_root is not None:
        required_frames = ("daily_bars",) if daily else ("full_universe_second_detail_open",)
        try:
            bundle = load_export_bundle(
                export_bundle_root,
                required_frames=required_frames,
                manifest_prefix="databento_volatility_production_",
            )
        except Exception as exc:
            logger.warning(
                "canonical export bundle unavailable for symbol=%s timeframe=%s export_bundle_root=%s: %s",
                symbol_name,
                canonical_tf,
                export_bundle_root,
                exc,
            )
            bundle = None
            bundle_load_failed = True

        if isinstance(bundle, dict):
            frames = bundle.get("frames", {})
            if daily:
                daily_frame = frames.get("daily_bars")
                if isinstance(daily_frame, pd.DataFrame) and not daily_frame.empty:
                    filtered = daily_frame.loc[daily_frame.get("symbol", "").astype(str).str.strip().str.upper().eq(symbol_name)].copy()
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

    if daily and isinstance(workbook_path, Path) and workbook_path.exists():
        try:
            daily_bars = read_daily_bars(workbook_path)
        except Exception as exc:
            logger.warning(
                "workbook daily_bars sheet unreadable for symbol=%s workbook_path=%s: %s",
                symbol_name,
                workbook_path,
                exc,
            )
            daily_bars = pd.DataFrame()
        if not daily_bars.empty:
            daily_bars["symbol"] = daily_bars.get("symbol", "").astype(str).str.strip().str.upper()
            filtered = daily_bars.loc[daily_bars["symbol"].eq(symbol_name)].copy()
            bars = _normalize_numeric_bars(filtered, timestamp_column="trade_date")
            if not bars.empty:
                return bars.reset_index(drop=True), "workbook_fallback"

    if not daily and (bundle_load_failed or export_bundle_root is None):
        # No intraday source available: workbook only ships daily_bars, so an
        # intraday request that misses the canonical bundle silently degrades
        # to empty bars. Surface this so callers / monitoring can react instead
        # of treating the empty frame as "no events".
        logger.warning(
            "no intraday source available for symbol=%s timeframe=%s; workbook fallback is daily-only and bundle is %s",
            symbol_name,
            canonical_tf,
            "unavailable" if bundle_load_failed else "missing",
        )

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
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
    out = out.dropna(subset=["timestamp", "open", "high", "low", "close"]).copy()
    epoch = pd.Timestamp("1970-01-01", tz="UTC")
    out["timestamp"] = ((out["timestamp"] - epoch) // pd.Timedelta(seconds=1)).astype("int64")
    return out.reset_index(drop=True)


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


def _history_window(bars: pd.DataFrame, *, anchor_idx: int, lookback_bars: int = _SQ_LOOKBACK_BARS) -> pd.DataFrame:
    start = max(0, int(anchor_idx) - int(lookback_bars) + 1)
    return bars.iloc[start : anchor_idx + 1].reset_index(drop=True)


def _event_session_key(anchor_ts: float, timeframe: str) -> str:
    if str(timeframe).strip().upper() == "1D":
        return "session:NONE"
    session = build_session_context_block(timestamp=datetime.fromtimestamp(float(anchor_ts), tz=UTC))
    return f"session:{session.get('SESSION_CONTEXT', 'NONE')}"


def _event_session_label(anchor_ts: float, timeframe: str) -> str:
    return _event_session_key(anchor_ts, timeframe).split(":", 1)[1]


def _scored_event_context(
    anchor_ts: float,
    timeframe: str,
    *,
    bias_direction: str,
    vol_regime_label: str,
) -> dict[str, str]:
    return {
        "session": _event_session_label(anchor_ts, timeframe),
        "htf_bias": _normalize_direction(bias_direction),
        "vol_regime": str(vol_regime_label).strip().upper() or "NORMAL",
    }


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

    hit = touch_idx is not None and (invalid_idx is None or touch_idx < invalid_idx)
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
    emit_partial_50: bool = False,
) -> dict[str, Any] | None:
    low = float(event.get("low", 0.0) or 0.0)
    high = float(event.get("high", 0.0) or 0.0)
    anchor_ts = float(event.get("anchor_ts", event.get("time", 0.0)) or 0.0)
    direction = str(event.get("dir", "BULL")).upper()
    if low <= 0 or high <= 0 or anchor_ts <= 0 or high <= low:
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

    hit = mitigated_idx is not None and (invalid_idx is None or mitigated_idx < invalid_idx)
    mae, mfe = _directional_excursions((low + high) / 2.0, direction, future)

    # R3: Partial-fill tracking for FVG-type zones
    future_highs = [float(v) for v in pd.to_numeric(future["high"], errors="coerce").dropna().tolist()]
    future_lows = [float(v) for v in pd.to_numeric(future["low"], errors="coerce").dropna().tolist()]
    partial_fill_pct = compute_fvg_partial_fill(low, high, direction, future_highs, future_lows)

    payload: dict[str, Any] = {
        "hit": hit,
        "time_to_mitigation": float((mitigated_idx + 1) if hit and mitigated_idx is not None else 0.0),
        "invalidated": bool(invalid_idx is not None or not bool(event.get("valid", True))),
        "mae": mae,
        "mfe": mfe,
        "partial_fill_pct": partial_fill_pct,
    }
    # Q3 D1 follow-up #1b: surface the strict partial-50 label on the
    # benchmark/stratified payload (FVG only) so the next cron snapshot
    # carries it through to ``fvg_label_audit_q3.py`` aggregation. The
    # lenient ``hit`` flag stays canonical for legacy KPIs.
    if emit_partial_50:
        future_closes = [
            float(v) for v in pd.to_numeric(future["close"], errors="coerce").dropna().tolist()
        ]
        payload["label_partial_50"] = bool(
            label_fvg_partial_50(low, high, direction, future_highs, future_lows, future_closes)
        )
    return payload


def _expected_reversal_direction(side: str) -> str:
    return "BULLISH" if str(side).upper() == "SELL_SIDE" else "BEARISH"


def _normalize_direction(raw: str) -> str:
    normalized = str(raw).strip().upper()
    if normalized in {"UP", "BULL", "BULLISH"}:
        return "BULLISH"
    if normalized in {"DOWN", "BEAR", "BEARISH"}:
        return "BEARISH"
    return "NEUTRAL"


def _direction_vote_label(direction: str) -> str:
    normalized = _normalize_direction(direction)
    if normalized == "BULLISH":
        return "BULL"
    if normalized == "BEARISH":
        return "BEAR"
    return "NONE"


def _expected_event_direction(event: dict[str, Any], family: EventFamily) -> str:
    if family == "SWEEP":
        return _expected_reversal_direction(str(event.get("side", "SELL_SIDE")))
    return _normalize_direction(str(event.get("dir", "NEUTRAL")))


def _anchor_reference_price(event: dict[str, Any], *, family: EventFamily, bars: pd.DataFrame, anchor_idx: int) -> float:
    if family == "BOS":
        price = float(event.get("price", 0.0) or 0.0)
        if price > 0:
            return price
    if family in {"OB", "FVG"}:
        low = float(event.get("low", 0.0) or 0.0)
        high = float(event.get("high", 0.0) or 0.0)
        if low > 0 and high >= low:
            return (low + high) / 2.0
    close = float(pd.to_numeric(bars.iloc[anchor_idx].get("close"), errors="coerce") or 0.0)
    if close > 0:
        return close
    return float(event.get("price", 0.0) or 0.0)


def _mitigation_state(*, age_bars: int, mitigated: bool) -> str:
    if mitigated:
        return "mitigated"
    if age_bars <= 10:
        return "fresh"
    if age_bars <= 30:
        return "touched"
    return "stale"


def _candidate_mitigated_at_anchor(
    event: dict[str, Any],
    diagnostics_by_id: dict[str, dict[str, Any]],
    *,
    anchor_ts: float,
) -> bool:
    if not bool(event.get("valid", True)):
        return True
    event_id = str(event.get("id", "")).strip()
    diagnostic = diagnostics_by_id.get(event_id, {})
    if not diagnostic.get("mitigated"):
        return False
    mitigated_ts = float(diagnostic.get("mitigated_ts", 0.0) or 0.0)
    return mitigated_ts > 0.0 and mitigated_ts <= float(anchor_ts)


def _session_context_light_for_event(
    *,
    anchor_ts: float,
    family: EventFamily,
    expected_direction: str,
    bias_direction: str,
    vol_regime_label: str,
) -> dict[str, Any]:
    session_context = build_session_context_block(timestamp=datetime.fromtimestamp(float(anchor_ts), tz=UTC))
    normalized_bias = _normalize_direction(bias_direction)
    aligned = (
        expected_direction != "NEUTRAL"
        and normalized_bias != "NEUTRAL"
        and normalized_bias == expected_direction
    )
    score = 0
    if str(session_context.get("SESSION_CONTEXT", "NONE")) != "NONE":
        score += 1
    if bool(session_context.get("IN_KILLZONE", False)):
        score += 1
    if aligned:
        score += 2
    elif normalized_bias == "NEUTRAL" and expected_direction != "NEUTRAL":
        score += 1
    if family in {"BOS", "OB", "FVG"}:
        score += 1

    compression_regime = {
        "SQUEEZE_ON": str(vol_regime_label).strip().upper() == "LOW_VOL",
        "ATR_REGIME": {
            "LOW_VOL": "COMPRESSION",
            "NORMAL": "NORMAL",
            "HIGH_VOL": "EXPANSION",
            "EXTREME": "EXHAUSTION",
        }.get(str(vol_regime_label).strip().upper(), "NORMAL"),
        "ATR_RATIO": {
            "LOW_VOL": 0.6,
            "NORMAL": 1.0,
            "HIGH_VOL": 1.6,
            "EXTREME": 2.4,
        }.get(str(vol_regime_label).strip().upper(), 1.0),
    }
    broad_block = {
        "SESSION_CONTEXT": session_context.get("SESSION_CONTEXT", "NONE"),
        "IN_KILLZONE": session_context.get("IN_KILLZONE", False),
        "SESSION_DIRECTION_BIAS": normalized_bias if normalized_bias != "NEUTRAL" else expected_direction,
        "SESSION_CONTEXT_SCORE": min(score, 5),
    }
    return build_session_context_light(session_context=broad_block, compression_regime=compression_regime)


def _structure_state_light_for_event(
    *,
    event: dict[str, Any],
    family: EventFamily,
    history_bars: pd.DataFrame,
    expected_direction: str,
) -> dict[str, Any]:
    structure_state = build_structure_state(snapshot=history_bars)
    if family == "BOS" and expected_direction in {"BULLISH", "BEARISH"}:
        structure_state["STRUCTURE_STATE"] = expected_direction
        structure_state["STRUCTURE_BULL_ACTIVE"] = expected_direction == "BULLISH"
        structure_state["STRUCTURE_BEAR_ACTIVE"] = expected_direction == "BEARISH"
        structure_state["BOS_BULL"] = expected_direction == "BULLISH"
        structure_state["BOS_BEAR"] = expected_direction == "BEARISH"
        structure_state["CHOCH_BULL"] = False
        structure_state["CHOCH_BEAR"] = False
        structure_state["STRUCTURE_LAST_EVENT"] = "BOS_BULL" if expected_direction == "BULLISH" else "BOS_BEAR"
        structure_state["STRUCTURE_EVENT_AGE_BARS"] = 0
        structure_state["STRUCTURE_FRESH"] = True
    elif structure_state.get("STRUCTURE_LAST_EVENT") == "NONE" and expected_direction in {"BULLISH", "BEARISH"}:
        structure_state["STRUCTURE_STATE"] = expected_direction
        structure_state["STRUCTURE_BULL_ACTIVE"] = expected_direction == "BULLISH"
        structure_state["STRUCTURE_BEAR_ACTIVE"] = expected_direction == "BEARISH"
    return build_structure_state_light(structure_state=structure_state)


def _ob_context_light_for_event(
    *,
    current_event: dict[str, Any],
    family: EventFamily,
    orderblocks: list[dict[str, Any]],
    bars: pd.DataFrame,
    anchor_idx: int,
    anchor_ts: float,
    current_price: float,
    diagnostics_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    # Distance scaling below divides by ``current_price`` (with a defensive
    # ``max(..., 1e-9)`` previously). A non-positive or non-finite price
    # makes distance meaningless and used to silently demote candidates
    # via inflated distances; short-circuit to the empty payload instead.
    if not (math.isfinite(current_price) and current_price > 0):
        return {
            "PRIMARY_OB_SIDE": "NONE",
            "PRIMARY_OB_DISTANCE": 0.0,
            "OB_FRESH": False,
            "OB_AGE_BARS": 0,
            "OB_MITIGATION_STATE": "stale",
        }
    best: tuple[tuple[int, int, int, float, int], dict[str, Any]] | None = None
    current_id = str(current_event.get("id", "")).strip()

    for candidate in orderblocks:
        candidate_id = str(candidate.get("id", "")).strip()
        candidate_anchor_ts = float(candidate.get("anchor_ts", candidate.get("time", 0.0)) or 0.0)
        if candidate_anchor_ts <= 0 or candidate_anchor_ts > float(anchor_ts):
            continue
        candidate_idx = _find_bar_index(bars, candidate_anchor_ts)
        if candidate_idx is None or candidate_idx > anchor_idx:
            continue
        low = float(candidate.get("low", 0.0) or 0.0)
        high = float(candidate.get("high", 0.0) or 0.0)
        if low <= 0 or high < low:
            continue
        side = _direction_vote_label(str(candidate.get("dir", "NEUTRAL")))
        if side == "NONE":
            continue
        age_bars = max(anchor_idx - candidate_idx, 0)
        mitigated = _candidate_mitigated_at_anchor(candidate, diagnostics_by_id, anchor_ts=anchor_ts)
        midpoint = (low + high) / 2.0
        distance = 0.0 if candidate_id == current_id and family == "OB" else abs(current_price - midpoint) / current_price * 100.0
        priority = (
            0 if candidate_id == current_id and family == "OB" else 1,
            0 if not mitigated else 1,
            0 if age_bars <= 10 else (1 if age_bars <= 30 else 2),
            round(distance, 6),
            age_bars,
        )
        payload = {
            "PRIMARY_OB_SIDE": side,
            "PRIMARY_OB_DISTANCE": round(distance, 4),
            "OB_FRESH": age_bars <= 10 and not mitigated,
            "OB_AGE_BARS": age_bars,
            "OB_MITIGATION_STATE": _mitigation_state(age_bars=age_bars, mitigated=mitigated),
        }
        if best is None or priority < best[0]:
            best = (priority, payload)

    return best[1] if best is not None else {
        "PRIMARY_OB_SIDE": "NONE",
        "PRIMARY_OB_DISTANCE": 0.0,
        "OB_FRESH": False,
        "OB_AGE_BARS": 0,
        "OB_MITIGATION_STATE": "stale",
    }


def _fvg_lifecycle_light_for_event(
    *,
    current_event: dict[str, Any],
    family: EventFamily,
    fvgs: list[dict[str, Any]],
    bars: pd.DataFrame,
    anchor_idx: int,
    anchor_ts: float,
    current_price: float,
    diagnostics_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if not (math.isfinite(current_price) and current_price > 0):
        return {
            "PRIMARY_FVG_SIDE": "NONE",
            "PRIMARY_FVG_DISTANCE": 0.0,
            "FVG_FILL_PCT": 0.0,
            "FVG_MATURITY_LEVEL": 0,
            "FVG_FRESH": False,
            "FVG_INVALIDATED": False,
        }
    best: tuple[tuple[int, int, float, int], dict[str, Any]] | None = None
    current_id = str(current_event.get("id", "")).strip()

    for candidate in fvgs:
        candidate_id = str(candidate.get("id", "")).strip()
        candidate_anchor_ts = float(candidate.get("anchor_ts", candidate.get("time", 0.0)) or 0.0)
        if candidate_anchor_ts <= 0 or candidate_anchor_ts > float(anchor_ts):
            continue
        candidate_idx = _find_bar_index(bars, candidate_anchor_ts)
        if candidate_idx is None or candidate_idx > anchor_idx:
            continue
        low = float(candidate.get("low", 0.0) or 0.0)
        high = float(candidate.get("high", 0.0) or 0.0)
        if low <= 0 or high < low:
            continue
        side = _direction_vote_label(str(candidate.get("dir", "NEUTRAL")))
        if side == "NONE":
            continue
        invalidated = _candidate_mitigated_at_anchor(candidate, diagnostics_by_id, anchor_ts=anchor_ts)
        midpoint = (low + high) / 2.0
        distance = 0.0 if candidate_id == current_id and family == "FVG" else abs(current_price - midpoint) / current_price * 100.0
        fill_pct = 1.0 if invalidated else 0.0
        maturity = 3 if invalidated else 0
        priority = (
            0 if candidate_id == current_id and family == "FVG" else 1,
            0 if not invalidated else 1,
            round(distance, 6),
            max(anchor_idx - candidate_idx, 0),
        )
        payload = {
            "PRIMARY_FVG_SIDE": side,
            "PRIMARY_FVG_DISTANCE": round(distance, 4),
            "FVG_FILL_PCT": round(fill_pct, 4),
            "FVG_MATURITY_LEVEL": maturity,
            "FVG_FRESH": not invalidated,
            "FVG_INVALIDATED": invalidated,
        }
        if best is None or priority < best[0]:
            best = (priority, payload)

    return best[1] if best is not None else {
        "PRIMARY_FVG_SIDE": "NONE",
        "PRIMARY_FVG_DISTANCE": 0.0,
        "FVG_FILL_PCT": 0.0,
        "FVG_MATURITY_LEVEL": 0,
        "FVG_FRESH": False,
        "FVG_INVALIDATED": False,
    }


def _liquidity_support_for_event(
    *,
    current_event: dict[str, Any],
    family: EventFamily,
    sweeps: list[dict[str, Any]],
    bars: pd.DataFrame,
    anchor_idx: int,
    anchor_ts: float,
) -> dict[str, Any]:
    best: tuple[tuple[int, int], dict[str, Any]] | None = None
    current_id = str(current_event.get("id", "")).strip()

    for candidate in sweeps:
        candidate_id = str(candidate.get("id", "")).strip()
        candidate_anchor_ts = float(candidate.get("time", candidate.get("anchor_ts", 0.0)) or 0.0)
        if candidate_anchor_ts <= 0 or candidate_anchor_ts > float(anchor_ts):
            continue
        candidate_idx = _find_bar_index(bars, candidate_anchor_ts)
        if candidate_idx is None or candidate_idx > anchor_idx:
            continue
        age_bars = max(anchor_idx - candidate_idx, 0)
        side = str(candidate.get("side", "SELL_SIDE")).strip().upper()
        if side == "SELL_SIDE":
            bull_sweep = True
            bear_sweep = False
            direction = "BULL"
        elif side == "BUY_SIDE":
            bull_sweep = False
            bear_sweep = True
            direction = "BEAR"
        else:
            continue
        quality = 5 if candidate_id == current_id and family == "SWEEP" else max(1, 5 - min(age_bars, 4))
        payload: dict[str, Any] = {
            "RECENT_BULL_SWEEP": bull_sweep,
            "RECENT_BEAR_SWEEP": bear_sweep,
            "SWEEP_DIRECTION": direction,
            "SWEEP_QUALITY_SCORE": quality,
        }

        # Phase B — Sweep Trap Classifier (shadow enrichment, default OFF).
        if is_sweep_trap_enabled():
            try:
                swept_level = float(candidate.get("swept_level", 0.0) or 0.0)
                sweep_extreme = float(candidate.get("sweep_extreme", 0.0) or 0.0)
                origin_level = float(candidate.get("origin_level", swept_level) or swept_level)
                look_ahead_end = min(anchor_idx, candidate_idx + 14) if candidate_idx is not None else anchor_idx
                post_bars_df = bars.iloc[candidate_idx + 1 : look_ahead_end] if candidate_idx is not None else bars.iloc[0:0]
                post_sweep_bars = [
                    {"open": float(r["open"]), "high": float(r["high"]),
                     "low": float(r["low"]), "close": float(r["close"])}
                    for _, r in post_bars_df.iterrows()
                ]
                if swept_level > 0:
                    trap = classify_sweep_trap(
                        swept_level=swept_level,
                        sweep_extreme=sweep_extreme,
                        origin_level=origin_level,
                        is_bullish_sweep=bull_sweep,
                        post_sweep_bars=post_sweep_bars,
                    )
                    payload["SWEEP_TRAP_TYPE"] = trap.trap_type
                    payload["SWEEP_RECLAIM_BARS"] = trap.sweep_reclaim_bars
                    payload["SWEEP_RECLAIM_STRENGTH"] = trap.reclaim_strength
                    payload["SWEEP_FIB_RETRACE"] = trap.fib_retrace_depth
                    payload["SWEEP_TRAP_QUALITY_SCORE"] = trap.trap_quality_score

                    # Phase C — Reaction Zone (depends on Phase B active).
                    if is_reaction_zone_enabled() and swept_level > 0:
                        zone = compute_reaction_zone(
                            swept_level=swept_level,
                            sweep_extreme=sweep_extreme,
                            is_bullish_sweep=bull_sweep,
                            post_sweep_bars=post_sweep_bars,
                        )
                        payload["REACTION_ZONE_LOW"] = zone.reaction_zone_low
                        payload["REACTION_ZONE_HIGH"] = zone.reaction_zone_high
                        payload["REACTION_ZONE_CONFIRMED"] = zone.close_back_inside_zone
                        payload["REACTION_WICK_RATIO"] = zone.wick_rejection_ratio
                        payload["REACTION_BODY_RATIO"] = zone.confirmation_body_ratio
                        payload["REACTION_BARS_TO_CONFIRM"] = zone.bars_to_confirm
                        # Discount trap quality when reaction zone is unconfirmed.
                        if not zone.close_back_inside_zone and "SWEEP_TRAP_QUALITY_SCORE" in payload:
                            payload["SWEEP_TRAP_QUALITY_SCORE"] = (
                                payload["SWEEP_TRAP_QUALITY_SCORE"] * 0.50
                            )
            except Exception:
                pass  # Phase B/C is additive; failure must not break v1 scoring.
        priority = (0 if candidate_id == current_id and family == "SWEEP" else 1, age_bars)
        if best is None or priority < best[0]:
            best = (priority, payload)

    return best[1] if best is not None else {
        "RECENT_BULL_SWEEP": False,
        "RECENT_BEAR_SWEEP": False,
        "SWEEP_DIRECTION": "NONE",
        "SWEEP_QUALITY_SCORE": 0,
    }


# ---------------------------------------------------------------------------
# Phase A helper — freshness/invalidation shadow enrichment
# ---------------------------------------------------------------------------

def _freshness_state_light_for_event(
    *,
    event: dict[str, Any],
    anchor_idx: int,
    bars: pd.DataFrame,
) -> dict[str, Any]:
    """Build Phase A freshness enrichment for a single SMC event.

    Returns a dict with ``freshness_bucket``, ``freshness_penalty``,
    ``event_age_bars``, ``event_age_seconds``, ``invalidated_at``, and
    ``mitigated_at`` keys suitable for insertion under ``"freshness_v2"``
    in the enrichment dict.

    Falls back to a ``"fresh"`` state with full penalty (1.0) on any error,
    so v2 scoring degrades gracefully when data is incomplete.
    """
    try:
        event_bar = int(event.get("bar_index", anchor_idx))
        age_bars: int = max(0, anchor_idx - event_bar)

        mitigated: bool = bool(event.get("mitigated", False))
        invalidated: bool = bool(event.get("invalidated", False))
        mitigated_ts: float | None = event.get("mitigated_ts") or event.get("mitigated_at")
        invalidated_ts: float | None = event.get("invalidated_ts") or event.get("invalidated_at")

        # Approximate bar duration from the bars DataFrame when available.
        bar_seconds: float = 60.0
        if hasattr(bars, "index") and len(bars) >= 2:
            try:
                t0 = bars.index[-2]
                t1 = bars.index[-1]
                delta = (t1 - t0).total_seconds()  # type: ignore[operator]
                if delta > 0:
                    bar_seconds = float(delta)
            except Exception:
                pass

        state = classify_freshness(
            age_bars,
            mitigated=mitigated,
            invalidated=invalidated,
            mitigated_ts=float(mitigated_ts) if mitigated_ts is not None else None,
            invalidated_ts=float(invalidated_ts) if invalidated_ts is not None else None,
            bar_seconds=bar_seconds,
        )
        return {
            "freshness_bucket": state.freshness_bucket,
            "freshness_penalty": state.freshness_penalty,
            "event_age_bars": state.event_age_bars,
            "event_age_seconds": state.event_age_seconds,
            "invalidated_at": state.invalidated_at,
            "mitigated_at": state.mitigated_at,
        }
    except Exception:
        return {
            "freshness_bucket": "fresh",
            "freshness_penalty": 1.0,
            "event_age_bars": 0,
            "event_age_seconds": 0.0,
            "invalidated_at": None,
            "mitigated_at": None,
        }


# ---------------------------------------------------------------------------
# Phase D helper — confluence shadow enrichment
# ---------------------------------------------------------------------------

def _confluence_light_for_event(
    *,
    ob_light: dict[str, Any] | None,
    fvg_light: dict[str, Any] | None,
    sweep_light: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build Phase D confluence enrichment for a single SMC event.

    Returns a dict with ``raw_confluence_score`` and ``confluence_tier``
    for insertion under ``"confluence_v2"`` in the enrichment dict.
    """
    result = compute_confluence(ob_light, fvg_light, sweep_light)
    return {
        "ob_contribution": result.ob_contribution,
        "fvg_contribution": result.fvg_contribution,
        "sweep_contribution": result.sweep_contribution,
        "raw_confluence_score": result.raw_confluence_score,
        "confluence_tier": result.confluence_tier,
    }


def _event_signal_quality_score(
    *,
    event: dict[str, Any],
    family: EventFamily,
    bars: pd.DataFrame,
    anchor_idx: int,
    anchor_ts: float,
    bias_direction: str,
    vol_regime_label: str,
    event_risk_light: dict[str, Any],
    orderblocks: list[dict[str, Any]],
    fvgs: list[dict[str, Any]],
    sweeps: list[dict[str, Any]],
    orderblock_diagnostics: dict[str, dict[str, Any]],
    fvg_diagnostics: dict[str, dict[str, Any]],
) -> float:
    history_bars = _history_window(bars, anchor_idx=anchor_idx)
    expected_direction = _expected_event_direction(event, family)
    current_price = _anchor_reference_price(event, family=family, bars=bars, anchor_idx=anchor_idx)
    enrichment = {
        "event_risk_light": dict(event_risk_light),
        "structure_state_light": _structure_state_light_for_event(
            event=event,
            family=family,
            history_bars=history_bars,
            expected_direction=expected_direction,
        ),
        "session_context_light": _session_context_light_for_event(
            anchor_ts=anchor_ts,
            family=family,
            expected_direction=expected_direction,
            bias_direction=bias_direction,
            vol_regime_label=vol_regime_label,
        ),
        "ob_context_light": _ob_context_light_for_event(
            current_event=event,
            family=family,
            orderblocks=orderblocks,
            bars=bars,
            anchor_idx=anchor_idx,
            anchor_ts=anchor_ts,
            current_price=current_price,
            diagnostics_by_id=orderblock_diagnostics,
        ),
        "fvg_lifecycle_light": _fvg_lifecycle_light_for_event(
            current_event=event,
            family=family,
            fvgs=fvgs,
            bars=bars,
            anchor_idx=anchor_idx,
            anchor_ts=anchor_ts,
            current_price=current_price,
            diagnostics_by_id=fvg_diagnostics,
        ),
        "liquidity_sweeps": _liquidity_support_for_event(
            current_event=event,
            family=family,
            sweeps=sweeps,
            bars=bars,
            anchor_idx=anchor_idx,
            anchor_ts=anchor_ts,
        ),
        "compression_regime": {
            "SQUEEZE_ON": str(vol_regime_label).strip().upper() == "LOW_VOL",
            "ATR_REGIME": {
                "LOW_VOL": "COMPRESSION",
                "NORMAL": "NORMAL",
                "HIGH_VOL": "EXPANSION",
                "EXTREME": "EXHAUSTION",
            }.get(str(vol_regime_label).strip().upper(), "NORMAL"),
        },
    }
    # Phase A: freshness/invalidation shadow enrichment (no-op when disabled).
    if is_freshness_v2_enabled():
        enrichment["freshness_v2"] = _freshness_state_light_for_event(
            event=event,
            anchor_idx=anchor_idx,
            bars=bars,
        )

    # Phase D: confluence shadow enrichment (no-op when disabled).
    if is_confluence_score_enabled():
        enrichment["confluence_v2"] = _confluence_light_for_event(
            ob_light=enrichment.get("ob_context_light"),
            fvg_light=enrichment.get("fvg_lifecycle_light"),
            sweep_light=enrichment.get("liquidity_sweeps"),
        )

    # Route to v2 scoring function when SIGNAL_QUALITY_MODEL flag is set.
    _model = signal_quality_model()
    if _model in (_SQ_MODEL_V2, _SQ_MODEL_V21):
        signal_quality = build_signal_quality_v2(enrichment=enrichment)
    else:
        signal_quality = build_signal_quality(enrichment=enrichment)
    raw_score = float(signal_quality.get(_SQ_RAW_SCORE_NAME, 0.0) or 0.0)
    return round(max(0.0, min(100.0, raw_score)), 4)


def _directional_probability(expected_direction: str, *, bias_direction: str, bias_confidence: float) -> float:
    normalized_bias = str(bias_direction).upper()
    normalized_expected = _normalize_direction(expected_direction)
    confidence = max(float(bias_confidence), 0.0)
    if normalized_expected == "NEUTRAL" or normalized_bias == "NEUTRAL":
        return 0.5
    adjustment = min(0.15, 0.15 * max(confidence, 0.5))
    if normalized_bias == normalized_expected:
        return round(min(0.95, 0.5 + adjustment), 4)
    return round(max(0.05, 0.5 - adjustment), 4)


def _sweep_probability(side: str, *, bias_direction: str, bias_confidence: float) -> float:
    expected_direction = _expected_reversal_direction(side)
    return _directional_probability(expected_direction, bias_direction=bias_direction, bias_confidence=bias_confidence)


def _future_price_lists(bars: pd.DataFrame, *, anchor_idx: int, lookahead_bars: int) -> tuple[list[float], list[float], list[float]]:
    future = bars.iloc[anchor_idx + 1 : anchor_idx + 1 + lookahead_bars].reset_index(drop=True)
    highs = [float(value) for value in pd.to_numeric(future.get("high", []), errors="coerce").dropna().tolist()]
    lows = [float(value) for value in pd.to_numeric(future.get("low", []), errors="coerce").dropna().tolist()]
    closes = [float(value) for value in pd.to_numeric(future.get("close", []), errors="coerce").dropna().tolist()]
    return highs, lows, closes


def _score_bos_event(
    event: dict[str, Any],
    bars: pd.DataFrame,
    *,
    bias_direction: str,
    bias_confidence: float,
    event_context: dict[str, str],
    raw_score: float | None = None,
    raw_score_name: str | None = None,
) -> ScoredEvent | None:
    price = float(event.get("price", 0.0) or 0.0)
    anchor_ts = float(event.get("time", event.get("anchor_ts", 0.0)) or 0.0)
    direction = str(event.get("dir", "UP")).upper()
    if price <= 0 or anchor_ts <= 0:
        return None

    anchor_idx = _find_bar_index(bars, anchor_ts)
    if anchor_idx is None or anchor_idx >= len(bars) - 1:
        return None

    highs, lows, _ = _future_price_lists(bars, anchor_idx=anchor_idx, lookahead_bars=_BOS_LOOKAHEAD_BARS)
    if not highs and not lows:
        return None

    return ScoredEvent(
        event_id=str(event.get("id", "")).strip(),
        family="BOS",
        predicted_prob=_directional_probability(direction, bias_direction=bias_direction, bias_confidence=bias_confidence),
        outcome=label_bos_follow_through(
            price,
            direction,
            highs,
            lows,
            threshold_pct=_BOS_FOLLOW_THROUGH_THRESHOLD_PCT,
        ),
        timestamp=float(anchor_ts),
        context=dict(event_context),
        raw_score=raw_score,
        raw_score_name=raw_score_name,
    )


def _atr_at(bars: pd.DataFrame, anchor_idx: int, period: int = 14) -> float | None:
    """ATR at ``anchor_idx`` from the prior ``period`` bars (Wilder-style mean).

    Returns ``None`` when fewer than ``period`` prior bars exist or the
    series is degenerate. Pure-pandas, no extra dependency.
    """
    if anchor_idx < period:
        return None
    window = bars.iloc[anchor_idx - period : anchor_idx]
    if len(window) < period:
        return None
    high = pd.to_numeric(window.get("high"), errors="coerce")
    low = pd.to_numeric(window.get("low"), errors="coerce")
    close = pd.to_numeric(window.get("close"), errors="coerce")
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    tr = tr.dropna()
    if tr.empty:
        return None
    atr = float(tr.mean())
    if not math.isfinite(atr) or atr <= 0:
        return None
    return atr


def _fvg_hurst_50(bars: pd.DataFrame, anchor_idx: int) -> float | None:
    """Rolling-50-bar Hurst (R/S) on the closes leading up to ``anchor_idx``.

    Delegates to :func:`smc_core.fvg_quality.rolling_hurst` so the same
    estimator is used for scoring and for the per-event ledger.
    """
    from smc_core.fvg_quality import rolling_hurst

    if anchor_idx < 50:
        return None
    closes_series = pd.to_numeric(
        bars["close"].iloc[anchor_idx - 50 : anchor_idx], errors="coerce"
    ).dropna()
    if len(closes_series) < 16:
        return None
    return rolling_hurst([float(c) for c in closes_series.tolist()])


def _fvg_quality_features(
    *,
    event: dict[str, Any],
    bars: pd.DataFrame,
    anchor_idx: int,
    low: float,
    high: float,
    direction: str,
    event_context: dict[str, str],
    bias_direction: str,
) -> dict[str, Any]:
    """Return the five A1.B FVG quality features for a single event.

    Output keys exactly match :data:`scripts.fvg_quality_recalibration.FEATURE_KEYS`
    so the recalibration script picks them up via ``record["features"]``
    without a translation step:

    - ``gap_size_atr`` (float ≥ 0)
    - ``htf_aligned`` (bool)
    - ``distance_to_price_atr`` (float ≥ 0)
    - ``is_full_body`` (bool)
    - ``hurst_50`` (float in [0, 1] or omitted on insufficient data)

    Missing ATR or Hurst is omitted (rather than zero-filled) so the
    recalibration script's ``insufficient_features`` fallback can detect
    the gap correctly.
    """
    features: dict[str, Any] = {}
    atr = _atr_at(bars, anchor_idx)
    if atr is not None:
        gap = max(high - low, 0.0)
        features["gap_size_atr"] = round(gap / atr, 4)
        # Distance from the anchor candle's close to the zone midpoint.
        anchor_close = float(
            pd.to_numeric(bars["close"].iloc[anchor_idx], errors="coerce")
        )
        if math.isfinite(anchor_close):
            mid = (high + low) / 2.0
            features["distance_to_price_atr"] = round(abs(anchor_close - mid) / atr, 4)

    bias_norm = (bias_direction or "").upper()
    fvg_dir = direction.upper()
    bullish_dir = fvg_dir in {"UP", "BULL", "BULLISH"}
    bearish_dir = fvg_dir in {"DOWN", "BEAR", "BEARISH"}
    bullish_bias = bias_norm in {"UP", "BULL", "BULLISH"}
    bearish_bias = bias_norm in {"DOWN", "BEAR", "BEARISH"}
    features["htf_aligned"] = bool(
        (bullish_dir and bullish_bias) or (bearish_dir and bearish_bias)
    )

    # Anchor-candle full-body if |close - open| >= 0.7 * (high - low).
    try:
        open_ = float(pd.to_numeric(bars["open"].iloc[anchor_idx], errors="coerce"))
        close_ = float(pd.to_numeric(bars["close"].iloc[anchor_idx], errors="coerce"))
        bar_high = float(pd.to_numeric(bars["high"].iloc[anchor_idx], errors="coerce"))
        bar_low = float(pd.to_numeric(bars["low"].iloc[anchor_idx], errors="coerce"))
        # Zero-range bar (doji at low liquidity) cannot be "full body".
        # The previous ``max(rng, 1e-9)`` floor inflated body/range to ~1e9,
        # silently labelling every doji as full-body.
        rng = bar_high - bar_low
        features["is_full_body"] = bool(rng > 0 and abs(close_ - open_) / rng >= 0.7)
    except (KeyError, ValueError, TypeError):
        features["is_full_body"] = False

    hurst = _fvg_hurst_50(bars, anchor_idx)
    if hurst is not None:
        features["hurst_50"] = round(hurst, 4)
    return features


def _score_zone_event(
    event: dict[str, Any],
    bars: pd.DataFrame,
    *,
    family: EventFamily,
    bias_direction: str,
    bias_confidence: float,
    event_context: dict[str, str],
    raw_score: float | None = None,
    raw_score_name: str | None = None,
) -> ScoredEvent | None:
    low = float(event.get("low", 0.0) or 0.0)
    high = float(event.get("high", 0.0) or 0.0)
    anchor_ts = float(event.get("anchor_ts", event.get("time", 0.0)) or 0.0)
    direction = str(event.get("dir", "BULL")).upper()
    if low <= 0 or high <= 0 or anchor_ts <= 0 or high < low:
        return None

    anchor_idx = _find_bar_index(bars, anchor_ts)
    if anchor_idx is None or anchor_idx >= len(bars) - 1:
        return None

    lookahead = _FVG_LOOKAHEAD_BARS if family == "FVG" else _ZONE_LOOKAHEAD_BARS
    highs, lows, closes = _future_price_lists(bars, anchor_idx=anchor_idx, lookahead_bars=lookahead)
    if not highs and not lows and not closes:
        return None

    label_fn = label_orderblock_mitigation if family == "OB" else label_fvg_mitigation
    features: dict[str, Any] = {}
    if family == "FVG":
        features = _fvg_quality_features(
            event=event,
            bars=bars,
            anchor_idx=anchor_idx,
            low=low,
            high=high,
            direction=direction,
            event_context=event_context,
            bias_direction=bias_direction,
        )
        # Q3 D1 follow-up: emit the strict partial-50 label alongside the
        # lenient any-touch outcome so the next benchmark snapshot has a
        # clean A/B for FVG_LABEL_AUDIT_Q3 (see docs/STRATEGY_2026_Q3.md
        # §2.D1). Kept inside ``features`` to stay schema-compatible.
        features["label_partial_50"] = bool(
            label_fvg_partial_50(low, high, direction, highs, lows, closes)
        )
    return ScoredEvent(
        event_id=str(event.get("id", "")).strip(),
        family=family,
        predicted_prob=_directional_probability(direction, bias_direction=bias_direction, bias_confidence=bias_confidence),
        outcome=label_fn(low, high, direction, highs, lows, closes),
        timestamp=float(anchor_ts),
        context=dict(event_context),
        raw_score=raw_score,
        raw_score_name=raw_score_name,
        features=features,
    )


def _evaluate_sweep_event(
    event: dict[str, Any],
    bars: pd.DataFrame,
    *,
    bias_direction: str,
    bias_confidence: float,
    event_context: dict[str, str],
    raw_score: float | None = None,
    raw_score_name: str | None = None,
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
        context=dict(event_context),
        raw_score=raw_score,
        raw_score_name=raw_score_name,
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
    # #2667: surface contract-level warnings (e.g. ``legacy_tf_fallback``
    # from the cross-TF aliasing guard) in the measurement-evidence warning
    # stream so the benchmark runner (and its --strict-structure-tf flag)
    # can detect pairs that were served another timeframe's structure.
    contract_warnings = [str(item).strip() for item in (contract.get("warnings") or []) if str(item).strip()]
    warnings.extend(contract_warnings)
    details["canonical_event_counts"] = _canonical_event_counts(contract)
    event_risk_light, event_risk_details = _resolve_measurement_event_risk_light(symbol, timeframe)
    details.update(event_risk_details)

    raw_bars, bars_source_mode = _load_source_bars(symbol, timeframe, resolved_inputs)
    details["bars_source_mode"] = bars_source_mode
    details["raw_bar_rows"] = len(raw_bars)
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
    details["resampled_bar_rows"] = len(resampled_bars)

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
    # Disclose which inputs actually fed the merged bias (htf+session vs.
    # single-source vs. none) — mirrors vol_regime_model_source (audit #2670 W6).
    details["bias_source"] = bias_verdict.source
    details["vol_regime"] = vol_regime.label
    details["vol_regime_confidence"] = vol_regime.confidence
    details["vol_regime_model_source"] = vol_regime.model_source
    details["vol_regime_fallback_reason"] = vol_regime.fallback_reason
    details["vol_regime_forecast_volatility"] = vol_regime.forecast_volatility
    details["vol_regime_baseline_volatility"] = vol_regime.baseline_volatility
    details["vol_regime_forecast_ratio"] = vol_regime.forecast_ratio
    details["measurement_evidence_present"] = True
    skipped_counts = {family: 0 for family in _FAMILIES}

    for event in effective_structure["bos"]:
        evaluated = _evaluate_bos_event(event, resampled_bars)
        if evaluated is None:
            skipped_counts["BOS"] += 1
            continue
        events_by_family["BOS"].append(evaluated)
        anchor_ts = float(event.get("time", event.get("anchor_ts", 0.0)) or 0.0)
        anchor_idx = _find_bar_index(resampled_bars, anchor_ts)
        event_context = _scored_event_context(
            anchor_ts,
            timeframe,
            bias_direction=bias_verdict.direction,
            vol_regime_label=vol_regime.label,
        )
        raw_score = (
            _event_signal_quality_score(
                event=event,
                family="BOS",
                bars=resampled_bars,
                anchor_idx=anchor_idx,
                anchor_ts=anchor_ts,
                bias_direction=bias_verdict.direction,
                vol_regime_label=vol_regime.label,
                event_risk_light=event_risk_light,
                orderblocks=effective_structure["orderblocks"],
                fvgs=effective_structure["fvg"],
                sweeps=effective_structure["liquidity_sweeps"],
                orderblock_diagnostics=orderblock_diagnostics,
                fvg_diagnostics=fvg_diagnostics,
            )
            if anchor_idx is not None
            else None
        )
        scored_event = _score_bos_event(
            event,
            resampled_bars,
            bias_direction=bias_verdict.direction,
            bias_confidence=bias_verdict.confidence,
            event_context=event_context,
            raw_score=raw_score,
            raw_score_name=_SQ_RAW_SCORE_NAME if raw_score is not None else None,
        )
        if scored_event is not None:
            scored_events.append(scored_event)
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
        anchor_idx = _find_bar_index(resampled_bars, anchor_ts)
        event_context = _scored_event_context(
            anchor_ts,
            timeframe,
            bias_direction=bias_verdict.direction,
            vol_regime_label=vol_regime.label,
        )
        raw_score = (
            _event_signal_quality_score(
                event=event,
                family="OB",
                bars=resampled_bars,
                anchor_idx=anchor_idx,
                anchor_ts=anchor_ts,
                bias_direction=bias_verdict.direction,
                vol_regime_label=vol_regime.label,
                event_risk_light=event_risk_light,
                orderblocks=effective_structure["orderblocks"],
                fvgs=effective_structure["fvg"],
                sweeps=effective_structure["liquidity_sweeps"],
                orderblock_diagnostics=orderblock_diagnostics,
                fvg_diagnostics=fvg_diagnostics,
            )
            if anchor_idx is not None
            else None
        )
        scored_event = _score_zone_event(
            event,
            resampled_bars,
            family="OB",
            bias_direction=bias_verdict.direction,
            bias_confidence=bias_verdict.confidence,
            event_context=event_context,
            raw_score=raw_score,
            raw_score_name=_SQ_RAW_SCORE_NAME if raw_score is not None else None,
        )
        if scored_event is not None:
            scored_events.append(scored_event)
        _append_stratified_event(stratified_events, _event_session_key(anchor_ts, timeframe), "OB", evaluated)
        _append_stratified_event(stratified_events, f"htf_bias:{bias_verdict.direction}", "OB", evaluated)
        _append_stratified_event(stratified_events, f"vol_regime:{vol_regime.label}", "OB", evaluated)

    for event in effective_structure["fvg"]:
        evaluated = _evaluate_zone_event(
            event,
            resampled_bars,
            diagnostics_by_id=fvg_diagnostics,
            emit_partial_50=True,
        )
        if evaluated is None:
            skipped_counts["FVG"] += 1
            continue
        events_by_family["FVG"].append(evaluated)
        anchor_ts = float(event.get("anchor_ts", event.get("time", 0.0)) or 0.0)
        anchor_idx = _find_bar_index(resampled_bars, anchor_ts)
        event_context = _scored_event_context(
            anchor_ts,
            timeframe,
            bias_direction=bias_verdict.direction,
            vol_regime_label=vol_regime.label,
        )
        raw_score = (
            _event_signal_quality_score(
                event=event,
                family="FVG",
                bars=resampled_bars,
                anchor_idx=anchor_idx,
                anchor_ts=anchor_ts,
                bias_direction=bias_verdict.direction,
                vol_regime_label=vol_regime.label,
                event_risk_light=event_risk_light,
                orderblocks=effective_structure["orderblocks"],
                fvgs=effective_structure["fvg"],
                sweeps=effective_structure["liquidity_sweeps"],
                orderblock_diagnostics=orderblock_diagnostics,
                fvg_diagnostics=fvg_diagnostics,
            )
            if anchor_idx is not None
            else None
        )
        scored_event = _score_zone_event(
            event,
            resampled_bars,
            family="FVG",
            bias_direction=bias_verdict.direction,
            bias_confidence=bias_verdict.confidence,
            event_context=event_context,
            raw_score=raw_score,
            raw_score_name=_SQ_RAW_SCORE_NAME if raw_score is not None else None,
        )
        if scored_event is not None:
            scored_events.append(scored_event)
        _append_stratified_event(stratified_events, _event_session_key(anchor_ts, timeframe), "FVG", evaluated)
        _append_stratified_event(stratified_events, f"htf_bias:{bias_verdict.direction}", "FVG", evaluated)
        _append_stratified_event(stratified_events, f"vol_regime:{vol_regime.label}", "FVG", evaluated)

    for event in effective_structure["liquidity_sweeps"]:
        anchor_ts = float(event.get("time", event.get("anchor_ts", 0.0)) or 0.0)
        anchor_idx = _find_bar_index(resampled_bars, anchor_ts)
        event_context = _scored_event_context(
            anchor_ts,
            timeframe,
            bias_direction=bias_verdict.direction,
            vol_regime_label=vol_regime.label,
        )
        raw_score = (
            _event_signal_quality_score(
                event=event,
                family="SWEEP",
                bars=resampled_bars,
                anchor_idx=anchor_idx,
                anchor_ts=anchor_ts,
                bias_direction=bias_verdict.direction,
                vol_regime_label=vol_regime.label,
                event_risk_light=event_risk_light,
                orderblocks=effective_structure["orderblocks"],
                fvgs=effective_structure["fvg"],
                sweeps=effective_structure["liquidity_sweeps"],
                orderblock_diagnostics=orderblock_diagnostics,
                fvg_diagnostics=fvg_diagnostics,
            )
            if anchor_idx is not None
            else None
        )
        sweep_evidence = _evaluate_sweep_event(
            event,
            resampled_bars,
            bias_direction=bias_verdict.direction,
            bias_confidence=bias_verdict.confidence,
            event_context=event_context,
            raw_score=raw_score,
            raw_score_name=_SQ_RAW_SCORE_NAME if raw_score is not None else None,
        )
        if sweep_evidence is None:
            skipped_counts["SWEEP"] += 1
            continue
        benchmark_event, scored_event = sweep_evidence
        events_by_family["SWEEP"].append(benchmark_event)
        scored_events.append(scored_event)
        _append_stratified_event(stratified_events, _event_session_key(anchor_ts, timeframe), "SWEEP", benchmark_event)
        _append_stratified_event(stratified_events, f"htf_bias:{bias_verdict.direction}", "SWEEP", benchmark_event)
        _append_stratified_event(stratified_events, f"vol_regime:{vol_regime.label}", "SWEEP", benchmark_event)

    details["evaluated_event_counts"] = {family: len(events_by_family[family]) for family in _FAMILIES}
    details["skipped_event_counts"] = skipped_counts
    details["scoring_event_count"] = len(scored_events)
    details["scoring_event_counts_by_family"] = {
        family: sum(1 for event in scored_events if event.family == family)
        for family in _FAMILIES
    }
    details["signal_quality_raw_score_name"] = _SQ_RAW_SCORE_NAME if scored_events else None
    details["signal_quality_raw_score_count"] = sum(1 for event in scored_events if event.raw_score is not None)
    details["signal_quality_raw_score_complete"] = bool(scored_events) and all(
        event.raw_score is not None and event.raw_score_name == _SQ_RAW_SCORE_NAME
        for event in scored_events
    )
    scoring_result = score_events(scored_events)
    ensemble_generated_at = None
    if not resampled_bars.empty:
        try:
            ensemble_generated_at = float(resampled_bars["timestamp"].iloc[-1])
        except (TypeError, ValueError):
            ensemble_generated_at = None
    ensemble_quality = build_ensemble_quality(
        generated_at=ensemble_generated_at,
        bias_direction=bias_verdict.direction,
        bias_confidence=bias_verdict.confidence,
        vol_regime_label=vol_regime.label,
        vol_regime_confidence=vol_regime.confidence,
        scoring_result=scoring_result,
    )
    details["ensemble_quality"] = serialize_ensemble_quality(ensemble_quality)
    details["stratification_keys"] = sorted(stratified_events.keys())
    details["warnings"] = list(warnings)

    # ADR-0023 §4.1: produce FamilyEvent records for the magnitude-shadow
    # workflow.  This re-uses the same effective_structure + resampled_bars
    # that the scoring loop above consumed, so no extra detection cost.
    try:
        family_events = _family_events_from_structure(
            effective_structure,
            resampled_bars.to_dict("records"),
        )
    except Exception as exc:
        logger.warning("family_events_from_structure failed: %s", exc)
        family_events = []

    return MeasurementEvidence(events_by_family, stratified_events, scored_events, details, warnings, family_events)

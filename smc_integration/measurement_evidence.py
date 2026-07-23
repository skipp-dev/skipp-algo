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
from skipp_config import get_trading_thresholds
from smc_core.benchmark import EventFamily
from smc_core.bias_merge import merge_bias
from smc_core.cached_workbook_reader import read_daily_bars
from smc_core.ensemble_quality import build_ensemble_quality, serialize_ensemble_quality
from smc_core.event_freshness import classify_freshness  # Phase A
from smc_core.htf_context import build_htf_bias_context
from smc_core.label_horizons import LABEL_HORIZON_BARS
from smc_core.reaction_zone import compute_reaction_zone  # Phase C
from smc_core.scoring import (
    ScoredEvent,
    compute_fvg_partial_fill,
    label_bos_follow_through,
    label_fvg_mitigation,
    label_fvg_partial_50,
    label_orderblock_mitigation,
    label_sweep_reversal,
    normalize_sweep_side,
    score_events,
)
from smc_core.session_context import build_session_liquidity_context
from smc_core.sweep_trap import classify_sweep_trap  # Phase B
from smc_core.vol_regime import compute_vol_regime
from smc_integration.artifact_resolution import resolve_structure_artifact_inputs
from smc_integration.repo_sources import load_raw_meta_input_composite
from smc_integration.sources import structure_artifact_json
from smc_integration.timeframes import is_daily_timeframe

logger = logging.getLogger(__name__)


_FAMILIES: tuple[EventFamily, ...] = ("BOS", "OB", "FVG", "SWEEP")
# Label-resolution horizons come from the shared SSOT so governance walk-forward
# purge/embargo (governance.family_walkforward) cannot drift below these windows.
_BOS_LOOKAHEAD_BARS = LABEL_HORIZON_BARS["BOS"]
_ZONE_LOOKAHEAD_BARS = LABEL_HORIZON_BARS["OB"]
_FVG_LOOKAHEAD_BARS = LABEL_HORIZON_BARS["FVG"]
_SWEEP_LOOKAHEAD_BARS = LABEL_HORIZON_BARS["SWEEP"]
# Point-in-time context inputs (bias/vol-regime GARCH) are computed on at most
# this many trailing bars. Enough for ATR(14)/GARCH(1,1) stability and the
# session/HTF context; unbounded slices made full-session frames unaffordable
# (frame-fix follow-up 2026-07-13).
_PIT_CONTEXT_MAX_BARS = 512
# Reaction-zone shadow study: reaction confirmation is measured on bars 1..N of the
# sweep lookahead; the follow-through outcome is measured on the DISJOINT later
# window (bars N+1..lookahead) so a confirmation is never part of its own label.
_REACTION_CONFIRM_WINDOW_BARS = 3
_REACTION_SCHEMA_VERSION = 2  # v2: label only emitted with the FULL outcome window observed (edge-censoring fix); v1 rows may carry right-censored labels
# Sweep-trap shadow study schema. v1 = first leakage-free emission (trap features
# confirmed on bars 1..N, paired with the disjoint ``sweep_trap_outcome_late``).
_SWEEP_TRAP_SCHEMA_VERSION = 2  # v2: full-outcome-window guarantee (see _REACTION_SCHEMA_VERSION); evaluators must reject v1 rows
# Bound at import from the skipp_config SSOT, mirroring smc_core.scoring (which
# binds the same two knobs the same way): a SKIPP_TRADING_THRESHOLDS_CONFIG
# override takes effect at process start, not per-call — intended, since both
# label paths must agree on one threshold for a whole run, and any change is an
# era-cut of the shadow/calibration ledgers anyway (see the NOTE below).
_BOS_FOLLOW_THROUGH_THRESHOLD_PCT = get_trading_thresholds().smc_scoring.bos_follow_through_threshold_pct  # SSOT skipp_config (was a 0.003 hardcode shadowing the config knob)
_SWEEP_REVERSAL_THRESHOLD_PCT = get_trading_thresholds().smc_scoring.sweep_reversal_threshold_pct  # SSOT skipp_config; NOTE: overriding it changes labeling semantics -> era-cut shadow/calibration ledgers first
_SQ_LOOKBACK_BARS = 64
_SQ_RAW_SCORE_NAME = "SIGNAL_QUALITY_SCORE"


def _bool_env(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).strip() == "1"


def is_freshness_v2_enabled() -> bool:
    return _bool_env("ENABLE_FRESHNESS_V2_SCORE", "0")


def is_sweep_trap_enabled() -> bool:
    return _bool_env("ENABLE_SWEEP_TRAP", "0")


def is_reaction_zone_enabled() -> bool:  # study gate (compute_reaction_zone)
    return _bool_env("ENABLE_REACTION_ZONE_STUDY", "0")


def is_confluence_score_enabled() -> bool:
    return _bool_env("ENABLE_CONFLUENCE_SCORE", "0")


def signal_quality_model() -> str:
    return m if (m := os.environ.get("SIGNAL_QUALITY_MODEL", "v1").strip().lower()) in ("v1", "v2", "v2.1") else "v1"


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

    # ADR-0023 issue #3872: opt-in long-history override for the DAILY frame.
    # The rolling bundle's daily_bars spans only ~21 trading days — shorter
    # than 1D warmup + label horizons (FVG=20 daily bars), so the bundle-first
    # order below starves the 1D slice structurally. The rolling-bench
    # workflow points this env at the long-history workbook written by
    # scripts/fetch_benchmark_daily_history.py, so 1D detection (structure
    # exporter --workbook) and labeling (these bars) see the SAME long frame.
    # Strictly opt-in: env absent, file missing, or symbol not covered falls
    # through to the unchanged resolution order.
    if daily:
        override_raw = os.environ.get("SMC_DAILY_BARS_WORKBOOK_OVERRIDE", "").strip()
        if override_raw:
            override_path = Path(override_raw)
            override_bars = pd.DataFrame()
            if override_path.exists():
                try:
                    override_frame = read_daily_bars(override_path)
                except Exception as exc:
                    logger.warning(
                        "daily-bars override workbook unreadable for symbol=%s path=%s: %s",
                        symbol_name,
                        override_path,
                        exc,
                    )
                    override_frame = pd.DataFrame()
                if not override_frame.empty:
                    override_frame["symbol"] = (
                        override_frame.get("symbol", "").astype(str).str.strip().str.upper()
                    )
                    filtered = override_frame.loc[override_frame["symbol"].eq(symbol_name)].copy()
                    override_bars = _normalize_numeric_bars(filtered, timestamp_column="trade_date")
            else:
                logger.warning(
                    "daily-bars override set but missing for symbol=%s path=%s; using default resolution",
                    symbol_name,
                    override_path,
                )
            if not override_bars.empty:
                return override_bars.reset_index(drop=True), "workbook_override"

    bundle_load_failed = False
    if export_bundle_root is not None:
        # Frame-integrity audit 2026-07-13: intraday resolution prefers a
        # bundle carrying the genuine full-session 1m frame and falls back to
        # one with the open-window frame — required_frames also selects WHICH
        # manifest wins when several coexist (an older intraday-capable bundle
        # must beat a newer daily-only one).
        if daily:
            required_frame_attempts: tuple[tuple[str, ...], ...] = (("daily_bars",),)
        else:
            required_frame_attempts = (
                ("benchmark_universe_ohlcv_1m",),
                ("full_universe_second_detail_open",),
            )
        bundle = None
        last_exc: Exception | None = None
        for required_frames in required_frame_attempts:
            try:
                bundle = load_export_bundle(
                    export_bundle_root,
                    required_frames=required_frames,
                    manifest_prefix="databento_volatility_production_",
                    only_frames=(
                        # Behaviour-preserving: after the load this module reads
                        # daily_bars OR opportunistically BOTH intraday frames,
                        # regardless of which single frame the attempt required.
                        "daily_bars",
                        "benchmark_universe_ohlcv_1m",
                        "full_universe_second_detail_open",
                    ),
                )
                break
            except FileNotFoundError as exc:
                last_exc = exc
                continue
            except Exception as exc:
                last_exc = exc
                break
        if bundle is None:
            logger.warning(
                "canonical export bundle unavailable for symbol=%s timeframe=%s export_bundle_root=%s: %s",
                symbol_name,
                canonical_tf,
                export_bundle_root,
                last_exc,
            )
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
                # Frame-integrity audit 2026-07-13: prefer the genuine
                # full-session 1m frame (reference universe only); symbols it
                # does not cover fall through to the open-window resample.
                for frame_name in ("benchmark_universe_ohlcv_1m", "full_universe_second_detail_open"):
                    intraday = frames.get(frame_name)
                    if not isinstance(intraday, pd.DataFrame) or intraday.empty:
                        continue
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
    """Index of the bar CONTAINING ``event_ts`` (exact match, else the bar it fell in).

    Event timestamps are normally BAR-ALIGNED (the structure artifact stamps events
    on bar timestamps), so this resolves to the exact event bar and the caller's
    ``anchor_idx + 1`` forward slice starts on the bar strictly after the event. For
    an OFF-GRID ``event_ts`` (imported / rounded / resampled, falling strictly
    between two bars) the event occurred DURING the preceding bar, so we anchor on
    that CONTAINING bar rather than the following one — otherwise the first
    fully-post-event bar is silently consumed as the anchor and dropped from the
    forward window. Fail-closed rejection was deliberately NOT chosen: bars are
    resampled (``build_measurement_evidence``), so near-grid events are legitimate
    and must not be discarded. Returns ``None`` only when ``event_ts`` is after
    every bar (or bars is empty).
    """
    # Hot path (frame-fix follow-up 2026-07-13): with genuine full-session
    # frames this runs ~1.9 MILLION times per pair (context features probe
    # every neighbouring event); the previous Series.astype + boolean-mask
    # pipeline cost ~400s of a 528s pair build. The vectorized numpy scan
    # below is semantics-identical (first index-order bar with ts >= event_ts;
    # exact match wins, else the containing/preceding bar).
    values = bars["timestamp"].to_numpy(dtype="float64", copy=False)
    if values.size == 0:
        return None
    target = float(event_ts)
    mask = values >= target
    if not mask.any():
        return None
    pos = int(mask.argmax())
    if values[pos] == target:
        return int(bars.index[pos])
    # Off-grid: ``event_ts`` fell between the preceding bar and ``pos`` -> anchor
    # on the containing (preceding) bar when one exists.
    if pos > 0:
        logger.debug("event_ts %s is off the bar grid; anchoring on the containing bar", event_ts)
        return int(bars.index[pos - 1])
    return int(bars.index[pos])  # event precedes all bars -> keep first (outer guard drops it)


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
    # Daily bars have no intraday session; use the shared predicate so daily
    # ALIASES ("1d"/"D"/"daily") also short-circuit — an inline ``== "1D"`` would
    # miss them and compute a spurious intraday session block for a daily bar.
    if is_daily_timeframe(timeframe):
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
    # Fail-closed: an unknown/missing BOS direction is rejected, not silently
    # benchmarked as bullish (the old default "UP" + `!= "DOWN"` => bullish branch).
    norm_dir = _normalize_direction(str(event.get("dir", "")))
    if price <= 0 or anchor_ts <= 0 or norm_dir not in {"BULLISH", "BEARISH"}:
        return None
    direction = "DOWN" if norm_dir == "BEARISH" else "UP"

    anchor_idx = _find_bar_index(bars, anchor_ts)
    if anchor_idx is None or anchor_idx >= len(bars) - 1:
        return None

    # KPI horizon = the ScoredEvent BOS label window (was unbounded-to-end, so a
    # touch 100 bars later counted as a KPI hit but a label miss). Cap to align.
    future = bars.iloc[anchor_idx + 1 : anchor_idx + 1 + _BOS_LOOKAHEAD_BARS].reset_index(drop=True)
    if len(future) < _BOS_LOOKAHEAD_BARS:
        return None  # right-censoring guard (mirror of _score_bos_event): truncated window -> skip, not a final miss

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
    lookahead_bars: int = _ZONE_LOOKAHEAD_BARS,
    emit_partial_50: bool = False,
) -> dict[str, Any] | None:
    low = float(event.get("low", 0.0) or 0.0)
    high = float(event.get("high", 0.0) or 0.0)
    anchor_ts = float(event.get("anchor_ts", event.get("time", 0.0)) or 0.0)
    # Fail-closed: an unknown/missing OB/FVG direction is rejected, not silently
    # benchmarked as bullish (the old default "BULL" + non-bear => bullish branch).
    norm_dir = _normalize_direction(str(event.get("dir", "")))
    if low <= 0 or high <= 0 or anchor_ts <= 0 or high <= low or norm_dir not in {"BULLISH", "BEARISH"}:
        return None
    direction = "BEAR" if norm_dir == "BEARISH" else "BULL"

    anchor_idx = _find_bar_index(bars, anchor_ts)
    if anchor_idx is None or anchor_idx >= len(bars) - 1:
        return None

    # KPI horizon = the ScoredEvent zone label window (OB vs FVG), was unbounded.
    future = bars.iloc[anchor_idx + 1 : anchor_idx + 1 + lookahead_bars].reset_index(drop=True)
    if len(future) < lookahead_bars:
        return None  # right-censoring guard (mirror of _score_zone_event): truncated window -> skip, not a final miss

    event_id = str(event.get("id", "")).strip()
    diag = diagnostics_by_id.get(event_id, {})
    mitigated_idx: int | None = None
    mitigated_ts = diag.get("mitigated_ts")
    if diag.get("mitigated") and mitigated_ts is not None:
        absolute_idx = _find_bar_index(bars, float(mitigated_ts))
        if absolute_idx is not None and absolute_idx > anchor_idx:
            mitigated_idx = absolute_idx - anchor_idx - 1
    # A diagnostic mitigation beyond the evaluation window is not a hit within
    # the label horizon (mirrors the capped touch/invalidation below).
    if mitigated_idx is not None and mitigated_idx >= len(future):
        mitigated_idx = None

    # Truth-audit E9 (2026-07-11): mitigation = PENETRATION of the zone, not
    # band-membership of the bar extreme. The old ``low <= row_high <= high``
    # missed a bar that wicked entirely THROUGH the zone (fully filled it),
    # keeping this KPI blind to the same full-fill events that the scoring
    # labels (fixed in #3387) already count. This mirror was not covered by
    # #3387; align it here (bullish: row_low <= high; bearish: row_high >= low).
    if direction in {"BEAR", "BEARISH", "DOWN"}:
        if mitigated_idx is None:
            mitigated_idx = _find_first_index(future, lambda row: float(row["high"]) >= low)
        invalid_idx = _find_first_index(future, lambda row: float(row["close"]) > high)
    else:
        if mitigated_idx is None:
            mitigated_idx = _find_first_index(future, lambda row: float(row["low"]) <= high)
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
    # Shared fail-closed SSOT (SELL_SIDE→BULLISH, BUY_SIDE→BEARISH, else NEUTRAL);
    # an unknown/missing side no longer resolves to a silent bearish default here
    # while defaulting bullish in _expected_event_direction below.
    return normalize_sweep_side(side)


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
        # Fail-closed: a missing side is NEUTRAL, not a silent bullish SELL_SIDE.
        return _expected_reversal_direction(str(event.get("side", "")))
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



def _ob_support_score(*, ob_fresh: bool, ob_distance: float, mitigation_state: str) -> float:
    """Orthogonal order-block support score for the confluence detector (0-15)."""
    if mitigation_state == "mitigated":
        return 0.0
    if ob_fresh and ob_distance < 2.0:
        return 15.0
    if ob_distance < 3.0:
        return 9.0
    if ob_distance < 5.0:
        return 4.5
    return 0.0


def _fvg_gap_score(*, fvg_fresh: bool, fvg_invalidated: bool, fvg_fill_pct: float, fvg_distance: float) -> float:
    """Orthogonal fair-value gap score for the confluence detector (0-15)."""
    if fvg_invalidated or fvg_fill_pct >= 1.0:
        return 0.0
    if fvg_fresh and fvg_distance < 2.0:
        return 15.0
    if fvg_distance < 3.0:
        return 7.5
    if fvg_distance < 5.0:
        return 3.0
    return 0.0


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
    # The BOS family carries both BOS and CHOCH events; preserve the distinction —
    # downstream sweep-trap / reaction-zone / confluence logic branches on BOS_*
    # vs CHOCH_*. Only a known kind flips the light; an unknown kind is NOT silently
    # written as BOS (fail-closed → falls through to the default structure state).
    event_kind = str(event.get("kind", "BOS")).strip().upper()
    if (
        family == "BOS"
        and expected_direction in {"BULLISH", "BEARISH"}
        and event_kind in {"BOS", "CHOCH"}
    ):
        is_bullish = expected_direction == "BULLISH"
        is_choch = event_kind == "CHOCH"
        structure_state["STRUCTURE_STATE"] = expected_direction
        structure_state["STRUCTURE_BULL_ACTIVE"] = is_bullish
        structure_state["STRUCTURE_BEAR_ACTIVE"] = not is_bullish
        structure_state["BOS_BULL"] = (not is_choch) and is_bullish
        structure_state["BOS_BEAR"] = (not is_choch) and (not is_bullish)
        structure_state["CHOCH_BULL"] = is_choch and is_bullish
        structure_state["CHOCH_BEAR"] = is_choch and (not is_bullish)
        prefix = "CHOCH" if is_choch else "BOS"
        structure_state["STRUCTURE_LAST_EVENT"] = f"{prefix}_BULL" if is_bullish else f"{prefix}_BEAR"
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
            "OB_SUPPORT_SCORE": 0.0,
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
        ob_fresh = age_bars <= 10 and not mitigated
        mitigation_state = _mitigation_state(age_bars=age_bars, mitigated=mitigated)
        payload = {
            "PRIMARY_OB_SIDE": side,
            "PRIMARY_OB_DISTANCE": round(distance, 4),
            "OB_FRESH": ob_fresh,
            "OB_AGE_BARS": age_bars,
            "OB_MITIGATION_STATE": mitigation_state,
            "OB_SUPPORT_SCORE": round(_ob_support_score(
                ob_fresh=ob_fresh,
                ob_distance=distance,
                mitigation_state=mitigation_state,
            ), 2),
        }
        if best is None or priority < best[0]:
            best = (priority, payload)

    return best[1] if best is not None else {
        "PRIMARY_OB_SIDE": "NONE",
        "PRIMARY_OB_DISTANCE": 0.0,
        "OB_FRESH": False,
        "OB_AGE_BARS": 0,
        "OB_MITIGATION_STATE": "stale",
        "OB_SUPPORT_SCORE": 0.0,
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
            "FVG_GAP_SCORE": 0.0,
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
            "FVG_GAP_SCORE": round(_fvg_gap_score(
                fvg_fresh=not invalidated,
                fvg_invalidated=invalidated,
                fvg_fill_pct=fill_pct,
                fvg_distance=distance,
            ), 2),
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
        "FVG_GAP_SCORE": 0.0,
    }


#: Lookback (bars) used to locate the pre-sweep leg origin for the sweep-trap
#: fib_retrace_depth. See ``_derive_sweep_trap_geometry``.
_SWEEP_ORIGIN_LOOKBACK_BARS = 20


def _derive_sweep_trap_geometry(
    candidate: dict[str, Any],
    bars: pd.DataFrame,
    candidate_idx: int | None,
    *,
    is_bullish_sweep: bool,
) -> tuple[float, float, float]:
    """Derive ``(swept_level, sweep_extreme, origin_level)`` for a sweep event.

    The lean sweep producers only carry ``price``/``side``; ``classify_sweep_trap``
    needs the swept level, the sweep candle's extreme, and the pre-sweep leg
    origin. We compute them here — the single choke point where the sweep event
    and the bar frame are both available — rather than at each of the several
    sweep producers (profile engine, legacy high/low, liquidity engine). A
    producer-provided value wins if present, for forward-compat.

    - ``swept_level``  = the level taken (the event ``price``).
    - ``sweep_extreme``= the sweep bar's low (bullish/``SELL_SIDE``) or high (bearish).
    - ``origin_level`` = the opposite extreme of the leg into the sweep — the max
      high (bullish) / min low (bearish) over the lookback up to the sweep bar,
      i.e. where the move that swept the level originated. Falls back to
      ``swept_level`` (⇒ fib depth 0) when the leg is degenerate.
    """
    swept_level = float(candidate.get("price", 0.0) or 0.0)
    swept_level = float(candidate.get("swept_level", swept_level) or swept_level)

    if candidate_idx is None or candidate_idx < 0 or candidate_idx >= len(bars):
        return (
            swept_level,
            float(candidate.get("sweep_extreme", 0.0) or 0.0),
            float(candidate.get("origin_level", swept_level) or swept_level),
        )

    sweep_bar = bars.iloc[candidate_idx]
    derived_extreme = float(sweep_bar["low"] if is_bullish_sweep else sweep_bar["high"])
    sweep_extreme = float(candidate.get("sweep_extreme", derived_extreme) or derived_extreme)

    leg = bars.iloc[max(0, candidate_idx - _SWEEP_ORIGIN_LOOKBACK_BARS) : candidate_idx + 1]
    if is_bullish_sweep:
        derived_origin = float(pd.to_numeric(leg["high"], errors="coerce").max())
    else:
        derived_origin = float(pd.to_numeric(leg["low"], errors="coerce").min())
    if not math.isfinite(derived_origin):
        derived_origin = swept_level
    origin_level = float(candidate.get("origin_level", derived_origin) or derived_origin)

    return swept_level, sweep_extreme, origin_level


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
        # No SELL_SIDE default: a missing side is ambiguous and must fall through
        # to the `else: continue` skip below, not be treated as a bullish sweep.
        side = str(candidate.get("side", "")).strip().upper()
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

        # Phase B/C — Sweep Trap Classifier + Reaction Zone (shadow enrichment,
        # default OFF). Both consume the SAME derived sweep geometry, but each is
        # now INDEPENDENTLY gated: the reaction-zone study runs on its own flag and
        # no longer requires sweep-trap to be enabled (2026-07-13 — it was
        # previously nested inside the Phase B block, so the study flag alone was a
        # silent no-op on this path). Mirrors the _evaluate_sweep_event OR-gate.
        run_sweep_trap = is_sweep_trap_enabled()
        run_reaction = is_reaction_zone_enabled()
        if run_sweep_trap or run_reaction:
            try:
                swept_level, sweep_extreme, origin_level = _derive_sweep_trap_geometry(
                    candidate, bars, candidate_idx, is_bullish_sweep=bull_sweep
                )
                # The anchor bar is a COMPLETED bar in this offline path — its close is
                # the current reference price (_anchor_reference_price) and it is included
                # in the lookback (_history_window), so include it in the post-sweep window
                # too: end = anchor_idx + 1. Otherwise a reclaim ON the anchor bar is missed
                # until the next anchor. The candidate_idx + 14 cap still bounds the window
                # to <= 13 post-sweep bars (enough to separate reclaims on bars 1..12 from
                # "later than 12"), so including the anchor never widens it past that.
                look_ahead_end = min(anchor_idx + 1, candidate_idx + 14) if candidate_idx is not None else anchor_idx + 1
                post_bars_df = bars.iloc[candidate_idx + 1 : look_ahead_end] if candidate_idx is not None else bars.iloc[0:0]
                post_sweep_bars = [
                    {"open": float(r["open"]), "high": float(r["high"]),
                     "low": float(r["low"]), "close": float(r["close"])}
                    for _, r in post_bars_df.iterrows()
                ]
                if swept_level > 0:
                    if run_sweep_trap:
                        trap = classify_sweep_trap(
                            swept_level=swept_level,
                            sweep_extreme=sweep_extreme,
                            origin_level=origin_level,
                            is_bullish_sweep=bull_sweep,
                            post_sweep_bars=post_sweep_bars,
                        )
                        # NAME COLLISION, DIFFERENT WINDOWS: these UPPERCASE enrichment
                        # fields classify on the up-to-13-bar anchor window above and CAN
                        # yield trap_type="delayed"; the lowercase ledger features
                        # (sweep_trap_* in _evaluate_sweep_event) classify on the 3-bar
                        # confirm window (#3509) where "delayed" is UNREACHABLE. Do not
                        # compare or join them by name alone (a *_ANCHOR_WINDOW alias
                        # rename is pending; no silent rename — Pine/enrichment consumers).
                        payload["SWEEP_TRAP_TYPE"] = trap.trap_type
                        payload["SWEEP_RECLAIM_BARS"] = trap.sweep_reclaim_bars
                        payload["SWEEP_RECLAIM_STRENGTH"] = trap.reclaim_strength
                        payload["SWEEP_FIB_RETRACE"] = trap.fib_retrace_depth
                        payload["SWEEP_TRAP_QUALITY_SCORE"] = trap.trap_quality_score
                        payload["SWEEP_TRAP_STATUS"] = "ok"

                    # Phase C — Reaction Zone. Independently gated: it reuses the
                    # geometry above but does NOT require sweep-trap to be on.
                    if run_reaction:
                        zone = compute_reaction_zone(
                            swept_level=swept_level,
                            sweep_extreme=sweep_extreme,
                            is_bullish_sweep=bull_sweep,
                            post_sweep_bars=post_sweep_bars,
                        )
                        payload["REACTION_BAND_LOW"] = zone.rejection_band_low
                        payload["REACTION_BAND_HIGH"] = zone.rejection_band_high
                        payload["REACTION_IN_REJECTION_BAND"] = zone.close_in_rejection_band
                        payload["REACTION_BARS_TO_REJECTION_BAND"] = zone.bars_to_rejection_band
                        payload["REACTION_LEVEL_RECLAIMED"] = zone.level_reclaimed
                        payload["REACTION_BARS_TO_RECLAIM"] = zone.bars_to_reclaim
                        payload["REACTION_CLOSE_DISTANCE_PCT"] = zone.close_distance_pct
                        payload["REACTION_BODY_RATIO"] = zone.body_ratio
                        payload["REACTION_DIRECTIONAL_BODY"] = zone.directional_body
                        payload["REACTION_WICK_RATIO"] = zone.rejection_wick_ratio
                        payload["REACTION_STATUS"] = "ok"
                        # Phase C is OBSERVE-ONLY: the raw fields above are recorded
                        # for the follow-through study; NO discount is applied to any
                        # score. (The prior 0.5 discount keyed on an inverted "close
                        # back inside zone" confirmation and is removed here.)
            except Exception as exc:  # Phase B/C is additive; failure must not break v1 scoring.
                # Emit an explicit per-event error status + code so a failed
                # enrichment is distinguishable from "flag off" / "no geometry" /
                # "not applicable" (all of which leave the fields simply absent).
                # Downstream shadow-eval can now count SWEEP_TRAP_STATUS=="error"
                # instead of silently shrinking the sample. WARNING (was DEBUG).
                # Each status is stamped only for the flag that was actually armed.
                if run_sweep_trap:
                    payload["SWEEP_TRAP_STATUS"] = "error"
                    payload["SWEEP_TRAP_ERROR"] = type(exc).__name__
                if run_reaction:
                    payload["REACTION_STATUS"] = "error"
                logger.warning(
                    "Phase B/C sweep-trap/reaction enrichment failed (fail-soft): %s",
                    type(exc).__name__,
                    exc_info=True,
                )
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
    anchor_ts: float,
    bars: pd.DataFrame,
) -> dict[str, Any]:
    """Build Phase A freshness enrichment for a single SMC event.

    Returns a dict with ``freshness_bucket``, ``freshness_penalty``,
    ``event_age_bars``, ``event_age_seconds``, ``invalidated_at``, and
    ``mitigated_at`` keys suitable for insertion under ``"freshness_v2"``
    in the enrichment dict.

    On any internal error emits an explicit ``"unknown"`` freshness state with a
    WARNING (never a silent best-case ``"fresh"``/1.0): a failed classification is
    not evidence of freshness, so the penalty is set to the conservative
    "cannot-confirm-freshness" floor (the ``stale`` decay, 0.60) — the dynamic
    score portion is discounted rather than granted full strength.
    """
    try:
        event_bar = int(event.get("bar_index", anchor_idx))
        age_bars: int = max(0, anchor_idx - event_bar)

        mitigated_ts: float | None = event.get("mitigated_ts") or event.get("mitigated_at")
        invalidated_ts: float | None = event.get("invalidated_ts") or event.get("invalidated_at")
        # Point-in-time gate (audit 2026-07-13, mirrors _candidate_mitigated_at_anchor):
        # the mitigated/invalidated flags are computed on the FULL historical frame,
        # so honour a state only when its timestamp was already reached at the anchor.
        # A later mitigation/invalidation must not colour an event's freshness (and
        # thus its own raw_score) at its own anchor. No usable ts -> not-yet-known.
        mitigated: bool = (
            bool(event.get("mitigated", False))
            and mitigated_ts is not None
            and float(mitigated_ts) <= float(anchor_ts)
        )
        invalidated: bool = (
            bool(event.get("invalidated", False))
            and invalidated_ts is not None
            and float(invalidated_ts) <= float(anchor_ts)
        )
        # Drop future/unknown timestamps so classify_freshness never records them.
        if not mitigated:
            mitigated_ts = None
        if not invalidated:
            invalidated_ts = None

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
                logger.debug(
                    "freshness_v2: bar-seconds approximation failed; using default",
                    exc_info=True,
                )

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
        # A failed freshness classification is NOT evidence of freshness. Emit an
        # explicit "unknown" state with a WARNING (was: a silent "fresh"/1.0, which
        # granted full-strength credit and could inflate the live v2 score). The
        # penalty is the conservative "stale" decay floor (0.60, see
        # event_freshness._DECAY) so build_signal_quality_v2 discounts the dynamic
        # OB/FVG/liquidity portion rather than granting it in full.
        logger.warning(
            "freshness_v2: classification failed for event; emitting 'unknown' "
            "state with conservative penalty (no full-strength credit)",
            exc_info=True,
        )
        return {
            "freshness_bucket": "unknown",
            "freshness_penalty": 0.60,
            "event_age_bars": None,
            "event_age_seconds": None,
            "invalidated_at": None,
            "mitigated_at": None,
            "freshness_error": True,
        }


# ---------------------------------------------------------------------------
# Phase D helper — confluence shadow enrichment
# ---------------------------------------------------------------------------

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
            anchor_ts=anchor_ts,
            bars=bars,
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
    """Heuristic direction PRIOR (0.5 ± bias-derived adjustment), NOT an empirical
    probability. ``bias_confidence`` is the fixed-table conviction weight from
    ``merge_bias`` (HTF=0.8 / SESSION=0.5 …), so the returned value is the RAW,
    uncalibrated input the calibration layer maps — Brier/log-loss/ECE on it grade
    a heuristic prior, not a fitted model. It only earns the name ``predicted_prob``
    once a train-only, OOS-evaluated calibrator produces it (rename-later)."""
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
    if len(highs) < _BOS_LOOKAHEAD_BARS or len(lows) < _BOS_LOOKAHEAD_BARS:
        return None  # right-censoring guard: truncated window at the data edge -> skip, not a final False label

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
    """ATR at ``anchor_idx`` from the prior ``period`` bars (simple mean of TR, no Wilder smoothing).

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
    if min(len(highs), len(lows), len(closes)) < lookahead:
        return None  # right-censoring guard: truncated window at the data edge -> skip, not a final False label

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
    # No SELL_SIDE default: this side drives the outcome label, the invalidation
    # branch, the MAE/MFE direction and is_bullish geometry. A missing/unknown
    # side (normalize_sweep_side -> "NEUTRAL") is fail-closed to a skip rather
    # than silently evaluated as a bullish SELL_SIDE sweep.
    side = str(event.get("side", "")).upper()
    if price <= 0 or anchor_ts <= 0 or normalize_sweep_side(side) == "NEUTRAL":
        return None

    anchor_idx = _find_bar_index(bars, anchor_ts)
    if anchor_idx is None or anchor_idx >= len(bars) - 1:
        return None

    future = bars.iloc[anchor_idx + 1 : anchor_idx + 1 + _SWEEP_LOOKAHEAD_BARS].reset_index(drop=True)
    if len(future) < _SWEEP_LOOKAHEAD_BARS:
        return None  # right-censoring guard: a truncated window at the data edge must be UNRESOLVED (skip), not labeled False

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

    # WS4a shadow-observe: when ENABLE_SWEEP_TRAP is on, classify the trap for
    # THIS sweep and log its quality into the event ledger ``features``
    # observe-only. These fields do NOT feed the score: compute_confluence
    # defaults to prefer_trap_score=False and thus ignores
    # SWEEP_TRAP_QUALITY_SCORE, using only the coarse SWEEP_QUALITY_SCORE, until
    # WS4b promotion flips the caller. (Before that guard the trap score DID leak
    # into confluence whenever ENABLE_CONFLUENCE_SCORE was also on.)
    features: dict[str, Any] = {}
    if (is_sweep_trap_enabled() or is_reaction_zone_enabled()) and price > 0:
        is_bullish = side == "SELL_SIDE"
        swept_level, sweep_extreme, origin_level = _derive_sweep_trap_geometry(
            event, bars, anchor_idx, is_bullish_sweep=is_bullish
        )
        if swept_level > 0:
            post_sweep_bars = [
                {"open": float(r["open"]), "high": float(r["high"]),
                 "low": float(r["low"]), "close": float(r["close"])}
                for _, r in future.iterrows()
            ]
            if is_sweep_trap_enabled():
                # Leakage-free split (mirrors the reaction-zone study): classify the
                # trap on the CONFIRMATION window (bars 1..N) only, and pair it with a
                # DISJOINT late outcome (bars N+1..lookahead). Before this the trap
                # reclaim timing/strength were derived from the same 8-bar window that
                # produced the reversal label -> target leakage; prior Brier/lift are
                # not valid promotion evidence.
                trap = classify_sweep_trap(
                    swept_level=swept_level,
                    sweep_extreme=sweep_extreme,
                    origin_level=origin_level,
                    is_bullish_sweep=is_bullish,
                    post_sweep_bars=post_sweep_bars[:_REACTION_CONFIRM_WINDOW_BARS],
                )
                trap_late_closes = [b["close"] for b in post_sweep_bars[_REACTION_CONFIRM_WINDOW_BARS:]]
                features["sweep_trap_schema_version"] = _SWEEP_TRAP_SCHEMA_VERSION
                features["sweep_trap_type"] = trap.trap_type
                features["sweep_trap_reclaim_bars"] = trap.sweep_reclaim_bars
                features["sweep_trap_reclaim_strength"] = round(trap.reclaim_strength, 4)
                features["sweep_trap_fib_retrace"] = round(trap.fib_retrace_depth, 4)
                features["sweep_trap_quality_score"] = round(trap.trap_quality_score, 4)
                features["sweep_trap_outcome_late"] = label_sweep_reversal(
                    price, side, trap_late_closes, threshold_pct=_SWEEP_REVERSAL_THRESHOLD_PCT
                )
            if is_reaction_zone_enabled():
                # Reaction confirmation on the FIRST window (bars 1..N); follow-through
                # outcome on the DISJOINT later window (bars N+1..lookahead). Keeping the
                # windows non-overlapping avoids target leakage (a reclaim close is itself
                # an early close-through the level, i.e. part of label_sweep_reversal).
                rz = compute_reaction_zone(
                    swept_level=swept_level,
                    sweep_extreme=sweep_extreme,
                    is_bullish_sweep=is_bullish,
                    post_sweep_bars=post_sweep_bars[:_REACTION_CONFIRM_WINDOW_BARS],
                )
                late_closes = [b["close"] for b in post_sweep_bars[_REACTION_CONFIRM_WINDOW_BARS:]]
                late_outcome = label_sweep_reversal(
                    price, side, late_closes, threshold_pct=_SWEEP_REVERSAL_THRESHOLD_PCT
                )
                band_width_pct = (
                    (rz.rejection_band_high - rz.rejection_band_low) / swept_level * 100.0
                    if swept_level > 0 else 0.0
                )
                features["reaction_schema_version"] = _REACTION_SCHEMA_VERSION
                features["reaction_direction"] = "bull" if is_bullish else "bear"
                features["reaction_level_reclaimed"] = rz.level_reclaimed
                features["reaction_in_rejection_band"] = rz.close_in_rejection_band
                features["reaction_close_distance_pct"] = round(rz.close_distance_pct, 6)
                features["reaction_body_ratio"] = round(rz.body_ratio, 6)
                features["reaction_directional_body"] = rz.directional_body
                features["reaction_wick_ratio"] = round(rz.rejection_wick_ratio, 6)
                features["reaction_bars_to_reclaim"] = rz.bars_to_reclaim
                features["reaction_bars_to_rejection_band"] = rz.bars_to_rejection_band
                features["reaction_band_width_pct"] = round(band_width_pct, 6)
                features["reaction_outcome_late"] = late_outcome

    scored_event = ScoredEvent(
        event_id=str(event.get("id", "")),
        family="SWEEP",
        predicted_prob=_sweep_probability(side, bias_direction=bias_direction, bias_confidence=bias_confidence),
        outcome=outcome,
        timestamp=float(anchor_ts),
        context=dict(event_context),
        raw_score=raw_score,
        raw_score_name=raw_score_name,
        features=features,
    )
    return {
        "hit": outcome,
        "time_to_mitigation": float((hit_idx + 1) if hit_idx is not None else 0.0),
        "invalidated": invalidated,
        "mae": mae,
        "mfe": mfe,
    }, scored_event


def build_measurement_evidence(
    symbol: str,
    timeframe: str,
    *,
    anchor_window_days: float | None = None,
) -> MeasurementEvidence:
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

    # Incremental scoring window (frame-fix follow-up 2026-07-13): re-scoring
    # the ENTIRE multi-week event population on every rolling run made the CI
    # sweep exceed its 120-minute budget once genuine full-session frames
    # landed (#3616 -> ~2.3k events/pair; run 29276673623 timed out). With a
    # window, each run evaluates/scores only events anchored within the
    # trailing N days of the frame — older events were already scored by
    # previous rolling runs and reach the corpus via the accumulated pool.
    # ``None`` keeps the previous unbounded behaviour. Always disclosed.
    details["scoring_anchor_window_days"] = anchor_window_days
    skipped_out_of_window = {family: 0 for family in _FAMILIES}
    if anchor_window_days is not None and not resampled_bars.empty:
        try:
            frame_end_ts = float(resampled_bars["timestamp"].iloc[-1])
        except (TypeError, ValueError):
            frame_end_ts = None
        if frame_end_ts is not None:
            cutoff_ts = frame_end_ts - float(anchor_window_days) * 86400.0
            for contract_key, family in (
                ("bos", "BOS"),
                ("orderblocks", "OB"),
                ("fvg", "FVG"),
                ("liquidity_sweeps", "SWEEP"),
            ):
                kept: list[dict[str, Any]] = []
                for event in effective_structure[contract_key]:
                    raw_anchor = event.get("anchor_ts")
                    if raw_anchor is None:
                        raw_anchor = event.get("time")
                    try:
                        event_anchor_ts = float(raw_anchor) if raw_anchor is not None else 0.0
                    except (TypeError, ValueError):
                        event_anchor_ts = 0.0
                    if event_anchor_ts and event_anchor_ts < cutoff_ts:
                        skipped_out_of_window[family] += 1
                    else:
                        # Unparseable anchors stay in: the per-family
                        # evaluators reject them with their own guards.
                        kept.append(event)
                effective_structure[contract_key] = kept
    details["skipped_out_of_window_counts"] = skipped_out_of_window

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
    # Dual-write (confidence-vocabulary program): bias_conviction_score is the
    # honest name (fixed-table conviction weight, not a probability);
    # bias_confidence stays as the legacy alias until the close-window cleanup.
    details["bias_confidence"] = bias_verdict.confidence
    details["bias_conviction_score"] = bias_verdict.confidence
    # Disclose which inputs actually fed the merged bias (htf+session vs.
    # single-source vs. none) — mirrors vol_regime_model_source (audit #2670 W6).
    details["bias_source"] = bias_verdict.source
    details["bias_source_detail"] = bias_verdict.source_detail
    details["bias_chart_tf_direction"] = bias_verdict.chart_tf_direction
    details["vol_regime"] = vol_regime.label
    details["vol_regime_confidence"] = vol_regime.confidence
    details["vol_regime_model_source"] = vol_regime.model_source
    details["vol_regime_fallback_reason"] = vol_regime.fallback_reason
    details["vol_regime_forecast_volatility"] = vol_regime.forecast_volatility
    details["vol_regime_baseline_volatility"] = vol_regime.baseline_volatility
    details["vol_regime_forecast_ratio"] = vol_regime.forecast_ratio
    details["measurement_evidence_present"] = True
    skipped_counts = {family: 0 for family in _FAMILIES}
    # Frame-integrity audit 2026-07-13: events whose anchor resolves but whose
    # FULL label horizon does not fit before the frame edge. These are exactly
    # the events the right-censoring guard in _score_zone_event /
    # _evaluate_sweep_event (correctly) refuses to label — counting them makes
    # a family that silently vanishes from the calibrator population loud.
    scoring_censored_counts = {family: 0 for family in _FAMILIES}
    _family_lookahead = {
        "BOS": _BOS_LOOKAHEAD_BARS,
        "OB": _ZONE_LOOKAHEAD_BARS,
        "FVG": _FVG_LOOKAHEAD_BARS,
        "SWEEP": _SWEEP_LOOKAHEAD_BARS,
    }

    def _count_if_full_horizon_censored(family: str, anchor_idx: int | None) -> None:
        if anchor_idx is not None and anchor_idx + _family_lookahead[family] > len(resampled_bars) - 1:
            scoring_censored_counts[family] += 1

    # Point-in-time context: each event is scored/stratified with ONLY the bias
    # and vol-regime observable AT ITS ANCHOR BAR — never the single
    # end-of-sample verdict computed above. Applying the end-of-sample
    # bias/vol to earlier events leaks future information into
    # predicted_prob, the context strata and raw_score (audit 2026-07-13).
    # The end-of-sample values stay in ``details`` as a run-level summary only.
    #
    # Granularity + cost (frame-fix follow-up 2026-07-13): with genuine
    # full-session intraday frames a pair carries thousands of event anchors;
    # a GARCH fit per unique anchor made ONE pair take ~11 minutes. The PIT
    # context is therefore computed once per TRADING-DAY bucket (the slice
    # ends at the FIRST bar of the anchor's day, which is <= every anchor in
    # that day — still strictly no lookahead) and the vol/bias inputs are
    # capped to the trailing _PIT_CONTEXT_MAX_BARS bars. Day granularity is
    # exactly the effective granularity the pre-fix 1-bar/day frames had.
    _pit_cache: dict[Any, tuple[Any, Any]] = {}
    _neutral_bias = merge_bias(None, None)
    _pit_bar_dates = (
        pd.to_datetime(resampled_bars["timestamp"], unit="s", utc=True, errors="coerce").dt.date
        if not resampled_bars.empty and pd.api.types.is_numeric_dtype(resampled_bars["timestamp"])
        else (
            pd.to_datetime(resampled_bars["timestamp"], utc=True, errors="coerce").dt.date
            if not resampled_bars.empty
            else pd.Series(dtype="object")
        )
    )
    _pit_day_first_idx: dict[Any, int] = {}
    for _bar_idx, _bar_date in enumerate(_pit_bar_dates):
        if _bar_date is not None and _bar_date not in _pit_day_first_idx:
            _pit_day_first_idx[_bar_date] = _bar_idx
    # Run-level (end-of-sample) verdict, kept for the aggregate ensemble summary
    # below; the per-event loops rebind bias_verdict/vol_regime to point-in-time.
    run_bias_verdict, run_vol_regime = bias_verdict, vol_regime

    def _point_in_time_context(anchor_idx: int | None) -> tuple[Any, Any]:
        if anchor_idx is None or anchor_idx < 0:
            # Cannot localize the event -> neutral, never the end-of-sample verdict.
            return _neutral_bias, compute_vol_regime(resampled_bars.iloc[:0])
        anchor_date = _pit_bar_dates.iloc[anchor_idx] if anchor_idx < len(_pit_bar_dates) else None
        bucket_end_idx = _pit_day_first_idx.get(anchor_date, anchor_idx)
        cache_key = anchor_date if anchor_date is not None else anchor_idx
        cached = _pit_cache.get(cache_key)
        if cached is not None:
            return cached
        slice_start = max(0, bucket_end_idx + 1 - _PIT_CONTEXT_MAX_BARS)
        slice_bars = resampled_bars.iloc[slice_start : bucket_end_idx + 1]
        try:
            pit_session = build_session_liquidity_context(slice_bars, tz="America/New_York")
        except Exception:
            pit_session = {}
        try:
            pit_htf = build_htf_bias_context(slice_bars, timeframe=timeframe, htf_frames=None)
        except Exception:
            pit_htf = {}
        result = (
            merge_bias(pit_htf or None, pit_session or None),
            compute_vol_regime(slice_bars),
        )
        _pit_cache[cache_key] = result
        return result

    for event in effective_structure["bos"]:
        evaluated = _evaluate_bos_event(event, resampled_bars)
        if evaluated is None:
            skipped_counts["BOS"] += 1
            continue
        events_by_family["BOS"].append(evaluated)
        anchor_ts = float(event.get("time", event.get("anchor_ts", 0.0)) or 0.0)
        anchor_idx = _find_bar_index(resampled_bars, anchor_ts)
        _count_if_full_horizon_censored("BOS", anchor_idx)
        # Point-in-time: rebind to the bias/vol observable at this event's anchor.
        bias_verdict, vol_regime = _point_in_time_context(anchor_idx)
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
        evaluated = _evaluate_zone_event(
            event,
            resampled_bars,
            diagnostics_by_id=orderblock_diagnostics,
            lookahead_bars=_ZONE_LOOKAHEAD_BARS,
        )
        if evaluated is None:
            skipped_counts["OB"] += 1
            continue
        events_by_family["OB"].append(evaluated)
        anchor_ts = float(event.get("anchor_ts", event.get("time", 0.0)) or 0.0)
        anchor_idx = _find_bar_index(resampled_bars, anchor_ts)
        _count_if_full_horizon_censored("OB", anchor_idx)
        # Point-in-time: rebind to the bias/vol observable at this event's anchor.
        bias_verdict, vol_regime = _point_in_time_context(anchor_idx)
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
            lookahead_bars=_FVG_LOOKAHEAD_BARS,
            emit_partial_50=True,
        )
        if evaluated is None:
            skipped_counts["FVG"] += 1
            continue
        events_by_family["FVG"].append(evaluated)
        anchor_ts = float(event.get("anchor_ts", event.get("time", 0.0)) or 0.0)
        anchor_idx = _find_bar_index(resampled_bars, anchor_ts)
        _count_if_full_horizon_censored("FVG", anchor_idx)
        # Point-in-time: rebind to the bias/vol observable at this event's anchor.
        bias_verdict, vol_regime = _point_in_time_context(anchor_idx)
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
        _count_if_full_horizon_censored("SWEEP", anchor_idx)
        # Point-in-time: rebind to the bias/vol observable at this event's anchor.
        bias_verdict, vol_regime = _point_in_time_context(anchor_idx)
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
    details["scoring_censored_counts"] = scoring_censored_counts
    # Frame-integrity audit 2026-07-13: disclose the bar frame's shape so a
    # degenerate frame (e.g. 1 bar/trading-day resampled from a minutes-wide
    # source window) is visible in every scoring artifact instead of silently
    # starving long-horizon families (FVG horizon 20 > a 19-bar frame can
    # NEVER produce a scorable FVG event).
    # ``resampled_bars.timestamp`` is epoch SECONDS here (_to_epoch_seconds ran
    # above); parsing without unit="s" reads nanoseconds -> every bar lands on
    # 1970-01-01 and trading_days degenerates to 1 (telemetry-units fix
    # 2026-07-13, caught by the first real full-session frame run).
    if resampled_bars.empty:
        _frame_ts = pd.Series(dtype="datetime64[ns, UTC]")
    elif pd.api.types.is_numeric_dtype(resampled_bars["timestamp"]):
        _frame_ts = pd.to_datetime(resampled_bars["timestamp"], unit="s", utc=True, errors="coerce").dropna()
    else:
        _frame_ts = pd.to_datetime(resampled_bars["timestamp"], utc=True, errors="coerce").dropna()
    _frame_days = int(_frame_ts.dt.date.nunique()) if len(_frame_ts) else 0
    details["frame"] = {
        "n_bars": len(resampled_bars),
        "trading_days": _frame_days,
        "bars_per_day_median": float(_frame_ts.dt.date.value_counts().median()) if _frame_days else 0.0,
    }
    details["family_full_horizon_capacity"] = {
        family: max(0, len(resampled_bars) - 1 - _family_lookahead[family])
        for family in _FAMILIES
    }
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
        bias_direction=run_bias_verdict.direction,
        bias_confidence=run_bias_verdict.confidence,
        vol_regime_label=run_vol_regime.label,
        vol_regime_confidence=run_vol_regime.confidence,
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

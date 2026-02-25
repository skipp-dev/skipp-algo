"""Two-stage filter → rank pipeline with sector-relative scoring,
weighted ensemble, time-aware freshness, tiered confidence, and
VWAP-distance enrichment.

Replaces the monolithic ``rank_candidates`` in ``screen.py`` for the
advanced ranking path while keeping the legacy function available for
backward compatibility.
"""
from __future__ import annotations

import math
import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import date
from pathlib import Path
from typing import Any

from .utils import to_float as _to_float, MIN_PRICE_THRESHOLD, SEVERE_GAP_DOWN_THRESHOLD
from .technical_analysis import (
    apply_diminishing_returns,
    compute_risk_penalty,
    classify_instrument,
    compute_adaptive_gates,
    validate_data_quality,
    GateTracker,
    compute_entry_probability,
    calculate_ewma,
    calculate_ewma_metrics,
    calculate_ewma_score,
    resolve_regime_weights,
    detect_symbol_regime,
)
from .signal_decay import adaptive_freshness_decay, adaptive_half_life
from .dirty_flag_manager import PipelineDirtyManager

logger = logging.getLogger("open_prep.scorer")

# ---------------------------------------------------------------------------
# Weight configuration (ensemble)
# ---------------------------------------------------------------------------
OUTCOMES_DIR = Path("artifacts/open_prep/outcomes")

DEFAULT_WEIGHTS: dict[str, float] = {
    "gap": 0.8,
    "gap_sector_relative": 0.6,
    "rvol": 1.2,
    "macro": 0.7,
    "momentum_z": 0.5,
    "hvb": 0.3,
    "earnings_bmo": 1.5,
    "news": 0.8,
    "ext_hours": 1.0,
    "analyst_catalyst": 0.5,
    "vwap_distance": 0.4,
    "freshness_decay": 0.3,
    "institutional_quality": 0.3,
    "estimate_revision": 0.4,
    "ewma": 0.4,
    # Penalties (applied as subtractions)
    "liquidity_penalty": 1.5,
    "corporate_action_penalty": 1.0,
    "risk_off_penalty_multiplier": 2.0,
}

# Filter thresholds (MIN_PRICE_THRESHOLD and SEVERE_GAP_DOWN_THRESHOLD imported from utils)
RISK_OFF_EXTREME_THRESHOLD = -0.75
GAP_CAP_ABS = 10.0
RVOL_CAP = 10.0

# Freshness decay
FRESHNESS_HALF_LIFE_SECONDS = 600.0  # 10 minutes

# ---------------------------------------------------------------------------
# Weight ensemble loader
# ---------------------------------------------------------------------------

def load_weight_set(label: str = "default") -> dict[str, float]:
    """Load a named weight set from disk, falling back to DEFAULT_WEIGHTS."""
    if label == "default":
        return dict(DEFAULT_WEIGHTS)
    path = OUTCOMES_DIR / f"weights_{label}.json"
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                merged = dict(DEFAULT_WEIGHTS)
                merged.update({k: float(v) for k, v in data.items() if isinstance(v, (int, float))})
                return merged
        except Exception:
            logger.warning("Failed to load weight set '%s', using default.", label)
    return dict(DEFAULT_WEIGHTS)


def save_weight_set(label: str, weights: dict[str, float]) -> None:
    """Persist a weight set to disk (atomic write with fsync)."""
    import tempfile as _tempfile
    OUTCOMES_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTCOMES_DIR / f"weights_{label}.json"
    content = json.dumps(weights, indent=2, allow_nan=False)
    fd, tmp = _tempfile.mkstemp(dir=str(OUTCOMES_DIR), suffix=".tmp")
    try:
        os.write(fd, content.encode("utf-8"))
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(tmp, str(path))
    except BaseException:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Time-aware freshness decay
# ---------------------------------------------------------------------------

def freshness_decay_score(
    elapsed_seconds: float | None,
    atr_pct: float | None = None,
) -> float:
    """Exponential freshness decay.  Returns 0..1 (1 = perfectly fresh).

    Uses :func:`signal_decay.adaptive_half_life` to scale the half-life by
    instrument volatility (ATR%), falling back to the constant 600 s when
    *atr_pct* is not available.
    """
    if elapsed_seconds is None:
        return 0.0
    if elapsed_seconds <= 0:
        return 1.0
    hl = adaptive_half_life(atr_pct) if atr_pct is not None else FRESHNESS_HALF_LIFE_SECONDS
    return math.exp(-elapsed_seconds * math.log(2) / hl)


# ---------------------------------------------------------------------------
# Sector-relative gap scoring
# ---------------------------------------------------------------------------

def compute_sector_relative_gap(
    gap_pct: float,
    symbol_sector: str | None,
    sector_changes: dict[str, float],
) -> float:
    """Return gap_pct minus the sector average change.

    If sector is unknown, returns 0.0 (neutral — no penalty or benefit).
    """
    if not symbol_sector or not sector_changes:
        return 0.0
    sector_avg = sector_changes.get(symbol_sector, 0.0)
    return gap_pct - sector_avg


# ---------------------------------------------------------------------------
# VWAP distance feature
# ---------------------------------------------------------------------------

def compute_vwap_distance_pct(
    vwap: float | None,
    prev_close: float | None,
) -> float:
    """Distance from premarket VWAP to prior day's close, as %."""
    if vwap is None or prev_close is None or prev_close <= 0 or vwap <= 0:
        return 0.0
    return ((vwap - prev_close) / prev_close) * 100.0


# ---------------------------------------------------------------------------
# Stage 1: FILTER
# ---------------------------------------------------------------------------

@dataclass
class FilterResult:
    """Result of the filter stage for a single symbol."""
    symbol: str
    passed: bool
    filter_reasons: list[str]
    allowed_setups: list[str]
    max_trades: int
    long_allowed: bool
    # Extracted numeric features for scoring stage
    features: dict[str, Any] = field(default_factory=dict)


def _compute_ewma_feature(quote: dict[str, Any], price: float) -> float:
    """Extract daily bars from a quote dict and return a 0.0–1.0 EWMA score.

    If the quote contains a ``daily_bars`` key (list of OHLCV dicts), compute
    the full EWMA pipeline.  Otherwise return 0.5 (neutral).
    """
    bars = quote.get("daily_bars")
    if not bars or not isinstance(bars, list) or len(bars) < 10:
        return 0.5  # neutral — no daily-bar history available

    ewma_data = calculate_ewma(bars, length=min(50, len(bars)))
    if ewma_data is None:
        return 0.5

    metrics = calculate_ewma_metrics(price, ewma_data)
    return calculate_ewma_score(metrics)


def filter_candidate(
    quote: dict[str, Any],
    bias: float,
    *,
    news_score: float = 0.0,
    news_metrics_entry: dict[str, Any] | None = None,
    sector_changes: dict[str, float] | None = None,
    symbol_sector: str | None = None,
    institutional_quality: float = 0.0,
    estimate_revision_score: float = 0.0,
    gate_tracker: GateTracker | None = None,
) -> FilterResult:
    """Stage 1: apply hard filters and extract features.

    Returns a FilterResult with:
      - ``passed=True`` if the symbol survives all hard filters
      - ``filter_reasons`` listing why it was rejected (if any)
      - ``features`` dict with all numeric features for the scorer
    """
    symbol = str(quote.get("symbol") or "").strip().upper()

    price = _to_float(quote.get("price"), default=0.0)
    gap_pct = _to_float(
        quote.get("gap_pct") or quote.get("changesPercentage") or quote.get("changePercentage"),
        default=0.0,
    )
    gap_available_raw = quote.get("gap_available")
    gap_available = False if gap_available_raw is None else bool(gap_available_raw)
    volume = _to_float(quote.get("volume"), default=0.0)
    avg_volume = _to_float(
        quote.get("avgVolume")
        or quote.get("avg_volume")
        or quote.get("averageVolume")
        or quote.get("avgVolume3Month")
        or quote.get("avgVolume50"),
        default=0.0,
    )
    if avg_volume <= 0.0 and volume > 0.0:
        # Fail-open fallback: when provider omits avg-volume baseline,
        # use current volume so quality gates remain informative but not
        # universally tripped by missing metadata.
        avg_volume = volume
    atr = _to_float(quote.get("atr"), default=0.0)
    momentum_z = _to_float(quote.get("momentum_z_score"), default=0.0)
    rel_vol = _to_float(quote.get("volume_ratio"), default=0.0)
    if rel_vol <= 0.0:
        rel_vol = (volume / avg_volume) if avg_volume > 0 else 0.0
    is_hvb = bool(quote.get("is_hvb", False))
    earnings_today = bool(quote.get("earnings_today", False))
    earnings_timing = quote.get("earnings_timing") or ""
    ext_hours_score = _to_float(quote.get("ext_hours_score"), default=0.0)
    ext_volume_ratio = _to_float(quote.get("ext_volume_ratio"), default=0.0)
    premarket_stale = bool(quote.get("premarket_stale", False))
    spread_bps_raw = quote.get("premarket_spread_bps")
    premarket_spread_bps: float | None = None
    if spread_bps_raw is not None:
        val = _to_float(spread_bps_raw, default=float("nan"))
        premarket_spread_bps = None if math.isnan(val) else val
    corporate_action_penalty = _to_float(quote.get("corporate_action_penalty"), default=0.0)
    analyst_catalyst_score = _to_float(quote.get("analyst_catalyst_score"), default=0.0)
    split_today = bool(quote.get("split_today", False))
    dividend_today = bool(quote.get("dividend_today", False))
    ipo_window = bool(quote.get("ipo_window", False))
    premarket_change_raw = quote.get("premarket_change_pct")
    premarket_change_pct_val = _to_float(premarket_change_raw, default=float("nan"))
    premarket_change_pct: float | None = (
        None if math.isnan(premarket_change_pct_val) else premarket_change_pct_val
    )
    earnings_risk_window = bool(quote.get("earnings_risk_window", False))
    freshness_sec_raw = _to_float(quote.get("premarket_freshness_sec"), default=float("nan"))
    freshness_sec: float | None = None if math.isnan(freshness_sec_raw) else freshness_sec_raw
    vwap_raw2 = _to_float(quote.get("vwap"), default=float("nan"))
    vwap: float | None = None if vwap_raw2 != vwap_raw2 else vwap_raw2
    prev_close_raw2 = _to_float(quote.get("previousClose"), default=float("nan"))
    prev_close: float | None = None if prev_close_raw2 != prev_close_raw2 else prev_close_raw2

    # --- Hard filter checks ---
    filter_reasons: list[str] = []
    allowed_setups = ["orb", "gap_go", "vwap_reclaim", "hod_reclaim"]
    max_trades = 2

    if price < MIN_PRICE_THRESHOLD:
        filter_reasons.append("price_below_5")
    if bias <= RISK_OFF_EXTREME_THRESHOLD:
        filter_reasons.append("macro_risk_off_extreme")
        allowed_setups = ["vwap_reclaim"]
        max_trades = 1
        if rel_vol <= 0.0:
            filter_reasons.append("missing_rvol")
    if gap_pct <= SEVERE_GAP_DOWN_THRESHOLD:
        filter_reasons.append("severe_gap_down")
    if split_today:
        filter_reasons.append("split_today")
    if ipo_window:
        filter_reasons.append("ipo_window")
    if bias < -0.25 and bias > RISK_OFF_EXTREME_THRESHOLD:
        filter_reasons.append("macro_bias_short")
    if premarket_stale:
        filter_reasons.append("premarket_stale")
    if premarket_spread_bps is not None and premarket_spread_bps > 200.0:
        filter_reasons.append("spread_too_wide")
    if avg_volume > 0.0 and avg_volume < 100_000:
        filter_reasons.append("insufficient_liquidity")
    if atr <= 0.0:
        filter_reasons.append("atr_missing")
    if earnings_risk_window:
        filter_reasons.append("earnings_risk_window")

    # --- Data-quality hard filters ---
    # Zero-volume: no meaningful trading → cannot score reliably
    if volume <= 0.0 and avg_volume > 0.0:
        filter_reasons.append("zero_volume")
    # RSI extremes: implausible data (RSI should be 0..100)
    rsi_raw = _to_float(quote.get("rsi") or quote.get("rsi14"), default=float("nan"))
    if not math.isnan(rsi_raw) and (rsi_raw <= 0.1 or rsi_raw >= 99.9):
        filter_reasons.append("rsi_extreme")

    # Hard-block codes that prevent any trading
    hard_blocks = {
        "price_below_5",
        "severe_gap_down",
        "missing_rvol",
        "macro_risk_off_extreme",
        "split_today",
        "ipo_window",
        "zero_volume",
    }
    long_allowed = not any(r in hard_blocks for r in filter_reasons)
    passed = long_allowed  # Must pass hard-blocks to enter scoring

    # --- Data quality validation (#8) — warn-only, fail-open ---
    dq_payload = dict(quote)
    dq_payload["avg_volume"] = avg_volume
    dq_payload["avgVolume"] = avg_volume
    dq = validate_data_quality(dq_payload)
    if not dq.passed:
        for issue in dq.issues:
            if issue not in filter_reasons:
                filter_reasons.append(issue)
        if gate_tracker:
            for issue in dq.issues:
                gate_tracker.reject(symbol, issue, {"source": "data_quality"})
        # NOTE: do NOT set passed=False here — fail-open design.
        # DQ issues are informational warn-flags, not hard-blocks.

    # --- Gate tracking for existing hard-blocks (#10) ---
    if gate_tracker and not long_allowed:
        for reason in filter_reasons:
            if reason in hard_blocks:
                gate_tracker.reject(symbol, reason, {"price": price, "gap_pct": gap_pct})

    # --- Instrument classification (#5) ---
    atr_pct_val = (atr / price * 100.0) if price > 0 and atr > 0 else 0.0
    instrument_class = classify_instrument(price, atr_pct_val)

    # --- Sector-relative gap ---
    sector_rel_gap = compute_sector_relative_gap(
        gap_pct, symbol_sector, sector_changes or {},
    )
    sector_change_pct = (sector_changes or {}).get(symbol_sector or "", 0.0)

    # --- VWAP distance ---
    vwap_dist_pct = compute_vwap_distance_pct(vwap, prev_close)

    # --- Freshness decay (adaptive half-life based on ATR%) ---
    freshness = adaptive_freshness_decay(
        freshness_sec,
        atr_pct=atr_pct_val if atr_pct_val > 0 else None,
        instrument_class=instrument_class,
    )
    freshness_half_life = adaptive_half_life(
        atr_pct=atr_pct_val if atr_pct_val > 0 else None,
        instrument_class=instrument_class,
    )

    # --- Earnings BMO flag ---
    earnings_bmo = earnings_today and str(earnings_timing).lower() in {"bmo", "before market open"}

    # Build features dict for scorer
    features: dict[str, Any] = {
        "price": price,
        "gap_pct": gap_pct,
        "gap_available": gap_available,
        "gap_pct_for_scoring": gap_pct if gap_available else 0.0,
        "sector_relative_gap": round(sector_rel_gap, 4),
        "sector_change_pct": round(sector_change_pct, 4),
        "symbol_sector": symbol_sector or "",
        "volume": volume,
        "avg_volume": avg_volume,
        "rel_vol": rel_vol,
        "rel_vol_capped": min(rel_vol, RVOL_CAP),
        "atr": atr,
        "momentum_z": max(min(momentum_z, 5.0), -5.0),
        "is_hvb": is_hvb,
        "earnings_today": earnings_today,
        "earnings_timing": earnings_timing,
        "earnings_bmo": earnings_bmo,
        "earnings_risk_window": earnings_risk_window,
        "is_premarket_mover": bool(quote.get("is_premarket_mover", False)),
        "ext_hours_score": ext_hours_score,
        "ext_volume_ratio": ext_volume_ratio,
        "premarket_stale": premarket_stale,
        "premarket_spread_bps": premarket_spread_bps,
        "premarket_change_pct": premarket_change_pct,
        "corporate_action_penalty": corporate_action_penalty,
        "analyst_catalyst_score": analyst_catalyst_score,
        "split_today": split_today,
        "dividend_today": dividend_today,
        "ipo_window": ipo_window,
        "news_score": news_score,
        "news_metrics": news_metrics_entry or {},
        "vwap_distance_pct": round(vwap_dist_pct, 4),
        "freshness_decay": round(freshness, 4),
        "freshness_half_life_s": round(freshness_half_life, 0),
        "institutional_quality": institutional_quality,
        "estimate_revision_score": estimate_revision_score,
        "data_sufficiency_low": avg_volume <= 0.0 or rel_vol <= 0.0,
        # Pass-through fields for output
        "gap_type": quote.get("gap_type"),
        "gap_scope": quote.get("gap_scope"),
        "gap_from_ts": quote.get("gap_from_ts"),
        "gap_to_ts": quote.get("gap_to_ts"),
        "gap_reason": quote.get("gap_reason"),
        "gap_bucket": quote.get("gap_bucket"),
        "gap_grade": quote.get("gap_grade"),
        "warn_flags": quote.get("warn_flags", ""),
        "atr_pct": quote.get("atr_pct"),
        "pdh": quote.get("pdh"),
        "pdl": quote.get("pdl"),
        "pdh_source": quote.get("pdh_source"),
        "pdl_source": quote.get("pdl_source"),
        "dist_to_pdh_atr": quote.get("dist_to_pdh_atr"),
        "dist_to_pdl_atr": quote.get("dist_to_pdl_atr"),
        "premarket_high": quote.get("premarket_high"),
        "premarket_low": quote.get("premarket_low"),
        "upgrade_downgrade_emoji": quote.get("upgrade_downgrade_emoji", ""),
        "upgrade_downgrade_label": quote.get("upgrade_downgrade_label", ""),
        "upgrade_downgrade_action": quote.get("upgrade_downgrade_action", ""),
        "upgrade_downgrade_firm": quote.get("upgrade_downgrade_firm", ""),
        "upgrade_downgrade_date": quote.get("upgrade_downgrade_date"),
        # Playbook-relevant news enrichment (via news.py)
        "news_event_class": (news_metrics_entry or {}).get("event_class", "UNKNOWN"),
        "news_event_label": (news_metrics_entry or {}).get("event_label", "generic"),
        "news_event_labels_all": (news_metrics_entry or {}).get("event_labels_all", []),
        "news_materiality": (news_metrics_entry or {}).get("materiality", "LOW"),
        "news_recency_bucket": (news_metrics_entry or {}).get("recency_bucket", "UNKNOWN"),
        "news_age_minutes": (news_metrics_entry or {}).get("age_minutes"),
        "news_is_actionable": (news_metrics_entry or {}).get("is_actionable", False),
        "news_source_tier": (news_metrics_entry or {}).get("source_tier", "TIER_3"),
        "news_source_rank": (news_metrics_entry or {}).get("source_rank", 3),
        # Technical analysis enrichment (#5 instrument classification, #3 risk penalty)
        "instrument_class": instrument_class,
        "atr_pct_computed": round(atr_pct_val, 4),
        "spread_pct": (premarket_spread_bps / 10_000.0) if premarket_spread_bps is not None else 0.0,
        "data_quality_issues": dq.issues,
        # EWMA: compute from daily bars if available
        "ewma_score": _compute_ewma_feature(quote, price),
        # Regime detection (#15): from ADX + BB width if available
        "symbol_regime": detect_symbol_regime(
            adx=_to_float(quote.get("adx"), default=15.0),
            bb_width_pct=_to_float(quote.get("bb_width_pct"), default=3.0),
        ),
    }

    return FilterResult(
        symbol=symbol,
        passed=passed,
        filter_reasons=filter_reasons,
        allowed_setups=allowed_setups,
        max_trades=max_trades,
        long_allowed=long_allowed,
        features=features,
    )


# ---------------------------------------------------------------------------
# Stage 2: SCORE
# ---------------------------------------------------------------------------

def score_candidate(
    fr: FilterResult,
    bias: float,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Stage 2: compute the composite score from pre-extracted features.

    Returns a full ranked-candidate dict with score, breakdown, and all
    pass-through fields.
    """
    w = weights or DEFAULT_WEIGHTS
    f = fr.features

    # --- #15  Regime-adaptive weight adjustment ---
    symbol_regime = f.get("symbol_regime", "NEUTRAL")
    w = resolve_regime_weights(w, symbol_regime)

    gap_pct_for_scoring = f["gap_pct_for_scoring"]
    rel_vol_capped = f["rel_vol_capped"]
    momentum_z = f["momentum_z"]
    ext_hours_score = f["ext_hours_score"]
    analyst_catalyst_score = f["analyst_catalyst_score"]
    corporate_action_penalty = f["corporate_action_penalty"]
    news_score = f["news_score"]

    # --- Components (with diminishing returns #2) ---
    # For positive-only components, normalize to [0,1], apply sqrt(), then scale.
    # Gap and momentum can be negative, so DR is only on absolute magnitude.
    gap_raw = max(min(gap_pct_for_scoring, GAP_CAP_ABS), -GAP_CAP_ABS)
    gap_component = w["gap"] * gap_raw  # gap can be negative, no DR
    gap_sector_rel_component = w["gap_sector_relative"] * max(
        min(f["sector_relative_gap"], GAP_CAP_ABS), -GAP_CAP_ABS
    )
    # rvol: apply DR to compress extreme relative-volume spikes
    rvol_normed = min(rel_vol_capped / RVOL_CAP, 1.0) if RVOL_CAP > 0 else 0.0
    rvol_component = w["rvol"] * apply_diminishing_returns(rvol_normed)
    macro_component = w["macro"] * max(bias, 0.0)
    momentum_component = w["momentum_z"] * momentum_z  # can be negative
    hvb_component = w["hvb"] if f["is_hvb"] else 0.0
    earnings_bmo_component = w["earnings_bmo"] if f["earnings_bmo"] else 0.0
    # news / ext_hours: apply DR (positive-only scores)
    news_normed = min(max(news_score, 0.0), 1.0)
    news_component = w["news"] * apply_diminishing_returns(news_normed)
    ext_normed = min(max(ext_hours_score, 0.0), 1.0)
    ext_hours_component = w["ext_hours"] * apply_diminishing_returns(ext_normed)
    analyst_catalyst_component = w["analyst_catalyst"] * analyst_catalyst_score
    vwap_dist_component = w["vwap_distance"] * max(min(f["vwap_distance_pct"], 5.0), -5.0)
    freshness_component = w["freshness_decay"] * f["freshness_decay"]
    institutional_component = w["institutional_quality"] * f["institutional_quality"]
    estimate_rev_component = w["estimate_revision"] * f["estimate_revision_score"]

    # EWMA component (#14): energy-weighted mean reversion signal
    ewma_raw = f.get("ewma_score", 0.5)
    ewma_component = w.get("ewma", 0.4) * apply_diminishing_returns(max(min(ewma_raw, 1.0), 0.0))

    # --- #8  Score Component Cap (40%) ---
    # Prevent any single positive component from dominating > 40% of the
    # total positive contribution.  Iterative: re-compute total after each
    # capping pass until convergence (prevents single-pass overshoot where
    # a capped component still exceeds 40% of the post-cap total).
    _components = {
        "gap": gap_component,
        "gap_sector_rel": gap_sector_rel_component,
        "rvol": rvol_component,
        "macro": macro_component,
        "momentum": momentum_component,
        "hvb": hvb_component,
        "earnings_bmo": earnings_bmo_component,
        "news": news_component,
        "ext_hours": ext_hours_component,
        "analyst_catalyst": analyst_catalyst_component,
        "vwap_dist": vwap_dist_component,
        "freshness": freshness_component,
        "institutional": institutional_component,
        "estimate_rev": estimate_rev_component,
        "ewma": ewma_component,
    }
    for _ in range(5):  # max 5 iterations; typically converges in 2
        _total_positive = sum(max(v, 0.0) for v in _components.values())
        if _total_positive <= 0:
            break
        _cap = 0.40 * _total_positive
        changed = False
        for k, v in _components.items():
            if v > _cap:
                _components[k] = _cap
                changed = True
        if not changed:
            break

    gap_component = _components["gap"]
    gap_sector_rel_component = _components["gap_sector_rel"]
    rvol_component = _components["rvol"]
    macro_component = _components["macro"]
    momentum_component = _components["momentum"]
    hvb_component = _components["hvb"]
    earnings_bmo_component = _components["earnings_bmo"]
    news_component = _components["news"]
    ext_hours_component = _components["ext_hours"]
    analyst_catalyst_component = _components["analyst_catalyst"]
    vwap_dist_component = _components["vwap_dist"]
    freshness_component = _components["freshness"]
    institutional_component = _components["institutional"]
    estimate_rev_component = _components["estimate_rev"]
    ewma_component = _components["ewma"]

    # --- Penalties ---
    liquidity_penalty = w["liquidity_penalty"] if f["price"] < MIN_PRICE_THRESHOLD else 0.0
    corp_penalty = w["corporate_action_penalty"] * max(corporate_action_penalty, 0.0)
    risk_off_penalty = abs(min(bias, 0.0)) * w["risk_off_penalty_multiplier"]

    # --- Risk penalty (#3) ---
    risk_penalty_val = compute_risk_penalty(
        price=f["price"],
        atr=f["atr"],
        volume_ratio=f.get("rel_vol", 0.0),
        spread_pct=f.get("spread_pct", 0.0),
    )

    score = (
        gap_component
        + gap_sector_rel_component
        + rvol_component
        + macro_component
        + momentum_component
        + hvb_component
        + earnings_bmo_component
        + news_component
        + ext_hours_component
        + analyst_catalyst_component
        + vwap_dist_component
        + freshness_component
        + institutional_component
        + estimate_rev_component
        + ewma_component
        - liquidity_penalty
        - corp_penalty
        - risk_off_penalty
        - risk_penalty_val
    )

    # --- Counter-Trend Penalty ---
    # When momentum strongly opposes the gap direction, apply a multiplicative
    # penalty.  Inspired by IB_MON's trend-alignment safeguard.
    counter_trend_penalty = 0.0
    if momentum_z < -2.5:
        counter_trend_penalty = min(0.40, abs(momentum_z + 2.5) * 0.20)
        score = score * (1.0 - counter_trend_penalty)

    # --- Entry Probability (#13) ---
    entry_probability = compute_entry_probability(
        score=score,
        momentum_z=momentum_z,
        volume_ratio=f.get("rel_vol", 1.0),
        atr_pct=_to_float(f.get("atr_pct"), default=0.0),
        spread_pct=f.get("spread_pct", 0.0),
    )

    nm = f.get("news_metrics") or {}

    return {
        "symbol": fr.symbol,
        "score": round(score, 4),
        "price": f["price"],
        "gap_pct": f["gap_pct"],
        "gap_type": f["gap_type"],
        "gap_scope": f["gap_scope"],
        "gap_available": f["gap_available"],
        "gap_from_ts": f["gap_from_ts"],
        "gap_to_ts": f["gap_to_ts"],
        "gap_reason": f["gap_reason"],
        "gap_bucket": f["gap_bucket"],
        "gap_grade": f["gap_grade"],
        "sector_relative_gap": f["sector_relative_gap"],
        "sector_change_pct": f["sector_change_pct"],
        "symbol_sector": f["symbol_sector"],
        "warn_flags": f["warn_flags"],
        "volume": f["volume"],
        "avg_volume": f["avg_volume"],
        "volume_ratio": round(f["rel_vol"], 4),
        "atr": round(f["atr"], 4),
        "atr_pct": f["atr_pct"],
        "momentum_z_score": round(f["momentum_z"], 4),
        "pdh": f["pdh"],
        "pdl": f["pdl"],
        "pdh_source": f["pdh_source"],
        "pdl_source": f["pdl_source"],
        "dist_to_pdh_atr": f["dist_to_pdh_atr"],
        "dist_to_pdl_atr": f["dist_to_pdl_atr"],
        "earnings_today": f["earnings_today"],
        "earnings_timing": f["earnings_timing"] or None,
        "earnings_bmo": f["earnings_bmo"],
        "is_premarket_mover": f["is_premarket_mover"],
        "premarket_change_pct": f["premarket_change_pct"],
        "premarket_high": f["premarket_high"],
        "premarket_low": f["premarket_low"],
        "ext_hours_score": round(f["ext_hours_score"], 4),
        "premarket_stale": f["premarket_stale"],
        "premarket_spread_bps": f["premarket_spread_bps"],
        "split_today": f["split_today"],
        "dividend_today": f["dividend_today"],
        "ipo_window": f["ipo_window"],
        "corporate_action_penalty": round(max(f["corporate_action_penalty"], 0.0), 4),
        "analyst_catalyst_score": round(f["analyst_catalyst_score"], 4),
        "macro_bias": round(bias, 4),
        "news_catalyst_score": round(news_score, 4),
        "news_sentiment_emoji": nm.get("sentiment_emoji", "🟡"),
        "news_sentiment_label": nm.get("sentiment_label", "neutral"),
        "news_sentiment_score": nm.get("sentiment_score", 0.0),
        "upgrade_downgrade_emoji": f["upgrade_downgrade_emoji"],
        "upgrade_downgrade_label": f["upgrade_downgrade_label"],
        "upgrade_downgrade_action": f["upgrade_downgrade_action"],
        "upgrade_downgrade_firm": f["upgrade_downgrade_firm"],
        "upgrade_downgrade_date": f["upgrade_downgrade_date"],
        # Playbook-relevant fields
        "news_event_class": f.get("news_event_class", "UNKNOWN"),
        "news_event_label": f.get("news_event_label", "generic"),
        "news_event_labels_all": f.get("news_event_labels_all", []),
        "news_materiality": f.get("news_materiality", "LOW"),
        "news_recency_bucket": f.get("news_recency_bucket", "UNKNOWN"),
        "news_age_minutes": f.get("news_age_minutes"),
        "news_is_actionable": f.get("news_is_actionable", False),
        "news_source_tier": f.get("news_source_tier", "TIER_3"),
        "news_source_rank": f.get("news_source_rank", 3),
        "vwap_distance_pct": f["vwap_distance_pct"],
        "freshness_decay": f["freshness_decay"],
        "freshness_half_life_s": f.get("freshness_half_life_s", 600),
        "institutional_quality": round(f["institutional_quality"], 4),
        "estimate_revision_score": round(f["estimate_revision_score"], 4),
        "allowed_setups": fr.allowed_setups,
        "max_trades": fr.max_trades,
        "data_sufficiency": {
            "low": f["data_sufficiency_low"],
            "avg_volume_missing": f["avg_volume"] <= 0.0,
            "rel_volume_missing": f["rel_vol"] <= 0.0,
        },
        "score_breakdown": {
            "gap_component": round(gap_component, 4),
            "gap_sector_rel_component": round(gap_sector_rel_component, 4),
            "rvol_component": round(rvol_component, 4),
            "macro_component": round(macro_component, 4),
            "momentum_component": round(momentum_component, 4),
            "hvb_component": round(hvb_component, 4),
            "earnings_bmo_component": round(earnings_bmo_component, 4),
            "news_component": round(news_component, 4),
            "ext_hours_component": round(ext_hours_component, 4),
            "analyst_catalyst_component": round(analyst_catalyst_component, 4),
            "vwap_distance_component": round(vwap_dist_component, 4),
            "freshness_component": round(freshness_component, 4),
            "institutional_component": round(institutional_component, 4),
            "estimate_revision_component": round(estimate_rev_component, 4),
            "ewma_component": round(ewma_component, 4),
            "corporate_action_penalty": round(corp_penalty, 4),
            "liquidity_penalty": round(liquidity_penalty, 4),
            "risk_off_penalty": round(risk_off_penalty, 4),
            "risk_penalty": round(risk_penalty_val, 4),
            "counter_trend_penalty": round(counter_trend_penalty, 4),
        },
        # Technical analysis enrichment
        "instrument_class": f.get("instrument_class", "mid_cap"),
        "symbol_regime": symbol_regime,
        "entry_probability": entry_probability,
        "data_quality_issues": f.get("data_quality_issues", []),
        "long_allowed": fr.long_allowed,
        "no_trade_reason": fr.filter_reasons,
    }


# ---------------------------------------------------------------------------
# Tiered confidence
# ---------------------------------------------------------------------------

def classify_confidence_tier(
    score: float,
    all_scores: list[float],
    warn_flags: str = "",
) -> str:
    """Classify a candidate into a confidence tier.

    - HIGH_CONVICTION: score > mean + 2σ AND no warn_flags
    - STANDARD: score > mean + 1σ
    - WATCHLIST: everything else
    """
    if len(all_scores) < 5:
        # With fewer than 5 samples, Bessel's correction makes stdev
        # unreliable — default to STANDARD to avoid spurious tiers.
        return "STANDARD"

    n = len(all_scores)
    mean = sum(all_scores) / n
    variance = sum((x - mean) ** 2 for x in all_scores) / (n - 1)
    std = math.sqrt(variance) if variance > 0 else 0.001

    if score > mean + 2 * std and not warn_flags.strip():
        return "HIGH_CONVICTION"
    if score > mean + 1 * std:
        return "STANDARD"
    return "WATCHLIST"


# ---------------------------------------------------------------------------
# Full two-stage pipeline
# ---------------------------------------------------------------------------

def rank_candidates_v2(
    quotes: list[dict[str, Any]],
    bias: float,
    top_n: int = 20,
    *,
    news_scores: dict[str, float] | None = None,
    news_metrics: dict[str, dict[str, Any]] | None = None,
    sector_changes: dict[str, float] | None = None,
    symbol_sectors: dict[str, str] | None = None,
    institutional_scores: dict[str, float] | None = None,
    estimate_revisions: dict[str, float] | None = None,
    weight_label: str = "default",
    vix_level: float | None = None,
    gate_tracker: GateTracker | None = None,
    dirty_manager: PipelineDirtyManager | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Two-stage filter→rank pipeline.

    Returns ``(ranked, filtered_out)`` where:
    - ``ranked`` is the top-N scored candidates
    - ``filtered_out`` contains symbols that failed hard filters, with reasons
    """
    if gate_tracker is None:
        gate_tracker = GateTracker()

    weights = load_weight_set(weight_label)
    by_news: dict[str, float] = {str(k).upper(): _to_float(v, default=0.0) for k, v in (news_scores or {}).items()}
    by_news_metrics: dict[str, dict] = {
        str(k).upper(): v for k, v in (news_metrics or {}).items() if isinstance(v, dict)
    }
    by_sectors = {str(k).upper(): str(v) for k, v in (symbol_sectors or {}).items()}
    by_institutional = {str(k).upper(): _to_float(v, default=0.0) for k, v in (institutional_scores or {}).items()}
    by_revisions = {str(k).upper(): _to_float(v, default=0.0) for k, v in (estimate_revisions or {}).items()}

    # Build sector_changes lookup: sector_name → changesPercentage
    sec_changes: dict[str, float] = {}
    if sector_changes:
        sec_changes = sector_changes

    # --- Stage 1: Filter ---
    passed: list[FilterResult] = []
    filtered_out: list[dict[str, Any]] = []

    for quote in quotes:
        symbol = str(quote.get("symbol") or "").strip().upper()
        if not symbol:
            continue

        fr = filter_candidate(
            quote,
            bias,
            news_score=by_news.get(symbol, 0.0),
            news_metrics_entry=by_news_metrics.get(symbol),
            sector_changes=sec_changes,
            symbol_sector=by_sectors.get(symbol),
            institutional_quality=by_institutional.get(symbol, 0.0),
            estimate_revision_score=by_revisions.get(symbol, 0.0),
            gate_tracker=gate_tracker,
        )
        if fr.passed:
            passed.append(fr)
        else:
            filtered_out.append({
                "symbol": symbol,
                "filter_reasons": fr.filter_reasons,
                "price": fr.features.get("price", 0.0),
                "gap_pct": fr.features.get("gap_pct", 0.0),
            })

    # --- Stage 2: Score (with dirty-flag skip) ---
    scored: list[dict[str, Any]] = []
    for fr in passed:
        if dirty_manager is not None:
            fp = dirty_manager.fingerprint(fr.symbol, fr.features)
            if dirty_manager.is_clean(fr.symbol, fp):
                scored.append(dirty_manager.get_cached(fr.symbol))
                continue
            row = score_candidate(fr, bias, weights)
            dirty_manager.update(fr.symbol, fp, row)
        else:
            row = score_candidate(fr, bias, weights)
        scored.append(row)

    # --- Adaptive gating (#4): soft annotation, fail-open ---
    if vix_level is not None:
        for row in scored:
            inst_class = row.get("instrument_class", "mid_cap")
            gates = compute_adaptive_gates(
                vix_level=vix_level,
                instrument_class=inst_class,
            )
            row["adaptive_gates"] = gates
            # Soft warn-flag when score is below adaptive threshold
            if row["score"] < gates["score_min"]:
                gate_tracker.reject(row["symbol"], "adaptive_score_min", {
                    "score": row["score"],
                    "threshold": gates["score_min"],
                    "vix": vix_level,
                    "instrument_class": inst_class,
                })
                row["adaptive_gate_warning"] = True
            else:
                row["adaptive_gate_warning"] = False

    # Sort by score descending, symbol ascending for tie-breaking
    scored.sort(key=lambda r: (-r["score"], r["symbol"]))

    # --- Tiered confidence ---
    all_scores = [r["score"] for r in scored]
    for row in scored:
        row["confidence_tier"] = classify_confidence_tier(
            row["score"], all_scores, row.get("warn_flags", ""),
        )

    ranked = scored[:top_n]

    # --- Log gate tracking summary (#10) ---
    if gate_tracker.rejection_count > 0:
        summary = gate_tracker.summary()
        logger.info(
            "Gate tracking: %d rejections across %d symbols — top gates: %s",
            summary["total_rejections"],
            len(summary["by_symbol"]),
            ", ".join(f"{g}({c})" for g, c in sorted(
                summary["by_gate"].items(), key=lambda x: -x[1]
            )[:5]),
        )

        # --- #2  Bottleneck detection ---
        total_input = len(quotes)
        bottlenecks = gate_tracker.bottleneck_report(total_input)
        for bn in bottlenecks:
            logger.warning(
                "⚠ BOTTLENECK: %s", bn["recommendation"],
            )

    return ranked, filtered_out

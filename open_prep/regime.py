"""Market regime classifier.

Detects risk-on / risk-off / rotation regimes from macro bias, VIX level,
and sector breadth.  Each regime produces a recommended weight adjustment
factor that the scorer can apply.

Also provides per-symbol regime detection (TRENDING / RANGING) via ADX
and Bollinger Band width (#12).
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .technical_analysis import detect_symbol_regime as _detect_symbol_regime
from .utils import to_float

logger = logging.getLogger("open_prep.regime")


# ---------------------------------------------------------------------------
# Regime enum values
# ---------------------------------------------------------------------------
REGIME_RISK_ON = "RISK_ON"
REGIME_RISK_OFF = "RISK_OFF"
REGIME_ROTATION = "ROTATION"
REGIME_NEUTRAL = "NEUTRAL"
_VALID_REGIMES = frozenset({REGIME_RISK_ON, REGIME_RISK_OFF, REGIME_ROTATION, REGIME_NEUTRAL})

# ---------------------------------------------------------------------------
# VIX thresholds — dead-zone of ±1 pt applied via _prev_regime to prevent
# flicker when VIX hovers close to a boundary.
# ---------------------------------------------------------------------------
VIX_LOW = 15.0
VIX_HIGH = 25.0
VIX_EXTREME = 35.0
_VIX_HYSTERESIS = 1.0  # require VIX to cross threshold by this margin to flip


@dataclass
class RegimeSnapshot:
    """Snapshot of the current market regime (plain dataclass — NOT frozen/immutable)."""

    regime: str  # RISK_ON | RISK_OFF | ROTATION | NEUTRAL
    vix_level: float | None
    macro_bias: float
    sector_breadth: float  # fraction of sectors positive (0..1)
    leading_sectors: list[str]
    lagging_sectors: list[str]
    weight_adjustments: dict[str, float]  # multiplier per score component
    reasons: list[str]
    # Optional CNN equity Fear & Greed snapshot (see
    # ``open_prep.sentiment_fng.fetch_cnn_equity_fear_greed``). Plumbed
    # through the snapshot for C5 sentiment-regime stratification — does
    # NOT alter regime classification or weight adjustments today.
    fear_greed: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "regime": self.regime,
            "vix_level": self.vix_level,
            "macro_bias": round(self.macro_bias, 4),
            "sector_breadth": round(self.sector_breadth, 4),
            "leading_sectors": self.leading_sectors,
            "lagging_sectors": self.lagging_sectors,
            "weight_adjustments": {k: round(v, 4) for k, v in self.weight_adjustments.items()},
            "reasons": self.reasons,
        }
        if self.fear_greed is not None:
            out["fear_greed"] = dict(self.fear_greed)
        return out


# ---------------------------------------------------------------------------
# Weight adjustment profiles per regime
# ---------------------------------------------------------------------------

# Multipliers applied to the base weights in the scorer
_WEIGHT_ADJ_RISK_ON: dict[str, float] = {
    "gap": 1.2,
    "gap_sector_relative": 0.8,
    "rvol": 1.1,
    "macro": 1.3,
    "momentum_z": 1.1,
    "earnings_bmo": 1.2,
    "ext_hours": 1.0,
    "freshness_decay": 0.8,
    "risk_off_penalty_multiplier": 0.5,
}

_WEIGHT_ADJ_RISK_OFF: dict[str, float] = {
    "gap": 0.5,
    "gap_sector_relative": 0.5,
    "rvol": 0.8,
    "macro": 1.5,
    "momentum_z": 0.6,
    "earnings_bmo": 0.8,
    "ext_hours": 0.7,
    "freshness_decay": 1.3,
    "risk_off_penalty_multiplier": 2.0,
    "liquidity_penalty": 2.0,
}

_WEIGHT_ADJ_ROTATION: dict[str, float] = {
    "gap": 0.7,
    "gap_sector_relative": 1.8,  # Sector-relative matters much more
    "rvol": 1.0,
    "macro": 0.8,
    "momentum_z": 1.3,
    "earnings_bmo": 1.0,
    "ext_hours": 1.0,
    "freshness_decay": 1.0,
}

_WEIGHT_ADJ_NEUTRAL: dict[str, float] = {}  # No adjustments

# Module-level previous regime for hysteresis (sticky guard)
_prev_regime: str | None = None
_prev_regime_lock = threading.Lock()


def reset_regime_state(seed: str | None = None) -> None:
    """Reset — or seed — the module-level hysteresis anchor.

    Call with no argument at session boundaries or test setUp to clear the
    anchor and prevent stale regime bleeding across pipeline runs in long-lived
    processes. Pass a known prior regime as *seed* to anchor the VIX dead-zone
    in :func:`classify_regime` so it can suppress boundary flicker within a
    session; an unknown value clears the anchor (identical to a plain reset).
    """
    global _prev_regime
    with _prev_regime_lock:
        _prev_regime = seed if seed in _VALID_REGIMES else None


# Two runs are the "same session" when their timestamps are within this window.
# Pre-open + RTH span ~12h; day-to-day runs are >=24h apart, so this cleanly
# separates intra-session dashboard refreshes from a fresh trading day.
_SAME_SESSION_MAX_AGE_HOURS = 12.0


def seed_regime_state(regime: str | None) -> None:
    """Seed the hysteresis anchor from a known prior regime.

    Thin alias over ``reset_regime_state(seed=regime)`` kept for call-site
    clarity (see :func:`reset_regime_state`).
    """
    reset_regime_state(seed=regime)


def _prior_regime_if_same_session(
    snapshot: dict[str, Any],
    now_utc: datetime | None = None,
) -> str | None:
    """Return the prior run's regime iff its snapshot is from the same session.

    ``snapshot`` is the persisted previous-run payload (``diff.save_result_snapshot``)
    carrying ``regime`` and ``ts`` (the run's ``generated_at`` ISO timestamp).
    Returns ``None`` — meaning "reset, do not seed" — when the regime/ts are
    missing, unparseable, in the future (clock skew), or older than
    ``_SAME_SESSION_MAX_AGE_HOURS`` (a different trading session).
    """
    prior = snapshot.get("regime")
    ts = snapshot.get("ts")
    if prior not in _VALID_REGIMES or not isinstance(ts, str):
        return None
    try:
        prior_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if prior_dt.tzinfo is None:
        prior_dt = prior_dt.replace(tzinfo=UTC)
    now = now_utc or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    age_hours = (now - prior_dt).total_seconds() / 3600.0
    if 0.0 <= age_hours < _SAME_SESSION_MAX_AGE_HOURS:
        return prior
    return None


def seed_regime_hysteresis_from_prior_run(now_utc: datetime | None = None) -> str | None:
    """Seed the regime hysteresis from the prior run's persisted regime.

    Replaces the unconditional :func:`reset_regime_state` at the head of the
    pipeline. The anti-flicker VIX dead-zone in :func:`classify_regime` needs a
    prior regime, but every ``generate_open_prep_result`` call — including each
    streamlit dashboard refresh — otherwise wiped it, so the regime (and the
    regime-adjusted scoring weights) flickered when VIX hovered near a threshold.
    The diff snapshot already persists the prior run's regime; seed from it when
    the run is in the same session, else reset (no stale cross-session bleed).

    Fails safe: any error loading/parsing the snapshot resets the anchor,
    exactly matching the previous ``reset_regime_state`` behaviour. Returns the
    seeded regime (or ``None`` when reset) for logging/tests.
    """
    prior_regime: str | None = None
    try:
        from .diff import load_previous_snapshot  # lazy: avoid an import cycle at module load

        snapshot = load_previous_snapshot()
        if isinstance(snapshot, dict):
            prior_regime = _prior_regime_if_same_session(snapshot, now_utc)
    except Exception as exc:  # fail-safe: any snapshot error resets the anchor, exactly like reset_regime_state()
        logger.debug("regime hysteresis seed failed, resetting anchor: %s", exc)
        prior_regime = None
    seed_regime_state(prior_regime)
    return prior_regime


def classify_regime(
    *,
    macro_bias: float,
    vix_level: float | None = None,
    sector_performance: list[dict[str, Any]] | None = None,
    fear_greed: dict[str, Any] | None = None,
) -> RegimeSnapshot:
    """Classify the current market regime.

    Includes hysteresis (DORMANT in prod: reset_regime_state()+single call keep
    ``_prev_regime`` None): retains the prior regime near a VIX boundary.

    Parameters
    ----------
    macro_bias : float
        Current macro bias score from -1 to +1.
    vix_level : float | None
        Current VIX level. If unavailable, regime relies on macro bias
        and sector breadth only.
    sector_performance : list[dict]
        Sector performance rows with ``sector`` and ``changesPercentage``.
    """
    global _prev_regime
    sectors = sector_performance or []
    reasons: list[str] = []

    # --- Sector breadth ---
    positive_sectors = [s for s in sectors if to_float(s.get("changesPercentage")) > 0.0]
    total = len(sectors) or 1
    breadth = len(positive_sectors) / total

    leading = [s.get("sector", "?") for s in sectors if to_float(s.get("changesPercentage")) > 0.5]
    lagging = [s.get("sector", "?") for s in sectors if to_float(s.get("changesPercentage")) < -0.5]

    # --- Classification logic ---
    regime = REGIME_NEUTRAL
    vix = vix_level

    # Strong risk-off signals
    if vix is not None and vix >= VIX_EXTREME:
        regime = REGIME_RISK_OFF
        reasons.append(f"VIX extreme ({vix:.1f} >= {VIX_EXTREME})")
    elif macro_bias <= -0.5:
        regime = REGIME_RISK_OFF
        reasons.append(f"Macro bias strongly negative ({macro_bias:.2f})")
    elif vix is not None and vix >= VIX_HIGH and macro_bias < 0:
        regime = REGIME_RISK_OFF
        reasons.append(f"VIX elevated ({vix:.1f}) + negative bias ({macro_bias:.2f})")

    # Rotation: mixed breadth, not clearly risk-on or risk-off
    elif 0.3 <= breadth <= 0.7 and len(leading) >= 2 and len(lagging) >= 2:
        regime = REGIME_ROTATION
        reasons.append(f"Sector breadth mixed ({breadth:.0%}): {len(leading)} leading, {len(lagging)} lagging")

    # Risk-on: broad participation
    elif macro_bias >= 0.3 and breadth >= 0.6:
        regime = REGIME_RISK_ON
        reasons.append(f"Macro bias positive ({macro_bias:.2f}) + broad breadth ({breadth:.0%})")
    elif vix is not None and vix <= VIX_LOW and macro_bias >= 0:
        regime = REGIME_RISK_ON
        reasons.append(f"VIX low ({vix:.1f}) + non-negative bias ({macro_bias:.2f})")
    elif breadth >= 0.75:
        regime = REGIME_RISK_ON
        reasons.append(f"Very broad sector breadth ({breadth:.0%})")

    # Default: NEUTRAL
    else:
        reasons.append(f"No clear regime signal (bias={macro_bias:.2f}, breadth={breadth:.0%})")

    # Select weight adjustments
    adj_map = {
        REGIME_RISK_ON: _WEIGHT_ADJ_RISK_ON,
        REGIME_RISK_OFF: _WEIGHT_ADJ_RISK_OFF,
        REGIME_ROTATION: _WEIGHT_ADJ_ROTATION,
        REGIME_NEUTRAL: _WEIGHT_ADJ_NEUTRAL,
    }

    # --- Hysteresis: if VIX is within dead-zone of a threshold, keep previous ---
    with _prev_regime_lock:
        if _prev_regime is not None and regime != _prev_regime and vix is not None:
            in_dead_zone = (
                abs(vix - VIX_LOW) < _VIX_HYSTERESIS
                or abs(vix - VIX_HIGH) < _VIX_HYSTERESIS
                or abs(vix - VIX_EXTREME) < _VIX_HYSTERESIS
            )
            if in_dead_zone:
                regime = _prev_regime
                reasons.append(f"VIX hysteresis: keeping {regime} (VIX {vix:.1f} in dead-zone)")

        _prev_regime = regime

    # --- Optional sentiment annotation (no behavioural effect) ---
    # We attach the CNN equity F&G snapshot to the result and add a
    # human-readable reason. C5 stratification can later use this field
    # to bucket trades by sentiment regime; deliberately NOT used to
    # override the VIX/macro/breadth regime here.
    fng_payload: dict[str, Any] | None = None
    if isinstance(fear_greed, dict):
        raw_value = fear_greed.get("value")
        if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
            value_f = float(raw_value)
            if 0.0 <= value_f <= 100.0:
                fng_payload = dict(fear_greed)
                label = fear_greed.get("label") or "?"
                reasons.append(f"F&G={value_f:.0f} ({label}) [annotation only]")

    return RegimeSnapshot(
        regime=regime,
        vix_level=vix,
        macro_bias=macro_bias,
        sector_breadth=breadth,
        leading_sectors=leading,
        lagging_sectors=lagging,
        weight_adjustments=adj_map.get(regime, {}),
        reasons=reasons,
        fear_greed=fng_payload,
    )


def apply_regime_adjustments(
    base_weights: dict[str, float],
    regime: RegimeSnapshot,
) -> dict[str, float]:
    """Return a copy of base_weights multiplied by regime adjustments."""
    adjusted = dict(base_weights)
    for key, multiplier in regime.weight_adjustments.items():
        if key in adjusted:
            adjusted[key] = adjusted[key] * multiplier
    return adjusted


# ---------------------------------------------------------------------------
# Per-Symbol Regime Detection (#12)
# ---------------------------------------------------------------------------

# Weight adjustments for per-symbol TRENDING regime
_WEIGHT_ADJ_SYMBOL_TRENDING: dict[str, float] = {
    "momentum_z": 1.5,       # Trend signal more reliable
    "rvol": 1.2,             # Volume confirms trend
    "gap": 1.2,              # Gap with trend = higher conviction
    "freshness_decay": 0.7,  # Trend persists → less freshness sensitivity
}

# Weight adjustments for per-symbol RANGING regime
_WEIGHT_ADJ_SYMBOL_RANGING: dict[str, float] = {
    "momentum_z": 0.7,       # Momentum whipsaws in range
    "rvol": 0.9,             # Volume less meaningful
    "gap": 0.8,              # Gaps often filled in range
    "vwap_distance": 1.3,    # Mean-reversion more reliable
    "freshness_decay": 1.2,  # Recency matters more
}


@dataclass
class SymbolRegimeInfo:
    """Per-symbol regime classification result."""

    symbol: str
    regime: str  # "TRENDING" | "RANGING" | "NEUTRAL"
    adx: float
    bb_width_pct: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "regime": self.regime,
            "adx": round(self.adx, 2),
            "bb_width_pct": round(self.bb_width_pct, 2),
        }


def classify_symbol_regime(
    symbol: str,
    adx: float,
    bb_width_pct: float,
) -> SymbolRegimeInfo:
    """Classify a single symbol as TRENDING, RANGING, or NEUTRAL.

    Delegates to ``technical_analysis.detect_symbol_regime`` for the logic. Note (2026-07-08): unused in production — the scorer uses ``technical_analysis.resolve_regime_weights`` with different multipliers instead of this per-symbol regime path.
    """
    regime = _detect_symbol_regime(adx, bb_width_pct)
    return SymbolRegimeInfo(
        symbol=symbol,
        regime=regime,
        adx=adx,
        bb_width_pct=bb_width_pct,
    )


def apply_symbol_regime_adjustments(
    base_weights: dict[str, float],
    symbol_regime: str,
) -> dict[str, float]:
    """Adjust scorer weights based on per-symbol regime. Note (2026-07-08): unused in production — the scorer uses ``technical_analysis.resolve_regime_weights`` with different multipliers; the ``_WEIGHT_ADJ_SYMBOL_*`` tables above are a parallel, non-live adjustment table.

    Parameters
    ----------
    base_weights : dict
        Current weight set (might already be adjusted for market regime).
    symbol_regime : str
        ``"TRENDING"``, ``"RANGING"``, or ``"NEUTRAL"`` from ``classify_symbol_regime``.

    Returns
    -------
    dict
        Adjusted weight set.  ``NEUTRAL`` returns weights unchanged.
    """
    if symbol_regime == "NEUTRAL":
        return dict(base_weights)
    adj = _WEIGHT_ADJ_SYMBOL_TRENDING if symbol_regime == "TRENDING" else _WEIGHT_ADJ_SYMBOL_RANGING
    adjusted = dict(base_weights)
    for key, mult in adj.items():
        if key in adjusted:
            adjusted[key] = adjusted[key] * mult
    return adjusted

"""Phase C — Reaction Zone for Liquidity Sweeps.

After a sweep trap is identified (Phase B), the *reaction zone* is the price
range within which price must close back to confirm a genuine reclaim, as
opposed to a wick-only test.  Confirmation of the reaction zone is a strong
filter: sweeps that close back *inside* the zone with a meaningful body and
minimal wick have historically much higher reversal follow-through rates than
bare wick tests.

This module provides:

* :class:`ReactionZone` — enrichment payload added to the liquidity-sweep
  context when ``ENABLE_REACTION_ZONE=1``.
* :func:`compute_reaction_zone` — pure-math computation; no I/O.

Integration
-----------
Called inside :func:`~smc_integration.measurement_evidence._liquidity_support_for_event`
after :func:`~smc_core.sweep_trap.classify_sweep_trap` when Phase C is enabled.
The reaction zone fields gate the trap quality score: an unconfirmed zone
discounts ``trap_quality_score`` by 50%.

Phase C depends on Phase B (sweep trap must be active for the zone to be
meaningful).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from smc_core.v2_config import reaction_zone_config
from smc_core.v2_features import reaction_zone_enabled


@dataclass(frozen=True, slots=True)
class ReactionZone:
    """Reaction zone descriptor for a liquidity sweep reclaim.

    Parameters
    ----------
    reaction_zone_low:
        Lower boundary of the reaction zone (in price units).  For a bullish
        sweep reclaim, this is the swept level minus one ATR-fraction; for a
        bearish reclaim it is the swept level.
    reaction_zone_high:
        Upper boundary of the reaction zone.
    close_back_inside_zone:
        ``True`` if the reclaim bar's close falls within
        ``[reaction_zone_low, reaction_zone_high]``.
    wick_rejection_ratio:
        Ratio of the wick beyond the zone boundary to the total candle range,
        0.0–1.0.  High values indicate the close is near the boundary with a
        long wick (weak confirmation); low values indicate a clean body close.
    confirmation_body_ratio:
        Body size as a fraction of the total candle range on the reclaim bar,
        0.0–1.0.  High values (≥ 0.6) indicate a strong body confirmation.
    bars_to_confirm:
        Number of bars from the sweep extreme to the first confirming close
        inside the reaction zone.  ``-1`` if no confirming close occurred.
    """

    reaction_zone_low: float
    reaction_zone_high: float
    close_back_inside_zone: bool
    wick_rejection_ratio: float
    confirmation_body_ratio: float
    bars_to_confirm: int


# ---------------------------------------------------------------------------
# Zone sizing defaults
# ---------------------------------------------------------------------------

#: Reaction zone width as a fraction of the sweep body (swept_level →
#: sweep_extreme distance).  ``0.382`` corresponds to the 38.2% Fibonacci level —
#: a common institutional reclaim target.
ZONE_WIDTH_FRACTION: float = 0.382

#: Minimum body-to-range ratio for a close to count as "confirmation".
MIN_CONFIRMATION_BODY_RATIO: float = 0.30


def compute_reaction_zone(
    *,
    swept_level: float,
    sweep_extreme: float,
    is_bullish_sweep: bool,
    post_sweep_bars: Sequence[dict[str, Any]],
) -> ReactionZone:
    """Compute the reaction zone and check for price confirmation.

    Parameters
    ----------
    swept_level:
        Prior swing high (bullish) or swing low (bearish) that was swept.
    sweep_extreme:
        Most extreme price reached by the sweep candle.
    is_bullish_sweep:
        ``True`` if price swept *above* a prior high.
    post_sweep_bars:
        Sequence of OHLC dicts for bars after the sweep candle.

    Returns
    -------
    ReactionZone
        Fully populated reaction zone descriptor.  If no bars are supplied,
        all confirmation fields default to ``False`` / ``-1`` / ``0.0``.
    """
    sweep_body: float = abs(swept_level - sweep_extreme)
    zone_width: float = sweep_body * ZONE_WIDTH_FRACTION if sweep_body > 1e-10 else 0.0

    # Define zone boundaries relative to the swept level.
    if is_bullish_sweep:
        # Reclaim = price falls back below swept_level.
        # Reaction zone: [swept_level - zone_width, swept_level]
        zone_low: float = swept_level - zone_width
        zone_high: float = swept_level
    else:
        # Reclaim = price rises back above swept_level.
        # Reaction zone: [swept_level, swept_level + zone_width]
        zone_low = swept_level
        zone_high = swept_level + zone_width

    if not post_sweep_bars:
        return ReactionZone(
            reaction_zone_low=zone_low,
            reaction_zone_high=zone_high,
            close_back_inside_zone=False,
            wick_rejection_ratio=0.0,
            confirmation_body_ratio=0.0,
            bars_to_confirm=-1,
        )

    confirm_bar_idx: int = -1
    confirm_wick_ratio: float = 0.0
    confirm_body_ratio: float = 0.0

    for idx, bar in enumerate(post_sweep_bars):
        close: float = float(bar["close"])
        high: float = float(bar["high"])
        low: float = float(bar["low"])
        open_: float = float(bar["open"])

        # Check: close falls inside the zone.
        if zone_low <= close <= zone_high:
            candle_range: float = high - low
            if candle_range < 1e-10:
                confirm_body_ratio = 1.0
                confirm_wick_ratio = 0.0
            else:
                body: float = abs(close - open_)
                confirm_body_ratio = body / candle_range

                # Wick beyond zone boundary.
                if is_bullish_sweep:
                    wick_beyond: float = max(0.0, high - zone_high)
                else:
                    wick_beyond = max(0.0, zone_low - low)
                confirm_wick_ratio = wick_beyond / candle_range

            if confirm_body_ratio >= MIN_CONFIRMATION_BODY_RATIO:
                confirm_bar_idx = idx + 1  # 1-indexed
                break

    close_back: bool = confirm_bar_idx >= 1

    return ReactionZone(
        reaction_zone_low=zone_low,
        reaction_zone_high=zone_high,
        close_back_inside_zone=close_back,
        wick_rejection_ratio=confirm_wick_ratio,
        confirmation_body_ratio=confirm_body_ratio,
        bars_to_confirm=confirm_bar_idx,
    )


def detect_reaction_zone(enrichment: dict[str, Any] | None = None) -> dict[str, Any]:
    """Detect a reaction-zone context from enrichment data.

    This detector-style API is retained for v2 integration tests while
    ``compute_reaction_zone`` remains the canonical Phase C computation used
    by measurement evidence.
    """
    neutral = {
        "REACTION_ZONE_DETECTED": False,
        "REACTION_ZONE_CONFIDENCE": 0,
        "REACTION_ZONE_DIRECTION": "neutral",
    }

    if not reaction_zone_enabled():
        return neutral

    enr = enrichment or {}

    ssl = enr.get("structure_state_light") or {}
    last_event = str(ssl.get("STRUCTURE_LAST_EVENT", "NONE"))
    structure_fresh = bool(ssl.get("STRUCTURE_FRESH", False))

    ob_light = enr.get("ob_context_light") or {}
    ob_fresh = bool(ob_light.get("OB_FRESH", False))
    ob_distance = float(ob_light.get("PRIMARY_OB_DISTANCE", 99.0))
    ob_side = str(ob_light.get("PRIMARY_OB_SIDE", "NONE"))

    fvg_light = enr.get("fvg_lifecycle_light") or {}
    fvg_fresh = bool(fvg_light.get("FVG_FRESH", False))
    fvg_distance = float(fvg_light.get("PRIMARY_FVG_DISTANCE", 99.0))
    fvg_side = str(fvg_light.get("PRIMARY_FVG_SIDE", "NONE"))

    ls = enr.get("liquidity_sweeps") or {}
    recent_bull_sweep = ls.get("RECENT_BULL_SWEEP", False)
    recent_bear_sweep = ls.get("RECENT_BEAR_SWEEP", False)
    has_sweep = bool(recent_bull_sweep) or bool(recent_bear_sweep)
    sweep_direction = str(ls.get("SWEEP_DIRECTION", "NONE"))

    scl = enr.get("session_context_light") or {}
    sc = enr.get("session_context") or {}
    session_bias = str(
        _prefer_lean_value(scl, sc, "SESSION_DIRECTION_BIAS", "NEUTRAL")
    ).upper()

    if not (structure_fresh or has_sweep):
        return neutral

    threshold = reaction_zone_config.distance_threshold_pct
    has_near_support = (
        (ob_fresh and ob_distance < threshold)
        or (fvg_fresh and fvg_distance < threshold)
    )
    if not has_near_support:
        return neutral

    direction = "neutral"
    if ob_side in ("BULL", "BEAR"):
        direction = ob_side.lower()
    elif fvg_side in ("BULL", "BEAR"):
        direction = fvg_side.lower()
    elif sweep_direction in ("BULL", "BEAR"):
        direction = sweep_direction.lower()
    elif last_event in ("BOS_BULL", "CHOCH_BULL"):
        direction = "bull"
    elif last_event in ("BOS_BEAR", "CHOCH_BEAR"):
        direction = "bear"

    bias_aligned = (
        (direction == "bull" and session_bias == "BULLISH")
        or (direction == "bear" and session_bias == "BEARISH")
    )
    confidence = (
        reaction_zone_config.bias_aligned_confidence
        if bias_aligned
        else reaction_zone_config.bias_misaligned_confidence
    )

    return {
        "REACTION_ZONE_DETECTED": True,
        "REACTION_ZONE_CONFIDENCE": confidence,
        "REACTION_ZONE_DIRECTION": direction,
    }


def _prefer_lean_value(
    primary: dict[str, Any],
    fallback: dict[str, Any],
    key: str,
    default: Any,
) -> Any:
    if key in primary:
        return primary[key]
    return fallback.get(key, default)

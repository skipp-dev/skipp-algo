"""Phase C — Reaction to a Liquidity Sweep.

After a sweep (Phase B), two INDEPENDENT signals are measured — never conflated:

* ``level_reclaimed`` — the authoritative reversal confirmation: price CLOSES
  back through the swept level in the reversal direction (bull: ``close >=
  swept_level``; bear: ``close <= swept_level``). This is the same "reclaim"
  meaning used by :mod:`smc_core.sweep_trap` and the
  :func:`smc_core.scoring.label_sweep_reversal` outcome label — and it is
  UNBOUNDED on the favourable side, so a strong reclaim counts (it is not capped
  at the level).
* ``close_in_rejection_band`` — OBSERVATION ONLY: a close that recovered into a
  narrow band on the swept (penetration) side WITHOUT reclaiming the level. An
  *early rejection* candidate, never treated as a reclaim. The band is HALF-OPEN
  at the level (bull: ``[level - w, level)``; bear: ``(level, level + w]``) so a
  close exactly ON ``swept_level`` is a reclaim, never "in the band" — the two
  raw signals are therefore strictly disjoint.

Three DISTINCT reclaim-related thresholds live in this subsystem — do not conflate:
  * this module's level-touch (``close >= / <= swept_level`` — inclusive of the level);
  * :mod:`smc_core.sweep_trap`'s strict level-cross (``close > / < swept_level``);
  * :func:`smc_core.scoring.label_sweep_reversal`'s OUTCOME, which additionally
    requires ~0.5% follow-through past the level (``threshold_pct`` default).

Both are recorded raw; neither gates live scoring (Phase C is observe-only).
Since 2026-07-13 the study and the context detector have SEPARATE flags
(``ENABLE_REACTION_ZONE_STUDY`` gates :func:`compute_reaction_zone`;
``ENABLE_REACTION_CONTEXT`` gates :func:`detect_reaction_zone`). The study gate
additionally differs by CONSUMER:
  * the ledger-emission path (``measurement_evidence._evaluate_sweep_event``) runs
    on the study flag alone;
  * the liquidity-enrichment path (``measurement_evidence._liquidity_support_for_event``)
    computes it only when ``ENABLE_SWEEP_TRAP`` is ALSO on — it is nested inside the
    Phase B block, so with the study on but sweep-trap off it never runs there.
The follow-up study will compare the two signals' follow-through predictive power on
a leakage-free window.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from smc_core.v2_config import reaction_zone_config
from smc_core.v2_features import reaction_context_enabled


@dataclass(frozen=True, slots=True)
class ReactionZone:
    """Reaction descriptor for a liquidity sweep — two independent signals.

    ``level_reclaimed`` is the authoritative reversal confirmation; the
    ``rejection_band``/``close_in_rejection_band`` fields are an observation-only
    early-rejection signal (a recovery that stopped short of the level). The
    remaining fields are raw quantities (measured at the reclaim bar) that the
    follow-up follow-through study consumes; nothing here gates live scoring.
    """

    # Rejection band (penetration side; OBSERVATION only, NOT a reclaim).
    rejection_band_low: float
    rejection_band_high: float
    close_in_rejection_band: bool
    bars_to_rejection_band: int

    # Level reclaim (the authoritative reversal confirmation).
    level_reclaimed: bool
    bars_to_reclaim: int
    close_distance_pct: float  # non-negative reclaim distance: 0.0 pre-reclaim, >0 past the level (rename->reclaim_distance_pct pending)
    body_ratio: float  # |close-open| / range at the reclaim bar
    directional_body: bool  # reclaim bar body in the reversal direction
    rejection_wick_ratio: float  # swept-side wick at the reclaim bar (bull: lower, bear: upper)


ZONE_WIDTH_FRACTION: float = 0.382


def compute_reaction_zone(
    *,
    swept_level: float,
    sweep_extreme: float,
    is_bullish_sweep: bool,
    post_sweep_bars: Sequence[dict[str, Any]],
) -> ReactionZone:
    """Measure a sweep's reaction: level-reclaim (authoritative) + rejection band.

    ``sweep_extreme`` is the sweep bar's extreme on the swept side (bar low for a
    bullish/sell-side sweep, bar high for a bearish/buy-side sweep), so it lies on
    the far side of ``swept_level`` from the reversal. ``level_reclaimed`` fires on
    the first post-sweep bar that closes back through ``swept_level`` in the
    reversal direction (unbounded — a strong reclaim counts). ``close_in_rejection
    _band`` fires on the first close inside the HALF-OPEN band ``[swept_level - w,
    swept_level)`` (bull) / ``(swept_level, swept_level + w]`` (bear), ``w = 0.382
    * sweep penetration`` where the penetration is ``|swept_level - sweep_extreme|``
    (the level→extreme excursion, NOT the sweep candle's open-close body, which is
    not available here) — a recovery that stopped short of the level (observation
    only, not a reclaim). A close exactly on ``swept_level`` is excluded from the
    band (it is a reclaim), keeping the two signals disjoint.
    """
    sweep_penetration: float = abs(swept_level - sweep_extreme)
    band_width: float = sweep_penetration * ZONE_WIDTH_FRACTION if sweep_penetration > 1e-10 else 0.0

    if is_bullish_sweep:
        band_low: float = swept_level - band_width
        band_high: float = swept_level
    else:
        band_low = swept_level
        band_high = swept_level + band_width

    reclaimed: bool = False
    bars_to_reclaim: int = -1
    close_distance_pct: float = 0.0
    body_ratio: float = 0.0
    directional_body: bool = False
    rejection_wick_ratio: float = 0.0
    in_band: bool = False
    bars_to_band: int = -1

    for idx, bar in enumerate(post_sweep_bars):
        close: float = float(bar["close"])
        high: float = float(bar["high"])
        low: float = float(bar["low"])
        open_: float = float(bar["open"])

        # Half-open at the level: a close exactly on ``swept_level`` is a reclaim
        # (handled below), never "recovered short of it", so the band and the
        # reclaim signal stay strictly disjoint (bull: [low, level); bear: (level, high]).
        in_zone: bool = (
            band_low <= close < swept_level if is_bullish_sweep else swept_level < close <= band_high
        )
        if not in_band and in_zone:
            in_band = True
            bars_to_band = idx + 1

        reclaim_hit: bool = close >= swept_level if is_bullish_sweep else close <= swept_level
        if not reclaimed and reclaim_hit:
            reclaimed = True
            bars_to_reclaim = idx + 1
            raw_dist: float = (close - swept_level) if is_bullish_sweep else (swept_level - close)
            close_distance_pct = (raw_dist / swept_level * 100.0) if swept_level > 1e-10 else 0.0
            candle_range: float = high - low
            if candle_range < 1e-10:
                # Zero-range (flat) candle: |close-open| is 0, so there is no body
                # and no wick. 1.0 would falsely signal maximum body quality.
                body_ratio = 0.0
                rejection_wick_ratio = 0.0
            else:
                body_ratio = abs(close - open_) / candle_range
                # Rejection wick = the tail on the SWEPT side (bull: lower, bear: upper).
                if is_bullish_sweep:
                    wick: float = min(open_, close) - low
                else:
                    wick = high - max(open_, close)
                rejection_wick_ratio = max(0.0, wick) / candle_range
            directional_body = (close > open_) if is_bullish_sweep else (close < open_)

        if in_band and reclaimed:
            break

    return ReactionZone(
        rejection_band_low=band_low,
        rejection_band_high=band_high,
        close_in_rejection_band=in_band,
        bars_to_rejection_band=bars_to_band,
        level_reclaimed=reclaimed,
        bars_to_reclaim=bars_to_reclaim,
        close_distance_pct=close_distance_pct,
        body_ratio=body_ratio,
        directional_body=directional_body,
        rejection_wick_ratio=rejection_wick_ratio,
    )


def detect_reaction_zone(enrichment: dict[str, Any] | None = None) -> dict[str, Any]:
    """Detect a reaction *context* from enrichment data (NOT the reclaim measurer).

    ``REACTION_CONTEXT_DETECTED`` means only that a fresh structure/sweep sits
    near an OB or FVG in a bias-aligned direction — it inspects NO swept level,
    extreme, post-sweep close, reclaim, or rejection band. It is a semantically
    different feature from :func:`compute_reaction_zone` (the canonical Phase C
    reclaim/band measurer used by measurement evidence). Since 2026-07-13 the two
    have separate flags: this detector is gated by ``ENABLE_REACTION_CONTEXT``
    (:func:`smc_core.v2_features.reaction_context_enabled`), the study by
    ``ENABLE_REACTION_ZONE_STUDY``; the old ``ENABLE_REACTION_ZONE`` still arms
    both.

    Output keys are ``REACTION_CONTEXT_DETECTED`` / ``_CONFIDENCE`` /
    ``_DIRECTION``. (The legacy ``REACTION_ZONE_*`` alias keys were dropped once
    their deprecation window closed — they had no consumer.) This detector-style
    API is retained for v2 integration tests.
    """
    neutral = {
        "REACTION_CONTEXT_DETECTED": False,
        "REACTION_CONTEXT_CONFIDENCE": 0,
        "REACTION_CONTEXT_DIRECTION": "neutral",
    }

    if not reaction_context_enabled():
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
    # Static alignment TIER, not a probability: a configured constant (default 60
    # aligned / 40 misaligned) — rename-later: REACTION_ZONE_HEURISTIC_SCORE.
    confidence = (
        reaction_zone_config.bias_aligned_confidence
        if bias_aligned
        else reaction_zone_config.bias_misaligned_confidence
    )

    return {
        "REACTION_CONTEXT_DETECTED": True,
        "REACTION_CONTEXT_CONFIDENCE": confidence,
        "REACTION_CONTEXT_DIRECTION": direction,
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

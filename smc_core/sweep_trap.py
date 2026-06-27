"""Phase B — Sweep Trap Classifier + SMC v2 enrichment wrapper.

A *sweep trap* (also: stop-hunt reversal, liquidity trap) occurs when price
sweeps a prior swing high/low to trigger resting orders, then reclaims the
swept level, trapping the breakout traders.  The quality of the reclaim — how
fast, how strongly, how deeply price reverses — is a leading indicator of
whether the sweep will produce a meaningful follow-through reversal.

This module provides:

* :class:`SweepTrapResult` — enrichment payload added to the liquidity-sweep
  context when ``ENABLE_SWEEP_TRAP=1``.
* :func:`classify_sweep_trap` — deterministic, pure-math classification; no
  I/O, no global state.
* :func:`detect_sweep_trap` — SMC v2 signal-quality enrichment wrapper that
  reads the lean ``liquidity_sweeps`` block and returns a neutral/detected
  verdict with a 0-100 confidence score.

Integration point
-----------------
:func:`~smc_integration.measurement_evidence._liquidity_support_for_event`
calls :func:`classify_sweep_trap` when the best sweep found for an event has
``ENABLE_SWEEP_TRAP`` enabled.  The result fields are merged into the liquidity
enrichment payload and propagated to ``label_sweep_reversal`` in
``smc_core/scoring.py`` for calibration.

:func:`detect_sweep_trap` is consumed by ``scripts/smc_signal_quality.py``
when ``SIGNAL_QUALITY_MODEL=v2`` or ``ENABLE_SWEEP_TRAP=1``.

Phase B is *parallel-safe* with Phase A (event_freshness) — neither depends on
the other at the enrichment level.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from smc_core.v2_config import sweep_trap_config
from smc_core.v2_features import sweep_trap_enabled

TrapType = Literal["immediate", "delayed", "failed"]

#: Maximum bars within which a "reclaim" is classified as *immediate*.
IMMEDIATE_RECLAIM_BARS: int = 3

#: Maximum bars for a *delayed* reclaim; anything beyond = *failed*.
DELAYED_RECLAIM_BARS: int = 12

#: Minimum close-back-above/below fraction of the sweep body to count as a
#: reclaim.  Below this threshold the close is a wick test, not a reclaim.
MIN_RECLAIM_CLOSE_FRACTION: float = 0.50


@dataclass(frozen=True, slots=True)
class SweepTrapResult:
    """Enrichment payload for Sweep Trap classification.

    Parameters
    ----------
    sweep_reclaim_bars:
        Number of bars from the sweep extreme to the first bar that closes
        back inside the swept level.  ``-1`` if no reclaim occurred within
        the look-ahead window (``trap_type="failed"``).
    trap_type:
        ``"immediate"`` — reclaim within 3 bars of the sweep.
        ``"delayed"`` — reclaim within 4–12 bars.
        ``"failed"`` — no reclaim within 12 bars or within the available data.
    reclaim_strength:
        0.0–1.0.  Fraction of the sweep body recovered on the reclaim bar(s).
        Computed as ``(close_reclaim - sweep_extreme) / (swept_level -
        sweep_extreme)``, clipped to [0, 1].  ``0.0`` for failed traps.
    fib_retrace_depth:
        0.0–1.0.  How deeply price retraced from the swept level back toward
        the pre-sweep origin before reversing.  ``0.0`` = no retrace (price
        went straight to the extreme), ``1.0`` = full retrace back to origin.
        Used to distinguish high-probability traps (deep retrace → clean
        rejection) from shallow tests.
    trap_quality_score:
        0.0–1.0 composite quality score.  Inputs: ``trap_type`` weight ×
        ``reclaim_strength`` × ``fib_retrace_depth`` blend.  Becomes
        ``SWEEP_TRAP_QUALITY_SCORE`` in the liquidity enrichment payload.
    """

    sweep_reclaim_bars: int
    trap_type: TrapType
    reclaim_strength: float
    fib_retrace_depth: float
    trap_quality_score: float


# ---------------------------------------------------------------------------
# Public classifier
# ---------------------------------------------------------------------------


def classify_sweep_trap(
    *,
    swept_level: float,
    sweep_extreme: float,
    origin_level: float,
    is_bullish_sweep: bool,
    post_sweep_bars: Sequence[dict[str, Any]],
) -> SweepTrapResult:
    """Classify the quality of a sweep trap from raw bar data.

    Parameters
    ----------
    swept_level:
        The prior swing high (bullish sweep) or swing low (bearish sweep)
        that was violated by the sweep.
    sweep_extreme:
        The most extreme price reached by the sweep candle (high for
        bullish sweeps, low for bearish sweeps).
    origin_level:
        Price level at the origin of the move leading to the sweep — used
        to measure ``fib_retrace_depth``.
    is_bullish_sweep:
        ``True`` if the sweep broke *above* a prior high (trapping longs
        who bought the breakout); ``False`` for a bearish sweep.
    post_sweep_bars:
        Sequence of OHLC dicts with keys ``"open"``, ``"high"``, ``"low"``,
        ``"close"`` for bars *after* the sweep candle.  The look-ahead window
        is determined by the length of this sequence (typically capped at
        ``DELAYED_RECLAIM_BARS + 1`` by the caller).

    Returns
    -------
    SweepTrapResult
        Fully populated trap classification.
    """
    sweep_body: float = abs(swept_level - sweep_extreme)
    if sweep_body < 1e-10:
        # Degenerate sweep — zero-body candle; classify as failed.
        return SweepTrapResult(
            sweep_reclaim_bars=-1,
            trap_type="failed",
            reclaim_strength=0.0,
            fib_retrace_depth=0.0,
            trap_quality_score=0.0,
        )

    fib_range: float = abs(swept_level - origin_level)

    reclaim_bar_idx: int = -1
    best_reclaim_close: float | None = None

    for idx, bar in enumerate(post_sweep_bars):
        close: float = float(bar["close"])
        if is_bullish_sweep:
            # Bearish reclaim: close back *below* swept_level
            if close < swept_level:
                reclaim_bar_idx = idx
                best_reclaim_close = close
                break
        else:
            # Bullish reclaim: close back *above* swept_level
            if close > swept_level:
                reclaim_bar_idx = idx
                best_reclaim_close = close
                break

    if reclaim_bar_idx == -1 or best_reclaim_close is None:
        return SweepTrapResult(
            sweep_reclaim_bars=-1,
            trap_type="failed",
            reclaim_strength=0.0,
            fib_retrace_depth=0.0,
            trap_quality_score=0.0,
        )

    # Reclaim found — classify type.
    bars_to_reclaim: int = reclaim_bar_idx + 1  # 1-indexed
    if bars_to_reclaim <= IMMEDIATE_RECLAIM_BARS:
        trap_type: TrapType = "immediate"
        type_weight: float = 1.0
    elif bars_to_reclaim <= DELAYED_RECLAIM_BARS:
        trap_type = "delayed"
        # Linear decay from 0.8 at bar 4 → 0.5 at bar 12.
        type_weight = 0.8 - 0.3 * (bars_to_reclaim - IMMEDIATE_RECLAIM_BARS) / (
            DELAYED_RECLAIM_BARS - IMMEDIATE_RECLAIM_BARS
        )
    else:
        return SweepTrapResult(
            sweep_reclaim_bars=bars_to_reclaim,
            trap_type="failed",
            reclaim_strength=0.0,
            fib_retrace_depth=0.0,
            trap_quality_score=0.0,
        )

    # Reclaim strength: fraction of sweep body recovered.
    if is_bullish_sweep:
        recovered: float = swept_level - best_reclaim_close
    else:
        recovered = best_reclaim_close - swept_level
    reclaim_strength: float = max(0.0, min(1.0, recovered / sweep_body))

    # Fib retrace depth: how deeply did price retrace from swept_level toward origin?
    if fib_range < 1e-10:
        fib_retrace_depth: float = 0.0
    else:
        if is_bullish_sweep:
            # How far did the extreme go above origin_level (before reversing)?
            depth: float = (sweep_extreme - swept_level) / fib_range
        else:
            depth = (swept_level - sweep_extreme) / fib_range
        fib_retrace_depth = max(0.0, min(1.0, depth))

    # Composite quality score.
    # High-quality trap: fast reclaim + full body recovery + deep retrace.
    trap_quality_score: float = (
        type_weight * 0.40
        + reclaim_strength * 0.35
        + fib_retrace_depth * 0.25
    )
    trap_quality_score = max(0.0, min(1.0, trap_quality_score))

    return SweepTrapResult(
        sweep_reclaim_bars=bars_to_reclaim,
        trap_type=trap_type,
        reclaim_strength=reclaim_strength,
        fib_retrace_depth=fib_retrace_depth,
        trap_quality_score=trap_quality_score,
    )


# ---------------------------------------------------------------------------
# SMC v2 signal-quality enrichment wrapper
# ---------------------------------------------------------------------------


def detect_sweep_trap(enrichment: dict[str, Any] | None = None) -> dict[str, Any]:
    """Detect a sweep-trap condition from enrichment data.

    Parameters
    ----------
    enrichment : dict | None
        Full enrichment dict.  Reads ``liquidity_sweeps`` and optional
        ``structure_state_light`` / ``structure_state`` blocks.

    Returns
    -------
    dict[str, Any]
        ``{"SWEEP_TRAP_DETECTED": bool, "SWEEP_TRAP_CONFIDENCE": int}``
        Confidence ranges from 0–100.  When the feature flag is OFF the
        detector always returns the neutral block
        ``{"SWEEP_TRAP_DETECTED": False, "SWEEP_TRAP_CONFIDENCE": 0}``.
    """
    neutral = {"SWEEP_TRAP_DETECTED": False, "SWEEP_TRAP_CONFIDENCE": 0}

    if not sweep_trap_enabled():
        return neutral

    enr = enrichment or {}
    ls = enr.get("liquidity_sweeps") or {}

    has_bull_sweep = bool(ls.get("RECENT_BULL_SWEEP", False))
    has_bear_sweep = bool(ls.get("RECENT_BEAR_SWEEP", False))
    # Round float quality scores to the nearest integer on the 0-5 scale.
    # Truncation would silently inflate confidence (e.g. 2.9 -> 2).
    sweep_quality = max(0, min(5, round(float(ls.get("SWEEP_QUALITY_SCORE", 0)))))
    sweep_direction = str(ls.get("SWEEP_DIRECTION", "NONE")).upper()

    if not (has_bull_sweep or has_bear_sweep) or sweep_direction == "NONE":
        return neutral

    # Quality must be poor for a trap.
    if sweep_quality >= sweep_trap_config.quality_threshold:
        return neutral

    # Base confidence: inversely proportional to quality on the 0-5 scale.
    quality_factor = max(0, min(100, (5 - sweep_quality) * 20))

    # Boost when only one direction swept (lopsided liquidity grab).
    both_sides = has_bull_sweep and has_bear_sweep
    direction_boost = 0 if both_sides else sweep_trap_config.lopsided_boost

    # Reduce confidence if structure already reversed against the sweep.
    ssl = enr.get("structure_state_light") or {}
    ss = enr.get("structure_state") or {}
    last_event = str(
        ssl.get("STRUCTURE_LAST_EVENT", ss.get("STRUCTURE_LAST_EVENT", "NONE"))
    ).upper()

    reversal_penalty = 0
    if (sweep_direction == "BULL" and last_event in ("BOS_BEAR", "CHOCH_BEAR")) or (
        sweep_direction == "BEAR" and last_event in ("BOS_BULL", "CHOCH_BULL")
    ):
        reversal_penalty = sweep_trap_config.reversal_penalty

    confidence = max(0, min(100, quality_factor + direction_boost - reversal_penalty))

    # If quality is poor but structure already reversed, the trap is no
    # longer active.
    if confidence == 0:
        return neutral

    return {
        "SWEEP_TRAP_DETECTED": True,
        "SWEEP_TRAP_CONFIDENCE": confidence,
    }

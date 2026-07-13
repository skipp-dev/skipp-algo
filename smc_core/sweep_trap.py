"""Phase B — Sweep Trap Classifier + SMC v2 enrichment wrapper.

A *sweep trap* (also: stop-hunt reversal, liquidity trap) occurs when price
sweeps a prior swing high/low to trigger resting orders, then reclaims the
swept level, trapping the breakout traders.  The reclaim quality — how fast,
how strongly, how deeply price reverses — is *hypothesised* to lead a
meaningful follow-through reversal.  This is an **unverified heuristic**, NOT
an empirically established leading indicator: ``trap_quality_score`` is a
hand-weighted shadow score (see its formula below) that has not yet been
calibrated against realised outcomes.  A leakage-free evaluator exists, but
until its ledger data is scored the predictive claim stays unproven — treat
the score as a ranking hypothesis, not a validated signal.

This module provides:

* :class:`SweepTrapResult` — enrichment payload added to the liquidity-sweep
  context when ``ENABLE_SWEEP_TRAP=1``.
* :func:`classify_sweep_trap` — deterministic, pure-math classification; no
  I/O, no global state.
* :func:`detect_sweep_trap` — SMC v2 signal-quality enrichment wrapper that
  reads the lean ``liquidity_sweeps`` block and returns a neutral/detected
  verdict with a 0-100 confidence score. NOTE: despite the ``SWEEP_TRAP_DETECTED``
  name, this wrapper only flags a *candidate* — a present sweep with a poor coarse
  ``SWEEP_QUALITY_SCORE``. It sees NO post-sweep bars and checks NO reclaim; the
  actual reclaim classification is :func:`classify_sweep_trap`. (A ``SWEEP_TRAP
  _CANDIDATE`` rename is pending; the flag currently downgrades signal freshness
  in ``scripts/smc_signal_quality.py``.)

Integration point
-----------------
:func:`~smc_integration.measurement_evidence._liquidity_support_for_event`
calls :func:`classify_sweep_trap` when ``ENABLE_SWEEP_TRAP`` is enabled AND the
candidate sweep carries ``swept_level > 0``.  Producers emit ``id/time/price/side``
only, but the integration choke point synthesises ``swept_level`` (=price) + sweep
geometry, so the classify path DOES run (observe-only).  The result fields merge into
the liquidity enrichment payload; they are NOT passed to ``label_sweep_reversal``
(that label takes ``(price, side, closes)`` only).

:func:`detect_sweep_trap` is consumed by ``scripts/smc_signal_quality.py``
when ``is_sweep_trap_enabled()`` (i.e. ``ENABLE_SWEEP_TRAP=1``); the
``SIGNAL_QUALITY_MODEL=v2`` route alone never calls it.

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


@dataclass(frozen=True, slots=True)
class SweepTrapResult:
    """Enrichment payload for Sweep Trap classification.

    Parameters
    ----------
    sweep_reclaim_bars:
        Number of bars from the sweep extreme to the first bar that closes
        back inside the swept level.  ``-1`` if no reclaim occurred within
        the available data; a reclaim later than 12 bars reports its actual
        (1-indexed) bar count with ``trap_type="failed"``.
    trap_type:
        ``"immediate"`` — reclaim within 3 bars of the sweep.
        ``"delayed"`` — reclaim within 4–12 bars.
        ``"failed"`` — reclaim after 12 bars, or none within the available data.
    reclaim_strength:
        0.0–1.0.  How far the FIRST reclaim close (the classifier stops at the
        first bar that closes back through the level, not the deepest one) moved
        back THROUGH the swept level, as a fraction of the **sweep penetration**
        — the wick distance the sweep pierced past the level, ``|sweep_extreme -
        swept_level|``, NOT the sweep candle's open→close body (the sweep
        candle's open/close are never passed to this function):
        ``|swept_level - close_reclaim| / |sweep_extreme - swept_level|``, clipped
        to [0, 1].  ``0.0`` for failed traps.
    fib_retrace_depth:
        0.0–1.0.  Penetration depth of the SWEEP CANDLE itself: ``|sweep_extreme
        - swept_level| / |swept_level - origin_level|``, clipped to [0, 1].
        Post-sweep bars are never consulted — this is NOT a measured retrace
        after the sweep.  ``0.0`` = the extreme barely pierced the level,
        ``1.0`` = the sweep penetrated a full pre-sweep leg beyond it.
    trap_quality_score:
        0.0–1.0 composite quality score: weighted SUM ``0.40 × type_weight
        + 0.35 × reclaim_strength + 0.25 × fib_retrace_depth``.  Becomes
        ``SWEEP_TRAP_QUALITY_SCORE`` in the liquidity enrichment payload.  The
        weights are a **hand-picked heuristic**, not empirically fitted — deeper
        penetration raising the score by up to 25% is an assumption pending
        outcome calibration, not a measured effect.
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
        The prior swing low (bullish sweep) or swing high (bearish sweep)
        that was violated by the sweep.
    sweep_extreme:
        The most extreme price reached by the sweep candle (low for
        bullish sweeps, high for bearish sweeps).
    origin_level:
        Price level at the origin of the move leading to the sweep — used
        to measure ``fib_retrace_depth``.
    is_bullish_sweep:
        ``True`` for a **bullish setup**: a swing low was swept (sell-side
        liquidity grabbed below ``swept_level``, i.e. ``side == "SELL_SIDE"``)
        and price is expected to reclaim *upward*, trapping sellers.
        ``False`` for a bearish setup (a swing high was swept, ``BUY_SIDE``,
        reclaim *downward*, trapping buyers). This matches the repo-wide
        convention (BULL ↔ SELL_SIDE taken).
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
    # Sweep penetration: how far the wick pierced PAST the swept level (NOT the
    # sweep candle's open→close body — open/close are not available here).
    sweep_penetration: float = abs(swept_level - sweep_extreme)
    if sweep_penetration < 1e-10:
        # Degenerate sweep — zero penetration past the level; classify as failed.
        return SweepTrapResult(
            sweep_reclaim_bars=-1,
            trap_type="failed",
            reclaim_strength=0.0,
            fib_retrace_depth=0.0,
            trap_quality_score=0.0,
        )

    fib_range: float = abs(swept_level - origin_level)

    reclaim_bar_idx: int = -1
    first_reclaim_close: float | None = None

    for idx, bar in enumerate(post_sweep_bars):
        # NOTE: this reclaim uses a STRICT level-cross (``>`` / ``<``). That is a
        # different threshold from reaction_zone's inclusive level-touch (``>=`` /
        # ``<=``) and from label_sweep_reversal's OUTCOME (which also needs ~0.5%
        # follow-through). The three are intentionally distinct — do not unify blindly.
        close: float = float(bar["close"])
        if is_bullish_sweep:
            # Bullish setup: swing low swept; reclaim = close back *above* it.
            if close > swept_level:
                reclaim_bar_idx = idx
                first_reclaim_close = close
                break
        else:
            # Bearish setup: swing high swept; reclaim = close back *below* it.
            if close < swept_level:
                reclaim_bar_idx = idx
                first_reclaim_close = close
                break

    if reclaim_bar_idx == -1 or first_reclaim_close is None:
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
        # Linear decay: ~0.767 at bar 4 → 0.5 at bar 12 (0.8 is the bar-3 asymptote).
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

    # Reclaim strength: fraction of the sweep penetration recovered (how far the
    # reclaim close moved back through swept_level, relative to the wick distance).
    if is_bullish_sweep:
        recovered: float = first_reclaim_close - swept_level
    else:
        recovered = swept_level - first_reclaim_close
    reclaim_strength: float = max(0.0, min(1.0, recovered / sweep_penetration))

    # "fib_retrace_depth" (misnomer — a rename to sweep_penetration_depth is
    # pending; see the field docstring): this measures ONLY the sweep candle's
    # own penetration past swept_level relative to the pre-sweep leg. No
    # post-sweep bar is consulted, so it is NOT a measured price retrace.
    if fib_range < 1e-10:
        fib_retrace_depth: float = 0.0
    else:
        if is_bullish_sweep:
            # Bullish: how far the swept LOW was pierced *below* swept_level,
            # relative to the pre-sweep leg.
            depth: float = (swept_level - sweep_extreme) / fib_range
        else:
            # Bearish: how far the swept HIGH was pierced *above* swept_level.
            depth = (sweep_extreme - swept_level) / fib_range
        fib_retrace_depth = max(0.0, min(1.0, depth))

    # Composite quality score (heuristic, unverified — see class docstring).
    # Higher score = fast reclaim + more penetration recovered + deeper sweep
    # penetration. Whether that ranks better follow-through is an untested
    # assumption pending outcome calibration.
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
    """Flag a sweep-trap *candidate* from enrichment data (not a confirmed reclaim).

    ``SWEEP_TRAP_DETECTED`` fires when a sweep is present with a poor coarse
    ``SWEEP_QUALITY_SCORE``. It inspects NO post-sweep bars and verifies NO
    reclaim — the true reclaim classification lives in :func:`classify_sweep_trap`.
    Treat the flag as "candidate" pending a ``SWEEP_TRAP_CANDIDATE`` rename.

    Parameters
    ----------
    enrichment : dict | None
        Full enrichment dict.  Reads ``liquidity_sweeps`` and optional
        ``structure_state_light`` / ``structure_state`` blocks.

    Returns
    -------
    dict[str, Any]
        ``{"SWEEP_TRAP_DETECTED": bool, "SWEEP_TRAP_HEURISTIC_SCORE": int}``
        ``SWEEP_TRAP_HEURISTIC_SCORE`` is a deterministic 0–100 HEURISTIC conviction
        score (inverse-quality + boost − penalty), NOT a probability or a percent.
        When the feature flag is OFF the detector always returns the neutral block
        ``{"SWEEP_TRAP_DETECTED": False, "SWEEP_TRAP_HEURISTIC_SCORE": 0}``.
    """
    neutral = {"SWEEP_TRAP_DETECTED": False, "SWEEP_TRAP_HEURISTIC_SCORE": 0}

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

    # A structure reversal only SUBTRACTS ``reversal_penalty`` from confidence;
    # it does not by itself deactivate the candidate. With the defaults a
    # lopsided quality-2 sweep is 60 + 20 - 40 = 40, so ``DETECTED`` stays True.
    # Only a confidence that reaches exactly 0 (penalty >= factor + boost)
    # collapses to the neutral block below.
    if confidence == 0:
        return neutral

    return {
        "SWEEP_TRAP_DETECTED": True,
        "SWEEP_TRAP_HEURISTIC_SCORE": confidence,
    }

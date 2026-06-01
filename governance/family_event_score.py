"""EV-24 raw per-family event score: a transparent, low-degrees-of-freedom
geometry-strength feature for the governed edge gate.

Why this exists
---------------
The real-run path (``scripts.run_edge_pipeline`` ->
``governance.family_event_adapter.family_events_from_structure`` ->
``governance.family_returns``) emits purely *structural* events: zone
geometry (OB/FVG ``low``/``high``) or a level price (BOS/SWEEP). No
per-event score was ever attached, so there was no probability to
calibrate -- the calibration metrics (brier/ece) stayed "not yet measured"
and the promotion gate fail-closed on every decision. This module supplies
the missing raw score so the *next* stage can calibrate it walk-forward.

What it computes (v1 baseline -- explicitly weak, never sold as an edge)
-----------------------------------------------------------------------
ONE ATR-normalised strength feature per family, computed only from data the
adapter already holds (the OHLC bars and the event geometry):

  * **Zone families (FVG, OB)** -> ``(zone_high - zone_low) / ATR(anchor)``.
    The zone thickness in ATR units: a larger displacement gap is the
    canonical "strength" of an order block / fair-value gap.
  * **Level families (BOS, SWEEP)** -> ``true_range(anchor_bar) / ATR(anchor)``.
    The anchor bar's own true range in ATR units: the displacement candle
    that produced the break / sweep.

The feature is returned **raw and unsquashed** (a positive float, not a
probability) and the *direction* (sign) is deliberately NOT hard-coded.
The downstream walk-forward Platt calibrator
(``governance.family_calibration``) fits the slope and intercept per family;
if the fitted slope is non-positive the feature carries no usable signal and
the family is reported as such rather than flattered.

Deliberate deviation from the EV-24 plan (decision #4, documented honesty)
--------------------------------------------------------------------------
The reviewed plan proposed reusing ``smc_core.fvg_quality.score_fvg`` for the
FVG family. That scorer needs ``htf_aligned`` and ``hurst`` inputs which the
*structural* adapter cannot supply without fabricating an HTF bias / a Hurst
estimate it never measured. Feeding worst-case constants for 3 of its 5
components would add opacity and degrees of freedom without adding signal --
the opposite of an honest, auditable v1. So FVG uses the same single
ATR-normalised zone-thickness feature as OB. This is a conscious, lower-DoF,
fabrication-free choice; revisit only with real HTF/Hurst inputs wired in.

Point-in-time guarantee
------------------------
``ATR`` is computed strictly from the ``period`` bars *ending at* the anchor
bar (inclusive), using each bar's prior close for the true range. It never
reads a bar after the anchor, so the score is leak-free by construction and
consistent with the EV-04 lookahead guard.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from governance.types import EventFamily

# Wilder ATR lookback. 14 is the standard default; a single shared period
# keeps the score's degrees of freedom minimal and avoids per-family tuning.
ATR_PERIOD = 14

# Provenance tag so the audit trail records which score produced a family's
# calibration samples.
SCORE_SOURCE = "atr_normalised_geometry_strength_v1"

_ZONE_FAMILIES = ("FVG", "OB")
_LEVEL_FAMILIES = ("BOS", "SWEEP")


def _true_range(bar: Mapping[str, Any], prev_close: float | None) -> float:
    """Wilder true range for one bar. ``prev_close=None`` -> high-low only."""
    high = float(bar["high"])
    low = float(bar["low"])
    if prev_close is None:
        return high - low
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def atr_at(
    bars: Sequence[Mapping[str, Any]],
    anchor_idx: int,
    *,
    period: int = ATR_PERIOD,
) -> float | None:
    """Mean true range over the ``period`` bars ending at ``anchor_idx``.

    Strictly point-in-time: uses only bars at indices
    ``[anchor_idx - period + 1, anchor_idx]`` (and each one's prior close),
    so it never sees a bar after the anchor. Returns ``None`` when there is
    not enough leading history or the ATR is non-positive (degenerate input).
    """
    if period <= 0 or anchor_idx < period or anchor_idx >= len(bars):
        return None
    total = 0.0
    for k in range(anchor_idx - period + 1, anchor_idx + 1):
        prev_close = float(bars[k - 1]["close"])
        total += _true_range(bars[k], prev_close)
    atr = total / period
    return atr if atr > 0.0 else None


def raw_score(
    family: EventFamily,
    *,
    bars: Sequence[Mapping[str, Any]],
    anchor_idx: int,
    zone_low: float | None = None,
    zone_high: float | None = None,
    period: int = ATR_PERIOD,
) -> float | None:
    """Raw ATR-normalised geometry-strength score for one event.

    Returns ``None`` (no score, family stays "not yet measured") when the
    trailing ATR cannot be computed or the geometry is degenerate. The value
    is an uncalibrated positive float; calibration happens downstream.
    """
    atr = atr_at(bars, anchor_idx, period=period)
    if atr is None:
        return None

    if family in _ZONE_FAMILIES:
        if zone_low is None or zone_high is None:
            return None
        height = float(zone_high) - float(zone_low)
        if height <= 0.0:
            return None
        return height / atr

    if family in _LEVEL_FAMILIES:
        prev_close = float(bars[anchor_idx - 1]["close"]) if anchor_idx >= 1 else None
        tr = _true_range(bars[anchor_idx], prev_close)
        if tr <= 0.0:
            return None
        return tr / atr

    return None

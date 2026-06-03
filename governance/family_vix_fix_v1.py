"""ADR-0019 step 2: point-in-time downside-volatility feature (Williams VIX Fix).

Why this exists
---------------
The v1 per-family score (``governance.family_event_score``,
``SCORE_SOURCE = "atr_normalised_geometry_strength_v1"``) is ONE ATR-normalised
geometry feature, and the first v2 candidate
(``governance.family_score_features_v2.relative_volume_at``) adds an order-flow
volume proxy. The Murphy/Brier decomposition of the EV-20 run pins the binding
promotion deficit on **resolution (discrimination)** -- the score needs more
*orthogonal* signal, not more of the same dimension.

This module supplies a candidate from a dimension neither v1 (pure geometry)
nor the relative-volume v2 candidate (raw participation) looks at: **realised
downside deviation**. Larry Williams' "VIX Fix" (public domain) is a synthetic
fear gauge computed from price alone -- it rises when the current bar's low is
far below the recent close highs, i.e. when the formation occurs amid a
capitulation / elevated-fear regime. That regime context is plausibly
discriminating for whether an SMC structure event resolves into follow-through,
and it is orthogonal to both formation geometry and formation volume.

This module supplies it as a **pure, leak-free extractor**. It is deliberately
NOT wired into ``raw_score`` / ``SCORE_SOURCE`` or the promotion gate: ADR-0019
mandates a shadow-first, pre-registered purged walk-forward A/B before any v2
feature may join the v1 calibration input. v1 stays the default until that A/B
clears (the same gate that retired the momentum-ribbon candidate, PR #2545).

What it computes (v2 candidate -- price-only, bar-computable)
------------------------------------------------------------
``williams_vix_fix_at`` -- the formation (anchor) bar's Williams VIX Fix:

    highest_close = max(close[anchor-lookback+1 .. anchor])
    wvf           = (highest_close - low[anchor]) / highest_close * 100

A larger value means the anchor bar's low punched further below the trailing
close peak (a higher-fear / capitulation footprint); a value near zero means
the bar closed/held near its recent highs. It needs no volume and no
trade-side data -- only the symbol's own price bars.

Point-in-time guarantee
-----------------------
The trailing close window ends at the anchor bar and the low is the anchor
bar's own low; it never reads a bar after the anchor, so the feature is
leak-free by construction and consistent with the EV-04 lookahead guard and
``family_event_score.atr_at`` / ``point_in_time_regime``.

Honest omission semantics
-------------------------
Returns ``None`` (feature absent -- never invented, never zero-filled) when:
``lookback`` is non-positive, there is not enough trailing history, any bar in
the window lacks a valid close, the anchor low is missing/invalid, or the
trailing close peak is non-positive (degenerate input). This mirrors the
omitted-not-zero-filled discipline of ``relative_volume_at``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

# Provenance tag recording how each event's Williams VIX Fix feature was
# produced. The ``_v1`` suffix versions this extractor; it is an ADR-0019 v2
# candidate feature, distinct from the v1 ``SCORE_SOURCE``.
WILLIAMS_VIX_FIX_SOURCE = "downside_volatility_williams_vix_fix_v1"

# Larry Williams' canonical VIX-Fix close lookback. Kept as a single module
# constant (no per-family tuning, minimal degrees of freedom). Warmup is
# ``WVF_LOOKBACK - 1`` bars of trailing history before the anchor.
WVF_LOOKBACK = 22


def _bar_field(bar: Mapping[str, Any], key: str) -> float | None:
    """Finite float for one bar field, or ``None`` when absent/invalid."""
    raw = bar.get(key)
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value:  # NaN guard
        return None
    return value


def williams_vix_fix_at(
    bars: Sequence[Mapping[str, Any]],
    anchor_idx: int,
    *,
    lookback: int = WVF_LOOKBACK,
) -> float | None:
    """Anchor-bar Williams VIX Fix from the trailing ``lookback`` closes.

    Strictly point-in-time: the close peak uses only bars at indices
    ``[anchor_idx - lookback + 1, anchor_idx]`` and the low is the anchor bar's
    own low, so it never reads a bar after the anchor and is leak-free by
    construction.

    Returns ``None`` (feature honestly absent) when ``lookback`` is
    non-positive, there is not enough trailing history, any close in the window
    is missing/invalid, the anchor low is missing/invalid, or the trailing
    close peak is non-positive.
    """
    if lookback <= 0 or anchor_idx < lookback - 1 or anchor_idx >= len(bars):
        return None

    anchor_low = _bar_field(bars[anchor_idx], "low")
    if anchor_low is None:
        return None

    highest_close: float | None = None
    for k in range(anchor_idx - lookback + 1, anchor_idx + 1):
        close = _bar_field(bars[k], "close")
        if close is None:
            return None
        if highest_close is None or close > highest_close:
            highest_close = close
    if highest_close is None or highest_close <= 0.0:
        return None

    return (highest_close - anchor_low) / highest_close * 100.0


__all__ = ["WILLIAMS_VIX_FIX_SOURCE", "williams_vix_fix_at"]

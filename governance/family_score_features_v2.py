"""ADR-0019 step 1: point-in-time order-flow features (family score v2).

Why this exists
---------------
The v1 per-family score (``governance.family_event_score``,
``SCORE_SOURCE = "atr_normalised_geometry_strength_v1"``) is ONE ATR-normalised
geometry feature. The Murphy/Brier decomposition of the EV-20 run pins the
binding promotion deficit on **resolution (discrimination)**, and the verified
feature-gap analysis (``docs/governance/resolution_feature_gap_analysis.md``,
ADR-0019) identifies **order-flow / volume** as the largest signal the score
does not yet look at -- the literal core of "Smart Money Concepts," available
in the data but dropped at the governance boundary.

This module supplies the first such feature as a **pure, leak-free extractor**.
It is deliberately NOT wired into ``raw_score`` / ``SCORE_SOURCE`` or the
promotion gate: ADR-0019 mandates a shadow-first, pre-registered purged
walk-forward A/B before any v2 feature may replace or join the v1 calibration
input. v1 stays the default until that A/B clears.

What it computes (v2 candidate -- order-flow, bar-computable)
------------------------------------------------------------
``relative_volume_at`` -- the formation (anchor) bar's volume relative to its
own trailing baseline:

    relative_volume = volume[anchor] / mean(volume[anchor-period .. anchor-1])

A value > 1 means the event formed on heavier-than-usual volume (an
institutional-footprint proxy); < 1 means it formed on thin volume. This is the
bar-computable order-flow proxy from ADR-0019's tier-1 feature hierarchy and
needs no trade-side (buy/sell) data -- trade-side imbalance / VPIN
(``ml.features.microstructure``) require trade-level side plumbing and are a
later slice.

Point-in-time guarantee
-----------------------
The baseline is the ``period`` bars *strictly before* the anchor; the value
uses the anchor bar itself. It never reads a bar after the anchor, so the
feature is leak-free by construction and consistent with the EV-04 lookahead
guard and ``family_event_score.atr_at`` / ``point_in_time_regime``.

Honest omission semantics
-------------------------
Returns ``None`` (feature absent -- never invented, never zero-filled) when:
volume is missing on any bar in the window, there is not enough trailing
history, or the trailing baseline is non-positive (degenerate input). This
mirrors the omitted-not-zero-filled discipline of
``smc_integration.measurement_evidence``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

# Reuse the v1 ATR lookback so the v2 order-flow baseline shares one trailing
# horizon and the module keeps a single point-in-time window constant (no
# per-family tuning, minimal degrees of freedom).
from governance.family_event_score import ATR_PERIOD

# Provenance tag recording how each event's relative-volume feature was
# produced. The ``_v2`` suffix marks it as an ADR-0019 candidate feature,
# distinct from the v1 ``SCORE_SOURCE``.
RELATIVE_VOLUME_SOURCE = "orderflow_relative_volume_v2"


def _bar_volume(bar: Mapping[str, Any]) -> float | None:
    """Non-negative float volume for one bar, or ``None`` when absent/invalid."""
    raw = bar.get("volume")
    if raw is None:
        return None
    try:
        vol = float(raw)
    except (TypeError, ValueError):
        return None
    if vol < 0.0:
        return None
    return vol


def relative_volume_at(
    bars: Sequence[Mapping[str, Any]],
    anchor_idx: int,
    *,
    period: int = ATR_PERIOD,
) -> float | None:
    """Anchor-bar volume divided by its trailing ``period``-bar mean volume.

    Strictly point-in-time: the baseline uses only bars at indices
    ``[anchor_idx - period, anchor_idx - 1]`` and the value uses the anchor bar
    at ``anchor_idx``, so it never reads a bar after the anchor and is leak-free
    by construction.

    Returns ``None`` (feature honestly absent) when ``period`` is non-positive,
    there is not enough trailing history, any bar in the window lacks a valid
    volume, or the trailing baseline mean is non-positive.
    """
    if period <= 0 or anchor_idx < period or anchor_idx >= len(bars):
        return None

    anchor_volume = _bar_volume(bars[anchor_idx])
    if anchor_volume is None:
        return None

    total = 0.0
    for k in range(anchor_idx - period, anchor_idx):
        vol = _bar_volume(bars[k])
        if vol is None:
            return None
        total += vol
    baseline = total / period
    if baseline <= 0.0:
        return None
    return anchor_volume / baseline


__all__ = ["RELATIVE_VOLUME_SOURCE", "relative_volume_at"]

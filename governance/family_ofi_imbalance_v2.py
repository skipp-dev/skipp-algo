"""ADR-0016 / ADR-0019 — order-flow imbalance shadow feature.

Order-flow imbalance is the *direction / one-sidedness* axis of order flow: of
all the size that traded, what net fraction leaned one way. Over a window it is

    OFI = abs(sum(signed_volume)) / sum(abs_volume)   in [0, 1]

where ``signed_volume`` is buy-aggressor minus sell-aggressor size and
``abs_volume`` is the total traded size (the unsigned magnitude) in the bar.
``OFI = 0`` is perfectly balanced two-sided flow; ``OFI = 1`` is fully one-sided
(every trade on the same side). This is a scale-free *ratio*, so it is orthogonal
to the order-flow features already on the path:

  * ``relative_volume`` is turnover MAGNITUDE (not direction),
  * Kyle's lambda is the price-IMPACT SLOPE per signed unit (price-coupled),
  * ``average_trade_size`` is PARTICIPANT SIZE (shares per trade).

A deep book can absorb very one-sided flow (high OFI) at low lambda; a thin book
shows high lambda at modest OFI. This is a *simplified bar-level imbalance*, NOT
canonical VPIN -- VPIN buckets on equal-volume bars and uses bulk-volume
classification; here the aggressor side is already known per trade and the
window is the same trailing time grid every v2 feature uses.

This module is RECORDED-ONLY (ADR-0019 discipline): a shadow feature whose
values ride alongside event outcomes so the pre-registered purged walk-forward
A/B can decide whether it lifts resolution. It is NOT wired into the v1 score or
any gate. Strictly point-in-time and honest-None: it never reads a bar after the
anchor and returns ``None`` rather than fabricating a value when its inputs are
absent or the window carries no traded size.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

# Reuse the v1 ATR lookback so this candidate shares the single trailing horizon
# every other v2 order-flow feature uses (no per-family tuning, minimal degrees
# of freedom).
from governance.family_event_score import ATR_PERIOD

# Provenance tag recording how each event's order-flow-imbalance feature was
# produced. The ``_v2`` suffix marks it as an ADR-0019 candidate, distinct from
# the v1 ``SCORE_SOURCE``.
OFI_IMBALANCE_SOURCE = "microstructure_ofi_imbalance_v2"


def _bar_signed_volume(bar: Mapping[str, Any]) -> float | None:
    """Signed aggressor volume for one bar, or ``None`` when absent/invalid.

    The producer embeds ``signed_volume`` only on bars whose bucket saw trades
    (``scripts.pull_databento_edge_input._merge_signed_volume_into_bars``); it is
    honestly absent on OHLCV-only runs and on no-trade buckets -> ``None``.
    """
    raw = bar.get("signed_volume")
    if raw is None:
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    if val != val:  # NaN guard
        return None
    return val


def _bar_abs_volume(bar: Mapping[str, Any]) -> float | None:
    """Total traded size (unsigned) for one bar, or ``None`` when absent/invalid.

    Embedded alongside ``signed_volume`` by the producer. Must be non-negative
    (it is a sum of trade sizes); a negative or NaN value is treated as corrupt
    and refused.
    """
    raw = bar.get("abs_volume")
    if raw is None:
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    if val != val or val < 0.0:  # NaN guard + non-negativity
        return None
    return val


def ofi_imbalance_at(
    bars: Sequence[Mapping[str, Any]],
    anchor_idx: int,
    *,
    period: int = ATR_PERIOD,
) -> float | None:
    """Order-flow imbalance over the trailing ``period``-bar window.

    Over the window of ``period`` bars ending at ``anchor_idx`` (inclusive),
    return ``abs(sum(signed_volume)) / sum(abs_volume)`` in ``[0, 1]``. Summing
    the signed and absolute volumes separately (rather than averaging per-bar
    ratios) weights each bar by its activity, so a single thin bar cannot
    dominate the estimate.

    Strictly point-in-time: the window covers indices
    ``[anchor_idx - period + 1, anchor_idx]`` and never touches a bar after the
    anchor, so it is leak-free by construction.

    Returns ``None`` (feature honestly absent) when ``period`` is below 1, there
    is not enough trailing history, any bar in the window lacks a valid
    ``signed_volume`` or ``abs_volume``, or the total traded size over the window
    is zero (no flow to measure -> undefined).
    """
    if period < 1 or anchor_idx < period - 1 or anchor_idx >= len(bars):
        return None

    total_signed = 0.0
    total_abs = 0.0
    for k in range(anchor_idx - period + 1, anchor_idx + 1):
        signed = _bar_signed_volume(bars[k])
        if signed is None:
            return None
        abs_vol = _bar_abs_volume(bars[k])
        if abs_vol is None:
            return None
        total_signed += signed
        total_abs += abs_vol

    if total_abs <= 0.0:
        return None
    ratio = abs(total_signed) / total_abs
    # |sum(signed)| <= sum(|size|) = total_abs holds exactly per bar, but float
    # rounding over a long window can nudge the ratio a hair past 1.0; clamp so
    # the recorded feature stays in its definitional [0, 1] range.
    return ratio if ratio <= 1.0 else 1.0


__all__ = ["OFI_IMBALANCE_SOURCE", "ofi_imbalance_at"]

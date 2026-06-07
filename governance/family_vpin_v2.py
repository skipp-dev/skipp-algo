"""ADR-0016 / ADR-0019 — VPIN order-flow toxicity shadow feature.

VPIN (Volume-synchronized Probability of Informed Trading) measures order-flow
*toxicity*: how persistently one-sided the flow is when each bucket is judged on
its own, rather than how the buckets net out. Over a window it is

    VPIN = sum(abs(signed_volume)) / sum(abs_volume)   in [0, 1]

where ``signed_volume`` is buy-aggressor minus sell-aggressor size and
``abs_volume`` is the total traded size (the unsigned magnitude) in the bar.
Equivalently, with per-bar ``buy = (abs + signed) / 2`` and
``sell = (abs - signed) / 2`` the bucket imbalance is
``abs(buy - sell) = abs(signed)``, so VPIN is the activity-weighted mean of the
per-bucket imbalance fraction. ``VPIN = 0`` is perfectly balanced two-sided flow
in every bucket; ``VPIN = 1`` is fully one-sided flow in every bucket.

This is the *toxicity* axis and is genuinely distinct from order-flow imbalance:

  * ``ofi_imbalance`` takes ``abs(sum(signed))`` -- the abs of the NET, so a buy
    bucket and a later equal sell bucket CANCEL (net direction over the window),
  * ``vpin`` takes ``sum(abs(signed))`` -- the abs PER bucket, so that same pair
    ADDS (sustained two-sided churn still scores high toxicity).

Hence ``vpin >= ofi_imbalance`` always, with equality only when every bucket in
the window leans the same way. A trend shows high OFI and high VPIN alike; a
choppy, heavily-traded-but-directionless tape shows low OFI yet high VPIN -- the
regime VPIN is built to flag. It is also orthogonal to the magnitude features
already on the path (``relative_volume`` turnover, Kyle's lambda price impact,
``average_trade_size`` participant size), being a scale-free ratio.

This is a *simplified bar-level VPIN*, NOT the canonical Easley/Lopez de Prado
estimator -- canonical VPIN re-buckets the tape into equal-VOLUME buckets and
bulk-classifies the aggressor side; here the aggressor side is already known per
trade and the bucket grid is the same trailing time grid every v2 feature uses.

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

# Provenance tag recording how each event's VPIN feature was produced. The
# ``_v2`` suffix marks it as an ADR-0019 candidate, distinct from the v1
# ``SCORE_SOURCE``.
VPIN_SOURCE = "microstructure_vpin_v2"


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


def vpin_at(
    bars: Sequence[Mapping[str, Any]],
    anchor_idx: int,
    *,
    period: int = ATR_PERIOD,
) -> float | None:
    """VPIN order-flow toxicity over the trailing ``period``-bar window.

    Over the window of ``period`` bars ending at ``anchor_idx`` (inclusive),
    return ``sum(abs(signed_volume)) / sum(abs_volume)`` in ``[0, 1]``. The
    absolute value is taken PER bar before summing -- the defining difference
    from ``ofi_imbalance``, which sums the signed volumes first and takes the
    absolute of the net. Summing absolute and total volumes separately (rather
    than averaging per-bar ratios) weights each bar by its activity, so a single
    thin bar cannot dominate the estimate.

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

    total_abs_signed = 0.0
    total_abs = 0.0
    for k in range(anchor_idx - period + 1, anchor_idx + 1):
        signed = _bar_signed_volume(bars[k])
        if signed is None:
            return None
        abs_vol = _bar_abs_volume(bars[k])
        if abs_vol is None:
            return None
        total_abs_signed += abs(signed)
        total_abs += abs_vol

    if total_abs <= 0.0:
        return None
    ratio = total_abs_signed / total_abs
    # abs(signed_k) <= abs_vol_k holds exactly per bar, so the sum ratio is <= 1,
    # but float rounding over a long window can nudge it a hair past 1.0; clamp
    # so the recorded feature stays in its definitional [0, 1] range.
    return ratio if ratio <= 1.0 else 1.0


__all__ = ["VPIN_SOURCE", "vpin_at"]

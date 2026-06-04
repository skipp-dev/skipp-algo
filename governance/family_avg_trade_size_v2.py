"""ADR-0016 / ADR-0019 — average trade size shadow feature.

Average trade size is the participant-size axis of order flow: how many shares
the typical trade carries. A bar's ``volume`` is the sum of all trade sizes in
its bucket and ``trade_count`` is how many trades produced it, so
``volume / trade_count`` is the mean shares-per-trade. Large average trade size
is a classic institutional-footprint proxy (block / smart-money activity);
small average trade size signals retail / fragmented flow.

This axis is orthogonal to the order-flow features already on the path:
``relative_volume`` is total turnover MAGNITUDE (not per-trade granularity),
``signed_volume`` / Kyle's lambda are flow DIRECTION and price IMPACT (not
participant size). Because ``volume = trade_count * avg_size`` is an identity,
``trade_count`` alone is NOT a separate candidate: count and average size
together add only ONE degree of freedom beyond the already-occupied magnitude
axis, and average size is the economically meaningful one.

This module is RECORDED-ONLY (ADR-0019 discipline): a shadow feature whose
values ride alongside event outcomes so the pre-registered purged walk-forward
A/B can decide whether it lifts resolution. It is NOT wired into the v1 score or
any gate. Like every ADR-0019 candidate it is strictly point-in-time and
honest-None: it never reads a bar after the anchor and returns ``None`` rather
than fabricating a value when its inputs are absent or degenerate.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

# Reuse the v1 ATR lookback so this candidate shares the single trailing horizon
# every other v2 order-flow feature uses (no per-family tuning, minimal degrees
# of freedom).
from governance.family_event_score import ATR_PERIOD

# Provenance tag recording how each event's average-trade-size feature was
# produced. The ``_v2`` suffix marks it as an ADR-0019 candidate, distinct from
# the v1 ``SCORE_SOURCE``.
AVG_TRADE_SIZE_SOURCE = "microstructure_avg_trade_size_v2"


def _bar_volume(bar: Mapping[str, Any]) -> float | None:
    """Non-negative float volume for one bar, or ``None`` when absent/invalid."""
    raw = bar.get("volume")
    if raw is None:
        return None
    try:
        vol = float(raw)
    except (TypeError, ValueError):
        return None
    if vol != vol or vol < 0.0:  # NaN guard + non-negativity
        return None
    return vol


def _bar_trade_count(bar: Mapping[str, Any]) -> float | None:
    """Non-negative float trade count for one bar, or ``None`` when absent.

    The producer embeds ``trade_count`` only on bars whose bucket saw trades
    (``scripts.pull_databento_edge_input._merge_signed_volume_into_bars``); it is
    honestly absent on OHLCV-only runs and on no-trade buckets -> ``None``.
    """
    raw = bar.get("trade_count")
    if raw is None:
        return None
    try:
        count = float(raw)
    except (TypeError, ValueError):
        return None
    if count != count or count < 0.0:  # NaN guard + non-negativity
        return None
    return count


def average_trade_size_at(
    bars: Sequence[Mapping[str, Any]],
    anchor_idx: int,
    *,
    period: int = ATR_PERIOD,
) -> float | None:
    """Mean shares-per-trade over the trailing ``period``-bar window.

    Over the window of ``period`` bars ending at ``anchor_idx`` (inclusive),
    return the volume-weighted average trade size
    ``sum(volume_k) / sum(trade_count_k)``. Summing numerator and denominator
    separately (rather than averaging per-bar ratios) weights each bar by its
    activity, so a single thin bar cannot dominate the estimate.

    Strictly point-in-time: the window covers indices
    ``[anchor_idx - period + 1, anchor_idx]`` and never touches a bar after the
    anchor, so it is leak-free by construction.

    Returns ``None`` (feature honestly absent) when ``period`` is below 1, there
    is not enough trailing history, any bar in the window lacks a valid volume
    or trade count, or the total trade count over the window is zero (no trades
    to average -> undefined).
    """
    if period < 1 or anchor_idx < period - 1 or anchor_idx >= len(bars):
        return None

    total_volume = 0.0
    total_count = 0.0
    for k in range(anchor_idx - period + 1, anchor_idx + 1):
        vol = _bar_volume(bars[k])
        if vol is None:
            return None
        count = _bar_trade_count(bars[k])
        if count is None:
            return None
        total_volume += vol
        total_count += count

    if total_count <= 0.0:
        return None
    return total_volume / total_count


__all__ = ["AVG_TRADE_SIZE_SOURCE", "average_trade_size_at"]

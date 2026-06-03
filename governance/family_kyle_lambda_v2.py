"""ADR-0016 — Kyle's lambda shadow feature on the aggressor-signed data path.

Kyle's lambda (Kyle, 1985) measures price impact per unit of signed order flow:
the slope of the regression of price change on signed volume. A high lambda
means each net buy/sell unit moves price a lot (illiquid / informed flow); a low
lambda means the book absorbs flow cheaply. Unlike the rejected tick-rule proxy
(ADR-0016 rejects it: 30-50% aggressor misclassification, Ellis/Michaely/O'Hara
2000), the ``signed_volume`` this feature consumes is sourced from the venue's
real per-trade ``side`` (Databento ``trades`` schema), bucketed onto the bar grid
by :func:`scripts.pull_databento_edge_input.aggregate_signed_volume`.

This module is RECORDED-ONLY (ADR-0019 discipline): it is a shadow feature whose
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

# Provenance tag recording how each event's Kyle-lambda feature was produced.
# The ``_v2`` suffix marks it as an ADR-0019 candidate, distinct from the v1
# ``SCORE_SOURCE``.
KYLE_LAMBDA_SOURCE = "microstructure_kyle_lambda_v2"


def _bar_close(bar: Mapping[str, Any]) -> float | None:
    """Finite float close for one bar, or ``None`` when absent/invalid."""
    raw = bar.get("close")
    if raw is None:
        return None
    try:
        close = float(raw)
    except (TypeError, ValueError):
        return None
    if close != close:  # NaN guard
        return None
    return close


def _bar_signed_volume(bar: Mapping[str, Any]) -> float | None:
    """Finite signed-volume for one bar, or ``None`` when absent/invalid.

    ``signed_volume`` may be negative (net sell pressure), so unlike raw volume
    there is no non-negativity constraint. Absent on bars whose bucket saw no
    trades (the producer omits the key honestly) -> ``None``.
    """
    raw = bar.get("signed_volume")
    if raw is None:
        return None
    try:
        signed = float(raw)
    except (TypeError, ValueError):
        return None
    if signed != signed:  # NaN guard
        return None
    return signed


def kyle_lambda_at(
    bars: Sequence[Mapping[str, Any]],
    anchor_idx: int,
    *,
    period: int = ATR_PERIOD,
) -> float | None:
    """OLS price-impact slope of ``close`` change on signed volume.

    Over the trailing window of ``period`` bars ending at ``anchor_idx``
    (inclusive), regress the per-bar close change ``y_k = close_k - close_{k-1}``
    on the per-bar signed volume ``x_k = signed_volume_k`` and return the OLS
    slope ``beta = sum((x-x_mean)(y-y_mean)) / sum((x-x_mean)^2)``.

    Strictly point-in-time: the window covers indices
    ``[anchor_idx - period + 1, anchor_idx]`` and reads ``close`` back to
    ``anchor_idx - period``; it never touches a bar after the anchor, so it is
    leak-free by construction. The slope may be positive or negative.

    Returns ``None`` (feature honestly absent) when ``period`` is below 2, there
    is not enough trailing history, any bar in the window lacks a valid close or
    signed volume, or the signed-volume series has zero variance (degenerate
    regression with no defined slope).
    """
    if period < 2 or anchor_idx < period or anchor_idx >= len(bars):
        return None

    xs: list[float] = []
    ys: list[float] = []
    for k in range(anchor_idx - period + 1, anchor_idx + 1):
        signed = _bar_signed_volume(bars[k])
        if signed is None:
            return None
        close_k = _bar_close(bars[k])
        close_prev = _bar_close(bars[k - 1])
        if close_k is None or close_prev is None:
            return None
        xs.append(signed)
        ys.append(close_k - close_prev)

    n = float(len(xs))
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    sxx = 0.0
    sxy = 0.0
    for x, y in zip(xs, ys, strict=True):
        dx = x - x_mean
        sxx += dx * dx
        sxy += dx * (y - y_mean)
    if sxx <= 0.0:
        return None
    return sxy / sxx


__all__ = ["KYLE_LAMBDA_SOURCE", "kyle_lambda_at"]

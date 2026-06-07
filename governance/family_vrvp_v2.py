"""ADR-0021 — VRVP volume-profile location shadow features.

A visible-range volume profile (VRVP) summarises *where* traded volume has piled
up over a trailing window: the VPOC (volume point of control — the single
busiest price) and the value area (the contiguous band, by convention 70 % of
volume, between VAL and VAH). Those landmarks describe acceptance vs rejection
of price, an axis the existing v1 score does not carry: BOS/OB/FVG/SWEEP score
*structure events*, not the volume-by-price context the event fires into.

This module exposes two scale-free, point-in-time *location* scalars relative to
the anchor bar's close:

  * ``vrvp_vpoc_distance_at`` — signed distance from the close to the VPOC,
    normalised by the profiled price range, so it is comparable across symbols
    and regimes. Positive when the close sits ABOVE the busiest price (price has
    travelled up and away from accepted value), negative below it.
  * ``vrvp_value_area_position_at`` — a discrete ``-1 / 0 / +1`` flag: below the
    value area (``close < VAL``), inside it (``VAL <= close <= VAH``), or above
    it (``close > VAH``). Whether the close is *inside* accepted value or has
    broken out of it is the cleanest, least over-fit read of the same context.

Both features wrap the leak-free :func:`scripts.smc_volume_profile.volume_profile_at`
trailing-window wrapper, so they are strictly point-in-time: they never read a
bar after the anchor.

This module is RECORDED-ONLY (ADR-0019 / ADR-0021 discipline): shadow features
whose values ride alongside event outcomes so a pre-registered purged
walk-forward A/B can decide whether they lift resolution. They are NOT wired into
the v1 score or any gate. They are honest-None: when the profile cannot be built,
the anchor close is absent, or the normalising range is degenerate, they return
``None`` rather than fabricating a value.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

# Reuse the v1 ATR lookback so this candidate shares the single trailing horizon
# every other v2 feature uses (no per-family tuning, minimal degrees of freedom).
from governance.family_event_score import ATR_PERIOD
from scripts.smc_volume_profile import volume_profile_at

# Provenance tag recording how each event's VRVP features were produced. The
# ``_v2`` suffix marks them as ADR-0021 candidates, distinct from the v1
# ``SCORE_SOURCE``.
VRVP_SOURCE = "volume_profile_vrvp_v2"


def _anchor_close(bar: Mapping[str, Any]) -> float | None:
    """Finite close of the anchor bar, or ``None`` when absent/invalid."""

    raw = bar.get("close", bar.get("c"))
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def vrvp_vpoc_distance_at(
    bars: Sequence[Mapping[str, Any]],
    anchor_idx: int,
    *,
    period: int = ATR_PERIOD,
) -> float | None:
    """Signed, range-normalised distance from the anchor close to the VPOC.

    Over the trailing window of ``period`` bars ending at ``anchor_idx``
    (inclusive), build the volume profile and return

        (close - vpoc) / (price_high - price_low)

    a scale-free signed displacement: ``> 0`` when the close is above the busiest
    price, ``< 0`` below it, ``0`` exactly at it. Normalising by the profiled
    price span keeps the feature comparable across symbols and volatility
    regimes.

    Strictly point-in-time via :func:`volume_profile_at`: the window covers
    indices ``[anchor_idx - period + 1, anchor_idx]`` and never touches a bar
    after the anchor.

    Returns ``None`` (feature honestly absent) when the anchor is out of range,
    the profile cannot be built, the anchor close is absent/invalid, or the
    profiled price range is non-positive (degenerate window -> undefined scale).
    """
    if anchor_idx < 0 or anchor_idx >= len(bars):
        return None

    close = _anchor_close(bars[anchor_idx])
    if close is None:
        return None

    profile = volume_profile_at(bars, anchor_idx, period=period)
    if profile is None:
        return None

    price_range = profile.price_high - profile.price_low
    if not math.isfinite(price_range) or price_range <= 0.0:
        return None
    if not math.isfinite(profile.vpoc):
        return None

    return (close - profile.vpoc) / price_range


def vrvp_value_area_position_at(
    bars: Sequence[Mapping[str, Any]],
    anchor_idx: int,
    *,
    period: int = ATR_PERIOD,
) -> float | None:
    """Discrete position of the anchor close relative to the value area.

    Over the trailing window of ``period`` bars ending at ``anchor_idx``
    (inclusive), build the volume profile and return

        -1.0  when  close < VAL   (below accepted value)
         0.0  when  VAL <= close <= VAH   (inside accepted value)
        +1.0  when  close > VAH   (above accepted value)

    The discrete form is deliberately the least over-fit read of value-area
    acceptance: it records only whether price has broken out of accepted value,
    not a continuous coordinate that would invite curve-fitting.

    Strictly point-in-time via :func:`volume_profile_at`: never touches a bar
    after the anchor.

    Returns ``None`` (feature honestly absent) when the anchor is out of range,
    the profile cannot be built, the anchor close is absent/invalid, the value
    area bounds are non-finite, or the bounds are inverted (``VAL > VAH``,
    a corrupt profile).
    """
    if anchor_idx < 0 or anchor_idx >= len(bars):
        return None

    close = _anchor_close(bars[anchor_idx])
    if close is None:
        return None

    profile = volume_profile_at(bars, anchor_idx, period=period)
    if profile is None:
        return None

    val = profile.val
    vah = profile.vah
    if not math.isfinite(val) or not math.isfinite(vah) or val > vah:
        return None

    if close < val:
        return -1.0
    if close > vah:
        return 1.0
    return 0.0


__all__ = [
    "VRVP_SOURCE",
    "vrvp_value_area_position_at",
    "vrvp_vpoc_distance_at",
]

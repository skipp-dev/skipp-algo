"""Visible-range volume profile (VRVP) — precise volume-by-price intelligence.

This module ports the precision logic of the ``SMC_VRVP_Overlay`` TradingView
study (EulerMethod-style visible-range volume profile) into vendor-neutral
Python so the engine can reason about *where* volume traded, not just *how much*.

It is the precise counterpart to the coarse ``_compute_volume_profile`` in
``scripts.smc_range_regime``, which bins each bar's whole volume into the single
row its *close* falls in and reports one VPOC. The coarse version is fine as a
range-regime input; this module adds the three precision features that the
coarse one lacks:

1. **Span distribution (LTF-equivalent).** Each bar's volume is spread across
   *every* price row its ``[low, high]`` span touches, weighted by a
   distribution kernel, instead of being dumped into the close bin. With no
   lower-timeframe feed available this span spread is the portable equivalent of
   the Pine study's ``request.security_lower_tf`` precision: it reconstructs the
   intra-bar shape of traded volume from the bar's own range.
2. **Delta split.** Up-volume (``close >= open``) and down-volume are tracked
   per row, so each row carries ``up``, ``down`` and ``delta = up - down`` — the
   buyer/seller breakdown the coarse profile cannot express.
3. **Multi-POC.** Up to N points of control are detected, either as the highest
   rows or (default) as separated high-volume nodes (local peaks with a minimum
   row separation), rather than a single VPOC.

Discipline: this is RECORDED-ONLY intelligence (ADR-0019 style). It computes a
profile over an explicit, caller-supplied bar window and is **not** wired into
the v1 score or any gate. The point-in-time wrapper ``volume_profile_at`` reads
only the trailing window ``[anchor - period + 1, anchor]`` and never a bar after
the anchor; every entry point returns ``None`` rather than fabricating a profile
when its inputs are absent or degenerate.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

# Provenance tag recording how a profile was produced.
VOLUME_PROFILE_SOURCE = "smc_vrvp_v1"

# Fraction of total volume that defines the value area (70% is the Market
# Profile convention and matches ``scripts.smc_range_regime.VALUE_AREA_PCT``).
DEFAULT_VALUE_AREA_PCT = 0.70

# Default number of price rows in the display profile.
DEFAULT_ROWS = 50

# Default number of points of control to surface.
DEFAULT_POC_COUNT = 3

_DISTRIBUTION_MODES = ("typical", "close", "uniform")
_POC_MODES = ("volume_nodes", "highest_rows")


@dataclass(frozen=True)
class VolumeRow:
    """One price row of the profile with its buyer/seller volume breakdown."""

    index: int
    low: float
    high: float
    mid: float
    up: float
    down: float

    @property
    def total(self) -> float:
        return self.up + self.down

    @property
    def delta(self) -> float:
        return self.up - self.down


@dataclass(frozen=True)
class VolumeProfile:
    """Result of a volume-by-price computation over a bar window."""

    rows: list[VolumeRow]
    vpoc: float
    pocs: list[float]
    vah: float
    val: float
    value_area_low: float
    value_area_high: float
    total_volume: float
    price_low: float
    price_high: float
    source: str = VOLUME_PROFILE_SOURCE
    diagnostics: dict[str, Any] = field(default_factory=dict)


def _bar_value(bar: Mapping[str, Any], *keys: str) -> float | None:
    """Return the first present, finite, float-coercible key, else ``None``."""

    for key in keys:
        if key not in bar:
            continue
        raw = bar[key]
        if raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value):
            return None
        return value
    return None


def _bar_ohlcv(bar: Mapping[str, Any]) -> tuple[float, float, float, float, float] | None:
    """Extract ``(open, high, low, close, volume)`` or ``None`` if unusable.

    Volume must be present and non-negative; high must be >= low; all values
    finite. Bars failing any check are reported as ``None`` so the caller can
    skip them without fabricating data.
    """

    open_ = _bar_value(bar, "open", "o")
    high = _bar_value(bar, "high", "h")
    low = _bar_value(bar, "low", "l")
    close = _bar_value(bar, "close", "c")
    volume = _bar_value(bar, "volume", "v")
    if open_ is None or high is None or low is None or close is None or volume is None:
        return None
    if volume < 0.0 or high < low:
        return None
    return open_, high, low, close, volume


def _tri_weight(price: float, center: float, half_width: float) -> float:
    """Triangular kernel: 1 at ``center``, fading to 0 at ``+/- half_width``."""

    if half_width <= 0.0:
        return 1.0
    w = 1.0 - abs(price - center) / half_width
    return w if w > 0.0 else 0.0


def _row_index(price: float, price_low: float, row_height: float, rows: int) -> int:
    idx = math.floor((price - price_low) / row_height)
    if idx < 0:
        return 0
    if idx > rows - 1:
        return rows - 1
    return idx


def _distribute_bar(
    *,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float,
    up_bins: list[float],
    down_bins: list[float],
    price_low: float,
    row_height: float,
    rows: int,
    distribution: str,
    degenerate_eps: float,
) -> None:
    """Spread one bar's volume across the rows its ``[low, high]`` span touches.

    Mirrors the Pine study's per-bar distribution: a degenerate (near-zero
    range) bar drops its whole volume in the close row; otherwise the volume is
    split across overlapping rows by the chosen kernel and renormalised so the
    bar conserves volume exactly.
    """

    is_up = close >= open_
    bar_range = high - low

    if bar_range < degenerate_eps:
        idx = _row_index(close, price_low, row_height, rows)
        if is_up:
            up_bins[idx] += volume
        else:
            down_bins[idx] += volume
        return

    if distribution == "close":
        center = close
    elif distribution == "uniform":
        center = math.nan  # unused
    else:  # "typical"
        center = (high + low + close) / 3.0
    half_spread = bar_range / 2.0

    k_start = _row_index(low, price_low, row_height, rows)
    k_end = _row_index(high, price_low, row_height, rows)

    weights: list[tuple[int, float]] = []
    weight_sum = 0.0
    for k in range(k_start, k_end + 1):
        row_bottom = price_low + k * row_height
        row_top = row_bottom + row_height
        overlap_top = min(high, row_top)
        overlap_bottom = max(low, row_bottom)
        if overlap_top <= overlap_bottom:
            continue
        if distribution == "uniform":
            weight = (overlap_top - overlap_bottom) / bar_range
        else:
            row_mid = (row_bottom + row_top) / 2.0
            weight = _tri_weight(row_mid, center, half_spread)
        if weight > 0.0:
            weights.append((k, weight))
            weight_sum += weight

    if weight_sum <= 0.0:
        # Kernel gave every overlapping row zero weight (possible when the
        # triangle apex sits outside the touched rows); fall back to the close
        # row so the bar still conserves its volume.
        idx = _row_index(close, price_low, row_height, rows)
        if is_up:
            up_bins[idx] += volume
        else:
            down_bins[idx] += volume
        return

    for k, weight in weights:
        contribution = volume * (weight / weight_sum)
        if is_up:
            up_bins[k] += contribution
        else:
            down_bins[k] += contribution


def _find_pocs(
    totals: Sequence[float],
    *,
    poc_count: int,
    poc_mode: str,
    min_separation: int | None,
) -> list[int]:
    """Return up to ``poc_count`` row indices ranked by volume (descending)."""

    rows = len(totals)
    if rows == 0:
        return []

    if poc_mode == "highest_rows":
        ranked = sorted(range(rows), key=lambda k: (totals[k], -k), reverse=True)
        return [k for k in ranked[:poc_count] if totals[k] > 0.0]

    # "volume_nodes": local peaks with a minimum row separation.
    auto_sep = max(2, round(rows / (poc_count * 2))) if poc_count > 0 else 2
    sep = min_separation if (min_separation is not None and min_separation > 0) else auto_sep

    peaks: list[int] = []
    for k in range(rows):
        c = totals[k]
        if c <= 0.0:
            continue
        prev_v = totals[k - 1] if k > 0 else 0.0
        next_v = totals[k + 1] if k < rows - 1 else 0.0
        if k == 0:
            is_peak = c > next_v
        elif k == rows - 1:
            is_peak = c > prev_v
        else:
            is_peak = c >= prev_v and c >= next_v and (c > prev_v or c > next_v)
        if is_peak:
            peaks.append(k)

    peaks.sort(key=lambda k: (totals[k], -k), reverse=True)

    selected: list[int] = []
    for cand in peaks:
        if len(selected) >= poc_count:
            break
        if all(abs(cand - chosen) >= sep for chosen in selected):
            selected.append(cand)
    return selected


def _value_area(
    totals: Sequence[float],
    primary_poc: int,
    *,
    value_area_pct: float,
) -> tuple[int, int]:
    """Expand from the primary POC until ``value_area_pct`` of volume is covered.

    Returns ``(val_index, vah_index)`` — the lowest and highest row indices in
    the value area.
    """

    rows = len(totals)
    total = sum(totals)
    if rows == 0 or total <= 0.0:
        return primary_poc, primary_poc

    target = total * value_area_pct
    vah_idx = primary_poc
    val_idx = primary_poc
    acc = totals[primary_poc]

    while acc < target:
        v_above = totals[vah_idx + 1] if vah_idx < rows - 1 else 0.0
        v_below = totals[val_idx - 1] if val_idx > 0 else 0.0
        if v_above == 0.0 and v_below == 0.0:
            break
        if v_above >= v_below and vah_idx < rows - 1:
            vah_idx += 1
            acc += v_above
        elif val_idx > 0:
            val_idx -= 1
            acc += v_below
        else:
            break
    return val_idx, vah_idx


def compute_volume_profile(
    bars: Sequence[Mapping[str, Any]],
    *,
    rows: int = DEFAULT_ROWS,
    value_area_pct: float = DEFAULT_VALUE_AREA_PCT,
    distribution: str = "typical",
    poc_count: int = DEFAULT_POC_COUNT,
    poc_mode: str = "volume_nodes",
    min_separation: int | None = None,
    ticksize: float | None = None,
) -> VolumeProfile | None:
    """Compute a precise volume-by-price profile over ``bars``.

    Args:
        bars: OHLCV bar mappings (``open``/``high``/``low``/``close``/``volume``).
            The caller decides the window; this function never looks outside it.
        rows: Number of price rows in the profile.
        value_area_pct: Fraction of volume defining the value area (0 < p <= 1).
        distribution: Intra-bar volume kernel — ``"typical"`` (triangle centred
            on the typical price, default), ``"close"`` (triangle centred on the
            close) or ``"uniform"`` (overlap-proportional).
        poc_count: Maximum number of points of control to surface.
        poc_mode: ``"volume_nodes"`` (separated local peaks, default) or
            ``"highest_rows"`` (top rows by volume).
        min_separation: Minimum row gap between volume nodes; ``None`` auto-sizes.
        ticksize: Price increment used to detect degenerate (zero-range) bars.

    Returns:
        A ``VolumeProfile``, or ``None`` if the inputs are unusable (no valid
        bars, non-positive total volume, or a degenerate overall price range).
    """

    if rows < 1:
        return None
    if not 0.0 < value_area_pct <= 1.0:
        return None
    if distribution not in _DISTRIBUTION_MODES:
        return None
    if poc_mode not in _POC_MODES:
        return None

    valid: list[tuple[float, float, float, float, float]] = []
    price_low = math.inf
    price_high = -math.inf
    for bar in bars:
        ohlcv = _bar_ohlcv(bar)
        if ohlcv is None:
            continue
        _open, high, low, close, volume = ohlcv
        valid.append(ohlcv)
        if low < price_low:
            price_low = low
        if high > price_high:
            price_high = high

    if not valid:
        return None

    price_range = price_high - price_low
    if price_range <= 0.0:
        return None

    row_height = price_range / rows
    # A bar narrower than one tick (or, lacking a ticksize, narrower than a tenth
    # of a row) is treated as degenerate and dropped into its close row.
    degenerate_eps = ticksize if (ticksize is not None and ticksize > 0.0) else row_height / 10.0

    up_bins = [0.0] * rows
    down_bins = [0.0] * rows
    for open_, high, low, close, volume in valid:
        if volume <= 0.0:
            continue
        _distribute_bar(
            open_=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            up_bins=up_bins,
            down_bins=down_bins,
            price_low=price_low,
            row_height=row_height,
            rows=rows,
            distribution=distribution,
            degenerate_eps=degenerate_eps,
        )

    totals = [up_bins[k] + down_bins[k] for k in range(rows)]
    total_volume = sum(totals)
    if total_volume <= 0.0:
        return None

    poc_indices = _find_pocs(
        totals,
        poc_count=poc_count,
        poc_mode=poc_mode,
        min_separation=min_separation,
    )
    if not poc_indices:
        # Degenerate fallback: pick the single highest row.
        poc_indices = [max(range(rows), key=lambda k: totals[k])]

    primary_poc = poc_indices[0]
    val_idx, vah_idx = _value_area(totals, primary_poc, value_area_pct=value_area_pct)

    profile_rows = [
        VolumeRow(
            index=k,
            low=price_low + k * row_height,
            high=price_low + (k + 1) * row_height,
            mid=price_low + (k + 0.5) * row_height,
            up=up_bins[k],
            down=down_bins[k],
        )
        for k in range(rows)
    ]

    def _row_mid(idx: int) -> float:
        return price_low + (idx + 0.5) * row_height

    return VolumeProfile(
        rows=profile_rows,
        vpoc=_row_mid(primary_poc),
        pocs=[_row_mid(idx) for idx in poc_indices],
        vah=price_low + (vah_idx + 1) * row_height,
        val=price_low + val_idx * row_height,
        value_area_low=price_low + val_idx * row_height,
        value_area_high=price_low + (vah_idx + 1) * row_height,
        total_volume=total_volume,
        price_low=price_low,
        price_high=price_high,
        diagnostics={
            "rows": rows,
            "distribution": distribution,
            "poc_mode": poc_mode,
            "poc_count": len(poc_indices),
            "value_area_pct": value_area_pct,
        },
    )


def volume_profile_at(
    bars: Sequence[Mapping[str, Any]],
    anchor_idx: int,
    *,
    period: int,
    **kwargs: Any,
) -> VolumeProfile | None:
    """Point-in-time wrapper: profile the trailing window ending at ``anchor_idx``.

    Reads only ``bars[anchor_idx - period + 1 : anchor_idx + 1]`` — never a bar
    after the anchor — so the result is leak-free by construction. Returns
    ``None`` for a bad period, an out-of-range anchor, or a window too short to
    cover ``period`` bars.
    """

    if period < 1:
        return None
    if anchor_idx < 0 or anchor_idx >= len(bars):
        return None
    start = anchor_idx - period + 1
    if start < 0:
        return None
    window = bars[start : anchor_idx + 1]
    return compute_volume_profile(window, **kwargs)

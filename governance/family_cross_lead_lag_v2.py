"""ADR-0021 — cross-asset lead-lag shadow feature.

Every other v2 feature is single-instrument: it looks only at the instrument's
own bar series. Cross-asset lead-lag is the first feature to look *outside* the
instrument — it measures whether a broad benchmark (SPY) *leads* the constituent,
the "common-factor price discovery" effect where index moves precede individual
constituents by one bar.

The statistic is a lag-1 asymmetric cross-correlation RATIO over the trailing
window of ``period`` bars ending at the anchor:

    lead_lag = corr(r^B_{t-1}, r^C_t) / corr(r^C_{t-1}, r^B_t)

where ``r^B`` are benchmark (SPY) one-bar returns and ``r^C`` are constituent
returns. The numerator measures how strongly the benchmark's PREVIOUS-bar return
predicts the constituent's CURRENT-bar return; the denominator measures the
reverse. Ratio ``> 1`` means the benchmark leads (information flows index ->
constituent); ratio ``< 1`` means the constituent leads; ``~1`` is symmetric
co-movement with no clear lead.

The lag is FIXED at one bar (15 minutes) — no per-event lag search, to keep the
degrees of freedom minimal (design doc §6.3 / §7 "do not optimize lag").

This is a genuinely ORTHOGONAL axis. The v1 score and every tested
microstructure feature (``ofi``, ``kyle_lambda``, ``vpin``, ``relative_volume``,
``average_trade_size``, ``signed_uoa_notional``, ``vrvp_*``) are pure
single-instrument reads; this is the first cross-instrument signal.

**Point-in-time guarantee.** The trailing window covers indices
``[anchor_idx - period + 1, anchor_idx]`` and never reads a bar after the anchor
on EITHER series. The benchmark bar at ``anchor_idx`` is the SPY bar whose
timestamp matches the constituent's anchor bar (both are bars on the same 15m
exchange grid), so the benchmark close is known at the same time as the
constituent close — no look-ahead.

This module is RECORDED-ONLY (ADR-0019 / ADR-0021 discipline): a shadow feature
whose values ride alongside event outcomes so the pre-registered purged
walk-forward A/B can decide whether it lifts resolution. It is NOT wired into the
v1 score or any gate. It is honest-None: it returns ``None`` rather than
fabricating a value when its inputs are absent, the two series are misaligned, or
either return series is degenerate (zero variance -> correlation undefined).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

# Reuse the v1 ATR lookback so this candidate shares the single trailing horizon
# every other v2 feature uses (no per-family tuning, minimal degrees of freedom).
from governance.family_event_score import ATR_PERIOD

# Provenance tag recording how each event's lead-lag feature was produced. The
# ``_v2`` suffix marks it as an ADR-0021 candidate, distinct from the v1
# ``SCORE_SOURCE``.
CROSS_LEAD_LAG_SOURCE = "cross_asset_lead_lag_v2"

# Lag horizon in bars. FIXED at one bar — the lead-lag thesis is "previous-bar
# benchmark return predicts current-bar constituent return". Exposed as a module
# constant for clarity, NOT as a tunable parameter (design doc §7).
_LAG_BARS = 1


def _bar_close(bar: Mapping[str, Any]) -> float | None:
    """Finite close of one bar, or ``None`` when absent/invalid."""
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


def _bar_timestamp(bar: Mapping[str, Any]) -> float | None:
    """Finite epoch-second timestamp of one bar, or ``None`` when absent/invalid."""
    raw = bar.get("timestamp")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def _window_closes(
    bars: Sequence[Mapping[str, Any]], start: int, anchor_idx: int
) -> list[float] | None:
    """Closes for ``bars[start : anchor_idx + 1]``, or ``None`` if any is invalid."""
    closes: list[float] = []
    for k in range(start, anchor_idx + 1):
        close = _bar_close(bars[k])
        if close is None:
            return None
        closes.append(close)
    return closes


def _returns(closes: Sequence[float]) -> list[float] | None:
    """Simple one-bar returns from a close series, or ``None`` if any is invalid.

    A non-positive base close would make the return undefined (division by zero
    or a negative price), so the whole series is refused rather than fabricated.
    """
    rets: list[float] = []
    for i in range(1, len(closes)):
        base = closes[i - 1]
        if base <= 0.0:
            return None
        rets.append((closes[i] - base) / base)
    return rets


def _pearson(x: Sequence[float], y: Sequence[float]) -> float | None:
    """Pearson correlation of two equal-length series, or ``None`` if degenerate.

    Returns ``None`` when either series has zero variance (the correlation
    denominator is undefined) — never a fabricated 0.0.
    """
    n = len(x)
    if n < 2 or n != len(y):
        return None
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    cov = 0.0
    var_x = 0.0
    var_y = 0.0
    for xi, yi in zip(x, y):
        dx = xi - mean_x
        dy = yi - mean_y
        cov += dx * dy
        var_x += dx * dx
        var_y += dy * dy
    if var_x <= 0.0 or var_y <= 0.0:
        return None
    denom = math.sqrt(var_x * var_y)
    if denom <= 0.0:
        return None
    return cov / denom


def cross_lead_lag_at(
    bars: Sequence[Mapping[str, Any]],
    benchmark_bars: Sequence[Mapping[str, Any]],
    anchor_idx: int,
    *,
    period: int = ATR_PERIOD,
) -> float | None:
    """Lag-1 asymmetric cross-correlation ratio (benchmark-leads / constituent-leads).

    Over the trailing window of ``period`` bars ending at ``anchor_idx``
    (inclusive), build constituent returns ``r^C`` and benchmark returns ``r^B``
    and return

        corr(r^B_{t-1}, r^C_t) / corr(r^C_{t-1}, r^B_t)

    a scale-free lead-lag statistic: ``> 1`` when the benchmark leads the
    constituent, ``< 1`` when the constituent leads, ``~1`` for symmetric
    co-movement. The lag is fixed at one bar.

    Strictly point-in-time: the window covers indices
    ``[anchor_idx - period + 1, anchor_idx]`` and never touches a bar after the
    anchor on either series. ``benchmark_bars`` is assumed index-aligned to
    ``bars`` (same 15m exchange grid); the caller
    (``governance.family_event_adapter.family_events_from_structure``) enforces
    timestamp alignment before calling and degrades to ``None`` on any mismatch.

    Returns ``None`` (feature honestly absent) when: ``period`` is below 3 (the
    lag-1 cross-correlation needs at least two paired return points), the anchor
    is out of range on either series, the two series differ in length, any bar in
    the window lacks a valid ``close`` (or a benchmark ``timestamp`` mismatches
    the constituent's at the anchor), either return series is zero-variance
    (correlation undefined), or the denominator cross-correlation is zero (the
    ratio is undefined).
    """
    # Need at least period bars of trailing history on the constituent, and the
    # lag-1 cross-correlation needs >= 2 paired points => period >= 3 closes
    # (period-1 returns, then period-2 lagged pairs => >= 2 requires period >= 4?
    # No: period closes -> period-1 returns -> (period-1)-1 = period-2 lag pairs;
    # period-2 >= 2 => period >= 4). Refuse below 3 closes outright (no returns at
    # all) and let _pearson refuse the n<2 paired case for period == 3.
    if period < 3:
        return None
    if anchor_idx < period - 1 or anchor_idx >= len(bars):
        return None
    if len(benchmark_bars) != len(bars):
        return None
    if anchor_idx >= len(benchmark_bars):
        return None

    start = anchor_idx - period + 1

    # Anchor-bar timestamp alignment guard (belt-and-braces; the adapter already
    # validates the whole series, but this keeps the extractor self-contained and
    # honest if called directly).
    c_ts = _bar_timestamp(bars[anchor_idx])
    b_ts = _bar_timestamp(benchmark_bars[anchor_idx])
    if c_ts is None or b_ts is None or c_ts != b_ts:
        return None

    c_closes = _window_closes(bars, start, anchor_idx)
    if c_closes is None:
        return None
    b_closes = _window_closes(benchmark_bars, start, anchor_idx)
    if b_closes is None:
        return None

    c_ret = _returns(c_closes)
    b_ret = _returns(b_closes)
    if c_ret is None or b_ret is None:
        return None
    if len(c_ret) != len(b_ret) or len(c_ret) < _LAG_BARS + 2:
        return None

    # Lag-1 pairs: benchmark[t-1] vs constituent[t], and the reverse.
    bench_lead_x = b_ret[: -_LAG_BARS]  # r^B_{t-1}
    cons_curr_y = c_ret[_LAG_BARS:]  # r^C_t
    cons_lead_x = c_ret[: -_LAG_BARS]  # r^C_{t-1}
    bench_curr_y = b_ret[_LAG_BARS:]  # r^B_t

    numerator = _pearson(bench_lead_x, cons_curr_y)
    denominator = _pearson(cons_lead_x, bench_curr_y)
    if numerator is None or denominator is None:
        return None
    if denominator == 0.0:
        return None

    return numerator / denominator


__all__ = ["CROSS_LEAD_LAG_SOURCE", "cross_lead_lag_at"]

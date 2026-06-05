"""Tick-level Hayashi-Yoshida cross-asset lead-lag (ADR-0021 v3 candidate).

Scope: ``docs/governance/tick_hayashi_yoshida_scope.md`` step 2 (the estimator).
This is the tick-native successor to
:mod:`governance.family_cross_lead_lag_v2`, which measured the cross-asset lead
on a 15m bar grid and returned a decisive *null* (ADR-0021 findings). The 15m
test had to resample two asynchronous tape series onto a common grid, which —
per the Epps effect — integrates a sub-minute lead away entirely. Hayashi-Yoshida
(2005) is the canonical fix: it estimates the cross-covariance of two
*asynchronous* return series **without resampling**, by summing products of
returns whose observation intervals overlap.

The lead-lag variant (shifted HY, Hoffmann-Rosenbaum-Yoshida 2013) computes the
HY cross-covariance over a grid of clock shifts ``theta`` and reads the lead off
the peak: shifting the benchmark's clock *forward* by ``theta`` aligns a past
benchmark move with a present constituent move, so the signed location of
``argmax_theta |HY(theta)|`` is the estimated lead time (positive ``theta`` =>
benchmark leads constituent).

Headline scalar (``cross_lead_lag_hy_at``) — chosen to be the tick-native analog
of the v2 ratio so the "did going tick-level change the verdict?" comparison is
apples-to-apples:

    ratio = max_{theta > 0} |HY(theta)|  /  max_{theta < 0} |HY(theta)|

unitless (the realized-variance normalization cancels), ``> 1`` when the
benchmark leads, ``< 1`` when the constituent leads, ``~1`` for symmetric
co-movement. This refines the scope's "normalized by zero-lag HY" wording to the
more robust, directly v2-comparable peak ratio.

Discipline carried over from v2:
* **Strictly point-in-time.** The window is the trailing ``window_s`` seconds of
  ticks *ending at and including* the anchor instant; no tick after the anchor is
  ever read on either series. The lag scan shifts intervals *mathematically*
  after slicing, so it never pulls in post-anchor data.
* **Honest-None.** Returns ``None`` (feature absent, never a fabricated number)
  on too-few ticks, zero realized variance, an empty window, unsorted input, a
  non-finite/non-positive price, or an undefined ratio denominator.

The pre-registered window/grid live as module constants (mirroring v2's
``ATR_PERIOD`` default) so they are fixed before any A/B, never tuned to outcome.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Sequence

# Provenance tag carried onto every emitted event, mirroring
# ``CROSS_LEAD_LAG_SOURCE`` in the v2 module.
CROSS_LEAD_LAG_HY_SOURCE = "cross_asset_lead_lag_hy_v3"

# Pre-registered (scope section 4). Trailing PIT window of ticks ending AT the
# anchor, in seconds. 1800s = 30 min, matching the step-1 coverage window where
# every event anchor carried >= 44 (p5) benchmark ticks.
_WINDOW_S = 1800.0

# Pre-registered symmetric lag grid magnitude in seconds: 2,4,...,60. The signed
# scan covers both +/- of each. The grid is FIXED here, never tuned to the
# outcome; the argmax is over the grid but the grid itself is locked.
_LAG_GRID_S: tuple[float, ...] = tuple(float(s) for s in range(2, 61, 2))

# Need at least two non-degenerate returns per series for a defined realized
# variance and a non-trivial overlap sum.
_MIN_RETURNS = 2

_NS_PER_S = 1_000_000_000.0


def _slice_returns(
    ts_ns: Sequence[int],
    price: Sequence[float],
    lo_ns: int,
    hi_ns: int,
) -> tuple[list[float], list[int], list[int], float] | None:
    """Slice ``[lo_ns, hi_ns]`` and build log-returns + their time intervals.

    Returns ``(returns, interval_starts, interval_ends, realized_variance)`` or
    ``None`` when the window yields fewer than two usable returns. Duplicate
    timestamps (simultaneous prints) collapse to the latest price — a PIT-safe
    dedup — so every emitted interval has strictly positive duration. Input is
    assumed sorted ascending by ``ts_ns`` (as the pull writes it); a strictly
    decreasing step is treated as corruption and refused.
    """
    n = len(ts_ns)
    if n == 0 or len(price) != n:
        return None

    lo = bisect.bisect_left(ts_ns, lo_ns)
    hi = bisect.bisect_right(ts_ns, hi_ns)

    rets: list[float] = []
    starts: list[int] = []
    ends: list[int] = []
    prev_t: int | None = None
    prev_p: float | None = None
    for k in range(lo, hi):
        try:
            ti = int(ts_ns[k])
            pf = float(price[k])
        except (TypeError, ValueError):
            return None
        if not math.isfinite(pf) or pf <= 0.0:
            return None
        if prev_t is None:
            prev_t, prev_p = ti, pf
            continue
        if ti == prev_t:
            # Simultaneous print: keep the latest price, emit no interval.
            prev_p = pf
            continue
        if ti < prev_t:
            return None  # unsorted -> refuse rather than fabricate
        rets.append(math.log(pf / prev_p))  # type: ignore[arg-type]
        starts.append(prev_t)
        ends.append(ti)
        prev_t, prev_p = ti, pf

    if len(rets) < _MIN_RETURNS:
        return None
    realized_var = math.fsum(r * r for r in rets)
    return rets, starts, ends, realized_var


def _hy_sum(
    rx: list[float],
    xs: list[int],
    xe: list[int],
    ry: list[float],
    ys: list[int],
    ye: list[int],
    shift_ns: int,
) -> float:
    """Hayashi-Yoshida cross-covariance of X and Y with Y's clock shifted.

    Sums ``rx[i] * ry[j]`` over every pair whose half-open intervals
    ``(xs[i], xe[i]]`` and the shifted ``(ys[j] + shift, ye[j] + shift]``
    overlap. Both interval lists are sorted and internally disjoint (consecutive
    ticks), so a single two-pointer sweep enumerates all overlapping pairs in
    O(len(X) + len(Y)) — advancing whichever interval ends first.
    """
    i = j = 0
    nx, ny = len(rx), len(ry)
    acc = 0.0
    while i < nx and j < ny:
        ys_s = ys[j] + shift_ns
        ye_s = ye[j] + shift_ns
        # Half-open overlap: (xs, xe] meets (ys_s, ye_s] iff xs < ye_s and ys_s < xe.
        if xs[i] < ye_s and ys_s < xe[i]:
            acc += rx[i] * ry[j]
        if xe[i] <= ye_s:
            i += 1
        else:
            j += 1
    return acc


def hy_lead_lag_curve(
    cons_ts_ns: Sequence[int],
    cons_price: Sequence[float],
    bench_ts_ns: Sequence[int],
    bench_price: Sequence[float],
    anchor_ts: float,
    *,
    window_s: float = _WINDOW_S,
    lag_grid_s: Sequence[float] = _LAG_GRID_S,
) -> dict[str, object] | None:
    """Full shifted-HY lead-lag curve over the trailing PIT tick window.

    ``anchor_ts`` is the anchor instant in epoch **seconds** (the bar-open the
    event anchors on). The window is ``[anchor_ts - window_s, anchor_ts]`` on
    both tape series, nanosecond-exact.

    Returns a dict with ``lags_s`` (signed, sorted), ``hy`` (matching HY values),
    ``argmax_lag_s`` (signed lead estimate; ``> 0`` => benchmark leads),
    ``ratio`` (lead-peak / lag-peak), and ``rho_peak`` (the peak |HY| normalized
    to a correlation magnitude). Returns ``None`` honestly when the window is
    degenerate (see :func:`_slice_returns`), either realized variance is zero, or
    the lag-side peak is zero (ratio undefined).
    """
    if window_s <= 0.0 or not lag_grid_s:
        return None
    try:
        anchor = float(anchor_ts)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(anchor):
        return None

    hi_ns = round(anchor * _NS_PER_S)
    lo_ns = round((anchor - window_s) * _NS_PER_S)

    cons = _slice_returns(cons_ts_ns, cons_price, lo_ns, hi_ns)
    bench = _slice_returns(bench_ts_ns, bench_price, lo_ns, hi_ns)
    if cons is None or bench is None:
        return None
    rx, xs, xe, rv_x = cons
    ry, ys, ye, rv_y = bench
    if rv_x <= 0.0 or rv_y <= 0.0:
        return None
    norm = math.sqrt(rv_x * rv_y)

    magnitudes = sorted({float(g) for g in lag_grid_s if float(g) > 0.0})
    if not magnitudes:
        return None

    lags: list[float] = []
    hy_vals: list[float] = []
    for lag in magnitudes:
        shift = round(lag * _NS_PER_S)
        hy_pos = _hy_sum(rx, xs, xe, ry, ys, ye, shift)
        hy_neg = _hy_sum(rx, xs, xe, ry, ys, ye, -shift)
        lags.append(-lag)
        hy_vals.append(hy_neg)
        lags.append(lag)
        hy_vals.append(hy_pos)

    order = sorted(range(len(lags)), key=lambda k: lags[k])
    lags = [lags[k] for k in order]
    hy_vals = [hy_vals[k] for k in order]

    lead_peak = max((abs(h) for lg, h in zip(lags, hy_vals) if lg > 0.0), default=0.0)
    lag_peak = max((abs(h) for lg, h in zip(lags, hy_vals) if lg < 0.0), default=0.0)
    if lag_peak <= 0.0:
        return None

    amax = max(range(len(hy_vals)), key=lambda k: abs(hy_vals[k]))
    return {
        "lags_s": lags,
        "hy": hy_vals,
        "argmax_lag_s": lags[amax],
        "ratio": lead_peak / lag_peak,
        "rho_peak": abs(hy_vals[amax]) / norm,
    }


def cross_lead_lag_hy_at(
    cons_ts_ns: Sequence[int],
    cons_price: Sequence[float],
    bench_ts_ns: Sequence[int],
    bench_price: Sequence[float],
    anchor_ts: float,
    *,
    window_s: float = _WINDOW_S,
    lag_grid_s: Sequence[float] = _LAG_GRID_S,
) -> float | None:
    """Tick-level HY lead-lag ratio at ``anchor_ts`` (the v3 headline scalar).

    Thin wrapper over :func:`hy_lead_lag_curve` returning the unitless
    lead/lag peak ratio (``> 1`` => benchmark leads constituent), or ``None``
    when the curve is undefined. This is the value the A/B harness consumes under
    feature key ``cross_lead_lag_hy``.
    """
    curve = hy_lead_lag_curve(
        cons_ts_ns,
        cons_price,
        bench_ts_ns,
        bench_price,
        anchor_ts,
        window_s=window_s,
        lag_grid_s=lag_grid_s,
    )
    if curve is None:
        return None
    return float(curve["ratio"])  # type: ignore[arg-type]


__all__ = [
    "CROSS_LEAD_LAG_HY_SOURCE",
    "cross_lead_lag_hy_at",
    "hy_lead_lag_curve",
]

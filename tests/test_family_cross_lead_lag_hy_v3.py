"""Synthetic property tests for the tick-level Hayashi-Yoshida estimator.

The contract that matters: on two **asynchronous** tape series with a *known*
injected lead, the estimator must recover that lead's sign and (approximately)
its magnitude BEFORE it is ever trusted on real data. The series are sampled at
different random tick times to genuinely exercise HY's non-synchronous handling
(a common-grid resampler would integrate the lead away -- the exact failure that
made the 15m bar test null).
"""

from __future__ import annotations

import math
import random

import pytest

from governance.family_cross_lead_lag_hy_v3 import (
    CROSS_LEAD_LAG_HY_SOURCE,
    cross_lead_lag_hy_at,
    hy_lead_lag_curve,
)

_NS = 1_000_000_000
_ANCHOR_S = 1800.0
_SPAN_S = 1800.0


def _signal(t: float) -> float:
    """Smooth, non-degenerate driver. Dominant period 120s keeps the single
    cross-covariance peak inside the +/-60s lag grid."""
    return math.sin(2.0 * math.pi * t / 120.0) + 0.5 * math.sin(2.0 * math.pi * t / 311.0)


def _async_times(seed: int, n: int = 800, span: float = _SPAN_S) -> list[float]:
    rng = random.Random(seed)
    return sorted(rng.uniform(0.0, span) for _ in range(n))


def _series(times: list[float], shift_s: float, *, amp: float = 0.01) -> tuple[list[int], list[float]]:
    """Price path = base * exp(amp * signal(t - shift)); log-returns ~ amp * signal diffs."""
    ts = [round(t * _NS) for t in times]
    px = [100.0 * math.exp(amp * _signal(t - shift_s)) for t in times]
    return ts, px


def test_recovers_benchmark_leads() -> None:
    # constituent(t) = signal(t - L): the constituent reproduces the benchmark's
    # move L seconds late, i.e. the benchmark LEADS by L. Aligning requires
    # shifting the benchmark clock forward by +L => positive argmax.
    lead_s = 10.0
    bench_ts, bench_px = _series(_async_times(1), shift_s=0.0)
    cons_ts, cons_px = _series(_async_times(2), shift_s=lead_s)

    curve = hy_lead_lag_curve(cons_ts, cons_px, bench_ts, bench_px, anchor_ts=_ANCHOR_S)
    assert curve is not None
    assert abs(float(curve["argmax_lag_s"]) - lead_s) <= 2.0  # within one grid step
    assert float(curve["ratio"]) > 1.0  # lead side dominates


def test_recovers_constituent_leads() -> None:
    # Mirror: benchmark reproduces the constituent's move late => constituent
    # leads, argmax negative, ratio < 1.
    lead_s = 10.0
    bench_ts, bench_px = _series(_async_times(3), shift_s=lead_s)
    cons_ts, cons_px = _series(_async_times(4), shift_s=0.0)

    curve = hy_lead_lag_curve(cons_ts, cons_px, bench_ts, bench_px, anchor_ts=_ANCHOR_S)
    assert curve is not None
    assert abs(float(curve["argmax_lag_s"]) + lead_s) <= 2.0
    assert float(curve["ratio"]) < 1.0


def test_symmetric_comovement_ratio_near_one() -> None:
    # Same driver, no lead, different async sampling => neither side dominates.
    bench_ts, bench_px = _series(_async_times(5), shift_s=0.0)
    cons_ts, cons_px = _series(_async_times(6), shift_s=0.0)

    curve = hy_lead_lag_curve(cons_ts, cons_px, bench_ts, bench_px, anchor_ts=_ANCHOR_S)
    assert curve is not None
    assert 0.5 < float(curve["ratio"]) < 2.0


def test_scalar_equals_curve_ratio() -> None:
    bench_ts, bench_px = _series(_async_times(7), shift_s=0.0)
    cons_ts, cons_px = _series(_async_times(8), shift_s=10.0)

    curve = hy_lead_lag_curve(cons_ts, cons_px, bench_ts, bench_px, anchor_ts=_ANCHOR_S)
    scalar = cross_lead_lag_hy_at(cons_ts, cons_px, bench_ts, bench_px, anchor_ts=_ANCHOR_S)
    assert curve is not None and scalar is not None
    assert scalar == pytest.approx(float(curve["ratio"]))


def test_strictly_point_in_time() -> None:
    # Ticks strictly after the anchor must never change the result.
    bench_ts, bench_px = _series(_async_times(9), shift_s=0.0)
    cons_ts, cons_px = _series(_async_times(10), shift_s=10.0)
    base = cross_lead_lag_hy_at(cons_ts, cons_px, bench_ts, bench_px, anchor_ts=_ANCHOR_S)

    # Append wild future ticks past the anchor on both series.
    fut_ts = [round((_ANCHOR_S + d) * _NS) for d in (1.0, 5.0, 30.0)]
    fut_px = [999.0, 0.01, 500.0]
    poisoned = cross_lead_lag_hy_at(
        cons_ts + fut_ts, cons_px + fut_px,
        bench_ts + fut_ts, bench_px + fut_px,
        anchor_ts=_ANCHOR_S,
    )
    assert base is not None and poisoned is not None
    assert poisoned == pytest.approx(base)


def test_none_on_too_few_ticks() -> None:
    assert cross_lead_lag_hy_at([0], [100.0], [0, _NS], [100.0, 101.0], anchor_ts=_ANCHOR_S) is None


def test_none_on_zero_variance() -> None:
    # Flat constituent prices => zero realized variance => undefined.
    ts = [round(t * _NS) for t in (1.0, 2.0, 3.0, 4.0)]
    flat = [100.0] * 4
    bench_ts, bench_px = _series(_async_times(11), shift_s=0.0)
    assert cross_lead_lag_hy_at(ts, flat, bench_ts, bench_px, anchor_ts=_ANCHOR_S) is None


def test_none_on_empty_window() -> None:
    bench_ts, bench_px = _series(_async_times(12), shift_s=0.0)
    cons_ts, cons_px = _series(_async_times(13), shift_s=0.0)
    # Anchor far before any tick => trailing window empty.
    assert cross_lead_lag_hy_at(cons_ts, cons_px, bench_ts, bench_px, anchor_ts=-5000.0) is None


def test_none_on_unsorted_input() -> None:
    ts = [round(t * _NS) for t in (1.0, 5.0, 3.0, 9.0)]  # 5 then 3: decreasing
    px = [100.0, 101.0, 102.0, 103.0]
    bench_ts, bench_px = _series(_async_times(14), shift_s=0.0)
    assert cross_lead_lag_hy_at(ts, px, bench_ts, bench_px, anchor_ts=_ANCHOR_S) is None


def test_collapses_duplicate_timestamps() -> None:
    # Two prints at the same instant must collapse (latest price wins), not crash.
    ts = [0, 0, 5 * _NS, 10 * _NS, 15 * _NS]
    px = [100.0, 100.5, 101.0, 100.7, 101.3]
    bench_ts, bench_px = _series(_async_times(15), shift_s=0.0)
    out = cross_lead_lag_hy_at(ts, px, bench_ts, bench_px, anchor_ts=_ANCHOR_S)
    assert out is not None and math.isfinite(out)


def test_source_tag() -> None:
    assert CROSS_LEAD_LAG_HY_SOURCE == "cross_asset_lead_lag_hy_v3"

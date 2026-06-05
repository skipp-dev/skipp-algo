"""ADR-0021 — cross-asset lead-lag shadow feature: extractor tests.

Covers the lag-1 asymmetric cross-correlation ratio against an index-aligned
benchmark, the exact ``+/-1`` ratios obtainable from the minimal (two-paired-
point) window, the honest-None refusals (period below the minimum, short
history, missing close, anchor-timestamp mismatch, length mismatch, zero-variance
returns, anchor out of range), and leak-freedom (bars after the anchor on either
series never change the result).

For a two-point Pearson correlation the value is exactly ``sign((x0-x1)(y0-y1))``,
i.e. ``+/-1`` with no floating-point slack, so the ``period == 4`` cases below
(four closes -> three returns -> two lag-paired points) yield exact ratios.
"""

from __future__ import annotations

from governance.family_cross_lead_lag_v2 import (
    CROSS_LEAD_LAG_SOURCE,
    cross_lead_lag_at,
)
from governance.family_event_score import ATR_PERIOD

_T0 = 1_700_000_000.0
_STEP = 900.0  # 15-minute bars (seconds)


def _bar(i: int, *, close: float, timestamp: float | None = None) -> dict:
    ts = _T0 + i * _STEP if timestamp is None else timestamp
    return {
        "timestamp": ts,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
    }


def _series(closes: list[float], *, shift: float = 0.0) -> list[dict]:
    """Aligned bar series from a list of closes; ``shift`` perturbs timestamps."""
    return [
        _bar(i, close=c, timestamp=_T0 + i * _STEP + shift)
        for i, c in enumerate(closes)
    ]


def test_source_tag_is_stable() -> None:
    assert CROSS_LEAD_LAG_SOURCE == "cross_asset_lead_lag_v2"


def test_ratio_is_plus_one_when_both_series_accelerate() -> None:
    # period=4 -> 3 returns -> 2 lag-paired points (exact +/-1 Pearson).
    # Benchmark returns strictly increasing: diffs (+, +).
    bench = _series([100.0, 101.0, 103.0, 106.0])
    # Constituent returns strictly increasing too: diffs (+, +).
    #   rc = [0.01, 0.019802, 0.029126]
    cons = _series([50.0, 50.5, 51.5, 53.0])
    # numerator   = sign((rb2-rb1)*(rc3-rc2)) = sign(+*+) = +1
    # denominator = sign((rc2-rc1)*(rb3-rb2)) = sign(+*+) = +1
    assert cross_lead_lag_at(cons, bench, 3, period=4) == 1.0


def test_ratio_is_minus_one_when_constituent_returns_reverse() -> None:
    bench = _series([100.0, 101.0, 103.0, 106.0])  # diffs (+, +)
    # Constituent returns: rc1=0.03, rc2=0.01, rc3=0.02 -> diffs (-, +).
    cons = _series([100.0, 103.0, 104.03, 106.1106])
    # numerator   = sign((rb2-rb1)*(rc3-rc2)) = sign(+*+) = +1
    # denominator = sign((rc2-rc1)*(rb3-rb2)) = sign(-*+) = -1
    assert cross_lead_lag_at(cons, bench, 3, period=4) == -1.0


def test_none_when_period_below_three() -> None:
    bench = _series([100.0, 101.0, 102.0, 103.0])
    cons = _series([50.0, 50.5, 51.0, 51.5])
    assert cross_lead_lag_at(cons, bench, 3, period=2) is None


def test_none_when_period_three_has_single_lag_pair() -> None:
    # period=3 -> 2 returns -> 1 lag-paired point -> Pearson n<2 -> None.
    bench = _series([100.0, 101.0, 103.0])
    cons = _series([50.0, 50.5, 51.5])
    assert cross_lead_lag_at(cons, bench, 2, period=3) is None


def test_none_when_history_too_short() -> None:
    bench = _series([100.0, 101.0, 103.0])
    cons = _series([50.0, 50.5, 51.5])
    assert cross_lead_lag_at(cons, bench, 2, period=4) is None


def test_none_when_anchor_out_of_range() -> None:
    bench = _series([100.0, 101.0, 103.0, 106.0])
    cons = _series([50.0, 50.5, 51.5, 53.0])
    assert cross_lead_lag_at(cons, bench, 4, period=4) is None


def test_none_when_constituent_close_missing() -> None:
    bench = _series([100.0, 101.0, 103.0, 106.0])
    cons = _series([50.0, 50.5, 51.5, 53.0])
    del cons[1]["close"]
    assert cross_lead_lag_at(cons, bench, 3, period=4) is None


def test_none_when_benchmark_close_missing() -> None:
    bench = _series([100.0, 101.0, 103.0, 106.0])
    cons = _series([50.0, 50.5, 51.5, 53.0])
    del bench[2]["close"]
    assert cross_lead_lag_at(cons, bench, 3, period=4) is None


def test_none_when_lengths_differ() -> None:
    bench = _series([100.0, 101.0, 103.0])
    cons = _series([50.0, 50.5, 51.5, 53.0])
    assert cross_lead_lag_at(cons, bench, 3, period=4) is None


def test_none_when_anchor_timestamp_misaligned() -> None:
    bench = _series([100.0, 101.0, 103.0, 106.0], shift=1.0)  # off by a second
    cons = _series([50.0, 50.5, 51.5, 53.0])
    assert cross_lead_lag_at(cons, bench, 3, period=4) is None


def test_none_when_constituent_returns_zero_variance() -> None:
    bench = _series([100.0, 101.0, 103.0, 106.0])
    cons = _series([50.0, 50.0, 50.0, 50.0])  # flat -> zero-variance returns
    assert cross_lead_lag_at(cons, bench, 3, period=4) is None


def test_none_when_benchmark_returns_zero_variance() -> None:
    bench = _series([100.0, 100.0, 100.0, 100.0])  # flat
    cons = _series([50.0, 50.5, 51.5, 53.0])
    assert cross_lead_lag_at(cons, bench, 3, period=4) is None


def test_leak_free_ignores_bars_after_anchor() -> None:
    bench_head = _series([100.0, 101.0, 103.0, 106.0])
    cons_head = _series([50.0, 50.5, 51.5, 53.0])
    bench_tail = _series([100.0, 101.0, 103.0, 106.0, 999.0, 0.5])
    cons_tail = _series([50.0, 50.5, 51.5, 53.0, 999.0, 0.5])
    assert cross_lead_lag_at(cons_head, bench_head, 3, period=4) == cross_lead_lag_at(
        cons_tail, bench_tail, 3, period=4
    )


def test_default_period_uses_atr_lookback() -> None:
    # With ATR_PERIOD bars of monotonic-but-curved closes on both legs the
    # feature emits a finite ratio (smoke test of the default-period path).
    n = ATR_PERIOD + 2
    bench = _series([100.0 + i * i * 0.1 for i in range(n)])
    cons = _series([50.0 + i * 0.7 + i * i * 0.05 for i in range(n)])
    result = cross_lead_lag_at(cons, bench, n - 1)
    assert result is not None

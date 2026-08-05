"""``compute_squeeze_on`` must actually warm up its two recursive indicators.

``#4013`` moved the squeeze to "full Pine parity", but only the Bollinger half
of the formula is a pure rolling window. The Keltner half needs history:
``ta.ema`` and ``ta.atr = ta.rma(ta.tr, length)`` are recursive over the whole
series TradingView has on the chart.

``_TF_RAW_BAR_REQUIREMENTS`` provisioned exactly ``period`` aggregated bars for
every timeframe (measured 2026-08-05: 5m -> 100 raw -> 20 aggregated). With
exactly ``length`` values ``_wilder_rma_last`` runs ZERO recursion steps and
degenerates to a plain mean of true ranges — bit-identical to the SMA-of-TR
that #4013 said it replaced — and ``_ema_last`` leaves 14.9 % of the Keltner
centre on its seed bar.

Seed weight decays as ``(1-alpha)**n``: the EMA needs 47 steps and the Wilder
RMA 90 steps to drop below 1 %. So a correct provisioning carries ``period``
plus a warm-up allowance, not ``period`` alone.
"""

from __future__ import annotations

import math

from services.live_overlay_daemon import compute

_PERIOD = 20
# Below this the seed bar still contributes >1% of the Keltner centre / ATR.
_MIN_WARMUP_STEPS = 47


def _minute_bars(count: int, *, start_ns: int = 0) -> list[dict[str, float | int]]:
    """Synthetic 1-minute bars stamped at bar OPEN, like the Databento feed."""
    return [
        {
            "ts_event": start_ns + i * 60_000_000_000,
            "close": 100.0 + 0.01 * i,
            "high": 100.2 + 0.01 * i,
            "low": 99.8 + 0.01 * i,
            "open": 100.0 + 0.01 * i,
            "volume": 1000.0,
        }
        for i in range(count)
    ]


def test_the_wilder_rma_degenerates_to_a_mean_without_warmup() -> None:
    """Guards the mechanism itself, independent of any provisioning number."""
    values = [1.0 + 0.05 * i for i in range(_PERIOD)]
    assert compute._wilder_rma_last(values, _PERIOD) == sum(values) / _PERIOD, (
        "with exactly `length` values the recursion body never runs — this is "
        "the degenerate case the provisioning must avoid"
    )
    longer = values + values
    assert compute._wilder_rma_last(longer, _PERIOD) != sum(longer[:_PERIOD]) / _PERIOD


def test_a_mis_warmed_series_gets_no_verdict_at_all() -> None:
    """The guard that makes every timeframe safe, including the ones whose
    aggregation depends on the session calendar (1H/4H): a series long enough
    for the Bollinger window but too short for the recursion must return None,
    never a boolean computed from an unwarmed EMA/ATR.
    """
    for extra in (0, 1, _MIN_WARMUP_STEPS - 1):
        bars = _minute_bars(_PERIOD + extra)
        assert compute.compute_squeeze_on(bars) is None, (
            f"{_PERIOD + extra} bars is enough for the Bollinger window but not "
            f"for the recursion — a verdict here is a wrong verdict"
        )
    assert compute.compute_squeeze_on(_minute_bars(_PERIOD + _MIN_WARMUP_STEPS)) is not None


def test_the_served_5m_timeframe_provisions_the_warmup() -> None:
    """5m is the only timeframe that carries the trade fields (main.py overlays
    ``_get_signal_fields`` for tf == "5m"), so it must be warm, not merely
    non-null."""
    aggregated = len(
        compute._bars_for_timeframe(_minute_bars(compute.raw_bars_required("5m")), "5m")
    )
    assert aggregated - _PERIOD >= _MIN_WARMUP_STEPS, (
        f"5m provisions {aggregated} aggregated bars => {aggregated - _PERIOD} "
        f"warm-up steps, below the {_MIN_WARMUP_STEPS} needed for <1% seed weight"
    )


def test_pine_ema_seed_is_the_sma_of_the_first_length_values() -> None:
    """Pine's own reference implementation seeds ``ta.ema`` with ``ta.sma``:

        sum := na(sum[1]) ? ta.sma(src, length) : alpha*src + (1-alpha)*nz(sum[1])

    With exactly ``length`` samples that makes ``ta.ema`` equal ``ta.sma``. The
    daemon used ``vals[0]`` instead and asserted in its docstring that this was
    Pine's convention. The repo had already corrected the same defect elsewhere
    (open_prep/technical_analysis._ema, eval-findings B7, 2026-06-11).
    """
    closes = [100.0 + 0.5 * i for i in range(_PERIOD)]
    assert compute._ema_last(closes, _PERIOD) == sum(closes) / _PERIOD

    # And the seed must keep decaying correctly once history exists.
    longer = [100.0 + 0.5 * i for i in range(_PERIOD * 5)]
    alpha = 2.0 / (_PERIOD + 1)
    expected = sum(longer[:_PERIOD]) / _PERIOD
    for value in longer[_PERIOD:]:
        expected = alpha * value + (1.0 - alpha) * expected
    assert compute._ema_last(longer, _PERIOD) == expected


def test_seed_weight_is_negligible_at_the_provisioned_depth() -> None:
    """End-to-end property: at the depth we now provision for the served 5m
    timeframe, the first bar cannot move the Keltner centre materially."""
    aggregated = len(
        compute._bars_for_timeframe(_minute_bars(compute.raw_bars_required("5m")), "5m")
    )
    residual = (1.0 - 2.0 / (_PERIOD + 1)) ** (aggregated - 1)
    assert residual < 0.01, (
        f"the seed bar still carries {residual:.1%} of the EMA at "
        f"{aggregated} aggregated bars"
    )
    assert math.isfinite(residual)

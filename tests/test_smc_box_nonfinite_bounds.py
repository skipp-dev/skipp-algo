"""Regression tests: SMC box factories & SmcBox reject non-finite bounds.

Round-6 bug-hunt finding (report Bug 5). The predicate guards (``is_ob_up`` …)
reject non-finite OHLC they read, and ``SmcBox.is_breached`` guards non-finite
*prices*, but the box *bounds* themselves were never guarded:

* ``_ordered_bounds`` only ordered ``(a, b)`` — an ``inf`` top or ``NaN``
  bottom sailed straight through into a live ``SmcBox``.
* The factories mix in fields their predicate never saw — ``make_ob_up``'s
  ``low_t1`` and ``make_ob_down``'s ``high_t1`` — so a corrupt value reaches
  the factory even through the guarded detector pipeline.

A box with a non-finite bound corrupts structure silently: an ``inf`` top can
never be breached from above while the finite side still mitigates, and a
``NaN`` bound makes ``is_breached``/``height`` nonsensical. The backtester feeds
raw un-coerced OHLC, so this is backtest decision integrity.
"""

from __future__ import annotations

import math

import pytest

from services.live_overlay_daemon.smc_ringbuffer import (
    BoxType,
    Direction,
    SmcBox,
    make_fvg_down,
    make_fvg_up,
    make_ob_down,
    make_ob_up,
    make_rjb_down,
    make_rjb_up,
)

NON_FINITE = [float("inf"), float("-inf"), float("nan")]


# --------------------------------------------------------------------------
# Factories fail soft: return None (skip the box) on a non-finite bound.
# --------------------------------------------------------------------------


# low_t1 becomes the bottom only via min(low_t1, low_t2); a +inf is discarded by
# min and never reaches a bound, so only -inf/NaN corrupt the box.
@pytest.mark.parametrize("bad", [float("-inf"), float("nan")])
def test_make_ob_up_rejects_nonfinite_low_t1(bad: float) -> None:
    """low_t1 is NOT covered by is_ob_up, so it is the reachable gap."""
    assert make_ob_up(bar_index=5, high_t2=200.0, low_t1=bad, low_t2=100.0) is None


def test_make_ob_up_ignores_pos_inf_low_t1_via_min() -> None:
    """+inf low_t1 is discarded by min(+inf, low_t2); a valid box still forms."""
    box = make_ob_up(bar_index=5, high_t2=200.0, low_t1=float("inf"), low_t2=100.0)
    assert box is not None and box.top == 200.0 and box.bottom == 100.0


# high_t1 becomes the top only via max(high_t1, high_t2); a -inf is discarded.
@pytest.mark.parametrize("bad", [float("inf"), float("nan")])
def test_make_ob_down_rejects_nonfinite_high_t1(bad: float) -> None:
    """high_t1 is NOT covered by is_ob_down, so it is the reachable gap."""
    assert make_ob_down(bar_index=5, high_t1=bad, high_t2=101.0, low_t2=96.0) is None


@pytest.mark.parametrize("bad", NON_FINITE)
def test_all_factories_reject_nonfinite_bounds(bad: float) -> None:
    assert make_ob_up(5, high_t2=bad, low_t1=97.0, low_t2=96.0) is None
    assert make_ob_down(5, high_t1=105.0, high_t2=104.0, low_t2=bad) is None
    assert make_fvg_up(5, low_t=bad, high_t2=100.0) is None
    assert make_fvg_down(5, high_t=105.0, low_t2=bad) is None
    assert make_rjb_down(5, high_t2=bad, close_t2=96.0) is None
    assert make_rjb_up(5, close_t2=100.0, low_t2=bad) is None


def test_finite_factories_still_build_ordered_boxes() -> None:
    """The guard must not regress the happy path."""
    for box in [
        make_ob_up(10, high_t2=100.0, low_t1=97.0, low_t2=96.0),
        make_ob_down(10, high_t1=105.0, high_t2=104.0, low_t2=99.0),
        make_fvg_up(10, low_t=105.0, high_t2=100.0),
        make_fvg_down(10, high_t=105.0, low_t2=100.0),
        make_rjb_down(10, high_t2=100.0, close_t2=96.0),
        make_rjb_up(10, close_t2=100.0, low_t2=96.0),
    ]:
        assert box is not None
        assert math.isfinite(box.top) and math.isfinite(box.bottom)
        assert box.top >= box.bottom


def test_make_ob_down_keeps_finite_box_when_max_discards_neg_inf() -> None:
    """-inf high_t1 is discarded by max(high_t1, high_t2); the box is still valid."""
    box = make_ob_down(5, high_t1=float("-inf"), high_t2=101.0, low_t2=96.0)
    assert box is not None
    assert box.top == 101.0 and box.bottom == 96.0


# --------------------------------------------------------------------------
# SmcBox enforces the invariant directly: non-finite bounds raise (fail fast,
# like RingBuffer(max_size<=0)) — a box is only ever built from real prices.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("bad", NON_FINITE)
def test_smcbox_raises_on_nonfinite_top(bad: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        SmcBox(
            left=0, right=1, top=bad, bottom=100.0,
            box_type=BoxType.ORDER_BLOCK, direction=Direction.BULLISH, created_at=0,
        )


@pytest.mark.parametrize("bad", NON_FINITE)
def test_smcbox_raises_on_nonfinite_bottom(bad: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        SmcBox(
            left=0, right=1, top=100.0, bottom=bad,
            box_type=BoxType.ORDER_BLOCK, direction=Direction.BULLISH, created_at=0,
        )


def test_smcbox_still_normalises_inverted_finite_bounds() -> None:
    """The pre-existing inverted-box normalisation must survive the new guard."""
    box = SmcBox(
        left=0, right=1, top=90.0, bottom=110.0,
        box_type=BoxType.ORDER_BLOCK, direction=Direction.BULLISH, created_at=0,
    )
    assert box.top == 110.0 and box.bottom == 90.0


# --------------------------------------------------------------------------
# Integration: no corrupt box can enter the manager via the detector path.
# --------------------------------------------------------------------------


def test_detector_skips_corrupt_ob_without_crashing() -> None:
    """End-to-end: a bullish-OB pattern whose t1.low is NaN (a field is_ob_up
    never inspects) must not crash process_candle or add a non-finite box."""
    from services.live_overlay_daemon.smc_signal_detector import Candle, SmcSignalDetector

    detector = SmcSignalDetector(max_boxes_per_direction=5)
    # c0 (t2): normal. c1 (t1): bearish with a corrupt NaN low. c2 (t): bullish
    # close above c1.high -> is_ob_up passes, make_ob_up sees low_t1=NaN.
    stream = [
        Candle(bar_index=0, open=100.0, high=105.0, low=95.0, close=100.0, volume=1000),
        Candle(bar_index=1, open=104.0, high=104.0, low=float("nan"), close=100.0, volume=1000),
        Candle(bar_index=2, open=100.0, high=111.0, low=100.0, close=110.0, volume=1000),
    ]
    for candle in stream:
        detector.process_candle(candle)  # must not raise

    stored = (
        list(detector.box_manager.bullish_boxes)
        + list(detector.box_manager.bearish_boxes)
    )
    for box in stored:
        assert math.isfinite(box.top) and math.isfinite(box.bottom)
    # The corrupt OB+ was skipped, so no bullish box was created from it.
    assert detector.box_manager.bullish_boxes.size() == 0

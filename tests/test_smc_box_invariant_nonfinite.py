"""SMC box invariant: no box may hold or act on non-finite (NaN/±inf) bounds.

Bug-hunt found that the predicate guards merged earlier (isfinite on OHLC) did
NOT cover the box-construction and box-use paths: the factories, _ordered_bounds
and SmcBox.__post_init__ still accepted non-finite bounds, and is_breached only
guarded the candle high/low — not the box's own top/bottom. A box with top=inf
was therefore mitigated the instant low fell below a finite bottom. These tests
pin the invariant end to end (construction, ordering, breach, detector window,
strong-impulse ignition + out-of-order phase accounting).
"""
from __future__ import annotations

import math

import pytest

from services.live_overlay_daemon import smc_ringbuffer as rb
from services.live_overlay_daemon.smc_ringbuffer import (
    BoxType,
    Direction,
    SmcBox,
    SmcBoxManager,
    make_fvg_down,
    make_fvg_up,
    make_ob_down,
    make_ob_up,
    make_rjb_down,
    make_rjb_up,
)
from services.live_overlay_daemon.smc_signal_detector import Candle, SmcSignalDetector
from services.live_overlay_daemon.strong_impulse_detector import (
    IgnitionCandleDetector,
    ImpulsePhase,
    ImpulseSignal,
    StrongImpulseDetector,
)

NAN = float("nan")
INF = float("inf")


def _box(top: float, bottom: float) -> SmcBox:
    return SmcBox(
        left=0, right=1, top=top, bottom=bottom,
        box_type=BoxType.ORDER_BLOCK, direction=Direction.BULLISH, created_at=0,
    )


class TestFactoryNonFinite:
    """SMC-1: factories reject NaN/±inf instead of building corrupt boxes."""

    def test_all_factories_reject_nan_and_inf(self) -> None:
        for bad in (NAN, INF, -INF):
            with pytest.raises(ValueError):
                make_ob_up(0, bad, 99.0, 98.0)
            with pytest.raises(ValueError):
                make_ob_up(0, 100.0, bad, 98.0)  # low_t1: the arg is_ob_up never guards
            with pytest.raises(ValueError):
                make_ob_down(0, bad, 101.0, 99.0)  # high_t1: is_ob_down never guards
            with pytest.raises(ValueError):
                make_fvg_up(0, bad, 100.0)
            with pytest.raises(ValueError):
                make_fvg_down(0, bad, 100.0)
            with pytest.raises(ValueError):
                make_rjb_down(0, bad, 100.0)
            with pytest.raises(ValueError):
                make_rjb_up(0, bad, 99.0)

    def test_finite_factory_inputs_still_build(self) -> None:
        box = make_ob_up(10, 100.0, 97.0, 96.0)
        assert (box.top, box.bottom) == (100.0, 96.0)


class TestOrderedBounds:
    """SMC-2: _ordered_bounds rejects non-finite and is idempotent for finite."""

    def test_rejects_nonfinite(self) -> None:
        for bad in (NAN, INF, -INF):
            with pytest.raises(ValueError):
                rb._ordered_bounds(0.0, bad)
            with pytest.raises(ValueError):
                rb._ordered_bounds(bad, 0.0)

    def test_idempotent_for_finite(self) -> None:
        once = rb._ordered_bounds(100.0, 110.0)
        assert once == rb._ordered_bounds(*once) == (110.0, 100.0)


class TestSmcBoxInvariant:
    """SMC-3/4/5: the box itself never holds or acts on non-finite bounds."""

    def test_construction_rejects_nonfinite_bounds(self) -> None:
        for bad in (NAN, INF, -INF):
            with pytest.raises(ValueError):
                _box(top=bad, bottom=100.0)
            with pytest.raises(ValueError):
                _box(top=110.0, bottom=bad)

    def test_finite_inverted_bounds_still_normalised(self) -> None:
        box = _box(top=100.0, bottom=110.0)
        assert (box.top, box.bottom) == (110.0, 100.0)

    def test_is_breached_ignores_corrupt_self_bounds(self) -> None:
        # Simulate a box that bypassed __post_init__ (e.g. a deserialization
        # path): is_breached must never act on it.
        corrupt = object.__new__(SmcBox)
        corrupt.top = INF
        corrupt.bottom = 100.0
        assert corrupt.is_breached(high=105.0, low=99.0) is False
        corrupt.top = 110.0
        corrupt.bottom = NAN
        assert corrupt.is_breached(high=105.0, low=99.0) is False

    def test_is_breached_still_works_for_finite_box(self) -> None:
        box = _box(top=110.0, bottom=100.0)
        assert box.is_breached(high=115.0, low=105.0) is True
        assert box.is_breached(high=108.0, low=105.0) is False

    def test_manager_cannot_hold_corrupt_box(self) -> None:
        # SMC-5: with the construction invariant, a corrupt box can't exist to
        # be added / served as active.
        mgr = SmcBoxManager(max_boxes_per_direction=5)
        with pytest.raises(ValueError):
            mgr.add_box(_box(top=NAN, bottom=100.0))
        assert mgr.get_active_boxes() == []


class TestDetectorWindowGuard:
    """SMC-6/7: a corrupt candle in the 3-bar window yields no non-finite box."""

    def test_nan_in_window_creates_no_nonfinite_box(self, caplog) -> None:
        import logging

        det = SmcSignalDetector(max_boxes_per_direction=10)
        # OB-shaped sequence, but t1.low (consumed by make_ob_up, never guarded
        # by is_ob_up) is NaN.
        seq = [
            Candle(0, 100.0, 101.0, 99.0, 100.0, 1000),
            Candle(1, 100.0, 101.0, 99.0, 100.0, 1000),
            Candle(2, 102.0, 103.0, 98.0, 99.0, 1000),
            Candle(3, 99.5, 100.0, NAN, 98.8, 1000),
            Candle(4, 99.0, 104.0, 98.5, 103.0, 2000),
        ]
        created = []
        with caplog.at_level(
            logging.WARNING, logger="services.live_overlay_daemon.smc_signal_detector"
        ):
            for c in seq:
                created += [s for s in det.process_candle(c) if s.event_type == "created"]

        assert all(math.isfinite(s.box.top) and math.isfinite(s.box.bottom) for s in created)
        assert all(
            math.isfinite(b.top) and math.isfinite(b.bottom)
            for b in det.get_active_structures()
        )
        assert any("non-finite OHLC" in r.getMessage() for r in caplog.records)

    def test_detection_resumes_on_clean_data(self) -> None:
        det = SmcSignalDetector(max_boxes_per_direction=10)
        det.process_candle(Candle(0, 100.0, INF, 99.0, 100.0, 0))  # corrupt
        det.process_candle(Candle(1, 102.0, 103.0, 98.0, 99.0, 1000))
        det.process_candle(Candle(2, 99.5, 100.0, 98.5, 98.8, 1000))
        signals = det.process_candle(Candle(3, 99.0, 104.0, 98.5, 103.0, 2000))
        ob = [
            s for s in signals
            if s.box_type == BoxType.ORDER_BLOCK and s.direction == Direction.BULLISH
        ]
        assert len(ob) == 1 and ob[0].event_type == "created"


class TestStrongImpulseNonFinite:
    """SMC-8/9: ignition rejects non-finite OHLC; phase accounting never
    records a negative confirmation for an out-of-order feed."""

    def test_ignition_detector_rejects_nonfinite(self) -> None:
        ig = IgnitionCandleDetector()
        ig.detect(0, 100.0, 101.0, 99.0, 100.0, 1.0)
        assert ig.detect(1, NAN, 101.0, 99.0, 100.0, 1.0) is None
        assert ig.detect(2, 100.0, INF, 99.0, 100.0, 1.0) is None
        assert all(math.isfinite(h["high"]) for h in ig.price_history)

    def test_update_phase_skips_out_of_order_bar(self) -> None:
        det = StrongImpulseDetector()
        det.active_impulses[100] = ImpulseSignal(
            bar_index=100, phase=ImpulsePhase.IGNITION, direction="long",
            ignition_bar=100, propulsion_strength=8.0, entry_price=100.0,
            invalidation_level=99.0, target_1=101.0, target_2=102.0, target_3=103.0,
            confirmation_bars=0,
        )
        # An earlier bar than the impulse's ignition bar must not advance it.
        updated = det.update_phase(bar_index=50, high=101.0, low=99.0, close=100.0)
        assert all(s.confirmation_bars >= 0 for s in updated)
        # The impulse itself keeps its non-negative confirmation count.
        assert det.active_impulses[100].confirmation_bars == 0

    def test_update_phase_advances_in_order(self) -> None:
        det = StrongImpulseDetector()
        det.active_impulses[10] = ImpulseSignal(
            bar_index=10, phase=ImpulsePhase.IGNITION, direction="long",
            ignition_bar=10, propulsion_strength=8.0, entry_price=100.0,
            invalidation_level=99.0, target_1=101.0, target_2=102.0, target_3=103.0,
            confirmation_bars=0,
        )
        updated = det.update_phase(bar_index=11, high=101.0, low=99.0, close=100.0)
        assert updated and updated[0].confirmation_bars == 1

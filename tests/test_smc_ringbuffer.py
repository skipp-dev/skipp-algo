"""Tests for SMC RingBuffer and technical analysis box manager.

Validates:
- O(1) append/eviction behavior (no O(n) array.shift)
- Bullish/bearish separation
- Mitigation state tracking
- Guard functions against NaN/edge-cases
- Box factory pattern
"""

from __future__ import annotations

import math
import pytest

from services.live_overlay_daemon.smc_ringbuffer import (
    BoxType,
    Direction,
    RingBuffer,
    SmcBox,
    SmcBoxManager,
    is_down,
    is_fvg_down,
    is_fvg_up,
    is_ob_down,
    is_ob_up,
    is_rjb_down,
    is_rjb_up,
    is_up,
    make_fvg_down,
    make_fvg_up,
    make_ob_down,
    make_ob_up,
    make_rjb_down,
    make_rjb_up,
)


class TestRingBuffer:
    """Test O(1) circular buffer."""

    def test_append_and_size(self) -> None:
        buf = RingBuffer[int](max_size=3)
        assert buf.size() == 0
        assert buf.append(1) is None  # Not full yet
        assert buf.size() == 1
        assert buf.append(2) is None
        assert buf.size() == 2

    def test_eviction_when_full(self) -> None:
        buf = RingBuffer[int](max_size=3)
        buf.append(1)
        buf.append(2)
        buf.append(3)
        assert buf.is_full()
        # Fourth append evicts oldest (1)
        evicted = buf.append(4)
        assert evicted == 1
        assert buf.size() == 3
        assert buf.get_oldest() == 2

    def test_get_by_index(self) -> None:
        buf = RingBuffer[int](max_size=5)
        buf.append(10)
        buf.append(20)
        buf.append(30)
        assert buf.get(0) == 10  # Oldest
        assert buf.get(1) == 20
        assert buf.get(2) == 30  # Latest
        assert buf.get(3) is None  # Out of bounds

    def test_get_latest(self) -> None:
        buf = RingBuffer[int](max_size=3)
        assert buf.get_latest() is None
        buf.append(1)
        assert buf.get_latest() == 1
        buf.append(2)
        assert buf.get_latest() == 2

    def test_iteration_oldest_to_newest(self) -> None:
        buf = RingBuffer[int](max_size=5)
        for i in range(1, 4):
            buf.append(i)
        assert list(buf) == [1, 2, 3]


class TestSmcBox:
    """Test box structure and breach detection."""

    def test_box_creation(self) -> None:
        box = SmcBox(
            left=10,
            right=15,
            top=100.0,
            bottom=95.0,
            box_type=BoxType.ORDER_BLOCK,
            direction=Direction.BULLISH,
            created_at=10,
        )
        assert box.width() == 5
        assert box.height() == 5.0
        assert not box.is_mitigated

    def test_is_breached_bullish(self) -> None:
        """Bullish box breached when price goes above top."""
        box = SmcBox(
            left=10,
            right=15,
            top=100.0,
            bottom=95.0,
            box_type=BoxType.ORDER_BLOCK,
            direction=Direction.BULLISH,
            created_at=10,
        )
        # No breach
        assert not box.is_breached(high=99.0, low=98.0)
        # Pierce top
        assert box.is_breached(high=101.0, low=99.0)

    def test_is_breached_bearish(self) -> None:
        """Bearish box breached when price goes below bottom."""
        box = SmcBox(
            left=10,
            right=15,
            top=100.0,
            bottom=95.0,
            box_type=BoxType.ORDER_BLOCK,
            direction=Direction.BEARISH,
            created_at=10,
        )
        # No breach
        assert not box.is_breached(high=96.0, low=95.1)
        # Pierce bottom
        assert box.is_breached(high=95.0, low=94.0)

    def test_is_breached_guards_nan(self) -> None:
        """Guard against NaN high/low."""
        box = SmcBox(
            left=10,
            right=15,
            top=100.0,
            bottom=95.0,
            box_type=BoxType.ORDER_BLOCK,
            direction=Direction.BULLISH,
            created_at=10,
        )
        assert not box.is_breached(high=math.nan, low=98.0)
        assert not box.is_breached(high=101.0, low=math.nan)

    def test_update_right(self) -> None:
        """Extend right edge forward."""
        box = SmcBox(
            left=10,
            right=15,
            top=100.0,
            bottom=95.0,
            box_type=BoxType.ORDER_BLOCK,
            direction=Direction.BULLISH,
            created_at=10,
        )
        box.update_right(20)
        assert box.right == 20
        # Can't move backwards
        box.update_right(18)
        assert box.right == 20


class TestSmcBoxManager:
    """Test unified box manager with direction separation."""

    def test_add_box_bullish(self) -> None:
        mgr = SmcBoxManager(max_boxes_per_direction=5)
        box = make_ob_up(bar_index=10, high_t2=100.0, low_t1=97.0, low_t2=96.0)
        evicted = mgr.add_box(box)
        assert evicted is None
        assert mgr.count_active(Direction.BULLISH) == 1
        assert mgr.count_active(Direction.BEARISH) == 0

    def test_add_box_bearish(self) -> None:
        mgr = SmcBoxManager(max_boxes_per_direction=5)
        box = make_ob_down(bar_index=10, high_t1=100.0, high_t2=101.0, low_t2=96.0)
        evicted = mgr.add_box(box)
        assert evicted is None
        assert mgr.count_active(Direction.BEARISH) == 1
        assert mgr.count_active(Direction.BULLISH) == 0

    def test_eviction_per_direction(self) -> None:
        """Each direction has its own buffer; eviction is per-direction."""
        mgr = SmcBoxManager(max_boxes_per_direction=2)
        # Add 3 bullish boxes to max=2
        for i in range(3):
            box = SmcBox(
                left=i * 10,
                right=i * 10 + 5,
                top=100.0,
                bottom=95.0,
                box_type=BoxType.ORDER_BLOCK,
                direction=Direction.BULLISH,
                created_at=i,
            )
            mgr.add_box(box)
        # Should have evicted oldest bullish
        assert len(mgr.bullish_boxes) == 2
        assert mgr.bullish_boxes.get_oldest().created_at == 1  # 0 was evicted

    def test_check_mitigation(self) -> None:
        """Mark box as mitigated when price breaches."""
        mgr = SmcBoxManager(max_boxes_per_direction=5)
        box = SmcBox(
            left=10,
            right=15,
            top=100.0,
            bottom=95.0,
            box_type=BoxType.ORDER_BLOCK,
            direction=Direction.BULLISH,
            created_at=10,
        )
        mgr.add_box(box)
        assert not box.is_mitigated

        # Price breaches above top
        mgr.check_mitigation(high=101.0, low=99.0, current_bar=16)
        assert box.is_mitigated
        assert box.mitigated_at == 16

    def test_check_mitigation_guards_nan(self) -> None:
        """Guard against NaN in check_mitigation."""
        mgr = SmcBoxManager(max_boxes_per_direction=5)
        box = SmcBox(
            left=10,
            right=15,
            top=100.0,
            bottom=95.0,
            box_type=BoxType.ORDER_BLOCK,
            direction=Direction.BULLISH,
            created_at=10,
        )
        mgr.add_box(box)
        # Should not crash on NaN
        mgr.check_mitigation(high=math.nan, low=99.0, current_bar=16)
        assert not box.is_mitigated

    def test_extend_right_edges(self) -> None:
        """Advance time: extend all box right edges."""
        mgr = SmcBoxManager(max_boxes_per_direction=5)
        box1 = make_ob_up(bar_index=10, high_t2=100.0, low_t1=97.0, low_t2=96.0)
        box2 = make_ob_down(bar_index=15, high_t1=105.0, high_t2=104.0, low_t2=99.0)
        mgr.add_box(box1)
        mgr.add_box(box2)

        mgr.extend_right_edges(current_bar=20)
        assert box1.right == 20
        assert box2.right == 20

    def test_get_active_boxes(self) -> None:
        """Return only unmitigated boxes."""
        mgr = SmcBoxManager(max_boxes_per_direction=5)
        box1 = make_ob_up(bar_index=10, high_t2=100.0, low_t1=97.0, low_t2=96.0)
        box2 = make_ob_down(bar_index=15, high_t1=105.0, high_t2=104.0, low_t2=99.0)
        mgr.add_box(box1)
        mgr.add_box(box2)

        assert len(mgr.get_active_boxes()) == 2
        box1.is_mitigated = True
        assert len(mgr.get_active_boxes()) == 1
        assert mgr.get_active_boxes()[0] == box2

    def test_get_boxes_by_type(self) -> None:
        """Filter boxes by type (OB vs FVG vs RJB)."""
        mgr = SmcBoxManager(max_boxes_per_direction=5)
        ob = make_ob_up(bar_index=10, high_t2=100.0, low_t1=97.0, low_t2=96.0)
        fvg = make_fvg_up(bar_index=15, low_t=105.0, high_t2=100.0)
        mgr.add_box(ob)
        mgr.add_box(fvg)

        assert len(mgr.get_boxes_by_type(BoxType.ORDER_BLOCK)) == 1
        assert len(mgr.get_boxes_by_type(BoxType.FAIR_VALUE_GAP)) == 1
        assert len(mgr.get_boxes_by_type(BoxType.REJECTION_BLOCK)) == 0


class TestPredicateFunctions:
    """Test candle pattern detection guards."""

    def test_is_up_valid(self) -> None:
        assert is_up(close=105.0, open=100.0)
        assert not is_up(close=95.0, open=100.0)
        assert not is_up(close=100.0, open=100.0)  # Doji

    def test_is_up_guards_nan(self) -> None:
        assert not is_up(close=math.nan, open=100.0)
        assert not is_up(close=105.0, open=math.nan)

    def test_is_ob_up(self) -> None:
        """Bullish OB: trapped bear, then bullish close above resistance."""
        # Trapped bear at t-2/t-1: closes 96, high 100
        # Current t: bullish close 102
        assert is_ob_up(
            close_t=102.0, open_t=101.0,
            close_t1=96.0, open_t1=100.0, high_t1=100.0,
            high_t2=100.0, low_t2=95.0,
        )
        # Doesn't trigger if current bar is bearish
        assert not is_ob_up(
            close_t=99.0, open_t=101.0,
            close_t1=96.0, open_t1=100.0, high_t1=100.0,
            high_t2=100.0, low_t2=95.0,
        )

    def test_is_ob_up_guards_nan(self) -> None:
        """Guard all parameters."""
        assert not is_ob_up(
            close_t=math.nan, open_t=101.0,
            close_t1=96.0, open_t1=100.0, high_t1=100.0,
            high_t2=100.0, low_t2=95.0,
        )

    def test_is_fvg_up(self) -> None:
        """Bullish FVG: gap between low_t and high_t2."""
        # Gap: 105 > 100
        assert is_fvg_up(low_t=105.0, high_t2=100.0)
        # No gap
        assert not is_fvg_up(low_t=95.0, high_t2=100.0)

    def test_is_rjb_down(self) -> None:
        """Rejection block: weak wick coverage."""
        # trapped: high=100, close=96 → wick=4
        # signal: high=97 → coverage = (97-96)/4 = 0.25 → rejects (< 0.2 threshold)
        # Note: threshold=0.2 means <20% of wick, so 0.25 would NOT reject
        # Let's use: high=96.5 → coverage = 0.5/4 = 0.125 < 0.2 ✓
        assert is_rjb_down(high_t1=96.5, close_t2=96.0, high_t2=100.0, threshold=0.2)
        # Full coverage → not rejection
        assert not is_rjb_down(high_t1=99.0, close_t2=96.0, high_t2=100.0, threshold=0.2)

    def test_is_rjb_down_guards_nan(self) -> None:
        assert not is_rjb_down(high_t1=math.nan, close_t2=96.0, high_t2=100.0)


class TestBoxFactories:
    """Test box creation helpers."""

    def test_make_ob_up(self) -> None:
        box = make_ob_up(bar_index=10, high_t2=100.0, low_t1=97.0, low_t2=96.0)
        assert box.box_type == BoxType.ORDER_BLOCK
        assert box.direction == Direction.BULLISH
        assert box.created_at == 10
        assert box.left == 8  # bar_index - 2
        assert box.right == 10
        assert box.top == 100.0
        assert box.bottom == 96.0  # min(97, 96)

    def test_make_fvg_up(self) -> None:
        box = make_fvg_up(bar_index=20, low_t=105.0, high_t2=100.0)
        assert box.box_type == BoxType.FAIR_VALUE_GAP
        assert box.direction == Direction.BULLISH
        assert box.top == 105.0
        assert box.bottom == 100.0

    def test_make_rjb_down(self) -> None:
        """RJB has lower strength (0.6 vs 1.0)."""
        box = make_rjb_down(bar_index=15, high_t2=100.0, close_t2=96.0)
        assert box.box_type == BoxType.REJECTION_BLOCK
        assert box.direction == Direction.BEARISH
        assert box.strength == 0.6  # Weaker signal

"""Live SMC signal detector using RingBuffer pattern.

Real-time Order Block / FVG / RJB detection for streaming market data.
Integrates with live_overlay_daemon for tick-by-tick signal routing.

Pattern: OHLC candle stream → detected structures → signal webhook/API.
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass
from typing import Optional

from services.live_overlay_daemon.smc_ringbuffer import (
    BoxType,
    Direction,
    SmcBox,
    SmcBoxManager,
    is_fvg_down,
    is_fvg_up,
    is_ob_down,
    is_ob_up,
    is_rjb_down,
    is_rjb_up,
    make_fvg_down,
    make_fvg_up,
    make_ob_down,
    make_ob_up,
    make_rjb_down,
    make_rjb_up,
)

logger = logging.getLogger(__name__)


@dataclass
class Candle:
    """OHLC candle with bar index."""

    bar_index: int
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class SignalEvent:
    """Detected structure signal (for webhook/API routing)."""

    bar_index: int
    box_type: BoxType
    direction: Direction
    box: SmcBox
    event_type: str  # 'created' | 'mitigated'


class SmcSignalDetector:
    """Real-time SMC signal detector.

    Maintains order history, detects patterns on each new candle,
    emits signals. ~O(n) per candle where n=max_boxes (typically 10-50).

    Usage:
        detector = SmcSignalDetector(max_boxes=10)
        for candle in stream:
            signals = detector.process_candle(candle)
            for sig in signals:
                webhook.post(sig)
    """

    def __init__(self, max_boxes_per_direction: int = 10):
        self.box_manager = SmcBoxManager(max_boxes_per_direction)
        self.history: list[Candle] = []
        self.signals: list[SignalEvent] = []

    def process_candle(self, candle: Candle) -> list[SignalEvent]:
        """Detect structures on new candle.

        Returns: list of new signals (created OB/FVG/RJB or mitigated).
        """
        self.signals.clear()
        self.history.append(candle)

        # Need 2 prior candles for pattern detection
        if len(self.history) < 3:
            return self.signals

        t = self.history[-1]  # Current
        t1 = self.history[-2]  # -1 bar
        t2 = self.history[-3]  # -2 bars

        # Extend all box right edges (time marches forward)
        self.box_manager.extend_right_edges(candle.bar_index)

        # Check for breaches (mitigation)
        self._detect_mitigations(t)

        # Detect new patterns
        self._detect_order_blocks(t, t1, t2)
        self._detect_fair_value_gaps(t, t2)
        self._detect_rejection_blocks(t, t1, t2)

        return self.signals

    def _detect_mitigations(self, t: Candle) -> None:
        """Scan all boxes for breach; emit 'mitigated' signals."""
        # Collect all boxes BEFORE checking mitigation
        all_boxes = list(self.box_manager.bullish_boxes) + list(self.box_manager.bearish_boxes)

        # Check for breaches and mark mitigated
        self.box_manager.check_mitigation(t.high, t.low, t.bar_index)

        # Emit signals for boxes that JUST got mitigated
        for box in all_boxes:
            if box.is_mitigated and box.mitigated_at == t.bar_index:
                self.signals.append(
                    SignalEvent(
                        bar_index=t.bar_index,
                        box_type=box.box_type,
                        direction=box.direction,
                        box=box,
                        event_type="mitigated",
                    )
                )

    def _detect_order_blocks(self, t: Candle, t1: Candle, t2: Candle) -> None:
        """Bullish and bearish order blocks."""
        # Bullish OB: trapped bear, then bullish close above resistance
        if is_ob_up(
            close_t=t.close, open_t=t.open,
            close_t1=t1.close, open_t1=t1.open, high_t1=t1.high,
            high_t2=t2.high, low_t2=t2.low,
        ):
            box = make_ob_up(t.bar_index, t2.high, t1.low, t2.low)
            evicted = self.box_manager.add_box(box)
            if evicted:
                logger.debug(f"Evicted old OB+ from bar {evicted.created_at}")
            self.signals.append(
                SignalEvent(
                    bar_index=t.bar_index,
                    box_type=BoxType.ORDER_BLOCK,
                    direction=Direction.BULLISH,
                    box=box,
                    event_type="created",
                )
            )

        # Bearish OB
        if is_ob_down(
            close_t=t.close, open_t=t.open,
            close_t1=t1.close, open_t1=t1.open, low_t1=t1.low,
            high_t2=t2.high, low_t2=t2.low,
        ):
            box = make_ob_down(t.bar_index, t1.high, t2.high, t2.low)
            evicted = self.box_manager.add_box(box)
            if evicted:
                logger.debug(f"Evicted old OB- from bar {evicted.created_at}")
            self.signals.append(
                SignalEvent(
                    bar_index=t.bar_index,
                    box_type=BoxType.ORDER_BLOCK,
                    direction=Direction.BEARISH,
                    box=box,
                    event_type="created",
                )
            )

    def _detect_fair_value_gaps(self, t: Candle, t2: Candle) -> None:
        """Bullish and bearish fair value gaps."""
        # Bullish FVG: gap between current low and 2-bar-ago high
        if is_fvg_up(low_t=t.low, high_t2=t2.high):
            box = make_fvg_up(t.bar_index, t.low, t2.high)
            evicted = self.box_manager.add_box(box)
            if evicted:
                logger.debug(f"Evicted old FVG+ from bar {evicted.created_at}")
            self.signals.append(
                SignalEvent(
                    bar_index=t.bar_index,
                    box_type=BoxType.FAIR_VALUE_GAP,
                    direction=Direction.BULLISH,
                    box=box,
                    event_type="created",
                )
            )

        # Bearish FVG
        if is_fvg_down(high_t=t.high, low_t2=t2.low):
            box = make_fvg_down(t.bar_index, t.high, t2.low)
            evicted = self.box_manager.add_box(box)
            if evicted:
                logger.debug(f"Evicted old FVG- from bar {evicted.created_at}")
            self.signals.append(
                SignalEvent(
                    bar_index=t.bar_index,
                    box_type=BoxType.FAIR_VALUE_GAP,
                    direction=Direction.BEARISH,
                    box=box,
                    event_type="created",
                )
            )

    def _detect_rejection_blocks(self, t: Candle, t1: Candle, t2: Candle) -> None:
        """Weak OBs: rejection blocks (reduced signal strength)."""
        # Bearish RJB: weak rejection at trapped candle high
        if is_rjb_down(high_t1=t1.high, close_t2=t2.close, high_t2=t2.high, threshold=0.2):
            box = make_rjb_down(t.bar_index, t2.high, t2.close)
            evicted = self.box_manager.add_box(box)
            if evicted:
                logger.debug(f"Evicted old RJB- from bar {evicted.created_at}")
            self.signals.append(
                SignalEvent(
                    bar_index=t.bar_index,
                    box_type=BoxType.REJECTION_BLOCK,
                    direction=Direction.BEARISH,
                    box=box,
                    event_type="created",
                )
            )

        # Bullish RJB
        if is_rjb_up(low_t1=t1.low, close_t2=t2.close, low_t2=t2.low, threshold=0.2):
            box = make_rjb_up(t.bar_index, t2.close, t2.low)
            evicted = self.box_manager.add_box(box)
            if evicted:
                logger.debug(f"Evicted old RJB+ from bar {evicted.created_at}")
            self.signals.append(
                SignalEvent(
                    bar_index=t.bar_index,
                    box_type=BoxType.REJECTION_BLOCK,
                    direction=Direction.BULLISH,
                    box=box,
                    event_type="created",
                )
            )

    def get_active_structures(self) -> list[SmcBox]:
        """Return all unmitigated boxes (for current state/dashboard)."""
        return self.box_manager.get_active_boxes()

    def get_structures_by_type(self, box_type: BoxType) -> list[SmcBox]:
        """Filter by structure type."""
        return self.box_manager.get_boxes_by_type(box_type)

    def count_structures(self, direction: Direction) -> int:
        """Count active structures in one direction."""
        return self.box_manager.count_active(direction)

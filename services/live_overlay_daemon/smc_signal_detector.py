"""Live SMC signal detector using RingBuffer pattern.

Real-time Order Block / FVG / RJB detection for streaming market data.
Integrates with live_overlay_daemon for tick-by-tick signal routing.

Pattern: OHLC candle stream → detected structures → signal webhook/API.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from services.live_overlay_daemon.smc_advanced_patterns import (
    BoSRefinement,
    BrokenFractalDetector,
    HVBDetector,
    LiquidityClusterDetector,
    PPDDClassifier,
)
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


def _candle_ohlc_is_finite(candle: Candle) -> bool:
    """True if every OHLC field is finite (no NaN / ±inf)."""
    return (
        math.isfinite(candle.open)
        and math.isfinite(candle.high)
        and math.isfinite(candle.low)
        and math.isfinite(candle.close)
    )


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

        # Advanced pattern detectors
        self.hvb_detector = HVBDetector(lookback=20, hvb_threshold=1.5)
        self.ppdd_classifier = PPDDClassifier(atr_multiple=2.0)
        self.liquidity_detector = LiquidityClusterDetector(
            cluster_distance_atr=0.5, min_confluences=2
        )
        self.fractal_detector = BrokenFractalDetector()
        self.bos_refiner = BoSRefinement()

        self.swing_highs: list[float] = []
        self.swing_lows: list[float] = []

    def process_candle(self, candle: Candle) -> list[SignalEvent]:
        """Detect structures on new candle.

        Returns: list of new signals (created OB/FVG/RJB or mitigated).
        """
        self.signals.clear()
        self.history.append(candle)
        # Only the last 3 candles are read; keep a small buffer so the
        # per-candle history cannot grow without bound in the daemon.
        if len(self.history) > 10:
            del self.history[:-10]

        # Need 2 prior candles for pattern detection
        if len(self.history) < 3:
            return self.signals

        t = self.history[-1]  # Current
        t1 = self.history[-2]  # -1 bar
        t2 = self.history[-3]  # -2 bars

        # Extend all box right edges (time marches forward)
        self.box_manager.extend_right_edges(candle.bar_index)

        # Check for breaches (mitigation) — check_mitigation guards NaN high/low.
        self._detect_mitigations(t)

        # Non-finite OHLC anywhere in the 3-bar detection window would flow into
        # the make_* factories and produce boxes with NaN bounds — silently
        # invalid signals that never mitigate (``high > nan`` is always False).
        # Skip core pattern creation for a corrupt window instead of emitting
        # them. (The factories also reject non-finite inputs as a hard backstop.)
        if _candle_ohlc_is_finite(t) and _candle_ohlc_is_finite(t1) and _candle_ohlc_is_finite(t2):
            self._detect_order_blocks(t, t1, t2)
            self._detect_fair_value_gaps(t, t2)
            self._detect_rejection_blocks(t, t1, t2)
        else:
            logger.warning(
                "Skipping SMC OB/FVG/RJB detection at bar %s: non-finite OHLC in "
                "detection window (t/t1/t2)",
                t.bar_index,
            )

        # Detect advanced patterns (HVB, Broken Fractal, etc.)
        self._detect_advanced_patterns(t)

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
                logger.debug("Evicted old OB+ from bar %s", evicted.created_at)
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
                logger.debug("Evicted old OB- from bar %s", evicted.created_at)
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
                logger.debug("Evicted old FVG+ from bar %s", evicted.created_at)
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
                logger.debug("Evicted old FVG- from bar %s", evicted.created_at)
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
                logger.debug("Evicted old RJB- from bar %s", evicted.created_at)
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
                logger.debug("Evicted old RJB+ from bar %s", evicted.created_at)
            self.signals.append(
                SignalEvent(
                    bar_index=t.bar_index,
                    box_type=BoxType.REJECTION_BLOCK,
                    direction=Direction.BULLISH,
                    box=box,
                    event_type="created",
                )
            )

    def _detect_advanced_patterns(self, t: Candle) -> None:
        """Detect HVB, PPDD, Broken Fractal, Liquidity Clusters."""
        # HVB Detection
        hvb = self.hvb_detector.detect(
            bar_index=t.bar_index,
            volume=t.volume,
            close=t.close,
            open=t.open,
            high=t.high,
            low=t.low,
        )
        if hvb.is_hvb:
            logger.debug(
                "[HVB] High Volume Bar at %s: %.2fx avg", t.bar_index, hvb.volume_ratio
            )

        # Track swing highs/lows for liquidity detection
        self._update_swing_points(t.high, t.low)

        # Detect Broken Fractal pattern
        bf = self.fractal_detector.detect(
            bar_index=t.bar_index,
            high=t.high,
            low=t.low,
            close=t.close,
        )
        if bf and bf.confirmed:
            logger.debug(
                "[BrokenFractal] %s break confirmed at %s", bf.break_direction.upper(), t.bar_index
            )

    def _update_swing_points(self, high: float, low: float) -> None:
        """Track swing highs/lows for liquidity cluster detection."""
        self.swing_highs.append(high)
        self.swing_lows.append(low)

        # Keep last 50 swings
        if len(self.swing_highs) > 50:
            self.swing_highs.pop(0)
        if len(self.swing_lows) > 50:
            self.swing_lows.pop(0)

    def get_active_structures(self) -> list[SmcBox]:
        """Return all unmitigated boxes (for current state/dashboard)."""
        return self.box_manager.get_active_boxes()

    def get_structures_by_type(self, box_type: BoxType) -> list[SmcBox]:
        """Filter by structure type."""
        return self.box_manager.get_boxes_by_type(box_type)

    def count_structures(self, direction: Direction) -> int:
        """Count active structures in one direction."""
        return self.box_manager.count_active(direction)

"""SMC RingBuffer & Event-Box Manager for technical analysis structures.

Optimized O(1) alternative to TradingView's array.shift() pattern.
Manages Order Blocks, Fair Value Gaps, Rejection Blocks with size-limits,
bullish/bearish separation, and mitigation state tracking.

Pattern: Real-time signal streaming with bounded memory for live market data.
"""

from __future__ import annotations

import enum
import math
from collections import deque
from dataclasses import dataclass, field


class BoxType(enum.Enum):
    """Box classification for event routing."""

    ORDER_BLOCK = "OB"
    FAIR_VALUE_GAP = "FVG"
    REJECTION_BLOCK = "RJB"
    BREAK_OF_STRUCTURE = "BoS"


class Direction(enum.Enum):
    """Bullish vs Bearish signal direction."""

    BULLISH = "+"
    BEARISH = "-"


@dataclass
class SmcBox:
    """Technical analysis box: bounded zone for market structure.

    Represents Order Blocks, Fair Value Gaps, etc. Tracks:
    - Position: left/right bar indices, top/bottom price levels
    - Classification: type, direction, mitigation state
    - Metadata: creation bar, signal strength
    """

    # Spatial bounds
    left: int  # Bar index where structure formed
    right: int  # Right edge (extends until mitigation or limit)
    top: float  # Upper price boundary
    bottom: float  # Lower price boundary

    # Classification
    box_type: BoxType
    direction: Direction

    # State
    created_at: int  # Creation bar_index
    is_mitigated: bool = False
    mitigated_at: int | None = None

    # Visual config
    color: str = "#00FF00"  # Hex; NOTE: not mutated on mitigation (only transparency changes)
    transparency: int = 90

    # Metadata
    strength: float = 1.0  # 0.0-1.0 confidence/robustness

    def __post_init__(self):
        """Enforce the box invariant: finite, ordered (top >= bottom) bounds.

        Two corruptions are guarded here:
        * Non-finite bounds (NaN / ±inf). An ``inf`` top can never be breached
          from above while the finite side still mitigates, a ``NaN`` bound makes
          ``is_breached``/``height`` nonsensical (``height()`` returns NaN/inf) —
          silent structure corruption. A box is only ever built from real price
          levels, so a non-finite bound is always a construction bug: fail fast
          (like ``RingBuffer.__post_init__`` on ``max_size <= 0``). The factories
          reach this only after their own finite-guard, so the data path skips
          corrupt candles rather than raising.
        * Inverted bounds (top < bottom, e.g. from corrupt candle data) would
          satisfy is_breached on virtually any candle and be silently mitigated.
        """
        if not math.isfinite(self.top) or not math.isfinite(self.bottom):
            raise ValueError(
                f"SmcBox bounds must be finite, got top={self.top}, bottom={self.bottom}"
            )
        if self.bottom > self.top:
            self.top, self.bottom = self.bottom, self.top

    def width(self) -> int:
        """Bar count spanned by this box."""
        return max(0, self.right - self.left)

    def height(self) -> float:
        """Price range (points) spanned."""
        return abs(self.top - self.bottom)

    def is_breached(self, high: float, low: float) -> bool:
        """True if current candle pierces the box (either boundary)."""
        # Non-finite prices (NaN and ±inf) must never mitigate a box: a single
        # corrupt high=inf / low=-inf tick would otherwise silently wipe every
        # active box. isfinite covers both, where the old isnan missed ±inf.
        if not math.isfinite(high) or not math.isfinite(low):
            return False
        # any box mitigates when price pierces either boundary (direction-agnostic)
        return high > self.top or low < self.bottom

    def update_right(self, new_right: int) -> None:
        """Extend right edge (as price moves forward)."""
        self.right = max(self.right, new_right)


@dataclass
class RingBuffer[T]:
    """Fixed-size circular buffer with O(1) append + eviction.

    Replaces TradingView's array.shift() (O(n)) with deque maxlen (O(1)).
    Automatically discards oldest entry when full.

    Pattern: Bounded event stream for real-time signal processing.
    """

    max_size: int
    _buffer: deque[T] = field(default_factory=deque)

    def __post_init__(self):
        """Initialize deque with fixed max_len."""
        if self.max_size <= 0:
            # deque(maxlen=0) is legal but append() would treat the empty
            # buffer as "full" and crash on self._buffer[0] (IndexError).
            raise ValueError(f"RingBuffer max_size must be positive, got {self.max_size}")
        self._buffer = deque(maxlen=self.max_size)

    def append(self, item: T) -> T | None:
        """Add item; return evicted item if buffer was full, else None.

        O(1) operation.
        """
        was_full = len(self._buffer) == self.max_size
        evicted = self._buffer[0] if was_full else None
        self._buffer.append(item)
        return evicted

    def size(self) -> int:
        """Current count."""
        return len(self._buffer)

    def is_full(self) -> bool:
        """True if at capacity."""
        return len(self._buffer) == self.max_size

    def get(self, index: int) -> T | None:
        """0-indexed access (0 = oldest)."""
        if 0 <= index < len(self._buffer):
            return self._buffer[index]
        return None

    def get_latest(self) -> T | None:
        """Most recently added item."""
        return self._buffer[-1] if self._buffer else None

    def get_oldest(self) -> T | None:
        """Oldest item (will be evicted next)."""
        return self._buffer[0] if self._buffer else None

    def __iter__(self):
        """Iterate oldest → newest."""
        return iter(self._buffer)

    def __len__(self) -> int:
        return len(self._buffer)


@dataclass
class SmcBoxManager:
    """Manages separate bullish/bearish box streams with state tracking.

    Routes boxes by direction, auto-evicts oldest when full, tracks
    mitigation state. Replaces four separate TradingView arrays with
    unified manager.

    O(1) append, O(n) scan for mitigation (where n=max_size, typically 10-50).
    """

    max_boxes_per_direction: int = 10

    def __post_init__(self):
        """Initialize buffers after field assignment."""
        self.bullish_boxes = RingBuffer[SmcBox](self.max_boxes_per_direction)
        self.bearish_boxes = RingBuffer[SmcBox](self.max_boxes_per_direction)

    def add_box(self, box: SmcBox) -> SmcBox | None:
        """Append box to appropriate direction buffer.

        Returns evicted box if buffer was full, else None.
        """
        if box.direction == Direction.BULLISH:
            return self.bullish_boxes.append(box)
        else:
            return self.bearish_boxes.append(box)

    def check_mitigation(self, high: float, low: float, current_bar: int) -> None:
        """Scan all active boxes for breach; mark mitigated + change color.

        O(n) where n = total active boxes (typically 20 for 10 bullish + 10 bearish).
        Call once per candle.
        """
        if not (math.isfinite(high) and math.isfinite(low)):
            return

        for box in self.bullish_boxes:
            if not box.is_mitigated and box.is_breached(high, low):
                box.is_mitigated = True
                box.mitigated_at = current_bar
                # Signal UI: color -> gray (or your mitigation_color)
                box.transparency = 50

        for box in self.bearish_boxes:
            if not box.is_mitigated and box.is_breached(high, low):
                box.is_mitigated = True
                box.mitigated_at = current_bar
                box.transparency = 50

    def extend_right_edges(self, current_bar: int) -> None:
        """Advance all box right edges (time marches forward)."""
        for box in self.bullish_boxes:
            box.update_right(current_bar)
        for box in self.bearish_boxes:
            box.update_right(current_bar)

    def get_active_boxes(self) -> list[SmcBox]:
        """Return all unmitigated boxes (for signal routing/backtesting)."""
        return [
            box for box in list(self.bullish_boxes) + list(self.bearish_boxes)
            if not box.is_mitigated
        ]

    def get_boxes_by_type(self, box_type: BoxType) -> list[SmcBox]:
        """Filter by type (OB / FVG / RJB / BoS)."""
        return [
            box for box in list(self.bullish_boxes) + list(self.bearish_boxes)
            if box.box_type == box_type
        ]

    def count_active(self, direction: Direction) -> int:
        """Count unmitigated boxes in one direction."""
        buf = (
            self.bullish_boxes
            if direction == Direction.BULLISH
            else self.bearish_boxes
        )
        return sum(1 for box in buf if not box.is_mitigated)


# ============================================================================
# Predicate Guards: Candle pattern detection (from Pine Script)
# ============================================================================


def is_up(close: float, open_: float) -> bool:
    """Bullish candle."""
    return math.isfinite(close) and math.isfinite(open_) and close > open_


def is_down(close: float, open_: float) -> bool:
    """Bearish candle."""
    return math.isfinite(close) and math.isfinite(open_) and close < open_


def is_ob_up(
    close_t: float, open_t: float,
    close_t1: float, open_t1: float, high_t1: float,
    high_t2: float, low_t2: float,
) -> bool:
    """Bullish Order Block: trapped bear → bullish engulf above resistance.

    Args:
        t: current bar, t-1: previous, t-2: trapped candle
        close_t, open_t: current close/open
        close_t1, open_t1, high_t1: previous bar data
        high_t2, low_t2: trapped candle bounds
    """
    if not all(math.isfinite(x) for x in [close_t, open_t, close_t1, open_t1, high_t1, high_t2, low_t2]):
        return False
    return is_down(close_t1, open_t1) and is_up(close_t, open_t) and close_t > high_t1


def is_ob_down(
    close_t: float, open_t: float,
    close_t1: float, open_t1: float, low_t1: float,
    high_t2: float, low_t2: float,
) -> bool:
    """Bearish Order Block: trapped bull → bearish engulf below support."""
    if not all(math.isfinite(x) for x in [close_t, open_t, close_t1, open_t1, low_t1, high_t2, low_t2]):
        return False
    return is_up(close_t1, open_t1) and is_down(close_t, open_t) and close_t < low_t1


def is_fvg_up(low_t: float, high_t2: float) -> bool:
    """Bullish Fair Value Gap: gap between current low and 2-bar-ago high.

    Pattern: two bars ago closes high, then gap up on current bar.
    """
    return math.isfinite(low_t) and math.isfinite(high_t2) and low_t > high_t2


def is_fvg_down(high_t: float, low_t2: float) -> bool:
    """Bearish Fair Value Gap: gap between current high and 2-bar-ago low."""
    return math.isfinite(high_t) and math.isfinite(low_t2) and high_t < low_t2


def is_rjb_down(
    high_t1: float, close_t2: float, high_t2: float,
    threshold: float = 0.2,
) -> bool:
    """Rejection Block Down: weak rejection at trapped candle high.

    Pattern: signal candle (t-1) closes high but doesn't fully engulf
    trapped candle (t-2). RJB = smaller rejection wick.

    Args:
        high_t1: signal candle high
        close_t2, high_t2: trapped candle close/high
        threshold: wick coverage % (0.2 = <20% of wick covered = rejection)
    """
    if not all(math.isfinite(x) for x in [high_t1, close_t2, high_t2]):
        return False
    wick_size = high_t2 - close_t2
    if wick_size <= 0:
        return False
    coverage = (high_t1 - close_t2) / wick_size
    return coverage < threshold


def is_rjb_up(
    low_t1: float, close_t2: float, low_t2: float,
    threshold: float = 0.2,
) -> bool:
    """Rejection Block Up: weak rejection at trapped candle low."""
    if not all(math.isfinite(x) for x in [low_t1, close_t2, low_t2]):
        return False
    wick_size = close_t2 - low_t2
    if wick_size <= 0:
        return False
    coverage = (close_t2 - low_t1) / wick_size
    return coverage < threshold


# ============================================================================
# Factory: Create boxes from pattern detection
# ============================================================================


def _ordered_bounds(a: float, b: float) -> tuple[float, float] | None:
    """Return ``(top, bottom)`` with ``top >= bottom``, or ``None`` if either
    bound is non-finite.

    Two corruptions are rejected before a box is ever built:
    * ``high < low`` corrupt candle data would otherwise produce an inverted box
      that ``is_breached`` mitigates on the very next candle (handled by the
      ordering here and by ``SmcBox.__post_init__``).
    * ``NaN`` / ``±inf`` bounds. The predicates guard OHLC they read, but the
      factories also mix in fields the predicate never saw (``make_ob_up``'s
      ``low_t1``, ``make_ob_down``'s ``high_t1``), so a non-finite value can
      still reach here. Returning ``None`` lets the caller skip the box — the
      fail-soft convention shared with the predicates and ``is_breached`` — so a
      single corrupt bar cannot fabricate an ``inf``/``NaN``-bounded box (and
      the backtester, which feeds raw un-coerced OHLC, is not aborted).
    """
    if not math.isfinite(a) or not math.isfinite(b):
        return None
    return (a, b) if a >= b else (b, a)


def make_ob_up(bar_index: int, high_t2: float, low_t1: float, low_t2: float) -> SmcBox | None:
    """Factory: bullish order block. ``None`` on non-finite/corrupt bounds."""
    bounds = _ordered_bounds(high_t2, min(low_t1, low_t2))
    if bounds is None:
        return None
    top, bottom = bounds
    return SmcBox(
        left=bar_index - 2,
        right=bar_index,
        top=top,
        bottom=bottom,
        box_type=BoxType.ORDER_BLOCK,
        direction=Direction.BULLISH,
        created_at=bar_index,
        color="#00FF00",  # Green
        strength=1.0,
    )


def make_ob_down(bar_index: int, high_t1: float, high_t2: float, low_t2: float) -> SmcBox | None:
    """Factory: bearish order block. ``None`` on non-finite/corrupt bounds."""
    bounds = _ordered_bounds(max(high_t1, high_t2), low_t2)
    if bounds is None:
        return None
    top, bottom = bounds
    return SmcBox(
        left=bar_index - 2,
        right=bar_index,
        top=top,
        bottom=bottom,
        box_type=BoxType.ORDER_BLOCK,
        direction=Direction.BEARISH,
        created_at=bar_index,
        color="#FF0000",  # Red
        strength=1.0,
    )


def make_fvg_up(bar_index: int, low_t: float, high_t2: float) -> SmcBox | None:
    """Factory: bullish fair value gap. ``None`` on non-finite/corrupt bounds."""
    bounds = _ordered_bounds(low_t, high_t2)
    if bounds is None:
        return None
    top, bottom = bounds
    return SmcBox(
        left=bar_index - 2,
        right=bar_index,
        top=top,
        bottom=bottom,
        box_type=BoxType.FAIR_VALUE_GAP,
        direction=Direction.BULLISH,
        created_at=bar_index,
        color="#000000",  # Black
        strength=1.0,
    )


def make_fvg_down(bar_index: int, high_t: float, low_t2: float) -> SmcBox | None:
    """Factory: bearish fair value gap. ``None`` on non-finite/corrupt bounds."""
    bounds = _ordered_bounds(low_t2, high_t)
    if bounds is None:
        return None
    top, bottom = bounds
    return SmcBox(
        left=bar_index - 2,
        right=bar_index,
        top=top,
        bottom=bottom,
        box_type=BoxType.FAIR_VALUE_GAP,
        direction=Direction.BEARISH,
        created_at=bar_index,
        color="#000000",  # Black
        strength=1.0,
    )


def make_rjb_down(bar_index: int, high_t2: float, close_t2: float) -> SmcBox | None:
    """Factory: bearish rejection block (weak OB). ``None`` on non-finite/corrupt bounds."""
    bounds = _ordered_bounds(high_t2, close_t2)
    if bounds is None:
        return None
    top, bottom = bounds
    return SmcBox(
        left=bar_index - 2,
        right=bar_index,
        top=top,
        bottom=bottom,
        box_type=BoxType.REJECTION_BLOCK,
        direction=Direction.BEARISH,
        created_at=bar_index,
        color="#FF0000",  # Red, reduced strength
        strength=0.6,  # Weaker signal
    )


def make_rjb_up(bar_index: int, close_t2: float, low_t2: float) -> SmcBox | None:
    """Factory: bullish rejection block. ``None`` on non-finite/corrupt bounds."""
    bounds = _ordered_bounds(close_t2, low_t2)
    if bounds is None:
        return None
    top, bottom = bounds
    return SmcBox(
        left=bar_index - 2,
        right=bar_index,
        top=top,
        bottom=bottom,
        box_type=BoxType.REJECTION_BLOCK,
        direction=Direction.BULLISH,
        created_at=bar_index,
        color="#00FF00",  # Green, reduced strength
        strength=0.6,
    )

"""Strong Impulse Signals — Real-time Impulse Detection and Propulsion Strength Scoring.

Implements impulse pattern recognition:
1. Ignition candle detection (3 criteria)
2. Propulsion strength scoring (0-10)
3. COIL → IGNITION → BREAK → THRUST → TARGET pattern
4. Invalidation level calculation
5. Automatic target projection

Based on: "Strong Impulse Signals [ProjectSyndicate]" TradingView indicator
"""

from __future__ import annotations

import dataclasses
import logging
import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class ImpulsePhase(Enum):
    """Stages of impulse pattern."""
    COIL = "coil"          # Consolidation phase
    IGNITION = "ignition"  # Breakout trigger
    BREAK = "break"        # Structural break
    THRUST = "thrust"      # Directional move
    TARGET = "target"      # Projected endpoint


@dataclass
class IgnitionCandle:
    """Detected ignition candle (high-confidence trigger)."""

    bar_index: int
    open: float
    high: float
    low: float
    close: float
    body_size: float  # close - open
    range: float  # high - low
    direction: str  # 'bullish' | 'bearish'

    def meets_criteria(self) -> bool:
        """Check if candle meets ignition criteria."""
        # Criteria: extend beyond recent range, body dominates, close at extreme
        return self.body_size > 0  # Valid


@dataclass
class PropulsionStrength:
    """Propulsion strength score (0-10)."""

    atr_displacement: float  # 0-2
    body_dominance: float  # 0-2 (body / range)
    close_position: float  # 0-2 (close near extreme?)
    momentum_score: float  # 0-2 (velocity)
    volume_confirmation: float  # 0-2 (volume strength)
    total_strength: float  # 0-10 sum

    def is_strong_impulse(self, threshold: float = 6.0) -> bool:
        """True if strength >= threshold."""
        return self.total_strength >= threshold


@dataclass
class ImpulseSignal:
    """Complete impulse signal with targets."""

    bar_index: int
    phase: ImpulsePhase
    direction: str  # 'long' | 'short'
    ignition_bar: int
    propulsion_strength: float  # 0-10
    entry_price: float
    invalidation_level: float
    target_1: float  # Conservative
    target_2: float  # Mid-range
    target_3: float  # Aggressive
    confirmation_bars: int  # How many bars until confirmed
    coil_start_bar: Optional[int] = None


class IgnitionCandleDetector:
    """Detect ignition candles (3-criteria high-confidence candles)."""

    def __init__(self, lookback: int = 20):
        self.lookback = lookback
        self.price_history: list[dict] = []

    def detect(
        self,
        bar_index: int,
        open: float,
        high: float,
        low: float,
        close: float,
        atr: float,
    ) -> Optional[IgnitionCandle]:
        """
        Detect ignition candle using 3 criteria:
        1. Extends beyond recent range
        2. Body dominates bar (body > range * 0.66)
        3. Closes at extreme end (close near high or low)
        """
        self.price_history.append(
            {"open": open, "high": high, "low": low, "close": close}
        )

        if len(self.price_history) > self.lookback:
            self.price_history.pop(0)

        body = abs(close - open)
        range_ = high - low

        if range_ == 0:
            return None

        if len(self.price_history) < 2:
            return None  # Not enough history
        recent_high = max(h["high"] for h in self.price_history[:-1])
        recent_low = min(l["low"] for l in self.price_history[:-1])

        # Criterion 1: Extends beyond recent range
        extends_beyond = high > recent_high or low < recent_low

        # Criterion 2: Body dominates (>60% of range)
        body_dominates = body > range_ * 0.6

        # Criterion 3: Close at extreme (within 25% of range from extreme)
        if close > open:  # Bullish
            close_at_extreme = (high - close) < range_ * 0.25
            direction = "bullish"
        else:  # Bearish
            close_at_extreme = (close - low) < range_ * 0.25
            direction = "bearish"

        all_criteria_met = extends_beyond and body_dominates and close_at_extreme

        if not all_criteria_met:
            return None

        logger.debug(f"[Impulse] Ignition candle {direction} at {bar_index}")

        return IgnitionCandle(
            bar_index=bar_index,
            open=open,
            high=high,
            low=low,
            close=close,
            body_size=body,
            range=range_,
            direction=direction,
        )


class PropulsionStrengthScorer:
    """Calculate propulsion strength (0-10)."""

    def __init__(self):
        self.momentum_history: list[float] = []

    def calculate(
        self,
        ignition: IgnitionCandle,
        atr: float,
        recent_momentum: float,  # 0-1
        volume_ratio: float,  # current_volume / avg_volume
    ) -> PropulsionStrength:
        """
        Calculate propulsion strength from 5 factors.

        Returns: PropulsionStrength (0-10)
        """
        # Factor 1: ATR Displacement (how many ATR did it move?)
        displacement = (ignition.range / atr) if atr > 0 else 0
        atr_displacement = min(2.0, displacement / 2.0)

        # Factor 2: Body Dominance (body / range)
        body_dom = (ignition.body_size / ignition.range) if ignition.range > 0 else 0
        body_dominance = min(2.0, body_dom * 3.0)

        # Factor 3: Close Position (close near extreme?)
        range_from_extreme = (
            (ignition.high - ignition.close)
            if ignition.direction == "bullish"
            else (ignition.close - ignition.low)
        )
        close_position = min(2.0, (1.0 - range_from_extreme / ignition.range) * 2.0)

        # Factor 4: Momentum
        momentum_score = min(2.0, recent_momentum * 2.0)

        # Factor 5: Volume Confirmation
        volume_confirmation = min(2.0, (volume_ratio - 1.0) * 2.0)

        total = (
            atr_displacement
            + body_dominance
            + close_position
            + momentum_score
            + volume_confirmation
        )

        return PropulsionStrength(
            atr_displacement=atr_displacement,
            body_dominance=body_dominance,
            close_position=close_position,
            momentum_score=momentum_score,
            volume_confirmation=volume_confirmation,
            total_strength=total,
        )


class InvalidationLevelCalculator:
    """Calculate invalidation levels (structural breaks)."""

    def calculate_invalidation(
        self,
        ignition: IgnitionCandle,
        direction: str,  # 'long' | 'short'
        atr: float,
    ) -> float:
        """
        Calculate where signal becomes invalid.

        For long: invalidation = low - 0.5*ATR
        For short: invalidation = high + 0.5*ATR
        """
        if direction == "long":
            return ignition.low - (atr * 0.5)
        else:
            return ignition.high + (atr * 0.5)


class TargetProjector:
    """Project take-profit targets based on propulsion."""

    def project_targets(
        self,
        entry: float,
        direction: str,  # 'long' | 'short'
        range_size: float,  # ignition candle range
        propulsion: float,  # 0-10 strength
    ) -> tuple[float, float, float]:
        """
        Project 3 targets based on propulsion strength.

        Stronger impulse = farther targets.
        """
        # Target multipliers increase with propulsion
        t1_multiplier = 1.0 + (propulsion * 0.15)  # 1.0x to 2.5x
        t2_multiplier = 2.0 + (propulsion * 0.20)  # 2.0x to 4.0x
        t3_multiplier = 3.0 + (propulsion * 0.25)  # 3.0x to 5.5x

        if direction == "long":
            tp1 = entry + (range_size * t1_multiplier)
            tp2 = entry + (range_size * t2_multiplier)
            tp3 = entry + (range_size * t3_multiplier)
        else:
            tp1 = entry - (range_size * t1_multiplier)
            tp2 = entry - (range_size * t2_multiplier)
            tp3 = entry - (range_size * t3_multiplier)

        return tp1, tp2, tp3


class StrongImpulseDetector:
    """Complete Strong Impulse Signal system."""

    def __init__(self):
        self.ignition_detector = IgnitionCandleDetector()
        self.propulsion_scorer = PropulsionStrengthScorer()
        self.invalidation_calc = InvalidationLevelCalculator()
        self.target_projector = TargetProjector()
        self.active_impulses: dict[int, ImpulseSignal] = {}

    def detect_impulse(
        self,
        bar_index: int,
        open: float,
        high: float,
        low: float,
        close: float,
        atr: float,
        recent_momentum: float,  # 0-1
        volume_ratio: float,  # current / avg
    ) -> Optional[ImpulseSignal]:
        """
        Run complete impulse detection pipeline.

        Returns: ImpulseSignal if strong impulse detected, else None.
        """
        # Step 1: Detect ignition candle
        ignition = self.ignition_detector.detect(
            bar_index=bar_index,
            open=open,
            high=high,
            low=low,
            close=close,
            atr=atr,
        )

        if not ignition:
            return None

        logger.debug(f"[Impulse] Ignition detected {ignition.direction} at {bar_index}")

        # Step 2: Calculate propulsion strength
        direction = "long" if ignition.direction == "bullish" else "short"
        propulsion = self.propulsion_scorer.calculate(
            ignition=ignition,
            atr=atr,
            recent_momentum=recent_momentum,
            volume_ratio=volume_ratio,
        )

        if not propulsion.is_strong_impulse(threshold=6.0):
            logger.debug(
                f"[Impulse] Weak propulsion: {propulsion.total_strength:.1f}/10"
            )
            return None

        logger.info(
            f"[Impulse] STRONG IMPULSE {direction} at {bar_index}: "
            f"propulsion={propulsion.total_strength:.1f}/10"
        )

        # Step 3: Calculate invalidation level
        invalidation = self.invalidation_calc.calculate_invalidation(
            ignition=ignition,
            direction=direction,
            atr=atr,
        )

        # Step 4: Project targets
        tp1, tp2, tp3 = self.target_projector.project_targets(
            entry=close,
            direction=direction,
            range_size=ignition.range,
            propulsion=propulsion.total_strength,
        )

        # Create signal
        signal = ImpulseSignal(
            bar_index=bar_index,
            phase=ImpulsePhase.IGNITION,
            direction=direction,
            ignition_bar=bar_index,
            propulsion_strength=propulsion.total_strength,
            entry_price=close,
            invalidation_level=invalidation,
            target_1=tp1,
            target_2=tp2,
            target_3=tp3,
            confirmation_bars=0,
        )

        self.active_impulses[bar_index] = signal
        return signal

    def update_phase(
        self,
        bar_index: int,
        high: float,
        low: float,
        close: float,
    ) -> list[ImpulseSignal]:
        """
        Update active impulses and detect phase transitions.

        Returns: List of updated signals.
        """
        updated_signals = []

        for pulse_bar, signal in list(self.active_impulses.items()):
            bars_since = bar_index - pulse_bar

            # Transition to BREAK phase
            if bars_since == 1 and signal.phase == ImpulsePhase.IGNITION:
                signal.phase = ImpulsePhase.BREAK

            # Transition to THRUST phase
            elif bars_since == 2 and signal.phase == ImpulsePhase.BREAK:
                signal.phase = ImpulsePhase.THRUST

            # Transition to TARGET phase
            elif bars_since >= 3 and signal.phase == ImpulsePhase.THRUST:
                signal.phase = ImpulsePhase.TARGET

            signal.confirmation_bars = bars_since
            updated_signals.append(signal)

        return updated_signals

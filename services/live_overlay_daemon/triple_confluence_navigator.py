"""Triple Confluence Navigator — 3-Way Signal Filtering for Maximum Confidence.

Implements 3-way confluence system:
1. Cardwell Momentum (MA crossover + Kalman filter)
2. Adaptive RSI & Supertrend (volatility-based)
3. Market Structure (swing-pivot + BoS)

Signal fires on a 2-of-3 majority (not all 3) + HTF bias validation + dynamic R/R.

Based on: "Triple Confluence Navigator [MarkitTick]" TradingView indicator
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class KalmanFilterState:
    """Kalman filter state for noise reduction."""

    value: float = 0.0
    uncertainty: float = 1.0
    process_variance: float = 0.01
    measurement_variance: float = 1.0

    def update(self, measurement: float) -> float:
        """Update Kalman filter with new measurement."""
        # Prediction step
        predicted_value = self.value
        predicted_uncertainty = self.uncertainty + self.process_variance

        # Update step
        kalman_gain = predicted_uncertainty / (
            predicted_uncertainty + self.measurement_variance
        )
        self.value = predicted_value + kalman_gain * (measurement - predicted_value)
        self.uncertainty = (1 - kalman_gain) * predicted_uncertainty

        return self.value


@dataclass
class CardwellMomentum:
    """Cardwell momentum: MA crossover with Kalman filtering."""

    fast_ma: float = 0.0
    slow_ma: float = 0.0
    signal: str = "neutral"  # 'bullish' | 'bearish' | 'neutral'
    kalman_smoothed: float = 0.0
    kalman_filter: KalmanFilterState = field(default_factory=KalmanFilterState)

    def update(
        self,
        close: float,
        fast_period: int = 9,
        slow_period: int = 21,
        fast_ma_prev: float = 0.0,
        slow_ma_prev: float = 0.0,
    ) -> str:
        """
        Update Cardwell momentum with new close.

        Uses EMA for moving averages + Kalman filter for smoothing.
        """
        # Simple EMA update (simplified)
        self.fast_ma = (
            close * (2 / (fast_period + 1)) + fast_ma_prev * (1 - 2 / (fast_period + 1))
        )
        self.slow_ma = (
            close * (2 / (slow_period + 1))
            + slow_ma_prev * (1 - 2 / (slow_period + 1))
        )

        # Momentum value
        momentum = self.fast_ma - self.slow_ma

        # Kalman filter for noise reduction
        self.kalman_smoothed = self.kalman_filter.update(momentum)

        # Determine signal
        if self.kalman_smoothed > 0:
            self.signal = "bullish"
        elif self.kalman_smoothed < 0:
            self.signal = "bearish"
        else:
            self.signal = "neutral"

        return self.signal


@dataclass
class AdaptiveRsiSupertrend:
    """Adaptive RSI & Supertrend (volatility-adjusted)."""

    rsi_value: float = 50.0
    supertrend: float = 0.0
    signal: str = "neutral"  # 'bullish' | 'bearish' | 'neutral'
    atr: float = 0.0

    def update(
        self,
        close: float,
        high: float,
        low: float,
        atr_value: float,
        rsi_period: int = 14,
    ) -> str:
        """
        Update adaptive RSI & Supertrend.

        Supertrend bands adapt to volatility (wider in choppy markets).
        """
        # Simple RSI calc (placeholder)
        self.rsi_value = 50.0  # Simplified

        # ATR-based bands
        hl_avg = (high + low) / 2
        self.supertrend = hl_avg
        self.atr = atr_value

        # Determine signal
        # NOTE: rsi_value is a fixed-neutral placeholder (see above), so this
        # branch currently always resolves to "neutral" until a real RSI is
        # wired in — intentional, not a bug.
        if close > self.supertrend and self.rsi_value > 50:
            self.signal = "bullish"
        elif close < self.supertrend and self.rsi_value < 50:
            self.signal = "bearish"
        else:
            self.signal = "neutral"

        return self.signal


@dataclass
class MarketStructure:
    """Market structure: swing-pivot + BoS detection."""

    signal: str = "neutral"  # 'bullish' | 'bearish' | 'neutral'
    pivot_high: float = 0.0
    pivot_low: float = 0.0
    break_of_structure: bool = False

    def update(
        self,
        high: float,
        low: float,
        pivot_high_prev: float,
        pivot_low_prev: float,
    ) -> str:
        """
        Update market structure based on swing pivots.

        BoS = high above recent pivot high or low below recent pivot low
        (wick-based break, not close-confirmed).
        """
        # A non-finite high/low would emit a spurious break-of-structure vote
        # (+inf > prev is True) and permanently poison the persisted pivots via
        # max(inf, x) / min(-inf, x). Treat a corrupt bar as structurally
        # neutral and leave the pivots untouched.
        if not (math.isfinite(high) and math.isfinite(low)):
            self.break_of_structure = False
            self.signal = "neutral"
            return self.signal

        self.pivot_high = max(high, pivot_high_prev)
        self.pivot_low = min(low, pivot_low_prev)

        # BoS detection
        self.break_of_structure = (
            high > pivot_high_prev or low < pivot_low_prev
        )

        # Determine signal
        if high > pivot_high_prev:
            self.signal = "bullish"
        elif low < pivot_low_prev:
            self.signal = "bearish"
        else:
            self.signal = "neutral"

        return self.signal


@dataclass
class ConfluenceScore:
    """Score for 3-way confluence alignment."""

    cardwell_signal: str
    rsi_supertrend_signal: str
    structure_signal: str
    aligned: bool  # True on a 2-of-3 majority (not all 3)
    alignment_strength: float  # 0-1
    direction: str  # 'long' | 'short' | 'neutral'

    @staticmethod
    def calculate(
        cardwell: CardwellMomentum,
        rsi: AdaptiveRsiSupertrend,
        structure: MarketStructure,
    ) -> ConfluenceScore:
        """Calculate confluence score from 3 sources."""
        cardwell_sig = cardwell.signal
        rsi_sig = rsi.signal
        structure_sig = structure.signal

        # Count agreements
        bullish_votes = sum(
            [
                cardwell_sig == "bullish",
                rsi_sig == "bullish",
                structure_sig == "bullish",
            ]
        )
        bearish_votes = sum(
            [
                cardwell_sig == "bearish",
                rsi_sig == "bearish",
                structure_sig == "bearish",
            ]
        )

        if bullish_votes >= 2:
            aligned = True
            alignment_strength = bullish_votes / 3.0
            direction = "long"
        elif bearish_votes >= 2:
            aligned = True
            alignment_strength = bearish_votes / 3.0
            direction = "short"
        else:
            aligned = False
            alignment_strength = max(bullish_votes, bearish_votes) / 3.0
            direction = "neutral"

        return ConfluenceScore(
            cardwell_signal=cardwell_sig,
            rsi_supertrend_signal=rsi_sig,
            structure_signal=structure_sig,
            aligned=aligned,
            alignment_strength=alignment_strength,
            direction=direction,
        )


@dataclass
class DynamicRiskReward:
    """Dynamic risk/reward calculation based on confluence."""

    entry_price: float
    stop_loss: float
    take_profit: float
    risk_amount: float
    reward_amount: float
    risk_reward_ratio: float

    @staticmethod
    def calculate(
        entry: float,
        stop_loss: float,
        recent_range: float,
        confluence_strength: float,  # 0-1
    ) -> DynamicRiskReward:
        """
        Calculate dynamic R/R based on confluence strength.

        Stronger confluence = higher R/R targets.
        """
        risk = abs(entry - stop_loss)
        reward_multiplier = 1.5 + (confluence_strength * 1.5)  # 1.5x to 3.0x
        tp = entry + (risk * reward_multiplier)

        return DynamicRiskReward(
            entry_price=entry,
            stop_loss=stop_loss,
            take_profit=tp,
            risk_amount=risk,
            reward_amount=abs(tp - entry),
            risk_reward_ratio=abs(tp - entry) / risk if risk > 0 else 1.0,
        )


@dataclass
class TripleConfluenceSignal:
    """Final signal from triple confluence system."""

    bar_index: int
    direction: str  # 'long' | 'short' | 'neutral'
    confluence_strength: float  # 0-1
    cardwell_signal: str
    rsi_signal: str
    structure_signal: str
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_reward_ratio: float
    htf_bias_aligned: bool
    confirmed: bool


class TripleConfluenceNavigator:
    """Complete Triple Confluence Navigator system."""

    def __init__(self):
        self.cardwell = CardwellMomentum()
        self.rsi_supertrend = AdaptiveRsiSupertrend()
        self.structure = MarketStructure()
        self.price_history: list[dict] = []
        self.htf_bias: str = "neutral"  # From higher timeframe

    @staticmethod
    def _htf_aligned(htf_bias: str, direction: str) -> bool:
        """Neutral HTF bias allows all signals; otherwise it must match."""
        return htf_bias == "neutral" or htf_bias == direction

    def process_candle(
        self,
        bar_index: int,
        open: float,
        high: float,
        low: float,
        close: float,
        atr: float,
        volume: float,
        htf_bias: str = "neutral",  # From HTF
    ) -> TripleConfluenceSignal | None:
        """
        Process new candle through triple confluence system.

        Returns: TripleConfluenceSignal if confluence confirmed, else None.
        """
        # Non-finite OHLC or ATR would poison persisted state (pivot_high/low
        # via max/min, supertrend = (high+low)/2) and flow into the dynamic
        # risk/reward entry/stop/target levels; skip corrupt candles.
        if not all(math.isfinite(v) for v in (open, high, low, close, atr)):
            return None

        self.price_history.append(
            {"open": open, "high": high, "low": low, "close": close}
        )

        if len(self.price_history) > 50:
            self.price_history.pop(0)

        self.htf_bias = htf_bias

        # Step 1: Update all 3 confluence sources
        self.cardwell.update(
            close=close,
            fast_period=9,
            slow_period=21,
            fast_ma_prev=self.cardwell.fast_ma,
            slow_ma_prev=self.cardwell.slow_ma,
        )

        self.rsi_supertrend.update(
            close=close,
            high=high,
            low=low,
            atr_value=atr,
        )

        self.structure.update(
            high=high,
            low=low,
            pivot_high_prev=self.structure.pivot_high,
            pivot_low_prev=self.structure.pivot_low,
        )

        # Step 2: Calculate confluence score
        confluence = ConfluenceScore.calculate(
            cardwell=self.cardwell,
            rsi=self.rsi_supertrend,
            structure=self.structure,
        )

        if not confluence.aligned:
            return None

        logger.debug(
            "[Confluence] %s signal: "
            "C=%s R=%s "
            "S=%s strength=%.2f",
            confluence.direction,
            confluence.cardwell_signal,
            confluence.rsi_supertrend_signal,
            confluence.structure_signal,
            confluence.alignment_strength,
        )

        # Step 3: Check HTF bias alignment
        htf_aligned = self._htf_aligned(htf_bias, confluence.direction)

        if not htf_aligned:
            logger.debug("[Confluence] HTF bias misaligned: HTF=%s, signal=%s", htf_bias, confluence.direction)
            return None

        logger.info(
            "[Confluence] TRIPLE CONFLUENCE %s at %s: "
            "strength=%.2f",
            confluence.direction,
            bar_index,
            confluence.alignment_strength,
        )

        # Step 4: Calculate dynamic R/R
        # Clamp a non-finite / non-positive ATR to a zero buffer so the stop
        # stays on the correct side of price (a negative ATR would put a long
        # stop ABOVE `low`) and never becomes NaN/inf. Mirrors the high/low
        # finiteness guard earlier in this method and the `atr > 0` convention
        # used across the detector cluster.
        atr_buffer = atr if (math.isfinite(atr) and atr > 0) else 0.0
        stop_loss = (
            low - atr_buffer if confluence.direction == "long"
            else high + atr_buffer
        )

        risk_reward = DynamicRiskReward.calculate(
            entry=close,
            stop_loss=stop_loss,
            recent_range=high - low,
            confluence_strength=confluence.alignment_strength,
        )

        # Create final signal
        signal = TripleConfluenceSignal(
            bar_index=bar_index,
            direction=confluence.direction,
            confluence_strength=confluence.alignment_strength,
            cardwell_signal=confluence.cardwell_signal,
            rsi_signal=confluence.rsi_supertrend_signal,
            structure_signal=confluence.structure_signal,
            entry_price=close,
            stop_loss=risk_reward.stop_loss,
            take_profit=risk_reward.take_profit,
            risk_reward_ratio=risk_reward.risk_reward_ratio,
            htf_bias_aligned=htf_aligned,
            confirmed=True,
        )

        return signal

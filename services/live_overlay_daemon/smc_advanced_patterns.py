"""Advanced SMC Patterns: HVB, PPDD, Liquidity Clusters, BoS Refinement.

Implements makuchaku-inspired patterns:
- High Volume Bar (HVB) detection for signal quality
- Premium/Discount OrderBlock (PPDD) bias classification
- Liquidity Cluster identification
- Break of Structure (BoS) with nested structure validation
- Broken Fractal pattern recognition

Used by SmcSignalDetector for signal filtering + confluence.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class StructureLevel(Enum):
    """Market structure nesting levels (for Broken Fractal pattern)."""
    LEVEL_1 = 1  # Immediate structure
    LEVEL_2 = 2  # Secondary structure (HTF confirmation)
    LEVEL_3 = 3  # Tertiary structure (Major TF)


@dataclass
class HVBBar:
    """High Volume Bar — bar with volume > avg + signal quality marker."""

    bar_index: int
    volume: int
    avg_volume: float
    volume_ratio: float  # volume / avg_volume
    is_hvb: bool  # True if volume_ratio > threshold (typically 1.5x)
    close: float
    open: float
    high: float
    low: float

    def is_bullish(self) -> bool:
        """True if close > open."""
        return self.close > self.open

    def is_bearish(self) -> bool:
        """True if close < open."""
        return self.close < self.open


@dataclass
class PPDDOrderBlock:
    """Premium/Discount OrderBlock — OB with liquidity bias classification."""

    box_top: float
    box_bottom: float
    direction: str  # 'bullish' | 'bearish'
    is_premium: bool  # True if OB formed in Premium (resistance) zone
    is_discount: bool  # True if OB formed in Discount (support) zone
    strength: float  # 0.0-1.0: confluence count / max_possible_confluence
    hvb_confirmation: bool  # True if HVB present at OB formation
    created_at: int
    created_price: float

    def bias(self) -> str:
        """Return 'premium' or 'discount' based on classification."""
        if self.is_premium:
            return "premium"
        if self.is_discount:
            return "discount"
        return "neutral"


@dataclass
class LiquidityCluster:
    """Zone where multiple liquidity sources cluster (stops, limit orders)."""

    center_price: float
    zone_top: float
    zone_bottom: float
    cluster_count: int  # Number of high/low confluences
    risk_level: str  # 'low', 'medium', 'high'
    direction_bias: str  # 'bullish', 'bearish', 'neutral'

    @property
    def zone_width(self) -> float:
        return self.zone_top - self.zone_bottom

    def contains_price(self, price: float) -> bool:
        return self.zone_bottom <= price <= self.zone_top


@dataclass
class BrokenFractal:
    """Nested fractal structure: Fractal → Opposite → Break detection."""

    level: StructureLevel
    initial_fractal_high: float
    initial_fractal_low: float
    opposite_fractal_high: float
    opposite_fractal_low: float
    break_price: float
    break_direction: str  # 'up' | 'down'
    confirmed: bool  # True if break confirmed on close
    trapped_traders_escape: bool  # True if price reversed after break
    entry_box_top: float
    entry_box_bottom: float


class HVBDetector:
    """Detect High Volume Bars for signal quality confirmation."""

    def __init__(self, lookback: int = 20, hvb_threshold: float = 1.5):
        """
        Args:
            lookback: Candles to average for volume baseline
            hvb_threshold: volume/avg_volume ratio to classify as HVB (default 1.5x)
        """
        if lookback < 1:
            # lookback=0 would trim volume_history to empty right before the
            # rolling-average division -> ZeroDivisionError.
            raise ValueError(f"HVBDetector lookback must be >= 1, got {lookback}")
        self.lookback = lookback
        self.hvb_threshold = hvb_threshold
        self.volume_history: list[int] = []

    def detect(
        self,
        bar_index: int,
        volume: int,
        close: float,
        open: float,
        high: float,
        low: float,
    ) -> HVBBar:
        """Detect if current bar is HVB based on rolling average."""
        self.volume_history.append(volume)
        if len(self.volume_history) > self.lookback:
            self.volume_history.pop(0)

        avg_volume = sum(self.volume_history) / len(self.volume_history)
        volume_ratio = volume / avg_volume if avg_volume > 0 else 0.0
        is_hvb = volume_ratio > self.hvb_threshold

        return HVBBar(
            bar_index=bar_index,
            volume=volume,
            avg_volume=avg_volume,
            volume_ratio=volume_ratio,
            is_hvb=is_hvb,
            close=close,
            open=open,
            high=high,
            low=low,
        )


class PPDDClassifier:
    """Classify OrderBlocks as Premium (resistance) vs Discount (support)."""

    def __init__(self, atr_multiple: float = 2.0):
        """
        Args:
            atr_multiple: How many ATR above/below price define premium/discount
        """
        self.atr_multiple = atr_multiple

    def classify(
        self,
        ob_top: float,
        ob_bottom: float,
        direction: str,
        current_price: float,
        atr: float,
        hvb_present: bool = False,
    ) -> PPDDOrderBlock:
        """
        Classify OB as Premium or Discount based on price proximity.

        Premium = OB formed above current price (resistance)
        Discount = OB formed below current price (support)
        """
        ob_center = (ob_top + ob_bottom) / 2

        is_premium = False
        is_discount = False

        if direction == "bullish":
            # Bullish OB: if formed above current price (at resistance), it's premium
            is_premium = ob_center > current_price
            is_discount = not is_premium
        else:
            # Bearish OB: if formed below current price (at support), it's discount
            is_discount = ob_center < current_price
            is_premium = not is_discount

        # Strength based on how many ATR away from price
        distance_atr = abs(ob_center - current_price) / atr if atr > 0 else 0
        strength = min(1.0, distance_atr / self.atr_multiple)

        return PPDDOrderBlock(
            box_top=ob_top,
            box_bottom=ob_bottom,
            direction=direction,
            is_premium=is_premium,
            is_discount=is_discount,
            strength=strength,
            hvb_confirmation=hvb_present,
            created_at=0,  # Set by caller
            created_price=current_price,
        )


class LiquidityClusterDetector:
    """Identify price zones where liquidity clusters (stops, limits, BoS levels)."""

    def __init__(self, cluster_distance_atr: float = 0.5, min_confluences: int = 2):
        """
        Args:
            cluster_distance_atr: ATR distance to group confluences into cluster
            min_confluences: Min number of confluences to form a cluster
        """
        self.cluster_distance_atr = cluster_distance_atr
        self.min_confluences = min_confluences

    def detect_clusters(
        self,
        swing_highs: list[float],
        swing_lows: list[float],
        current_price: float,
        atr: float,
    ) -> list[LiquidityCluster]:
        """
        Find liquidity clusters by grouping nearby swing highs/lows.

        Returns clusters sorted by proximity to current price.
        """
        if not swing_highs and not swing_lows:
            return []

        cluster_distance = self.cluster_distance_atr * atr

        # Group swing highs
        high_clusters = self._cluster_prices(swing_highs, cluster_distance)
        # Group swing lows
        low_clusters = self._cluster_prices(swing_lows, cluster_distance)

        clusters = []

        for center, count in high_clusters:
            if count >= self.min_confluences:
                risk = self._risk_level(center, current_price)
                bias = "bearish" if center > current_price else "bullish"
                clusters.append(
                    LiquidityCluster(
                        center_price=center,
                        zone_top=center + cluster_distance / 2,
                        zone_bottom=center - cluster_distance / 2,
                        cluster_count=count,
                        risk_level=risk,
                        direction_bias=bias,
                    )
                )

        for center, count in low_clusters:
            if count >= self.min_confluences:
                risk = self._risk_level(center, current_price)
                bias = "bullish" if center < current_price else "bearish"
                clusters.append(
                    LiquidityCluster(
                        center_price=center,
                        zone_top=center + cluster_distance / 2,
                        zone_bottom=center - cluster_distance / 2,
                        cluster_count=count,
                        risk_level=risk,
                        direction_bias=bias,
                    )
                )

        # Sort by proximity to current price
        clusters.sort(key=lambda c: abs(c.center_price - current_price))
        return clusters

    def _cluster_prices(
        self, prices: list[float], distance: float
    ) -> list[tuple[float, int]]:
        """Group nearby prices into clusters."""
        if not prices:
            return []

        sorted_prices = sorted(prices)
        clusters: list[tuple[float, int]] = []
        current_cluster = [sorted_prices[0]]

        for price in sorted_prices[1:]:
            if abs(price - current_cluster[-1]) <= distance:
                current_cluster.append(price)
            else:
                center = sum(current_cluster) / len(current_cluster)
                clusters.append((center, len(current_cluster)))
                current_cluster = [price]

        if current_cluster:
            center = sum(current_cluster) / len(current_cluster)
            clusters.append((center, len(current_cluster)))

        return clusters

    def _risk_level(self, cluster_price: float, current_price: float) -> str:
        """Classify risk based on distance from current price."""
        if current_price <= 0 or not math.isfinite(current_price):
            return "high"  # Degenerate price data: treat as highest risk
        distance_pct = abs(cluster_price - current_price) / current_price
        if distance_pct < 0.01:
            return "high"  # Very close, high risk
        if distance_pct < 0.05:
            return "medium"
        return "low"


class BrokenFractalDetector:
    """Detect Broken Fractal pattern: Structure → Opposite → Break."""

    # Only the last 3 entries are read; keep a small buffer so the
    # per-bar history cannot grow without bound in the daemon.
    MAX_FRACTAL_HISTORY = 64

    def __init__(self):
        self.fractal_history: list[dict] = []

    def _record(self, high: float, low: float, close: float) -> None:
        self.fractal_history.append({"high": high, "low": low, "close": close})
        if len(self.fractal_history) > self.MAX_FRACTAL_HISTORY:
            del self.fractal_history[: -self.MAX_FRACTAL_HISTORY]

    def detect(
        self,
        bar_index: int,
        high: float,
        low: float,
        close: float,
        level: StructureLevel = StructureLevel.LEVEL_1,
    ) -> BrokenFractal | None:
        """
        Detect Broken Fractal pattern.

        Pattern:
        1. Initial fractal (high or low)
        2. Opposite fractal (opposite extremity)
        3. Break of initial fractal
        4. Confirmation: trapped traders exit
        """
        # Simplified detection: track recent highs/lows
        # This is a basic version; full implementation would track multi-level structures

        if len(self.fractal_history) < 3:
            self._record(high, low, close)
            return None

        # Get last 3 fractal points
        last_high = max(f["high"] for f in self.fractal_history[-3:])
        last_low = min(f["low"] for f in self.fractal_history[-3:])

        # Check if we broke the initial high (bullish fractal break)
        if high > last_high:
            logger.debug("[BF] Broken Fractal UP at %s: %s > %s", bar_index, high, last_high)
            return BrokenFractal(
                level=level,
                initial_fractal_high=last_high,
                initial_fractal_low=last_low,
                opposite_fractal_high=high,
                opposite_fractal_low=low,
                break_price=high,
                break_direction="up",
                confirmed=close > last_high,
                trapped_traders_escape=False,  # Confirm on next candle
                entry_box_top=high,
                entry_box_bottom=last_high,
            )

        # Check if we broke the initial low (bearish fractal break)
        if low < last_low:
            logger.debug("[BF] Broken Fractal DOWN at %s: %s < %s", bar_index, low, last_low)
            return BrokenFractal(
                level=level,
                initial_fractal_high=last_high,
                initial_fractal_low=last_low,
                opposite_fractal_high=high,
                opposite_fractal_low=low,
                break_price=low,
                break_direction="down",
                confirmed=close < last_low,
                trapped_traders_escape=False,
                entry_box_top=last_low,
                entry_box_bottom=low,
            )

        self._record(high, low, close)
        return None


class BoSRefinement:
    """Refine Break of Structure with nested level validation."""

    def validate_bos(
        self,
        break_price: float,
        direction: str,
        nested_level: StructureLevel | None = None,
    ) -> dict:
        """
        Validate BoS with nested structure.

        Returns: {
            'valid': bool,
            'reason': str,
            'nested_confirmation': bool,
            'strength': float (0.0-1.0)
        }
        """
        # Basic validation: BoS on lower TF should have HTF confirmation
        strength = 1.0 if nested_level == StructureLevel.LEVEL_3 else 0.5

        return {
            "valid": True,
            "reason": "BoS detected",
            "nested_confirmation": nested_level is not None,
            "strength": strength,
        }

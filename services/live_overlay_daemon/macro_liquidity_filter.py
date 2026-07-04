"""Macro Liquidity Filter — SOFR-IORB based stress detection.

Real-time macro regime filter using SOFR (Secured Overnight Financing Rate)
and IORB (Interest on Reserve Balances) spread to suppress trading signals
during system stress periods.

SOFR - IORB spread thresholds:
- < 0 bp = Ample liquidity (Risk-On)
- 0-5 bp = Normal liquidity (Risk-Neutral)
- > 5 bp = Stress conditions (Risk-Off, suppress signals)

Data source: FRED (daily updates)
Update frequency: Once per day (typically 17:00 UTC)
"""

from __future__ import annotations

import dataclasses
import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


@dataclass
class LiquidityRegime:
    """Current market liquidity regime."""

    sofr_iorb_spread_bp: float  # SOFR - IORB in basis points
    stress_level: int  # 0 (no stress) to 10 (extreme stress)
    regime: str  # 'abundant', 'normal', 'tight', 'stress', 'extreme_stress'
    is_stressed: bool  # True if spread > 5 bp
    timestamp: datetime
    last_update: datetime
    bars_in_stress: int = 0  # How many bars stressed


@dataclass
class MacroLiquidityFilter:
    """Macro liquidity filter using SOFR-IORB spread."""

    # Configurable thresholds (in basis points)
    stress_threshold_bp: float = 5.0  # Suppress if spread > this
    extreme_threshold_bp: float = 15.0  # Extreme stress if spread > this
    normal_threshold_bp: float = 0.0  # Abundant if spread < this

    # State
    sofr_iorb_spread_bp: float = 0.0  # Current spread
    regime: LiquidityRegime = dataclasses.field(default_factory=lambda: LiquidityRegime(
        sofr_iorb_spread_bp=0.0,
        stress_level=0,
        regime='normal',
        is_stressed=False,
        timestamp=datetime.now(UTC),
        last_update=datetime.now(UTC),
        bars_in_stress=0,
    ))

    # History for analysis
    spread_history: list[float] = dataclasses.field(default_factory=list)
    regime_history: list[str] = dataclasses.field(default_factory=list)

    def update(
        self,
        sofr_rate: float,  # e.g., 4.33 (percent)
        iorb_rate: float,  # e.g., 4.33 (percent)
        bar_index: int = 0,
    ) -> LiquidityRegime:
        """Update regime with new SOFR/IORB rates.

        Args:
            sofr_rate: SOFR rate in percent (e.g., 4.33)
            iorb_rate: IORB rate in percent (e.g., 4.33)
            bar_index: Current bar index (for tracking)

        Returns: Updated LiquidityRegime
        """
        # Non-finite rates would produce a NaN spread: every `NaN < threshold`
        # is False, so the regime chain falls through to 'extreme_stress'
        # (stress_level=10) while `is_stressed = NaN > threshold` is False —
        # a contradictory regime that fails OPEN (does not suppress). Fail-safe
        # instead: keep the last known regime rather than corrupt state, and
        # do not abort the per-bar backtest loop.
        if not (math.isfinite(sofr_rate) and math.isfinite(iorb_rate)):
            logger.debug(
                "MacroLiquidityFilter: non-finite rates (sofr=%s, iorb=%s); regime unchanged",
                sofr_rate, iorb_rate,
            )
            return self.regime

        # Convert to basis points
        spread_bp = (sofr_rate - iorb_rate) * 100.0
        self.sofr_iorb_spread_bp = spread_bp
        self.spread_history.append(spread_bp)

        # Keep last 100 bars of history
        if len(self.spread_history) > 100:
            self.spread_history.pop(0)

        # Determine regime
        if spread_bp < self.normal_threshold_bp:
            regime_name = 'abundant'
            stress_level = 0
        elif spread_bp < self.stress_threshold_bp:
            regime_name = 'normal'
            stress_level = 2
        elif spread_bp < self.extreme_threshold_bp:
            regime_name = 'stress'
            stress_level = 7
            is_stressed = True
        else:
            regime_name = 'extreme_stress'
            stress_level = 10
            is_stressed = True

        is_stressed = spread_bp > self.stress_threshold_bp

        # Update bars in stress
        bars_in_stress = self.regime.bars_in_stress + (1 if is_stressed else 0)
        if not is_stressed:
            bars_in_stress = 0  # Reset counter on exit

        # Create new regime
        self.regime = LiquidityRegime(
            sofr_iorb_spread_bp=spread_bp,
            stress_level=stress_level,
            regime=regime_name,
            is_stressed=is_stressed,
            timestamp=datetime.now(UTC),
            last_update=datetime.now(UTC),
            bars_in_stress=bars_in_stress,
        )

        self.regime_history.append(regime_name)
        if len(self.regime_history) > 100:
            self.regime_history.pop(0)

        logger.debug(
            "[Macro] LSI update: spread=%.1fbp, regime=%s, stress=%s",
            spread_bp,
            regime_name,
            'ON' if is_stressed else 'OFF',
        )

        return self.regime

    def should_suppress_signals(self) -> bool:
        """True if current regime should suppress trading signals."""
        return self.regime.is_stressed

    def get_regime_score(self) -> float:
        """Return 0-1 risk-off score.

        0.0 = abundant liquidity (Risk-On)
        1.0 = extreme stress (Risk-Off)
        """
        if self.sofr_iorb_spread_bp < self.normal_threshold_bp:
            return 0.0
        elif self.sofr_iorb_spread_bp < self.stress_threshold_bp:
            return 0.3
        elif self.sofr_iorb_spread_bp < self.extreme_threshold_bp:
            return 0.7
        else:
            return 1.0

    def get_confidence_multiplier(self) -> float:
        """Return signal confidence multiplier (0.0-1.0).

        In normal regimes: 1.0
        In stress: scales down to 0.3 (suppress but don't mute)
        """
        risk_off_score = self.get_regime_score()

        # Linear scale: 1.0 at risk-on, 0.3 at extreme risk-off
        return 1.0 - (risk_off_score * 0.7)  # 1.0 to 0.3

    def reset(self) -> None:
        """Reset to initial state."""
        self.sofr_iorb_spread_bp = 0.0
        self.regime = LiquidityRegime(
            sofr_iorb_spread_bp=0.0,
            stress_level=0,
            regime='normal',
            is_stressed=False,
            timestamp=datetime.now(UTC),
            last_update=datetime.now(UTC),
            bars_in_stress=0,
        )
        self.spread_history.clear()
        self.regime_history.clear()


def estimate_daily_spread_from_history(
    spread_history: list[float],
) -> float | None:
    """Estimate current daily spread from intraday history.

    Since SOFR/IORB only update once daily, use rolling average
    of recent bars to estimate current daily value.
    """
    if not spread_history or len(spread_history) < 5:
        return None

    # Average last 5 bars (last hour for 1-hour bars)
    recent = spread_history[-5:]
    return sum(recent) / len(recent)

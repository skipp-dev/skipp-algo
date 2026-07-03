"""Ensemble Signal Router — Orchestrates all 4 advanced trading systems.

Combines:
1. SMT Sniper Entry Engine (liquidity + quality validation)
2. Strong Impulse Signals (ignition + propulsion)
3. Triple Confluence Navigator (3-way alignment gate)
4. Macro Liquidity Filter (SOFR-IORB stress suppression)

Routes final signals with conflict resolution and confidence scoring.
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass
from typing import Optional
from enum import Enum

from services.live_overlay_daemon.smc_signal_detector import SmcSignalDetector
from services.live_overlay_daemon.smt_sniper_validator import SmtSniperValidator, SmtSniperSignal
from services.live_overlay_daemon.strong_impulse_detector import StrongImpulseDetector, ImpulseSignal
from services.live_overlay_daemon.triple_confluence_navigator import TripleConfluenceNavigator, TripleConfluenceSignal
from services.live_overlay_daemon.macro_liquidity_filter import MacroLiquidityFilter, LiquidityRegime

logger = logging.getLogger(__name__)


class SignalSource(Enum):
    """Which system generated the signal."""
    SMC_PATTERN = "smc_pattern"  # Order Block, FVG, RJB
    SMT_SNIPER = "smt_sniper"  # Multi-stage validation
    STRONG_IMPULSE = "strong_impulse"  # Ignition + propulsion
    TRIPLE_CONFLUENCE = "triple_confluence"  # 3-way alignment


@dataclass
class ConflictResolution:
    """Conflict result when multiple systems disagree."""

    has_conflict: bool
    primary_source: SignalSource
    secondary_sources: list[SignalSource]
    agreement_count: int  # How many systems agreed
    confidence: float  # 0-1 (higher = more agreement)
    recommendation: str  # 'proceed' | 'suppress' | 'investigate'


@dataclass
class EnsembleSignal:
    """Final routed signal from ensemble."""

    bar_index: int
    direction: str  # 'long' | 'short' | 'neutral'
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: float  # 0-1 (weighted average)
    sources: list[SignalSource]  # Which systems voted
    sources_count: int  # How many systems voted
    smt_signal: Optional[SmtSniperSignal] = None
    impulse_signal: Optional[ImpulseSignal] = None
    confluence_signal: Optional[TripleConfluenceSignal] = None
    liquidity_regime: Optional[LiquidityRegime] = None
    conflict: Optional[ConflictResolution] = None


class EnsembleSignalRouter:
    """Orchestrates all 4 systems and routes final signals."""

    def __init__(self, max_smc_boxes: int = 10):
        # Core detectors
        self.smc_detector = SmcSignalDetector(max_boxes_per_direction=max_smc_boxes)
        self.smt_sniper = SmtSniperValidator()
        self.impulse_detector = StrongImpulseDetector()
        self.confluence_nav = TripleConfluenceNavigator()

        # Macro filter
        self.macro_filter = MacroLiquidityFilter(
            stress_threshold_bp=5.0,
            extreme_threshold_bp=15.0,
        )

        # Signal routing
        self.latest_ensemble_signal: Optional[EnsembleSignal] = None
        self.signal_history: list[EnsembleSignal] = []

    def process_candle(
        self,
        bar_index: int,
        open: float,
        high: float,
        low: float,
        close: float,
        atr: float,
        volume: int,
        htf_bias: str = "neutral",
        sofr_rate: Optional[float] = None,
        iorb_rate: Optional[float] = None,
    ) -> Optional[EnsembleSignal]:
        """Process one candle through complete ensemble.

        Args:
            bar_index: Current bar index
            open, high, low, close: OHLC
            atr: Average True Range
            volume: Volume
            htf_bias: Higher timeframe bias ('long' | 'short' | 'neutral')
            sofr_rate: SOFR rate in percent (optional)
            iorb_rate: IORB rate in percent (optional)

        Returns: EnsembleSignal if consensus reached, else None
        """
        # Step 0: Update macro regime
        if sofr_rate and iorb_rate:
            self.macro_filter.update(sofr_rate, iorb_rate, bar_index)

        # Check if macro stress should suppress signals
        if self.macro_filter.should_suppress_signals():
            logger.debug(
                f"[Ensemble] Macro stress active: {self.macro_filter.regime.regime}, "
                f"spread={self.macro_filter.sofr_iorb_spread_bp:.1f}bp"
            )
            # Suppress but continue to monitor
            confidence_multiplier = self.macro_filter.get_confidence_multiplier()
        else:
            confidence_multiplier = 1.0

        # Step 1: SMC Pattern Detection
        smc_signals = self.smc_detector.process_candle(
            self._make_smc_candle(bar_index, open, high, low, close, volume)
        )

        # Step 2: SMT Sniper Validation
        smt_signal = self.smt_sniper.validate_entry(
            bar_index=bar_index,
            high=high,
            low=low,
            close=close,
            atr=atr,
            structure_score=0.6,  # Placeholder: would come from SMC analysis
            correlated_markets={},  # Placeholder
            recent_momentum=0.5,  # Placeholder
        )

        # Step 3: Strong Impulse Detection
        impulse_signal = self.impulse_detector.detect_impulse(
            bar_index=bar_index,
            open=open,
            high=high,
            low=low,
            close=close,
            atr=atr,
            recent_momentum=0.5,  # Placeholder
            volume_ratio=1.0,  # Placeholder
        )

        # Step 4: Triple Confluence Navigator
        confluence_signal = self.confluence_nav.process_candle(
            bar_index=bar_index,
            open=open,
            high=high,
            low=low,
            close=close,
            atr=atr,
            volume=volume,
            htf_bias=htf_bias,
        )

        # Step 5: Merge signals
        signals = [s for s in [smt_signal, impulse_signal, confluence_signal] if s]

        if not signals:
            return None

        # Step 6: Resolve conflicts
        final_signal = self._merge_signals(
            bar_index=bar_index,
            smt_signal=smt_signal,
            impulse_signal=impulse_signal,
            confluence_signal=confluence_signal,
            confidence_multiplier=confidence_multiplier,
        )

        if final_signal:
            self.latest_ensemble_signal = final_signal
            self.signal_history.append(final_signal)
            logger.info(
                f"[Ensemble] SIGNAL {final_signal.direction.upper()} @ {bar_index}: "
                f"sources={final_signal.sources_count}, confidence={final_signal.confidence:.2f}"
            )

        return final_signal

    def _merge_signals(
        self,
        bar_index: int,
        smt_signal: Optional[SmtSniperSignal],
        impulse_signal: Optional[ImpulseSignal],
        confluence_signal: Optional[TripleConfluenceSignal],
        confidence_multiplier: float = 1.0,
    ) -> Optional[EnsembleSignal]:
        """Merge signals from all 3 systems with conflict resolution."""

        # Collect votes
        votes = []
        signals = []

        if smt_signal and smt_signal.direction == "long":
            votes.append(("long", 0.8, SignalSource.SMT_SNIPER))
            signals.append(smt_signal)
        elif smt_signal and smt_signal.direction == "short":
            votes.append(("short", 0.8, SignalSource.SMT_SNIPER))
            signals.append(smt_signal)

        if impulse_signal and impulse_signal.direction == "long":
            votes.append(("long", 0.85, SignalSource.STRONG_IMPULSE))
            signals.append(impulse_signal)
        elif impulse_signal and impulse_signal.direction == "short":
            votes.append(("short", 0.85, SignalSource.STRONG_IMPULSE))
            signals.append(impulse_signal)

        if confluence_signal and confluence_signal.direction == "long":
            votes.append(("long", 0.9, SignalSource.TRIPLE_CONFLUENCE))
            signals.append(confluence_signal)
        elif confluence_signal and confluence_signal.direction == "short":
            votes.append(("short", 0.9, SignalSource.TRIPLE_CONFLUENCE))
            signals.append(confluence_signal)

        if not votes:
            return None

        # Check for conflicts (different directions)
        long_votes = [v for v in votes if v[0] == "long"]
        short_votes = [v for v in votes if v[0] == "short"]

        if long_votes and short_votes:
            # Conflict: systems disagree
            logger.warning(
                f"[Ensemble] CONFLICT at {bar_index}: {len(long_votes)} longs, "
                f"{len(short_votes)} shorts. SUPPRESSING."
            )
            return None

        # All agree on direction
        direction = votes[0][0]
        avg_confidence = sum(v[1] for v in votes) / len(votes)
        avg_confidence = avg_confidence * confidence_multiplier

        # Aggregate entry/stop/TP
        entry = confluence_signal.entry_price if confluence_signal else (
            impulse_signal.entry_price if impulse_signal else smt_signal.entry_price
        )
        stop_loss = confluence_signal.stop_loss if confluence_signal else (
            impulse_signal.invalidation_level if impulse_signal else smt_signal.stop_loss
        )
        take_profit = confluence_signal.take_profit if confluence_signal else (
            impulse_signal.target_2 if impulse_signal else smt_signal.take_profit_2
        )

        sources = [v[2] for v in votes]

        return EnsembleSignal(
            bar_index=bar_index,
            direction=direction,
            entry_price=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            confidence=avg_confidence,
            sources=sources,
            sources_count=len(votes),
            smt_signal=smt_signal,
            impulse_signal=impulse_signal,
            confluence_signal=confluence_signal,
            liquidity_regime=self.macro_filter.regime,
        )

    def _make_smc_candle(
        self,
        bar_index: int,
        open: float,
        high: float,
        low: float,
        close: float,
        volume: int,
    ):
        """Convert to SMC candle format."""
        from services.live_overlay_daemon.smc_signal_detector import Candle

        return Candle(
            bar_index=bar_index,
            open=open,
            high=high,
            low=low,
            close=close,
            volume=volume,
        )

    def get_active_structures(self):
        """Get active SMC structures."""
        return self.smc_detector.get_active_structures()

    def get_signal_history(self, limit: int = 20) -> list[EnsembleSignal]:
        """Get recent signals."""
        return self.signal_history[-limit:]

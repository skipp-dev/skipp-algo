"""SMC v2 detector configuration (Phase 2 configurability).

All thresholds and confidence values are configurable via environment
variables so that live deployments can tune behaviour without code
changes.  Every setting has a safe default that matches the original
hard-coded behaviour.
"""

from __future__ import annotations

import os


def _env_int(name: str, default: int, min_val: int | None = None, max_val: int | None = None) -> int:
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    if min_val is not None:
        value = max(min_val, value)
    if max_val is not None:
        value = min(max_val, value)
    return value


def _env_float(name: str, default: float, min_val: float | None = None, max_val: float | None = None) -> float:
    try:
        value = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    if min_val is not None:
        value = max(min_val, value)
    if max_val is not None:
        value = min(max_val, value)
    return value


class SweepTrapConfig:
    """Tunables for the sweep-trap detector."""

    @property
    def quality_threshold(self) -> int:
        """Quality scores below this value can form a trap (0-5 scale)."""
        return _env_int("SMC_SWEEP_TRAP_QUALITY_THRESHOLD", 3, min_val=0, max_val=5)

    @property
    def lopsided_boost(self) -> int:
        """Extra confidence when only one sweep direction is present."""
        return _env_int("SMC_SWEEP_TRAP_LOPSIDED_BOOST", 20, min_val=0, max_val=100)

    @property
    def reversal_penalty(self) -> int:
        """Confidence reduction when structure reversed against the sweep."""
        return _env_int("SMC_SWEEP_TRAP_REVERSAL_PENALTY", 40, min_val=0, max_val=100)


class ReactionZoneConfig:
    """Tunables for the reaction-zone detector."""

    @property
    def distance_threshold_pct(self) -> float:
        """OB/FVG must be within this percentage distance to define a zone."""
        return _env_float("SMC_REACTION_ZONE_DISTANCE_PCT", 3.0, min_val=0.1, max_val=50.0)

    @property
    def bias_aligned_confidence(self) -> int:
        """Confidence when zone direction aligns with session bias."""
        return _env_int("SMC_REACTION_ZONE_BIAS_ALIGNED_CONFIDENCE", 60, min_val=0, max_val=100)

    @property
    def bias_misaligned_confidence(self) -> int:
        """Confidence when zone direction conflicts with session bias."""
        return _env_int("SMC_REACTION_ZONE_BIAS_MISALIGNED_CONFIDENCE", 40, min_val=0, max_val=100)


class ConfluenceScoreConfig:
    """Tunables for the confluence-score detector."""

    @property
    def points_per_signal(self) -> int:
        """Score contribution of each aligned signal."""
        return _env_int("SMC_CONFLUENCE_POINTS_PER_SIGNAL", 20, min_val=1, max_val=100)


class SmtDivergenceConfig:
    """Tunables for the SMT-divergence detector."""

    @property
    def confidence(self) -> int:
        """Confidence when a divergence is detected."""
        return _env_int("SMC_SMT_DIVERGENCE_CONFIDENCE", 70, min_val=0, max_val=100)


# Module-level singletons for convenient import.
sweep_trap_config = SweepTrapConfig()
reaction_zone_config = ReactionZoneConfig()
confluence_score_config = ConfluenceScoreConfig()
smt_divergence_config = SmtDivergenceConfig()

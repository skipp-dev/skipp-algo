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
    """Tunables for the reaction-*context* detector (``detect_reaction_zone``).

    These knobs ONLY affect the enrichment context detector (fresh structure/
    sweep near an OB/FVG). They do **not** configure the canonical measurement
    geometry in ``compute_reaction_zone`` — that path hard-codes
    ``ZONE_WIDTH_FRACTION`` / ``MIN_CONFIRMATION_BODY_RATIO`` and never reads
    this config. The env vars were renamed ``SMC_REACTION_ZONE_*`` →
    ``SMC_REACTION_CONTEXT_*`` (2026-07-13, clean cutover — verified unset in
    every Railway service) to match the ``ENABLE_REACTION_CONTEXT`` flag split.
    """

    @property
    def distance_threshold_pct(self) -> float:
        """OB/FVG must be within this percentage distance to flag a context."""
        return _env_float("SMC_REACTION_CONTEXT_DISTANCE_PCT", 3.0, min_val=0.1, max_val=50.0)

    @property
    def bias_aligned_confidence(self) -> int:
        """Confidence when context direction aligns with session bias."""
        return _env_int("SMC_REACTION_CONTEXT_BIAS_ALIGNED_CONFIDENCE", 60, min_val=0, max_val=100)

    @property
    def bias_misaligned_confidence(self) -> int:
        """Confidence when context direction conflicts with session bias."""
        return _env_int("SMC_REACTION_CONTEXT_BIAS_MISALIGNED_CONFIDENCE", 40, min_val=0, max_val=100)


# NOTE: the ``SMC_CONFLUENCE_POINTS_PER_SIGNAL`` knob (class ``ConfluenceScore
# Config``) was removed 2026-07-13 — it was RESERVED/UNWIRED and read nowhere.
# The real confluence detector (``smc_core/smc_confluence.py``) hard-codes its
# thresholds and uses a geometric mean, not a points-per-signal model, and the
# v2 bucket weight is hard-coded in ``scripts/smc_signal_quality.py``.


class SmtDivergenceConfig:
    """Tunables for the SMT-divergence detector.

    PRODUCTIVELY INERT — ``detect_smt_divergence`` returns neutral for every
    production event because no production producer builds the required
    ``correlated_context`` block (only tests supply it; see
    ``smc_core/smt_divergence.py``). Until a PIT-safe correlated-context feed
    exists, ``SMC_SMT_DIVERGENCE_HEURISTIC_SCORE`` has no observable effect in
    prod.
    """

    @property
    def confidence(self) -> int:
        """Heuristic conviction constant stamped on a detected divergence
        (0–100, NOT a probability). Env:
        ``SMC_SMT_DIVERGENCE_HEURISTIC_SCORE``. Inert in prod — see class doc."""
        return _env_int("SMC_SMT_DIVERGENCE_HEURISTIC_SCORE", 70, min_val=0, max_val=100)


# Module-level singletons for convenient import.
sweep_trap_config = SweepTrapConfig()
reaction_zone_config = ReactionZoneConfig()
smt_divergence_config = SmtDivergenceConfig()

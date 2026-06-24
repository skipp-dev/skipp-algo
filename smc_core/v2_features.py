"""SMC v2 feature-flag access layer for smc_core.

Phase 0c scaffolding (2026-06-24).  All flags default OFF; the module
exposes thin wrappers around ``open_prep.feature_flags`` so that later
phases can gate new logic consistently inside ``smc_core``.
"""
from __future__ import annotations

from open_prep.feature_flags import (
    is_confluence_score_enabled,
    is_freshness_v2_enabled,
    is_reaction_zone_enabled,
    is_smt_divergence_enabled,
    is_sweep_trap_enabled,
    signal_quality_model,
)


def sweep_trap_enabled() -> bool:
    """Return True when the Sweep Trap feature is enabled."""
    return is_sweep_trap_enabled()


def reaction_zone_enabled() -> bool:
    """Return True when the Reaction Zone feature is enabled."""
    return is_reaction_zone_enabled()


def confluence_score_enabled() -> bool:
    """Return True when the Confluence Score feature is enabled."""
    return is_confluence_score_enabled()


def freshness_v2_enabled() -> bool:
    """Return True when Freshness v2 is enabled."""
    return is_freshness_v2_enabled()


def smt_divergence_enabled() -> bool:
    """Return True when SMT Divergence is enabled."""
    return is_smt_divergence_enabled()


def active_signal_quality_model() -> str:
    """Return the active signal-quality model version (``"v1"`` default)."""
    return signal_quality_model()


def any_v2_feature_enabled() -> bool:
    """Return True if any SMC v2 feature flag is currently enabled."""
    return any(
        (
            sweep_trap_enabled(),
            reaction_zone_enabled(),
            confluence_score_enabled(),
            freshness_v2_enabled(),
            smt_divergence_enabled(),
        )
    )


def v2_feature_summary() -> dict[str, bool | str]:
    """Return a snapshot of all SMC v2 feature flags and the SQ model."""
    return {
        "sweep_trap": sweep_trap_enabled(),
        "reaction_zone": reaction_zone_enabled(),
        "confluence_score": confluence_score_enabled(),
        "freshness_v2": freshness_v2_enabled(),
        "smt_divergence": smt_divergence_enabled(),
        "signal_quality_model": active_signal_quality_model(),
    }

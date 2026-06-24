"""SMC v2 feature-flag access layer for smc_core.

Phase 0c scaffolding (2026-06-24).  All flags default OFF and are read
directly from environment variables so ``smc_core`` stays independent
from ``open_prep`` package imports.
"""

from __future__ import annotations

import os

_TRUE_VALUES = frozenset({"1", "true", "yes", "on", "y"})


def _flag_enabled(name: str) -> bool:
    raw = os.getenv(name, "")
    return raw.strip().lower() in _TRUE_VALUES


def sweep_trap_enabled() -> bool:
    """Return True when the Sweep Trap feature is enabled."""
    return _flag_enabled("ENABLE_SWEEP_TRAP")


def reaction_zone_enabled() -> bool:
    """Return True when the Reaction Zone feature is enabled."""
    return _flag_enabled("ENABLE_REACTION_ZONE")


def confluence_score_enabled() -> bool:
    """Return True when the Confluence Score feature is enabled."""
    return _flag_enabled("ENABLE_CONFLUENCE_SCORE")


def freshness_v2_enabled() -> bool:
    """Return True when Freshness v2 is enabled."""
    return _flag_enabled("ENABLE_FRESHNESS_V2")


def smt_divergence_enabled() -> bool:
    """Return True when SMT Divergence is enabled."""
    return _flag_enabled("ENABLE_SMT_DIVERGENCE")


def active_signal_quality_model() -> str:
    """Return the active signal-quality model version (``"v1"`` default)."""
    model = os.getenv("SIGNAL_QUALITY_MODEL", "v1").strip().lower()
    if model in {"v1", "v2", "v2.1"}:
        return model
    return "v1"


def v2_feature_summary() -> dict[str, bool | str]:
    """Return a snapshot of all v2 feature flags and the active model."""
    return {
        "model": active_signal_quality_model(),
        "sweep_trap": sweep_trap_enabled(),
        "reaction_zone": reaction_zone_enabled(),
        "confluence_score": confluence_score_enabled(),
        "freshness_v2": freshness_v2_enabled(),
        "smt_divergence": smt_divergence_enabled(),
    }

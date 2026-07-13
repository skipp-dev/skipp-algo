"""SMC v2 feature-flag access layer for smc_core.

Phase 0c scaffolding (2026-06-24).  All flags default OFF and are read
directly from environment variables so ``smc_core`` stays independent
from ``open_prep`` package imports.
"""

from __future__ import annotations

import os


def _flag_enabled(name: str) -> bool:
    """Return True only when the env var is set to ``"1"``.

    Matches the contract used by ``open_prep.feature_flags._bool_env``
    so operators see consistent semantics across the codebase.
    """
    return os.getenv(name, "").strip() == "1"


def sweep_trap_enabled() -> bool:
    """Return True when the Sweep Trap feature is enabled."""
    return _flag_enabled("ENABLE_SWEEP_TRAP")


def reaction_zone_study_enabled() -> bool:
    """Return True when the Reaction-Zone *study* is enabled.

    Canonical ``ENABLE_REACTION_ZONE_STUDY``; old ``ENABLE_REACTION_ZONE`` is a
    deprecated alias. Mirrors ``open_prep.feature_flags``.
    """
    return _flag_enabled("ENABLE_REACTION_ZONE_STUDY") or _flag_enabled("ENABLE_REACTION_ZONE")


def reaction_context_enabled() -> bool:
    """Return True when the Reaction-*context* detector is enabled.

    Canonical ``ENABLE_REACTION_CONTEXT``; old ``ENABLE_REACTION_ZONE`` is a
    deprecated alias. Gates :func:`smc_core.reaction_zone.detect_reaction_zone`.
    """
    return _flag_enabled("ENABLE_REACTION_CONTEXT") or _flag_enabled("ENABLE_REACTION_ZONE")


def reaction_zone_enabled() -> bool:
    """Deprecated: prefer :func:`reaction_zone_study_enabled` /
    :func:`reaction_context_enabled`. True iff either split feature is on."""
    return reaction_zone_study_enabled() or reaction_context_enabled()


def confluence_score_enabled() -> bool:
    """Return True when the Confluence Score feature is enabled."""
    return _flag_enabled("ENABLE_CONFLUENCE_SCORE")


def freshness_v2_enabled() -> bool:
    """Return True when the Freshness-v2 score model is enabled.

    Canonical ``ENABLE_FRESHNESS_V2_SCORE``; old ``ENABLE_FRESHNESS_V2`` is a
    deprecated alias.
    """
    return _flag_enabled("ENABLE_FRESHNESS_V2_SCORE") or _flag_enabled("ENABLE_FRESHNESS_V2")


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

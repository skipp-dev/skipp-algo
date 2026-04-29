"""Session liquidity context — backward-compatible re-export from smc_core.session_context.

All logic now lives in smc_core.session_context (F-08 layer cleanup).
"""
from __future__ import annotations

# Re-export everything for backward compatibility
from smc_core.session_context import (
    DEFAULT_KILLZONES,
    DEFAULT_OPENING_LEVELS,
    DEFAULT_TZ,
    build_dwm_levels,
    build_killzones,
    build_opening_levels,
    build_session_liquidity_context,
    build_session_pivots,
)

__all__ = [
    "DEFAULT_KILLZONES",
    "DEFAULT_OPENING_LEVELS",
    "DEFAULT_TZ",
    "build_dwm_levels",
    "build_killzones",
    "build_opening_levels",
    "build_session_liquidity_context",
    "build_session_pivots",
]


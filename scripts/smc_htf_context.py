"""HTF bias context — backward-compatible re-export from smc_core.htf_context.

All logic now lives in smc_core.htf_context (F-08 layer cleanup).
"""
from __future__ import annotations

# Re-export everything for backward compatibility
from smc_core.htf_context import (  # noqa: F401
    build_htf_bias_context,
    build_ipda_range,
    compute_calendar_boundaries,
    compute_fvg_bias_counter,
    select_ipda_htf,
)

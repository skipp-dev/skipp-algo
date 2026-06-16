"""Inventory pin for the active Pine surface (root + ``pine/`` + ``SMC++/``).

Background
==========

After the legacy move (``tests/test_pine_legacy_isolation.py``) the active
Pine surface consists of:

* ~15 ``SMC_*.pine`` orchestrators at the repo root (entry-point scripts).
* ``SkippALGO_Confluence.pine`` at the root (umbrella confluence script).
* ``test_div.pine`` at the root (compile-only smoke test).
* 6 published library candidates under ``pine/`` (skipp_*.pine).
* 8 private SMC libraries under ``SMC++/``.
* Generated artifacts under ``pine/generated/``.

This test pins those counts and the per-file inventory so that
* removing a Pine file forces an explicit decision,
* introducing a new Pine file at the root forces classification (active
  orchestrator vs. private library vs. legacy).

Companion tests
---------------

* ``tests/test_pine_legacy_isolation.py`` — pins ``pine/legacy/``.
* ``tests/test_pine_library_version_consistency.py`` — pins library
  major-version skew across active imports.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_ROOT_ORCHESTRATORS: frozenset[str] = frozenset({
    "SMC_Core_Engine.pine",
    "SMC_Dashboard.pine",
    "SMC_Event_Overlay.pine",
    "SMC_HTF_Confluence.pine",
    "SMC_Imbalance_Context.pine",
    "SMC_Liquidity_Context.pine",
    "SMC_Liquidity_Structure.pine",
    "SMC_Long_Strategy.pine",
    "SMC_Mobile_Dashboard.pine",
    "SMC_Orderflow_Overlay.pine",
    "SMC_Profile_Context.pine",
    "SMC_Session_Context.pine",
    "SMC_Setup_Check.pine",
    "SMC_Structure_Context.pine",
    "SMC_TV_Bridge.pine",
    "SkippALGO_Confluence.pine",
    "test_div.pine",
    # 2026-04-30 (commit 68e1aac0): companion overlays + exit/hold-mgr surfaces.
    # Inventory updated as part of v3 phase 1 pine-consumer-discipline fix.
    "SMC_Breakout_Overlay.pine",
    "SMC_Exit_Signal.pine",
    "SMC_Hold_Manager.pine",
    "SMC_VRVP_Overlay.pine",
})

_PINE_LIBRARIES: frozenset[str] = frozenset({
    "skipp_calibration.pine",
    "skipp_indicators.pine",
    "skipp_labels.pine",
    "skipp_math.pine",
    "skipp_scoring.pine",
    # feat/live-overlay-daemon (PR #2794): Pine consumer for the FastAPI daemon.
    "smc_live_overlay_consumer.pine",
})

_SMCPP_LIBRARIES: frozenset[str] = frozenset({
    "smc_bus_private.pine",
    "smc_context_resolvers.pine",
    "smc_core_types.pine",
    "smc_draw.pine",
    "smc_lifecycle_private.pine",
    "smc_observability_private.pine",
    "smc_profile_engine.pine",
    "smc_utils.pine",
})


def test_root_orchestrator_inventory_is_exact() -> None:
    """The repo root must contain exactly the canonical Pine orchestrators."""
    observed = frozenset(p.name for p in REPO_ROOT.glob("*.pine"))
    extras = sorted(observed - _ROOT_ORCHESTRATORS)
    missing = sorted(_ROOT_ORCHESTRATORS - observed)
    assert not extras, (
        f"NEW .pine file(s) at repo root: {extras}. "
        "Classify as orchestrator (add to _ROOT_ORCHESTRATORS), "
        "library (move under pine/ or SMC++/), or legacy (move under pine/legacy/)."
    )
    assert not missing, (
        f"Root orchestrator(s) removed: {missing}. "
        "Either remove from _ROOT_ORCHESTRATORS with CHANGELOG entry, "
        "or restore the file."
    )


def test_pine_library_inventory_is_exact() -> None:
    """``pine/*.pine`` must contain exactly the canonical published libraries."""
    pine_dir = REPO_ROOT / "pine"
    assert pine_dir.is_dir(), f"missing pine/: {pine_dir}"
    observed = frozenset(p.name for p in pine_dir.glob("*.pine"))
    extras = sorted(observed - _PINE_LIBRARIES)
    missing = sorted(_PINE_LIBRARIES - observed)
    assert not extras, f"NEW pine/ library(ies): {extras}"
    assert not missing, f"pine/ library(ies) removed: {missing}"


def test_smcpp_library_inventory_is_exact() -> None:
    """``SMC++/*.pine`` must contain exactly the canonical private libraries."""
    smcpp_dir = REPO_ROOT / "SMC++"
    assert smcpp_dir.is_dir(), f"missing SMC++/: {smcpp_dir}"
    observed = frozenset(p.name for p in smcpp_dir.glob("*.pine"))
    extras = sorted(observed - _SMCPP_LIBRARIES)
    missing = sorted(_SMCPP_LIBRARIES - observed)
    assert not extras, f"NEW SMC++ library(ies): {extras}"
    assert not missing, f"SMC++ library(ies) removed: {missing}"


def test_total_active_pine_surface_count() -> None:
    """Belt-and-braces: active surface count is pinned for at-a-glance review."""
    expected = len(_ROOT_ORCHESTRATORS) + len(_PINE_LIBRARIES) + len(_SMCPP_LIBRARIES)
    # 21 + 5 + 8 = 34 active Pine files
    # (was 17 + 5 + 8 = 30; +4 from F-04 PR #1924 promoting
    # SMC_Breakout_Overlay / Exit_Signal / Hold_Manager / VRVP_Overlay).
    assert expected == 35, f"inventory frozensets drifted: total={expected}"

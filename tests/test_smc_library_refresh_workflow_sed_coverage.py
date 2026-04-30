"""Pin that the version-bump sed targets every .pine consumer that
imports smc_micro_profiles_generated.

Guards against the 2026-04-22 regression where only
``SMC_Core_Engine.pine`` got re-pinned by
``.github/workflows/smc-library-refresh.yml``, leaving 13 other
top-level Pine consumers stranded on the previous library version
and silently importing stale exports.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PIN_PATTERN = re.compile(
    r"import preuss_steffen/smc_micro_profiles_generated/\d+"
)

EXPECTED_CONSUMERS: set[str] = {
    "SMC_Core_Engine.pine",
    "SMC_Dashboard.pine",
    "SMC_Mobile_Dashboard.pine",
    "SMC_Long_Strategy.pine",
    "SkippALGO_Confluence.pine",
    "SMC_Structure_Context.pine",
    "SMC_Session_Context.pine",
    "SMC_Profile_Context.pine",
    "SMC_Orderflow_Overlay.pine",
    "SMC_Liquidity_Structure.pine",
    "SMC_Liquidity_Context.pine",
    "SMC_Imbalance_Context.pine",
    "SMC_HTF_Confluence.pine",
    "SMC_Event_Overlay.pine",
    "SMC_Breakout_Overlay.pine",
}

EXCLUDED_PARTS = {"tests", "generated", "node_modules", ".git", "pine"}


def _discover_consumers() -> set[str]:
    consumers: set[str] = set()
    for pine in REPO.rglob("*.pine"):
        if any(p in EXCLUDED_PARTS for p in pine.relative_to(REPO).parts[:-1]):
            continue
        if PIN_PATTERN.search(pine.read_text(encoding="utf-8")):
            consumers.add(pine.name)
    return consumers


def test_all_pine_consumers_are_covered_by_version_bump() -> None:
    consumers = _discover_consumers()
    missing = EXPECTED_CONSUMERS - consumers
    assert not missing, (
        "Expected pine consumers no longer import the library — "
        "drop them from EXPECTED_CONSUMERS or restore the import: "
        f"{sorted(missing)}"
    )
    new_consumers = consumers - EXPECTED_CONSUMERS
    assert not new_consumers, (
        "New top-level pine consumers detected — add them to "
        "EXPECTED_CONSUMERS *and* the workflow git-add list in "
        ".github/workflows/smc-library-refresh.yml: "
        f"{sorted(new_consumers)}"
    )


def test_workflow_git_add_lists_every_pine_consumer() -> None:
    workflow = (
        REPO / ".github" / "workflows" / "smc-library-refresh.yml"
    ).read_text(encoding="utf-8")
    for name in EXPECTED_CONSUMERS:
        assert name in workflow, (
            f"{name} is missing from the smc-library-refresh.yml "
            "git-add list — version bump would commit a stale "
            "library pin for it."
        )


def test_workflow_uses_loop_based_pin_step() -> None:
    """Make sure the workflow no longer hard-codes the single-file
    sed path (which is the exact regression we are pinning against)."""
    workflow = (
        REPO / ".github" / "workflows" / "smc-library-refresh.yml"
    ).read_text(encoding="utf-8")
    assert "Bump library version in all pine consumers" in workflow, (
        "Workflow no longer contains the loop-based version-bump "
        "step. Did the single-file sed regression come back?"
    )
    assert "for f in \"${PINE_CONSUMERS[@]}\"" in workflow, (
        "Workflow version-bump step is no longer iterating over "
        "discovered consumers."
    )

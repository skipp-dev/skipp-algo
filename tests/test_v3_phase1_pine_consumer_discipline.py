"""v3 Phase 1 — Pine consumer discipline RED test.

Pins three architectural invariants that were violated on `main` HEAD
on 2026-04-30 after commit 68e1aac0 added four new top-level Pine files
without registering them in the governance surfaces:

1. Every top-level ``*.pine`` file must be classified in the SMC bus
   manifest (``scripts/smc_bus_manifest.py``) — either via a
   ``SurfaceDefinition`` entry or via the ``NON_SMC_PINE_FILES`` allow-list.
2. Every Pine file that imports
   ``preuss_steffen/smc_micro_profiles_generated`` must appear in the
   ``EXPECTED_CONSUMERS`` set in
   ``tests/test_smc_library_refresh_workflow_sed_coverage.py`` so the
   library-refresh workflow's loop-based pin step actually targets it.
3. Every such consumer must also appear in the ``git add`` block of
   ``.github/workflows/smc-library-refresh.yml`` — otherwise the
   workflow's auto-pin sed modifies the file but the modification is
   never staged, which trips the "Unexpected tracked changes remain
   unstaged before refresh commit" guard at the same step and aborts
   the entire refresh.

The four newly-added files (commit 68e1aac0) are:
- SMC_Breakout_Overlay.pine  — imports ``preuss_steffen/smc_micro_profiles_generated/1`` → MUST be in workflow & consumers set.
- SMC_Hold_Manager.pine      — imports ``skippALGO/smc_micro_profiles_generated/1`` (different namespace, not auto-pinned).
- SMC_Exit_Signal.pine       — pure BUS consumer, no library import.
- SMC_VRVP_Overlay.pine      — visual-only, no library import.

found via SMC review v3 phase 1
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _top_level_pine_files() -> set[str]:
    return {p.name for p in REPO_ROOT.glob("*.pine")}


def test_all_top_level_pine_files_classified_in_bus_manifest() -> None:
    """Every top-level .pine must be classified or explicitly excluded.

    Re-asserts ``test_smc_bus_manifest_contract::test_every_pine_file_is_classified_or_explicitly_excluded``
    from a different angle so a future refactor of the manifest does
    not silently drop the discipline.
    """
    from scripts import smc_bus_manifest as manifest

    governed = set(manifest.ALL_SMC_PINE_FILES) | set(manifest.NON_SMC_PINE_FILES)
    unclassified = _top_level_pine_files() - governed
    assert not unclassified, (
        "Top-level pine file(s) missing from bus manifest "
        "(scripts/smc_bus_manifest.py): "
        f"{sorted(unclassified)}. "
        "Add a SurfaceDefinition entry (active) or extend "
        "NON_SMC_PINE_FILES (out-of-scope)."
    )


_LIBRARY_PIN_RE = re.compile(
    r"import\s+preuss_steffen/smc_micro_profiles_generated/\d+",
)


def _consumers_of_preuss_library() -> set[str]:
    out: set[str] = set()
    for p in REPO_ROOT.glob("*.pine"):
        if _LIBRARY_PIN_RE.search(p.read_text(encoding="utf-8")):
            out.add(p.name)
    return out


def test_every_library_consumer_listed_in_workflow_git_add() -> None:
    """Every top-level pine that pins the preuss_steffen library must be
    on the ``git add`` line of the smc-library-refresh workflow."""
    workflow_path = REPO_ROOT / ".github" / "workflows" / "smc-library-refresh.yml"
    workflow_text = workflow_path.read_text(encoding="utf-8")
    consumers = _consumers_of_preuss_library()
    missing = [name for name in sorted(consumers) if name not in workflow_text]
    assert not missing, (
        "Pine consumer(s) of preuss_steffen library are missing from "
        ".github/workflows/smc-library-refresh.yml `git add` block. "
        "The workflow's loop-based sed step will modify these files "
        "but the unstaged-changes guard will abort the refresh: "
        f"{missing}"
    )


def test_every_library_consumer_listed_in_expected_consumers() -> None:
    """The refresh workflow's pin-coverage test mirrors the workflow.
    Adding a consumer here without bumping ``EXPECTED_CONSUMERS`` lets
    a stale-pin regression slip past CI."""
    from tests.test_smc_library_refresh_workflow_sed_coverage import (
        EXPECTED_CONSUMERS,
    )

    consumers = _consumers_of_preuss_library()
    new = consumers - EXPECTED_CONSUMERS
    assert not new, (
        "Pine consumer(s) of preuss_steffen library missing from "
        "EXPECTED_CONSUMERS in tests/test_smc_library_refresh_workflow"
        f"_sed_coverage.py: {sorted(new)}"
    )

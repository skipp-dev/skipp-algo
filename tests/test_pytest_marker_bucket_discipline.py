"""ADR-0012 Option B: pytest fast/slow bucket discipline.

The repository partitions its test suite between two CI jobs:

- ``fast-gates`` — required status check; the *fast* lane.
- ``validate``  — full-suite; the *slow* lane (everything else).

The partition is sourced from :mod:`tests._fast_inventory`. The root
``conftest.py`` auto-marks every test file **not** in that inventory
as ``slow`` at collection time, so devs can run ``pytest -m "not slow"``
locally and approximate the fast-gates set. NOTE (Phase 1): CI job
selection is unchanged — ``fast-gates`` runs an explicit file list and
``validate`` runs the full suite; the marker does not yet drive CI.

This test guards these invariants:

1. Every test/glob referenced in the ``fast-gates`` workflow is present
   in the inventory, so the conftest auto-marker never marks a
   fast-gates test ``slow``. The inventory MAY be a superset (it also
   pins this discipline test, which runs only in ``validate``), so the
   relationship is one-directional (workflow ⊆ inventory), not
   bidirectional.
2. The ``slow`` marker is registered in ``pyproject.toml`` so
   ``pytest --strict-markers`` does not error out.

See ``docs/adr/0012-fast-gates-vs-validate-separation.md``.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from tests._fast_inventory import FAST_TEST_FILES, FAST_TEST_GLOBS

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "smc-fast-pr-gates.yml"

_WF_TEST_RE = re.compile(r"tests/(test_[A-Za-z0-9_]+\.py)")

# Test files referenced in smc-fast-pr-gates.yml that intentionally
# do NOT live in the fast lane. Empty today; entries must come with
# a comment explaining why.
_KNOWN_NON_FAST_WF_REFS: frozenset[str] = frozenset()


def _workflow_referenced_test_basenames() -> set[str]:
    text = WORKFLOW.read_text(encoding="utf-8")
    return set(_WF_TEST_RE.findall(text)) - _KNOWN_NON_FAST_WF_REFS


def test_fast_inventory_matches_workflow_file_list() -> None:
    """Every test referenced in fast-gates.yml must be in FAST_TEST_FILES."""
    referenced = _workflow_referenced_test_basenames()
    missing = referenced - FAST_TEST_FILES
    assert not missing, (
        "Tests referenced in smc-fast-pr-gates.yml but missing from "
        f"tests/_fast_inventory.py FAST_TEST_FILES: {sorted(missing)}. "
        "Add them so the conftest auto-marker keeps the fast/slow "
        "partition consistent with CI (ADR-0012)."
    )


def test_fast_inventory_has_no_stale_entries() -> None:
    """Every FAST_TEST_FILES entry must correspond to an existing file."""
    tests_dir = REPO_ROOT / "tests"
    stale = {name for name in FAST_TEST_FILES if not (tests_dir / name).is_file()}
    assert not stale, (
        f"FAST_TEST_FILES contains entries that no longer exist on disk: "
        f"{sorted(stale)}. Drop them in this PR."
    )


def test_fast_globs_match_at_least_one_file() -> None:
    """Each glob in FAST_TEST_GLOBS must currently match at least one file."""
    tests_dir = REPO_ROOT / "tests"
    empty = [pat for pat in FAST_TEST_GLOBS if not list(tests_dir.glob(pat))]
    assert not empty, (
        f"FAST_TEST_GLOBS contains patterns that match no files: {empty}. "
        "Either remove the pattern or land the first matching test."
    )


def test_fast_globs_are_referenced_by_workflow() -> None:
    """Each FAST_TEST_GLOBS pattern must appear in the fast-gates workflow.

    Guards against the inventory's glob lane drifting from what CI
    actually expands (e.g. ``tests/test_smc_integration_*.py``).
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    unreferenced = [pat for pat in FAST_TEST_GLOBS if f"tests/{pat}" not in text]
    assert not unreferenced, (
        "FAST_TEST_GLOBS patterns not referenced in smc-fast-pr-gates.yml: "
        f"{unreferenced}. Keep the inventory glob lane in lock-step with the "
        "workflow so the conftest auto-marker matches CI (ADR-0012)."
    )


def test_slow_marker_is_registered() -> None:
    """pyproject.toml MUST register ``slow`` for ``--strict-markers``."""
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    markers = pyproject.get("tool", {}).get("pytest", {}).get("ini_options", {}).get("markers", [])
    assert any(str(m).startswith("slow:") for m in markers), (
        "pyproject.toml [tool.pytest.ini_options].markers MUST declare a "
        "``slow:`` marker (ADR-0012)."
    )

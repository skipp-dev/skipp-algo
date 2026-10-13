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
   fast-gates test ``slow``. The inventory MAY be a superset of the
   workflow refs, so the relationship is one-directional
   (workflow ⊆ inventory), not bidirectional. This discipline test is
   itself both in the inventory AND executed on the required
   ``fast-gates`` path (drift-guard step), so the partition is
   validated before merge rather than only post-merge in ``validate``.
2. The ``slow`` marker is registered in ``pyproject.toml`` so
   ``pytest --strict-markers`` does not error out.
3. The ``_KNOWN_NON_FAST_WF_REFS`` allowlist stays honest: every entry
   is still referenced in the workflow (no dead entries that could mask
   a missing inventory entry) and is disjoint from ``FAST_TEST_FILES``
   (no basename claimed as both fast and intentionally-not-fast).
4. ``is_fast`` — the public API the conftest auto-marker relies on —
   agrees with the inventory data, so a refactor cannot silently
   reshuffle the partition at collection time.

See ``docs/adr/0012-fast-gates-vs-validate-separation.md``.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from tests._fast_inventory import FAST_TEST_FILES, FAST_TEST_GLOBS, is_fast

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "smc-fast-pr-gates.yml"

_WF_TEST_RE = re.compile(r"tests/(test_[A-Za-z0-9_]+\.py)")

# Test files referenced in smc-fast-pr-gates.yml that intentionally
# do NOT live in the fast lane. Empty today; entries must come with
# a comment explaining why.
_KNOWN_NON_FAST_WF_REFS: frozenset[str] = frozenset()


def _workflow_raw_test_basenames() -> set[str]:
    """All ``tests/test_*.py`` basenames referenced in the workflow.

    Unlike :func:`_workflow_referenced_test_basenames`, this does NOT
    subtract :data:`_KNOWN_NON_FAST_WF_REFS`, so it is the ground truth
    used to validate the allowlist itself.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    return set(_WF_TEST_RE.findall(text))


def _workflow_referenced_test_basenames() -> set[str]:
    return _workflow_raw_test_basenames() - _KNOWN_NON_FAST_WF_REFS


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


def test_known_non_fast_allowlist_entries_are_referenced() -> None:
    """Every ``_KNOWN_NON_FAST_WF_REFS`` entry must exist in the workflow.

    The allowlist exists to subtract workflow refs that intentionally
    stay out of the fast lane. A dead entry (one no longer present in
    the workflow) is dangerous: it would silently subtract a basename
    that, if re-added to the workflow later, must instead be caught by
    ``test_fast_inventory_matches_workflow_file_list``. Keep the
    allowlist honest so it can never mask a genuinely missing inventory
    entry.
    """
    referenced = _workflow_raw_test_basenames()
    dead = _KNOWN_NON_FAST_WF_REFS - referenced
    assert not dead, (
        "_KNOWN_NON_FAST_WF_REFS entries no longer referenced in "
        f"smc-fast-pr-gates.yml: {sorted(dead)}. Remove them so the "
        "allowlist cannot mask a missing FAST_TEST_FILES entry (ADR-0012)."
    )


def test_known_non_fast_allowlist_disjoint_from_fast_inventory() -> None:
    """An allowlisted non-fast ref must not also claim fast membership.

    Being in both ``_KNOWN_NON_FAST_WF_REFS`` (intentionally NOT fast)
    and ``FAST_TEST_FILES`` (fast) is contradictory and would make the
    partition ambiguous.
    """
    contradictory = _KNOWN_NON_FAST_WF_REFS & FAST_TEST_FILES
    assert not contradictory, (
        "Basenames declared both non-fast (allowlist) and fast "
        f"(FAST_TEST_FILES): {sorted(contradictory)}. Pick one lane "
        "(ADR-0012)."
    )


def test_is_fast_agrees_with_inventory() -> None:
    """``is_fast`` — the API the conftest auto-marker relies on — must
    agree with the inventory data it is built from.

    Pins the public contract so a refactor of ``is_fast`` cannot quietly
    diverge from :data:`FAST_TEST_FILES` / :data:`FAST_TEST_GLOBS` and
    silently reshuffle the fast/slow partition at collection time.
    """
    not_fast = [name for name in FAST_TEST_FILES if not is_fast(name)]
    assert not not_fast, (
        f"is_fast() returned False for FAST_TEST_FILES entries: {sorted(not_fast)}."
    )

    tests_dir = REPO_ROOT / "tests"
    for pat in FAST_TEST_GLOBS:
        for match in tests_dir.glob(pat):
            assert is_fast(match.name), (
                f"is_fast() returned False for {match.name} matching glob {pat!r}."
            )

    # A basename matching neither the file set nor any glob must be slow.
    sentinel = "test_definitely_not_in_the_fast_lane_zzz.py"
    assert sentinel not in FAST_TEST_FILES
    assert not is_fast(sentinel), (
        f"is_fast() unexpectedly classified sentinel {sentinel!r} as fast."
    )

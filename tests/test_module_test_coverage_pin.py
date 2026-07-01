"""R9 (audit-L-1, 2026-05-12) — module-test coverage pin.

Background
==========
Several recent bugs (#2155 / #2163 / #2164) shipped because new modules
were added under ``open_prep/`` and ``newsstack_fmp/`` without an
accompanying ``tests/test_<module_name>*.py`` file. The bugs would have
been caught by even a trivial smoke test (``import``, call public
function with mock data).

This pin asserts that every non-trivial source module under
``open_prep/`` and ``newsstack_fmp/`` has at least one test file
referencing it. A "reference" is either:

  * A test file whose basename contains the module basename
    (``test_macro.py`` covers ``open_prep/macro.py``,
    ``test_macro_extended_coverage.py`` also counts).
  * A test file that contains an explicit ``import <full_module>`` or
    ``from <full_module>`` line.

A grandfather allowlist (``_GRANDFATHER_UNCOVERED``) lists the modules
that have no test today. The pin is **monotonic**: new uncovered
modules must either ship with a test or be added to the allowlist with
a written justification (``# audit-L-1 R9: <reason>``).

Trivial helpers (basename starting with ``_``) are auto-exempt because
they are tested transitively through their public callers.

See ``docs/AUDIT_L1_REVIEW_RETROSPECTIVE_2026-05-12.md`` \xa7R9.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TESTS_DIR = _REPO_ROOT / "tests"
_PACKAGE_PREFIXES = ("open_prep", "newsstack_fmp")

# Modules with no dedicated test today (grandfather). New entries must
# carry an inline ``# audit-L-1 R9: <reason>`` comment when added.
_GRANDFATHER_UNCOVERED: frozenset[str] = frozenset(
    {
        "config_validation",        # audit-L-1 R9: validator helpers exercised transitively via run_open_prep happy-path tests
        "dirty_flag_manager",       # audit-L-1 R9: flag I/O exercised transitively via outcome_backfill tests
        "ingest_opra_options_flow", # audit-L-1 R9: requires Databento OPRA.PILLAR entitlement; mock-stub test deferred to follow-up
        "log_redaction",            # audit-L-1 R9: redaction patterns covered by tests/test_secret_leakage_probes.py via the central helper
        "streamlit_monitor",        # audit-L-1 R9: ~3000-line streamlit UI; integration coverage owned by manual smoke checklist + dashboard CI
    }
)


def _discover_source_modules() -> list[str]:
    """Return ``[module_basename, ...]`` for every non-trivial source module."""

    out: list[str] = []
    for prefix in _PACKAGE_PREFIXES:
        pkg_root = _REPO_ROOT / prefix
        if not pkg_root.is_dir():
            continue
        for py in sorted(pkg_root.rglob("*.py")):
            if "__pycache__" in py.parts:
                continue
            if py.name == "__init__.py":
                continue
            basename = py.stem
            if basename.startswith("_"):
                # Private helpers are tested transitively.
                continue
            out.append(basename)
    return out


def _discover_test_corpus() -> str:
    """Concatenate every ``tests/test_*.py`` for substring/import scan."""

    chunks: list[str] = []
    for tf in sorted(_TESTS_DIR.glob("test_*.py")):
        try:
            chunks.append(f"### FILE: {tf.name} ###\n")
            chunks.append(tf.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(chunks)


def _module_has_coverage(basename: str, test_files: list[Path], corpus: str) -> bool:
    """Return True iff ``basename`` has at least one referencing test."""

    # 1. Basename match in test filename.
    for tf in test_files:
        if basename in tf.stem:
            return True
    # 2. Explicit import/reference in any test body.
    for prefix in _PACKAGE_PREFIXES:
        if (
            f"import {prefix}.{basename}" in corpus
            or f"from {prefix}.{basename}" in corpus
        ):
            return True
    return False


def _compute_uncovered() -> list[str]:
    test_files = sorted(_TESTS_DIR.glob("test_*.py"))
    corpus = _discover_test_corpus()
    uncovered: list[str] = []
    for basename in _discover_source_modules():
        if not _module_has_coverage(basename, test_files, corpus):
            uncovered.append(basename)
    return sorted(uncovered)


def test_r9_no_new_uncovered_source_modules() -> None:
    """No new uncovered source modules may appear under ``open_prep/`` or
    ``newsstack_fmp/`` without a test. Existing uncovered modules are
    listed in ``_GRANDFATHER_UNCOVERED``; once a module has been covered
    by a real test, it MUST be removed from the allowlist (the test
    enforces that too)."""

    uncovered = set(_compute_uncovered())

    # New uncovered modules \u2014 must be allowlisted explicitly with a reason.
    new_uncovered = uncovered - _GRANDFATHER_UNCOVERED
    if new_uncovered:
        formatted = "\n  - ".join(sorted(new_uncovered))
        raise AssertionError(
            "New source modules under open_prep/ or newsstack_fmp/ have no "
            "test_<module>*.py and no test that imports them. Add a smoke "
            "test in tests/, or (only as last resort) add the basename to "
            "_GRANDFATHER_UNCOVERED in tests/test_module_test_coverage_pin.py "
            "with an inline `# audit-L-1 R9: <reason>` comment:\n  - "
            + formatted
        )

    # Stale allowlist entries \u2014 modules that DO have a test now must not
    # remain in the grandfather list. Keep the allowlist minimal.
    stale = _GRANDFATHER_UNCOVERED - uncovered
    if stale:
        formatted = "\n  - ".join(sorted(stale))
        raise AssertionError(
            "Modules in _GRANDFATHER_UNCOVERED now have test coverage; "
            "remove them from the allowlist:\n  - " + formatted
        )


@pytest.mark.parametrize("uncovered_basename", sorted(_GRANDFATHER_UNCOVERED))
def test_r9_grandfather_entry_still_uncovered(uncovered_basename: str) -> None:
    """Each grandfather entry must still genuinely lack coverage, else
    the pin's allowlist drifts. This is enforced by the main test too,
    but parametrising here gives a per-entry failure for readability."""

    test_files = sorted(_TESTS_DIR.glob("test_*.py"))
    corpus = _discover_test_corpus()
    if _module_has_coverage(uncovered_basename, test_files, corpus):
        raise AssertionError(
            f"Module {uncovered_basename!r} is in _GRANDFATHER_UNCOVERED but "
            f"now has test coverage \u2014 remove it from the allowlist."
        )

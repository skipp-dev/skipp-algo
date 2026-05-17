"""Convergence-pin tests for the F2 helper module set.

Pins the cross-cutting invariants that keep the 8 F2 scripts a coherent
toolset rather than a pile of independently-drifting helpers:

  * All 8 helpers expose a ``main(argv)`` callable.
  * Their CLIs all accept ``--help`` and exit 0.
  * Journal/archive default paths agree across helpers (revert + promote
    write under the same ``artifacts/ci/f2/`` tree, share the same
    archive subdir).
  * Schema versions are positive integers (no accidental ``None``).

These are cheap, run-on-every-test invariants — they cost <100 ms but
catch a whole class of refactor regressions.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

F2_HELPERS = [
    "scripts.f2_run_promotion_gate",
    "scripts.f2_append_rollback_history",
    "scripts.f2_rotate_rollback_history",
    "scripts.f2_render_rollback_issue",
    "scripts.f2_revert_contextual_weights",
    "scripts.f2_promote_contextual_weights",
    "scripts.f2_summarize_history",
    "scripts.f2_inspect_status",
    "scripts.f2_weekly_digest",
    "scripts.f2_simulate_chain",
    "scripts.f2_cleanup_archives",
    "scripts.f2_runbook",
]


@pytest.mark.parametrize("module_name", F2_HELPERS)
def test_helper_exposes_main(module_name: str) -> None:
    mod = importlib.import_module(module_name)
    assert callable(getattr(mod, "main", None)), \
        f"{module_name} is missing a callable main()"


@pytest.mark.parametrize("module_name", F2_HELPERS)
def test_helper_help_exits_zero(module_name: str) -> None:
    """``python -m <module> --help`` must exit 0 with usage text on stdout."""
    result = subprocess.run(
        [sys.executable, "-m", module_name, "--help"],
        capture_output=True, text=True, timeout=15,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert result.returncode == 0, (
        f"{module_name} --help exited {result.returncode}: "
        f"stderr={result.stderr!r}"
    )
    assert "usage:" in result.stdout.lower()


def test_revert_and_promote_share_archive_subdir() -> None:
    """Both helpers archive into the same on-disk dir so a single
    ``contextual_calibration.archive/**`` glob covers both."""
    revert = importlib.import_module("scripts.f2_revert_contextual_weights")
    promote = importlib.import_module("scripts.f2_promote_contextual_weights")
    assert revert.ARCHIVE_SUBDIR_DEFAULT == promote.ARCHIVE_SUBDIR_DEFAULT
    assert revert.ARCHIVE_SUBDIR_DEFAULT == "contextual_calibration.archive"


def test_journals_live_under_artifacts_ci_f2() -> None:
    """Both helpers write their journals under the CI-uploaded dir."""
    revert = importlib.import_module("scripts.f2_revert_contextual_weights")
    promote = importlib.import_module("scripts.f2_promote_contextual_weights")
    # ``as_posix`` keeps the assertion stable on Windows where ``str(Path)`` uses ``\``.
    assert revert.JOURNAL_DEFAULT.as_posix().startswith("artifacts/ci/f2/")
    assert promote.JOURNAL_DEFAULT.as_posix().startswith("artifacts/ci/f2/")
    # Distinct files (don't accidentally clobber each other).
    assert revert.JOURNAL_DEFAULT != promote.JOURNAL_DEFAULT


def test_summarize_and_inspect_schema_versions_are_positive() -> None:
    summarize = importlib.import_module("scripts.f2_summarize_history")
    inspect = importlib.import_module("scripts.f2_inspect_status")
    assert isinstance(summarize.SUMMARY_SCHEMA_VERSION, int)
    assert summarize.SUMMARY_SCHEMA_VERSION >= 1
    assert isinstance(inspect.STATUS_SCHEMA_VERSION, int)
    assert inspect.STATUS_SCHEMA_VERSION >= 1


def test_render_rollback_issue_label_is_pinned() -> None:
    """The label is referenced verbatim in the daily workflow YAML
    (``--label f2-rollback`` and ``gh issue list --label f2-rollback``).
    Renaming it must be a deliberate two-place edit — pin it here."""
    render = importlib.import_module("scripts.f2_render_rollback_issue")
    assert render.ISSUE_LABEL == "f2-rollback"

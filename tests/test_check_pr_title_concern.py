"""Tests for ``scripts/check_pr_title_concern.py`` (ADR-0013 enforcement).

Also references the companion workflow basename ``pr-title-concern-lint``
so the workflow is not flagged by ``test_workflow_orphan_inventory``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_pr_title_concern.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "pr-title-concern-lint.yml"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_pr_title_concern", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_pr_title_concern"] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module()


VALID_TITLES = [
    "feat(test): ADR-0010 generic cron-invariants suite",
    "fix(credential-health): atomic-write exempt marker",
    "ci(actions): bump upload-artifact to v7 across all workflows",
    "test(workflows): pin live-window marker",
    "refactor(ledger): move allowlist to TOML",
    "chore(deps): bump pyyaml",
    "feat(api)!: drop legacy v1 endpoint",
    'Revert "feat(test): ADR-0010 generic cron-invariants suite"',
]

INVALID_TITLES = [
    "",
    "   ",
    "add a new feature",  # no concern prefix
    "feat: missing scope",  # scope required
    "Feature(test): capitalised concern",  # concern must be lowercase
    "bump(deps): unknown concern type",  # 'bump' not accepted
    "feat(): empty scope",
    "feat(test):",  # empty subject
    "feat(test): ",  # whitespace-only subject
]


@pytest.mark.parametrize("title", VALID_TITLES)
def test_valid_titles_pass(title: str) -> None:
    assert mod.validate_pr_title(title) == [], title


@pytest.mark.parametrize("title", INVALID_TITLES)
def test_invalid_titles_fail(title: str) -> None:
    assert mod.validate_pr_title(title) != [], title


def test_missing_scope_gives_actionable_hint() -> None:
    reasons = mod.validate_pr_title("feat: no scope here")
    assert any("scope is required" in r.lower() for r in reasons)


def test_unknown_concern_lists_accepted_types() -> None:
    reasons = mod.validate_pr_title("bump(deps): x")
    assert any("feat" in r and "fix" in r for r in reasons)


def test_main_reads_pr_title_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PR_TITLE", "feat(test): valid title")
    assert mod.main([]) == 0


def test_main_rejects_bad_title_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PR_TITLE", "not a valid title")
    assert mod.main([]) == 1


def test_main_no_title_returns_2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PR_TITLE", raising=False)
    assert mod.main([]) == 2


def test_env_takes_precedence_over_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PR_TITLE", "feat(test): from env")
    # argv title is invalid, but env (valid) wins → exit 0
    assert mod.main(["garbage title"]) == 0


def test_accepted_concerns_are_lowercase() -> None:
    assert all(c.islower() for c in mod.ACCEPTED_CONCERNS)


def test_companion_workflow_exists() -> None:
    """ADR-0013 enforcement is only real if the workflow ships with it."""
    assert WORKFLOW_PATH.is_file(), (
        "pr-title-concern-lint.yml workflow must exist to enforce ADR-0013 in CI."
    )

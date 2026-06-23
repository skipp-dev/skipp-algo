"""Regression tests for validation fixes in publish_signals_snapshot.

These test the corrected _is_valid_owner_repo and _is_valid_branch functions
which now properly reject invalid GitHub owner/repo names and git ref names.
"""

from __future__ import annotations

import pytest

from scripts import publish_signals_snapshot as mod


# ---------------------------------------------------------------------------
# _is_valid_owner_repo: must reject invalid GitHub usernames
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "repo",
    [
        # GitHub usernames may not end with a hyphen.
        "skippALGO-/skipp-algo",
        # GitHub usernames may not contain consecutive hyphens.
        "skipp--ALGO/skipp-algo",
        # GitHub usernames may not start with a hyphen.
        "-skippALGO/skipp-algo",
        # GitHub usernames may not contain an underscore.
        "skipp_ALGO/skipp-algo",
        # Empty owner or name component.
        "/skipp-algo",
        "skippALGO/",
    ],
)
def test_is_valid_owner_repo_rejects_invalid_github_names(repo: str) -> None:
    assert mod._is_valid_owner_repo(repo) is False


@pytest.mark.parametrize(
    "repo",
    [
        "skippALGO/skipp-algo-",  # repo names may end with a hyphen
        "skippALGO/skipp--algo",  # repo names may contain consecutive hyphens
        "skippALGO/skipp.algo",  # repo names may contain dots
        "skippALGO/skipp_algo",  # repo names may contain underscores
    ],
)
def test_is_valid_owner_repo_accepts_valid_repo_name_edge_cases(repo: str) -> None:
    """These should remain accepted."""
    assert mod._is_valid_owner_repo(repo) is True


# ---------------------------------------------------------------------------
# _is_valid_branch: must reject invalid git ref names
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "branch",
    [
        # A ref component must not start with a dot.
        ".hidden",
        "bot/.hidden",
        # A ref component must not be empty (consecutive or leading slash).
        "bot//branch",
        "/leading-slash",
        "trailing-slash/",
        # @{ sequence is forbidden in refs.
        "@",
        "foo@{bar",
        # ASCII control characters are forbidden.
        "foo\x00bar",
        "foo\x7fbar",
        "foo\x01bar",
    ],
)
def test_is_valid_branch_rejects_invalid_ref_names(branch: str) -> None:
    assert mod._is_valid_branch(branch) is False

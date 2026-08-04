"""Tests for scripts/check_commit_authors.py (audit P2 MED author enforcement)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "check_commit_authors.py"

_spec = importlib.util.spec_from_file_location("check_commit_authors", _SCRIPT)
assert _spec and _spec.loader
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def test_approved_identities_pass() -> None:
    rows = [
        ("a" * 40, "221361569+skipp-dev@users.noreply.github.com", "221361569+skipp-dev@users.noreply.github.com"),
        ("b" * 40, "github-actions[bot]@users.noreply.github.com", "github-actions[bot]@users.noreply.github.com"),
    ]
    assert mod._offenders(rows) == []


def test_dependabot_grouped_update_passes() -> None:
    # Measured on PR #4424 (2026-08-04): author is dependabot's numbered
    # no-reply, committer is GitHub's web-flow identity. All four grouped
    # update PRs (#4424-#4427) failed "Enforce approved commit authors" on
    # exactly this pair, so the Dependabot pipeline built in #4407/#4421 was
    # dead on arrival: no update PR could ever go green, regardless of content.
    rows = [
        ("d" * 40, "49699333+dependabot[bot]@users.noreply.github.com", "noreply@github.com"),
    ]
    assert mod._offenders(rows) == []


def test_an_unapproved_bot_is_still_flagged() -> None:
    # Negative control for the dependabot approval above: bot-ness alone must
    # not pass the gate — only the named identity does.
    rows = [
        ("e" * 40, "29139614+renovate[bot]@users.noreply.github.com", "noreply@github.com"),
    ]
    offenders = mod._offenders(rows)
    assert len(offenders) == 1
    assert "renovate" in offenders[0]


def test_corporate_author_is_flagged() -> None:
    rows = [
        ("c" * 40, "227788186+spreuss_cisco@users.noreply.github.com", "221361569+skipp-dev@users.noreply.github.com"),
    ]
    offenders = mod._offenders(rows)
    assert len(offenders) == 1
    assert "author=227788186+spreuss_cisco@users.noreply.github.com" in offenders[0]


def test_corporate_committer_is_flagged() -> None:
    rows = [
        ("d" * 40, "221361569+skipp-dev@users.noreply.github.com", "someone@corp.example"),
    ]
    offenders = mod._offenders(rows)
    assert len(offenders) == 1
    assert "committer=someone@corp.example" in offenders[0]


def test_github_squash_merge_committer_is_allowed() -> None:
    # A stacked PR squash-merged through the web UI: single parent, so
    # --no-merges does not exempt it, but the author is still the maintainer.
    rows = [
        ("f" * 40, "221361569+skipp-dev@users.noreply.github.com", "noreply@github.com"),
    ]
    assert mod._offenders(rows) == []


def test_github_identity_as_author_is_still_flagged() -> None:
    # Committer-only approval must not leak into the author check.
    rows = [
        ("0" * 40, "noreply@github.com", "221361569+skipp-dev@users.noreply.github.com"),
    ]
    offenders = mod._offenders(rows)
    assert len(offenders) == 1
    assert "author=noreply@github.com" in offenders[0]


def test_case_insensitive_match() -> None:
    rows = [
        ("e" * 40, "Preuss.Steffen@Yahoo.com", "PREUSS.STEFFEN@YAHOO.COM"),
    ]
    # _commit_identities lowercases; simulate that here.
    rows = [(s, a.lower(), c.lower()) for s, a, c in rows]
    assert mod._offenders(rows) == []


def test_check_config_rejects_non_approved(monkeypatch) -> None:
    monkeypatch.setattr(mod, "_run", lambda args: "someone@corp.example\n")
    assert mod._check_config() == 1


def test_check_config_accepts_approved(monkeypatch) -> None:
    monkeypatch.setattr(
        mod, "_run", lambda args: "221361569+skipp-dev@users.noreply.github.com\n"
    )
    assert mod._check_config() == 0

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

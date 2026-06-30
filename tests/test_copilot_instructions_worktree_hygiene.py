"""Pins for stale worktree hygiene in repository instructions."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTRUCTIONS = ROOT / ".github" / "copilot-instructions.md"


def _text() -> str:
    return INSTRUCTIONS.read_text(encoding="utf-8")


def test_stale_audit_and_fix_worktree_hygiene_is_documented() -> None:
    text = _text()
    assert "Worktree-Hygiene" in text
    assert "Alte lokale `audit/*`- und `fix/*`-Worktrees" in text
    assert "`git worktree list`, offener PR-Status und" in text
    assert "`origin/main`-Vergleich" in text
    assert "Stale Worktree-Regel" in text
    assert "kein offener PR existiert" in text
    assert "nach User-Freigabe Worktree +" in text
    assert "lokalen Branch löschen" in text

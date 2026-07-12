"""Pins for stale worktree hygiene in repository instructions."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTRUCTIONS = ROOT / ".github" / "copilot-instructions.md"


def _text() -> str:
    return INSTRUCTIONS.read_text(encoding="utf-8")


def _one_line() -> str:
    return " ".join(_text().split())


def _worktree_hygiene_blocks() -> list[str]:
    lines = _text().splitlines()
    blocks: list[str] = []
    for index, line in enumerate(lines):
        if not line.startswith("- Worktree-Hygiene:"):
            continue
        block_lines = [line]
        for next_line in lines[index + 1:]:
            if next_line.startswith("- Env-Vars"):
                break
            block_lines.append(next_line)
        blocks.append("\n".join(block_lines))
    return blocks


def test_stale_audit_and_fix_worktree_hygiene_is_documented() -> None:
    text = _one_line()
    assert "Worktree-Hygiene" in text
    assert "Alte lokale `audit/*`- und `fix/*`-Worktrees" in text
    assert "`git worktree list`, offener PR-Status und" in text
    assert "`origin/main`-Vergleich" in text
    assert "Stale Worktree-Regel" in text
    assert "lokaler Worktree/Branch keinen offenen PR hat" in text
    assert "diesen Worktree-Inhalt nicht mergen" in text
    assert "nach User-Freigabe Worktree +" in text
    assert "lokalen Branch löschen" in text


def test_duplicated_worktree_hygiene_blocks_do_not_drift() -> None:
    # #3371 ("de-duplicate copilot-instructions.md") intentionally collapsed the
    # Worktree-Hygiene rule to a single canonical block (e5a11ce3a had added it
    # twice). Pin exactly one block so an accidental re-duplication (which could
    # drift out of sync) is caught; the block's content is pinned by
    # test_stale_audit_and_fix_worktree_hygiene_is_documented.
    blocks = _worktree_hygiene_blocks()
    assert len(blocks) == 1

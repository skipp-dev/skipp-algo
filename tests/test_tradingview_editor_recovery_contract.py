from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TV_SHARED_PATH = ROOT / "automation/tradingview/lib/tv_shared.ts"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_ensure_pine_editor_keeps_internal_close_modal_recovery() -> None:
    source = _read(TV_SHARED_PATH)

    assert 'export async function ensurePineEditor(page: Page): Promise<void> {' in source
    assert 'tracePageEvent(page, "pine-editor-recovery-attempt", `close-modal:${attempt + 1}`);' in source
    assert 'await closeModal(page).catch(() => undefined);' in source
    assert 'tracePageEvent(page, "pine-editor-recovery-ok", `close-modal:${attempt + 1}`);' in source

    pattern = re.compile(
        r'export async function ensurePineEditor\(page: Page\): Promise<void> \{.*?'
        r'for \(let attempt = 0; attempt < 4; attempt \+= 1\) \{.*?'
        r'tracePageEvent\(page, "pine-editor-recovery-attempt", `close-modal:\$\{attempt \+ 1\}`\);.*?'
        r'await closeModal\(page\)\.catch\(\(\) => undefined\);.*?'
        r'tracePageEvent\(page, "pine-editor-recovery-ok", `close-modal:\$\{attempt \+ 1\}`\);',
        re.S,
    )
    assert pattern.search(source), 'ensurePineEditor must keep the closeModal recovery sequence inside the retry loop'

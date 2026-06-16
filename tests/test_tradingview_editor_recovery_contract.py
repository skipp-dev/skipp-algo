from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TV_SHARED_PATH = ROOT / "automation/tradingview/lib/tv_shared.ts"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_dismiss_cookie_banner_verifies_banner_gone_and_has_dom_dispatch_fallback() -> None:
    """dismissCookieBanner must verify the banner disappeared after each click and
    fall back to a DOM-level event dispatch if force:true 'succeeded' without
    triggering React's synthetic handler (observed 2026-06-16, run 27644780349:
    cookie-accept-click-error×6 + hover-click-error×6 → force-click 'ok' but
    banner still visible → pine-editor-open blocked)."""
    source = _read(TV_SHARED_PATH)

    assert "export async function dismissCookieBanner(page: Page): Promise<boolean> {" in source

    # Banner-visibility check after each click
    assert "hasVisibleLocator(tvSelectors.cookieAccept(page), 400)" in source
    assert 'tracePageEvent(page, "cookie-accept-banner-still-visible"' in source

    # DOM-dispatch fallback via page.evaluate
    assert "const domClicked = await page.evaluate((): boolean => {" in source
    assert 'tracePageEvent(page, "cookie-accept-dom-dispatch-ok"' in source
    assert 'tracePageEvent(page, "cookie-accept-dom-dispatch-no-target"' in source

    # Loop must be at least 5 attempts (banner-gone early-break is the happy path)
    pattern = re.compile(
        r"export async function dismissCookieBanner\(page: Page\): Promise<boolean> \{"
        r".*?for \(let attempt = 0; attempt < (?P<count>[5-9]|\d{2,}); attempt \+= 1\) \{",
        re.S,
    )
    m = pattern.search(source)
    assert m, "dismissCookieBanner retry loop must allow ≥5 attempts"
    assert int(m.group("count")) >= 5, f"expected ≥5 loop iterations, got {m.group('count')}"


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

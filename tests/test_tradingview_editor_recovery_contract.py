from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TV_SHARED_PATH = ROOT / "automation/tradingview/lib/tv_shared.ts"
RUNBOOK_PATH = ROOT / "docs/tradingview_operational_publish_runbook_2026-04-17.md"


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

    # Loop must be at least 5 attempts (early return true on success keeps happy-path cost zero)
    pattern = re.compile(
        r"export async function dismissCookieBanner\(page: Page\): Promise<boolean> \{"
        r".*?for \(let attempt = 0; attempt < (?P<count>[5-9]|\d{2,}); attempt \+= 1\) \{",
        re.S,
    )
    m = pattern.search(source)
    assert m, "dismissCookieBanner retry loop must allow ≥5 attempts"
    assert int(m.group("count")) >= 5, f"expected ≥5 loop iterations, got {m.group('count')}"

    # Terminal-verdict event + honest return false (observability-review 2026-06-17):
    # when all attempts are exhausted and the banner is still visible, a single
    # greppable marker must be emitted so a post-mortem reader does not have to
    # count per-attempt events, and the function must return false (not true).
    assert 'tracePageEvent(page, "cookie-accept-exhausted-still-visible"' in source
    assert "return false;" in source  # at least one explicit false return path


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


def test_set_editor_content_prepare_timeout_respects_ci_step_budget() -> None:
    source = _read(TV_SHARED_PATH)

    assert "Timeout contract: CI sets TV_STEP_TIMEOUT_MS" in source
    assert "values are operator overrides and intentionally win over the fallback" in source
    assert 'numEnv("TV_SET_EDITOR_CONTENT_TIMEOUT_MS", Math.max(stepTimeoutMs(), 90_000))' in source
    assert 'numEnv("TV_EDITOR_PREPARE_TIMEOUT_MS", Math.max(stepTimeoutMs(), 45_000))' in source
    assert '}, editorPrepareTimeoutMs);' in source
    assert '}, editorContentTimeoutMs);' in source


def test_tradingview_timeout_budget_contract_is_documented() -> None:
    runbook = _read(RUNBOOK_PATH)

    assert "CI Timeout Budget Contract" in runbook
    assert "`TV_STEP_TIMEOUT_MS`" in runbook
    assert "`TV_SET_EDITOR_CONTENT_TIMEOUT_MS`" in runbook
    assert "`TV_EDITOR_PREPARE_TIMEOUT_MS`" in runbook
    assert "defaults to `Math.max(TV_STEP_TIMEOUT_MS, 90000)`" in runbook
    assert "defaults to `Math.max(TV_STEP_TIMEOUT_MS, 45000)`" in runbook
    assert "Explicit editor-specific env vars" in runbook
    assert "intentionally win over those defaults" in runbook


def test_visible_legend_text_settings_fallback_has_distinct_exhaustion_events() -> None:
    source = _read(TV_SHARED_PATH)

    assert 'const VISIBLE_LEGEND_TEXT_SETTINGS_BUDGET_MS = 8_000;' in source
    assert 'const MAX_VISIBLE_LEGEND_TEXT_TARGETS = 3;' in source
    assert 'tracePageEvent(page, "script-settings-legend-text-budget-exhausted"' in source
    assert 'tracePageEvent(page, "script-settings-legend-text-target-cap-exhausted"' in source
    assert re.search(
        r"if \(attemptedTargets >= MAX_VISIBLE_LEGEND_TEXT_TARGETS\) \{\s*"
        r'tracePageEvent\(page, "script-settings-legend-text-target-cap-exhausted"',
        source,
        re.S,
    )
    assert re.search(
        r"if \(Date\.now\(\) - startedAt > VISIBLE_LEGEND_TEXT_SETTINGS_BUDGET_MS\) \{\s*"
        r'tracePageEvent\(page, "script-settings-legend-text-budget-exhausted"',
        source,
        re.S,
    )

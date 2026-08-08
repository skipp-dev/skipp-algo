import assert from "node:assert/strict";
import test from "node:test";

import {
  assertNoVisibleChartScriptError,
  launchTradingViewChromium,
  probeRuntimeSmoke,
} from "../lib/tv_shared.js";

// The chart-side error channel exists for ONE reason: a Pine compile error that
// lives only in the legend badge's `title`/`aria-label` and never in the page
// body text (the CE10271 class). The body-text channel cannot see those, which
// is why `getVisibleChartScriptError` walks the legend row instead.
//
// Before PR #4357 it resolved to `string | null` — with no third state for
// "I could not look".
// `findLegendRowWrappers` returns `[]` on three pure non-observation paths
// (`buttons.count().catch(() => 0)`, the single hardcoded
// `data-qa-id="legend-settings-action"` anchor not matching, and a 300 ms
// `innerText` timeout per ancestor depth), and an empty list makes the `for`
// loop body never run, so the function returned `null` = "clean".
//
// PR #4357 added the explicit unreadable sentinel and fail-closed gate. The
// tests below preserve that tri-state while allowing bounded, observable
// text-first recovery from hover-only and more-action-only legend rows.

test("a missing legend anchor must not read as a clean compile", async () => {
  const browser = await launchTradingViewChromium({ headless: true });
  try {
    const page = await browser.newPage();
    // A chart carrying a REAL compile error, rendered the way TradingView does
    // it — the error text lives only in the title attribute. The legend action
    // button is absent, which is what happens when TradingView renames the
    // qa-id (it has done so before) or when the row has not painted yet.
    await page.setContent(`
      <div class="chart-container">
        <div class="legend-row">
          <span>SMC Live Overlay v2</span>
          <span title="Compilation error: CE10271">!</span>
        </div>
      </div>
    `);

    const smoke = await probeRuntimeSmoke(page, "SMC Live Overlay");

    // Before the fix: compileError === null and, with the name visible on the
    // page, ok === true — a broken chart certified as clean.
    assert.notEqual(
      smoke.compileError,
      null,
      "an unobservable chart error channel must report a probe failure, not a clean compile",
    );
    assert.equal(smoke.ok, false);
  } finally {
    await browser.close();
  }
});

test("an observed, genuinely clean legend row still passes", async () => {
  // The counterpart that keeps the fix from degenerating into "always red":
  // when the anchor IS present and carries no error marker, the probe must
  // still report clean.
  const browser = await launchTradingViewChromium({ headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent(`
      <div class="chart-container">
        <div class="legend-row">
          <span>SMC Live Overlay v2</span>
          <button data-qa-id="legend-settings-action">Settings</button>
        </div>
      </div>
    `);

    const smoke = await probeRuntimeSmoke(page, "SMC Live Overlay");

    assert.equal(smoke.compileError, null);
    assert.equal(smoke.ok, true);
  } finally {
    await browser.close();
  }
});

// ── assertNoVisibleChartScriptError — the publish-time gate ─────────────────
// This is the hard gate `scripts/tv_publish_openprep_panel.ts` calls right
// before publishing. Until this fix it was built on
// `getVisibleChartScriptError`, whose own docstring says not to use it for
// gating: that view maps "could not look" to `null`, so an unreadable legend
// (button renamed, row not yet painted, etc.) certified a clean compile. The
// tests below pin the tri-state and its bounded recovery at the caller that
// actually gates a publish on it.

test("assertNoVisibleChartScriptError rejects when the legend cannot be read", async () => {
  // Same DOM shape as the probe-level test above (no
  // data-qa-id="legend-settings-action" anchor), but exercised through the
  // assert wrapper itself: a surface the probe could not look at must not be
  // certified clean.
  const browser = await launchTradingViewChromium({ headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent(`
      <div class="chart-container">
        <div class="legend-row">
          <span>SMC Live Overlay v2</span>
        </div>
      </div>
    `);

    await assert.rejects(
      () => assertNoVisibleChartScriptError(page, "SMC Live Overlay"),
      /unreadable/i,
    );
  } finally {
    await browser.close();
  }
});

test("assertNoVisibleChartScriptError rejects and names the error when the legend shows a compile error", async () => {
  const browser = await launchTradingViewChromium({ headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent(`
      <div class="chart-container">
        <div class="legend-row">
          <span>SMC Live Overlay v2</span>
          <span title="Compilation error: CE10271">!</span>
          <button data-qa-id="legend-settings-action">Settings</button>
        </div>
      </div>
    `);

    await assert.rejects(
      () => assertNoVisibleChartScriptError(page, "SMC Live Overlay"),
      /CE10271/,
    );
  } finally {
    await browser.close();
  }
});

test("assertNoVisibleChartScriptError resolves on a readable, error-free legend", async () => {
  const browser = await launchTradingViewChromium({ headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent(`
      <div class="chart-container">
        <div class="legend-row">
          <span>SMC Live Overlay v2</span>
          <button data-qa-id="legend-settings-action">Settings</button>
        </div>
      </div>
    `);

    await assert.doesNotReject(() =>
      assertNoVisibleChartScriptError(page, "SMC Live Overlay"),
    );
  } finally {
    await browser.close();
  }
});

test("assertNoVisibleChartScriptError observes a settings action rendered only after hover", async () => {
  const browser = await launchTradingViewChromium({ headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent(`
      <style>.legend-row button { display: none } .legend-row:hover button { display: block }</style>
      <div class="chart-container">
        <div class="legend-row">
          <span>SMC Live Overlay v2</span>
          <button data-qa-id="legend-settings-action">Settings</button>
        </div>
      </div>
    `);

    await assert.doesNotReject(() =>
      assertNoVisibleChartScriptError(page, "SMC Live Overlay"),
    );
  } finally {
    await browser.close();
  }
});

test("assertNoVisibleChartScriptError accepts a tight more-action-only legend row", async () => {
  const browser = await launchTradingViewChromium({ headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent(`
      <div class="chart-container">
        <div class="legend-row">
          <span>SMC Live Overlay v2</span>
          <button data-qa-id="legend-more-action">More</button>
        </div>
      </div>
    `);

    await assert.doesNotReject(() =>
      assertNoVisibleChartScriptError(page, "SMC Live Overlay"),
    );
  } finally {
    await browser.close();
  }
});

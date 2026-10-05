import assert from "node:assert/strict";
import test from "node:test";

import {
  assertNoVisibleChartScriptError,
  dismissPromotionOverlay,
  ensureCleanChartScriptForPublish,
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

test("publish preparation materializes an absent script before checking its legend", async () => {
  const browser = await launchTradingViewChromium({ headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent(`
      <div class="chart-container" id="chart"></div>
      <button id="add" onclick="
        const row = document.createElement('div');
        row.className = 'legend-row';
        row.innerHTML = '<span>Open-Prep Daily Panel</span><button data-qa-id=&quot;legend-settings-action&quot;>Settings</button>';
        document.getElementById('chart').appendChild(row);
        this.remove();
      ">Add to chart</button>
    `);

    await assert.doesNotReject(() =>
      ensureCleanChartScriptForPublish(page, "Open-Prep Daily Panel"),
    );
    assert.equal(await page.locator(".legend-row").count(), 1);
    assert.equal(await page.getByRole("button", { name: /add to chart/i }).count(), 0);
  } finally {
    await browser.close();
  }
});

test("publish preparation still rejects a chart error after materialization", async () => {
  const browser = await launchTradingViewChromium({ headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent(`
      <div class="chart-container" id="chart"></div>
      <button onclick="
        const row = document.createElement('div');
        row.className = 'legend-row';
        row.innerHTML = '<span>Open-Prep Daily Panel</span><span title=&quot;Compilation error: CE10271&quot;>!</span><button data-qa-id=&quot;legend-settings-action&quot;>Settings</button>';
        document.getElementById('chart').appendChild(row);
        this.remove();
      ">Add to chart</button>
    `);

    await assert.rejects(
      () => ensureCleanChartScriptForPublish(page, "Open-Prep Daily Panel"),
      /CE10271/,
    );
  } finally {
    await browser.close();
  }
});

// ---------------------------------------------------------------------------
// 2026-10-01, repair-only run 36859274386: a full-size TradingView promotion
// ("Don't miss this Autumn sale — Up to 80% off — Offer ends in …") sat on the
// chart and intercepted every click on five of seven settings dialogs
// (Playwright: "<div class=modalContent-…> from <div data-id=…> subtree
// intercepts pointer events"). bindingsRepaired: 0. The markup below mirrors
// what the failure evidence recorded: an overlap-manager entry whose text
// starts with "Close".
// ---------------------------------------------------------------------------

const PROMOTION_HTML = `
  <div id="overlap-manager-root">
    <div data-id="promo-1">
      <div class="modalContentWrapper-s5nsR9oq"><div class="modalContent-s5nsR9oq">
        <button id="promo-close"><span>Close</span></button>
        <h2>Don’t miss this Autumn sale</h2>
        <p>Up to 80% off</p>
        <p>Offer ends in</p>
        <button id="promo-cta">Explore offers</button>
      </div></div>
    </div>
    <div data-id="settings-1">
      <div role="dialog"><h2>SMC Setup Check</h2><button>Inputs</button><button>Style</button></div>
    </div>
  </div>`;

test("a promotion overlay is closed through its own close button, and nothing else is touched", async () => {
  const browser = await launchTradingViewChromium({ headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent(`${PROMOTION_HTML}
      <script>
        window.ctaClicks = 0;
        document.getElementById("promo-cta").addEventListener("click", () => { window.ctaClicks += 1; });
        document.getElementById("promo-close").addEventListener("click", () => {
          document.querySelector('[data-id="promo-1"]').remove();
        });
      </script>`);

    assert.equal(await dismissPromotionOverlay(page), true);

    assert.equal(await page.locator('[data-id="promo-1"]').count(), 0);
    assert.equal(await page.locator('[data-id="settings-1"]').count(), 1, "the settings dialog must survive");
    assert.equal(await page.evaluate("window.ctaClicks"), 0, "the offer button must never be clicked");
  } finally {
    await browser.close();
  }
});

test("without a promotion nothing is clicked and nothing is reported", async () => {
  const browser = await launchTradingViewChromium({ headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent(`
      <div id="overlap-manager-root">
        <div data-id="settings-1">
          <div role="dialog"><h2>SMC Setup Check</h2><button id="close">Close</button><button>Inputs</button></div>
        </div>
      </div>
      <script>
        window.closeClicks = 0;
        document.getElementById("close").addEventListener("click", () => { window.closeClicks += 1; });
      </script>`);

    assert.equal(await dismissPromotionOverlay(page), false);

    assert.equal(await page.evaluate("window.closeClicks"), 0, "a settings dialog's own Close is not a promotion");
    assert.equal(await page.locator('[data-id="settings-1"]').count(), 1);
  } finally {
    await browser.close();
  }
});

test("a promotion that will not close is reported as still present, not as dismissed", async () => {
  const browser = await launchTradingViewChromium({ headless: true });
  try {
    const page = await browser.newPage();
    // Close button present but inert, Escape ignored.
    await page.setContent(PROMOTION_HTML);

    assert.equal(await dismissPromotionOverlay(page), false);

    assert.equal(await page.locator('[data-id="promo-1"]').count(), 1);
  } finally {
    await browser.close();
  }
});

import assert from "node:assert/strict";
import test from "node:test";

import {
  closePineEditorIfVisible,
  launchTradingViewChromium,
} from "../lib/tv_shared.js";

// 2026-07-22: `closePineEditorIfVisible` returned void and swallowed every
// outcome, so a run where it did nothing was indistinguishable from one where
// it worked — the trace said `pine-editor-close-still-visible` and nothing acted
// on it. Live probing of the real chart established that TradingView's current
// Pine editor offers NO close affordance at all: the panel (`#pine-editor-dialog`,
// right-docked, 878x950) carries only Add-to-chart / Save / Publish / More,
// Escape does not dismiss it, the `[data-name="pine-dialog-button"]` toolbar
// toggle keeps `isActive` even on a direct DOM `.click()`, and the More menu has
// no close item. The function therefore has to be able to report failure.

test("reports success when no Pine editor is open", async () => {
  const browser = await launchTradingViewChromium({ headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent("<div id=\"chart\">no editor here</div>");
    assert.equal(await closePineEditorIfVisible(page), true);
  } finally {
    await browser.close();
  }
});

test("closes the editor when TradingView offers a close control", async () => {
  const browser = await launchTradingViewChromium({ headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent(`
      <div id="pine-editor-dialog">
        <button type="button" aria-label="Close" id="x">Close</button>
      </div>
      <script>
        document.getElementById("x").addEventListener("click", () => {
          document.getElementById("pine-editor-dialog").style.display = "none";
        });
      </script>
    `);
    assert.equal(await closePineEditorIfVisible(page), true);
    assert.equal(await page.locator("#pine-editor-dialog").isVisible(), false);
  } finally {
    await browser.close();
  }
});

test("reports failure instead of pretending when the panel has no close control", async () => {
  const browser = await launchTradingViewChromium({ headless: true });
  try {
    const page = await browser.newPage();
    // The shape TradingView actually serves: a visible panel whose only controls
    // are the editor toolbar. Nothing here can close it, and the caller must be
    // able to see that rather than read a swallowed void.
    await page.setContent(`
      <div id="pine-editor-dialog">
        <div><span>Untitled script</span>
          <button type="button" title="Add to chart">Add to chart</button>
          <button type="button" title="Save script">Save</button>
          <button type="button" title="Share your script with community">Publish script</button>
          <button type="button" title="More"></button>
        </div>
      </div>
    `);
    assert.equal(await closePineEditorIfVisible(page), false);
    assert.equal(await page.locator("#pine-editor-dialog").isVisible(), true);
  } finally {
    await browser.close();
  }
});

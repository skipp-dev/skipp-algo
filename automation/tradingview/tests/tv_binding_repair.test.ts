import assert from "node:assert/strict";
import test from "node:test";

import { canonicalSourceSelection, repairSelectedSource } from "../../../scripts/tv_verify_consumer_bindings.js";
import { launchTradingViewChromium } from "../lib/tv_shared.js";

test("binding repair scrolls a virtualized combobox before opening its options", async () => {
  const calls: string[] = [];
  const combo: any = {
    count: async () => 1,
    first: () => combo,
    isVisible: async () => true,
    scrollIntoViewIfNeeded: async () => { calls.push("scroll"); },
    click: async () => {
      assert.deepEqual(calls, ["scroll", "settle"]);
      calls.push("combo-click");
    },
  };
  const option: any = {
    first: () => option,
    count: async () => 1,
    waitFor: async () => {
      assert.equal(calls.at(-1), "combo-click");
      calls.push("option-visible");
    },
    click: async () => { calls.push("option-click"); },
  };
  const fallback: any = { last: () => fallback };
  const labels: any = {
    count: async () => 1,
    locator: () => ({ nth: () => combo }),
  };
  const page: any = {
    getByText: (value: string) => value === "BUS Ready" ? labels : fallback,
    getByRole: () => option,
    waitForTimeout: async () => { calls.push("settle"); },
  };

  await repairSelectedSource(page, "BUS Ready", "SMC Long-Dip Suite: BUS Ready");

  assert.deepEqual(calls, ["scroll", "settle", "combo-click", "option-visible", "option-click"]);
});

// ---------------------------------------------------------------------------
// 2026-10-01, repair-only run 36859274386 on vWgAWyfC. The source dropdown
// offered the producer's plots as
//     "SMC Long-Dip Suite · 411.0: BUS SchemaVersion"
// — TradingView puts the producer's status-line argument between the script
// name and the plot name. Ten days earlier (run 35590264660) the same dropdown
// read "SMC Long-Dip Suite: BUS SchemaVersion", and the other two layouts still
// do. The exact-text match found nothing: "Source option not found" for a
// source that was on screen (screenshot in the run's failure evidence).
// What "411.0" is, is NOT measured; the code only needs to know that it is
// not part of the identity.
// ---------------------------------------------------------------------------

test("a status-line argument between producer and plot name is not a different source", () => {
  const suite = "SMC Long-Dip Suite";
  assert.equal(canonicalSourceSelection("SMC Long-Dip Suite · 411.0: BUS Armed", suite), "SMC Long-Dip Suite: BUS Armed");
  assert.equal(canonicalSourceSelection("SMC Long-Dip Suite (15, close): BUS Armed", suite), "SMC Long-Dip Suite: BUS Armed");
  assert.equal(canonicalSourceSelection("SMC Long-Dip Suite: BUS Armed", suite), "SMC Long-Dip Suite: BUS Armed");
  // Unbound, unreadable and foreign selections pass through untouched.
  assert.equal(canonicalSourceSelection("Close", suite), "Close");
  assert.equal(canonicalSourceSelection(null, suite), null);
  assert.equal(canonicalSourceSelection("Volume · 20: Volume MA", suite), "Volume · 20: Volume MA");
  // A longer script name that merely STARTS with the producer's name is a
  // different script and must stay a mismatch.
  assert.equal(
    canonicalSourceSelection("SMC Long-Dip Suite Pro · 1.0: BUS Armed", suite),
    "SMC Long-Dip Suite Pro · 1.0: BUS Armed",
  );
  assert.equal(canonicalSourceSelection("SMC Long-Dip Suite Pro: BUS Armed", suite), "SMC Long-Dip Suite Pro: BUS Armed");
});

function sourceDialogHtml(options: string[]): string {
  return `
    <div class="row">
      <div class="cell"><span>BUS SchemaVersion</span></div>
      <div class="cell"><button role="combobox" id="combo">Close</button></div>
    </div>
    <div role="listbox" id="list" hidden>
      ${options.map((text) => `<div role="option">${text}</div>`).join("\n")}
    </div>
    <script>
      const combo = document.getElementById("combo");
      const list = document.getElementById("list");
      combo.addEventListener("click", () => { list.hidden = false; });
      for (const option of list.querySelectorAll('[role="option"]')) {
        option.addEventListener("click", () => { combo.textContent = option.textContent; list.hidden = true; });
      }
    </script>`;
}

test("binding repair selects the producer's plot when the option carries a status-line argument", async () => {
  const browser = await launchTradingViewChromium({ headless: true });
  try {
    const page = await browser.newPage();
    // The option list exactly as the run's screenshot shows it.
    await page.setContent(sourceDialogHtml([
      "Open", "High", "Low", "Close", "Volume",
      "SMC Long-Dip Suite · 411.0: BUS SchemaVersion",
      "SMC Long-Dip Suite · 411.0: BUS ZoneActive",
      "SMC Long-Dip Suite · 411.0: BUS Armed",
    ]));

    await repairSelectedSource(page as any, "BUS SchemaVersion", "SMC Long-Dip Suite: BUS SchemaVersion");

    assert.equal(await page.locator("#combo").innerText(), "SMC Long-Dip Suite · 411.0: BUS SchemaVersion");
  } finally {
    await browser.close();
  }
});

test("binding repair still takes the plain option where TradingView offers it", async () => {
  const browser = await launchTradingViewChromium({ headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent(sourceDialogHtml(["Close", "SMC Long-Dip Suite: BUS SchemaVersion"]));

    await repairSelectedSource(page as any, "BUS SchemaVersion", "SMC Long-Dip Suite: BUS SchemaVersion");

    assert.equal(await page.locator("#combo").innerText(), "SMC Long-Dip Suite: BUS SchemaVersion");
  } finally {
    await browser.close();
  }
});

test("binding repair refuses a look-alike producer and two instances of the real one", async () => {
  const browser = await launchTradingViewChromium({ headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent(sourceDialogHtml(["Close", "SMC Long-Dip Suite Pro · 1.0: BUS SchemaVersion"]));
    await assert.rejects(
      repairSelectedSource(page as any, "BUS SchemaVersion", "SMC Long-Dip Suite: BUS SchemaVersion"),
      /Source option not found/,
    );
    assert.equal(await page.locator("#combo").innerText(), "Close");

    // Two producer instances are two different parents; picking "the first"
    // would bind to an arbitrary one. (A fresh page: setContent keeps the
    // window, and the fixture's top-level `const` would not redeclare.)
    await page.close();
    const second = await browser.newPage();
    await second.setContent(sourceDialogHtml([
      "Close",
      "SMC Long-Dip Suite · 411.0: BUS SchemaVersion",
      "SMC Long-Dip Suite · 412.0: BUS SchemaVersion",
    ]));
    await assert.rejects(
      repairSelectedSource(second as any, "BUS SchemaVersion", "SMC Long-Dip Suite: BUS SchemaVersion"),
      /ambiguous/i,
    );
    assert.equal(await second.locator("#combo").innerText(), "Close");
  } finally {
    await browser.close();
  }
});

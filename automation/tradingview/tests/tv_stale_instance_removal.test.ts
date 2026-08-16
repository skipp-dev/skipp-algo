import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { LEGEND_TEXT_EXCLUDED_SURFACES } from "../lib/tv_shared.js";

const _dir = path.dirname(fileURLToPath(import.meta.url));
const SHARED = path.join(_dir, "..", "lib", "tv_shared.ts");

// Run 30702240413, same session, same DOM: findLegendRowWrappers (button-first,
// visibility without hover) reported 0 rows for the pre-#4263 overlay instance
// while the text-first settings opener found the row, hovered it, resolved its
// actionable wrapper and opened it — 60 rows, twice, in two runs. TradingView
// renders the legend action buttons on hover, so a probe that starts at the
// buttons never sees a row nobody is pointing at. Removal therefore never
// cleared the stale instance, the force-insert stacked a fresh one next to it,
// and the repair mutated the wrong one.
//
// These are source-structure pins plus one testable constant. The DOM behavior
// itself is Playwright-against-TradingView and can only be proven by the next
// CI run — that limit is stated here so nobody reads these tests as more than
// they are.

const source = () => fs.readFileSync(SHARED, "utf-8");

test("the excluded-surfaces selector keeps text discovery off non-legend matches", () => {
  // The script name also appears in the Object Tree, dialogs and menus
  // (measured 2026-07-31 during the CE10156 diagnosis). A remover that
  // resolves one of those as a "legend row" would delete nothing or worse.
  for (const surface of ['[role="dialog"]', '[role="menu"]', '[data-name="tree"]', '[data-name="pine-dialog"]']) {
    assert.ok(
      LEGEND_TEXT_EXCLUDED_SURFACES.includes(surface),
      `excluded surfaces must cover ${surface}`,
    );
  }
});

test("removal falls back to text-first discovery when the button-first probe sees nothing", () => {
  assert.match(
    source(),
    /findLegendRowWrappers\(page, scriptName\)[\s\S]{0,900}?findLegendRowWrappersByVisibleText\(page, scriptName\)/,
    "removeVisibleChartScriptInstances must try text discovery after an empty wrapper result",
  );
});

test("the text fallback hovers before resolving the actionable wrapper", () => {
  // The hover IS the fix: the buttons the wrapper resolution needs are
  // rendered on hover. Resolving first and hovering later re-creates the
  // blindness this exists to remove.
  assert.match(
    source(),
    /export async function findLegendRowWrappersByVisibleText[\s\S]*?\.hover\([\s\S]*?ancestor::\*\[\.\/\/button\[@data-qa-id="legend-settings-action"\]/,
    "hover must precede the ancestor resolution",
  );
});

test("the refresh fails closed when a text-visible row survives removal", () => {
  // Success detection inside removal is count/visibility based and blind to
  // exactly the row this is about, so it can report success it did not earn.
  // The refresh must re-probe by TEXT after removal and throw rather than
  // insert a duplicate next to a stale instance.
  assert.match(
    source(),
    /export async function refreshChartScriptInstance[\s\S]*?findLegendRowWrappersByVisibleText\(page, scriptName\)[\s\S]*?throw new Error\([\s\S]*?still on the chart after removal/,
    "refreshChartScriptInstance must re-probe by text and throw on residuals",
  );
});

test("the residual throw happens before the insert, not after", () => {
  const refresh = source().match(/export async function refreshChartScriptInstance[\s\S]*?\n\}/)?.[0] ?? "";
  const throwAt = refresh.indexOf("still on the chart after removal");
  const insertAt = refresh.indexOf("addCurrentScriptToChart");

  assert.ok(throwAt > 0, "residual throw must exist in refreshChartScriptInstance");
  assert.ok(insertAt > 0, "insert must exist in refreshChartScriptInstance");
  assert.ok(throwAt < insertAt, "a duplicate insert after the throw would recreate the bug");
});

// ---------------------------------------------------------------------------
// 2026-08-15 sweep: a CRASHED visibility probe in the removal path mapped to
// "cleared" (`.catch(() => false)`) and emitted the success trace — a stale
// instance left behind is the known measurement poison (UNIVERSE UNINIT).
// The keyboard twin already mapped the same failure to `true`; these pins
// hold the whole removal path to that doctrine.
// ---------------------------------------------------------------------------

test("a crashed visibility probe in the removal path never reads as cleared", () => {
  const sharedSource = fs.readFileSync(SHARED, "utf-8");
  // Slice from the keyboard helper through the removal loop: the doctrine
  // covers every visibility probe on the removal path, and the three sit in
  // two functions (tryKeyboardRemoveScriptInstance + the removal loop).
  const start = sharedSource.indexOf("async function tryKeyboardRemoveScriptInstance");
  const end = sharedSource.indexOf("export async function refreshChartScriptInstance");
  assert.ok(start > 0 && end > start, "removal path not found where expected");
  const removal = sharedSource.slice(start, end);
  const probes = removal.match(/isScriptStrictlyVisibleOnChartSurface\(page, scriptName\)\.catch\(\(\) => (true|false)\)/g) ?? [];
  assert.ok(probes.length >= 3, `expected the three visibility probes, found ${probes.length}`);
  for (const probe of probes) {
    assert.ok(probe.endsWith("=> true)"), `${probe} — a crashed probe must fail closed (still visible)`);
  }
});

test("a crashed chooser-inventory readout leaves a trace instead of an empty DOM claim", () => {
  const sharedSource = fs.readFileSync(SHARED, "utf-8");
  const start = sharedSource.indexOf("export async function collectPublishChooserInventory");
  const end = sharedSource.indexOf("async function tracePublishChooserAbsence");
  assert.ok(start > 0 && end > start, "chooser inventory function not found where expected");
  const inventory = sharedSource.slice(start, end);
  assert.match(inventory, /publish-chooser-inventory-probe-failed/);
  assert.doesNotMatch(
    inventory,
    /\.catch\(\(\) => \[\] as PublishChooserInventoryEntry\[\]\)/,
    "a silent [] fallback claims 'TradingView renders no matching controls' on a probe crash",
  );
});

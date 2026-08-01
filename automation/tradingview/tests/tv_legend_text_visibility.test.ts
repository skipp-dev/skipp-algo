import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { chartLegendTextVerdict, CHART_LEGEND_CONTAINER_SELECTOR } from "../lib/tv_shared.js";

const _dir = path.dirname(fileURLToPath(import.meta.url));
const SHARED = path.join(_dir, "..", "lib", "tv_shared.ts");

// Run 30718040533, against a clean layout: the fresh overlay instance was added
// (add-to-chart-click-settle hasLegendMatch:true) but verification then threw
// "Existing chart instance not found". Every on-chart detection funnels through
// hasLegendMatch = findLegendRowWrappers().length > 0, and that probe starts at
// the legend-settings-action button, which TradingView only renders on hover /
// right after an interaction. Seconds later at verify time the button is gone,
// so a script that IS on the chart reads as absent. The stale 60-input instance
// masked this for every earlier run because IT kept a rendered button.
//
// The fix keys presence on the visible legend TEXT inside the chart container,
// which does not depend on the transient button. chartLegendTextVerdict is the
// pure decision; the DOM predicate feeding it is Playwright-against-TradingView
// and is proven only by the next CI run — stated so nobody over-reads these.

test("legend text inside the chart container, outside excluded surfaces, counts as present", () => {
  assert.equal(chartLegendTextVerdict({ inContainer: true, inExcluded: false }), true);
});

test("the Pine editor's own title (excluded surface) never counts as on-chart", () => {
  // The editor shows the script name whenever it is open; treating that as
  // "on the chart" would make every check trivially true.
  assert.equal(chartLegendTextVerdict({ inContainer: true, inExcluded: true }), false);
  assert.equal(chartLegendTextVerdict({ inContainer: false, inExcluded: true }), false);
});

test("a name match outside any chart container is not a legend match", () => {
  assert.equal(chartLegendTextVerdict({ inContainer: false, inExcluded: false }), false);
});

test("the chart legend container selector targets the chart surface, not the editor", () => {
  assert.match(CHART_LEGEND_CONTAINER_SELECTOR, /chart-container/);
  assert.match(CHART_LEGEND_CONTAINER_SELECTOR, /chart-gui-wrapper/);
  assert.doesNotMatch(CHART_LEGEND_CONTAINER_SELECTOR, /pine-dialog/);
});

test("hasLegendMatch OR-wires the button-free text probe at the source", () => {
  // Source-structure pin: the fix must live in collectVisibleChartScriptState
  // so removal, the refresh residual check AND verify visibility all inherit
  // it — not a fourth per-surface patch.
  const source = fs.readFileSync(SHARED, "utf-8");
  const block = source.split("export async function collectVisibleChartScriptState", 2)[1] ?? "";
  assert.match(
    block.slice(0, 1600),
    /hasLegendMatch\s*=\s*legendWrappers\.length > 0\s*\|\|\s*await hasVisibleChartLegendText\(/,
    "hasLegendMatch must fall back to the text probe when the button probe is blind",
  );
});

test("the text probe excludes the editor and dialog surfaces, and traces when it fires", () => {
  const source = fs.readFileSync(SHARED, "utf-8");
  const block = source.split("async function hasVisibleChartLegendText", 2)[1] ?? "";
  // The pine editor host must be excluded, or the editor title reads as on-chart.
  assert.match(block.slice(0, 1800), /chartLegendExcludedSelector\(\)/);
  // Evidence, not faith: the next run must SHOW when text — not the button —
  // is what confirmed presence.
  assert.match(block.slice(0, 1800), /chart-legend-text-present/);
});

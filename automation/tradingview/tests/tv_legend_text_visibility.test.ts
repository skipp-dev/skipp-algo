import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import {
  buildScriptNamePatterns,
  chartLegendTextVerdict,
  CHART_LEGEND_CONTAINER_SELECTOR,
  resolveOpenScriptSearchNames,
} from "../lib/tv_shared.js";

const _dir = path.dirname(fileURLToPath(import.meta.url));
const SHARED = path.join(_dir, "..", "lib", "tv_shared.ts");
const REPO = path.join(_dir, "..", "..", "..");
const ROLLOUT = path.join(REPO, "automation", "tradingview", "config", "consumer-rollout.json");

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

// --------------------------------------------------------------------------
// 2026-08-31: the configured name and the name the LEGEND carries are two
// different things, and nothing checked that they can still find each other.
//
// The legend row shows the indicator() declaration title. The rollout config
// verifies a product name. For nine of ten consumers those are the same string;
// for "SMC Decision Board" (product name, docs/SMC_PRODUCT_IDENTITY.md) the
// source SMC_Long_Dip_Dashboard.pine declares "SMC Long-Dip Dashboard", and the
// alias table happened not to carry that spelling in this direction. Verify then
// threw "Existing chart instance not found" against a chart the indicator was
// plainly on -- every run since at least 2026-08-29, which also left
// outOfBandDrift at "unknown" instead of a verdict.
//
// Bound to the MECHANISM, not to that incident: the population is DERIVED from
// the rollout config and the declared titles, so a future consumer whose config
// name and declaration name drift apart fails here, without anyone editing a
// list. Only exact|loose are used -- those are the patterns the legend probes
// consult; a fuzzy hit does not open the gate (isScriptVisibleOnChart returns
// hasLegendMatch alone).
// --------------------------------------------------------------------------

function declaredIndicatorTitle(sourceRelPath: string): string | null {
  const abs = path.join(REPO, sourceRelPath);
  if (!fs.existsSync(abs)) return null;
  const m = fs.readFileSync(abs, "utf-8").match(/^\s*indicator\(\s*"([^"]+)"/m);
  return m ? m[1] : null;
}

function legendPathFinds(searchName: string, legendText: string): boolean {
  const [exact, loose] = buildScriptNamePatterns(searchName);
  return exact.test(legendText) || loose.test(legendText);
}

test("every verify target can find the title its own source declares", () => {
  const rollout = JSON.parse(fs.readFileSync(ROLLOUT, "utf-8")) as {
    verifyTargets: Array<{ source?: string; scriptName: string }>;
  };
  const targets = rollout.verifyTargets ?? [];
  assert.ok(targets.length > 0, "no verifyTargets in the rollout config — the population is empty");

  let checked = 0;
  for (const target of targets) {
    if (!target.source) continue;
    const declared = declaredIndicatorTitle(target.source);
    if (!declared) continue;
    checked += 1;
    const candidates = resolveOpenScriptSearchNames(target.scriptName);
    assert.ok(
      candidates.some((candidate) => legendPathFinds(candidate, declared)),
      `"${target.scriptName}" cannot find the legend text "${declared}" declared by `
      + `${target.source}. Candidates tried: ${JSON.stringify(candidates)}. Add the declared `
      + `title to legacyOpenScriptNames, or align the config with the declaration.`,
    );
  }
  // Positive control: an empty loop would pass every assertion above.
  assert.ok(checked >= targets.length - 1, `only ${checked} of ${targets.length} targets were actually checked`);
});

test("the legend TEXT probe resolves aliases, like the button probe next to it", () => {
  // Source-structure pin. The two probes are the two halves of one signal, and
  // the text half exists precisely for the case where the button half is blind.
  // A narrower fallback than the probe it backs up is the defect this fixes.
  const source = fs.readFileSync(SHARED, "utf-8");
  const block = source.split("async function hasVisibleChartLegendText", 2)[1] ?? "";
  assert.match(
    block.slice(0, 1600),
    /resolveOpenScriptSearchNames\(scriptName\)/,
    "hasVisibleChartLegendText must search every alias, not only the raw configured name",
  );
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

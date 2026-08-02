import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { OBJECT_TREE_PANEL_SELECTOR } from "../lib/tv_shared.js";

const _dir = path.dirname(fileURLToPath(import.meta.url));
const SHARED = path.join(_dir, "..", "lib", "tv_shared.ts");

// Operator suggestion 2026-08-02, and the measured gap it closes: every
// removal path anchored on the chart LEGEND row, which must first be found by
// the button-first probe — and TradingView renders those buttons on hover
// only, so the pre-#4263 overlay row was undiscoverable (0 wrappers in 192ms)
// while plainly visible to a human. Four detection variants failed on it and
// the operator removed it by hand: right sidebar -> Object Tree -> right
// click -> Remove.
//
// The Object Tree is a complete inventory panel: every applied object is a
// stable row (measured 2026-07-31, recorded at the identity-evidence probe:
// entries live under [data-name="tree"] inside the widgetbar), and the
// context-menu path needs no hover-rendered row buttons. The menu machinery
// (right-click, scriptRemovalActionLocators) already existed — only the tree
// as an ANCHOR surface was never built.
//
// The sidebar toggle's selectors and the live behavior are
// Playwright-against-TradingView and only a run proves them; these are
// source-structure pins plus one testable constant.

const source = () => fs.readFileSync(SHARED, "utf-8");

test("the tree panel selector matches the measured anchor", () => {
  assert.match(OBJECT_TREE_PANEL_SELECTOR, /data-name="tree"/);
});

test("tree removal is wired as the removal loop's last discovery fallback", () => {
  const s = source();
  const loop = s.split("export async function removeVisibleChartScriptInstances", 2)[1] ?? "";
  const head = loop.split("const targetWrapper", 2)[0];

  assert.match(head, /findLegendRowWrappersByVisibleText\(page, scriptName\)/,
    "text discovery stays the first fallback");
  assert.match(head, /removeChartScriptInstancesViaObjectTree\(page, scriptName\)/,
    "the tree is the last resort before giving up");
  const textAt = head.indexOf("findLegendRowWrappersByVisibleText");
  const treeAt = head.indexOf("removeChartScriptInstancesViaObjectTree");
  assert.ok(0 < textAt && textAt < treeAt, "tree runs only after both legend probes came up empty");
});

test("the tree path right-clicks the row and uses the existing Remove-menu machinery", () => {
  const block = source().split("export async function removeChartScriptInstancesViaObjectTree", 2)[1] ?? "";
  const body = block.split("\nexport ", 1)[0];

  assert.match(body, /button: "right"/, "the context menu comes from a right click, not a hover button");
  assert.match(body, /scriptRemovalActionLocators\(page\)/, "reuse the proven Remove-menu locators");
  assert.match(body, /scriptRemovalConfirmActionLocators\(page\)/, "and the confirm step some removals show");
});

test("the tree path counts its own rows instead of trusting the blind legend count", () => {
  // countChartScriptInstances is the probe that was blind for exactly the
  // rows this path exists to remove — using it to judge success would report
  // failure for every successful tree removal.
  const block = source().split("export async function removeChartScriptInstancesViaObjectTree", 2)[1] ?? "";
  const body = block.split("\nexport ", 1)[0];

  assert.doesNotMatch(body, /countChartScriptInstances\(/);
  assert.match(body, /objectTreeRowsForScript\(/, "before/after comes from the tree itself");
});

test("an unopenable tree is a zero-result, not a crash", () => {
  // The removal loop treats "nothing found" as "nothing to remove" and the
  // refresh's residual check stays the fail-closed backstop. A throw here
  // would turn a missing sidebar button into a hard failure on healthy runs.
  const block = source().split("export async function removeChartScriptInstancesViaObjectTree", 2)[1] ?? "";
  const body = block.split("\nexport ", 1)[0];

  assert.match(body, /return 0;/, "no tree, no rows -> zero removals");
});

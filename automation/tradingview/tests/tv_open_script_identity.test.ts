import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

// 2026-07-31 (CE10156 diagnosis): with a script ON THE CHART, the page-wide
// openScriptIdentity families are satisfied by the chart legend row — measured
// live: collectOpenScriptIdentityTexts returned the script name from four
// visible legend titles while the Pine editor sat on an untouched "Untitled
// script" draft. openExistingScript's already-open fast path then returned
// true without touching the editor, which silently invalidated every
// editor-side observation built on it.
//
// Two defenses were added, and these source pins keep them:
//  1. the already-open fast path must prove the MONACO BUFFER holds the script
//     (waitForVisiblePineDeclarationIdentity), unconditionally — a page-side
//     title match alone is never sufficient;
//  2. collectOpenScriptIdentityTexts must refuse evidence from chart legend
//     rows, recognized the same way countChartScriptInstances recognizes them
//     (a legend action button inside a small, short-text ancestor).

const _dir = path.dirname(fileURLToPath(import.meta.url));

function tvSharedSource(): string {
  return fs.readFileSync(path.join(_dir, "..", "lib", "tv_shared.ts"), "utf-8");
}

function functionBody(source: string, header: string): string {
  const start = source.indexOf(header);
  assert.ok(start !== -1, `expected to find ${JSON.stringify(header)} in tv_shared.ts`);
  const next = source.indexOf("\nexport ", start + header.length);
  return source.slice(start, next === -1 ? source.length : next);
}

test("the openExistingScript already-open fast path requires Monaco declaration identity unconditionally", () => {
  const body = functionBody(tvSharedSource(), "export async function openExistingScript(");
  const fastPath = body.slice(0, body.indexOf("for (let attempt = 0"));
  assert.ok(fastPath.length > 0, "expected the fast path segment before the selection-attempt loop");

  assert.match(
    fastPath,
    /const alreadyOpen = uiAlreadyOpen\s*&&\s*await waitForVisiblePineDeclarationIdentity\(/,
    "the already-open fast path must gate on waitForVisiblePineDeclarationIdentity — "
    + "a page-side title match is satisfied by the chart legend when the script is on the chart",
  );
  assert.doesNotMatch(
    fastPath,
    /!options\.requireVisibleDeclarationIdentity/,
    "the declaration requirement of the fast path must not be optional again",
  );
});

test("collectOpenScriptIdentityTexts refuses chart-surface evidence", () => {
  const body = functionBody(tvSharedSource(), "export async function collectOpenScriptIdentityTexts(");

  // Both leak surfaces were measured live on 2026-07-31: legend titles sit
  // under .chart-gui-wrapper/.chart-container, Object Tree entries under
  // [data-name="tree"] in the widgetbar. The qa-id proximity probe stays as
  // the second layer in case TradingView renames the wrapper classes.
  for (const marker of [
    ".chart-container",
    ".chart-gui-wrapper",
    '[data-name="tree"]',
    "legend-settings-action",
    "legend-more-action",
  ]) {
    assert.ok(
      body.includes(marker),
      `collectOpenScriptIdentityTexts must recognize chart-side surfaces via ${marker} — `
      + "chart-side titles carry the script name in exactly the shapes "
      + "the identity families accept",
    );
  }
  assert.match(
    body,
    /insideLegendRow/,
    "collectOpenScriptIdentityTexts must skip elements inside a recognized chart surface",
  );
});

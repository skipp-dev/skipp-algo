import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

// 2026-07-31: smc-library-refresh had been unable to publish since 2026-07-30
// while generating the library fine and passing its TradingView auth probe on
// every attempt. The failing step reported only "Could not open publish flow".
//
// Measured cause: TradingView relabelled the control. The Pine editor header
// reads "Add to chart", an unnamed button, [title="Share your script with
// community"], "More" — and every selector in pinePublishButtons keyed on the
// word "publish", which appears nowhere on it. Clicking the measured control
// does open the publish flow (it immediately shows the known "Script is not on
// the chart" gate).
//
// This pins the label so the next relabelling is a test failure with a name,
// not another week of a silently dead publish pipeline.

const _dir = path.dirname(fileURLToPath(import.meta.url));

function selectorsSource(): string {
  return fs.readFileSync(path.join(_dir, "..", "selectors.ts"), "utf-8");
}

function pinePublishButtonsBody(): string {
  const source = selectorsSource();
  const start = source.indexOf("pinePublishButtons(page: Page): Locator[] {");
  assert.ok(start !== -1, "pinePublishButtons not found in selectors.ts");
  const end = source.indexOf("\n  },", start);
  assert.ok(end !== -1, "could not delimit pinePublishButtons");
  return source.slice(start, end);
}

test("the publish control is matched by its measured title, not only by the word publish", () => {
  const body = pinePublishButtonsBody();
  assert.ok(
    body.includes('"Share your script with community"'),
    "pinePublishButtons must match the measured title of the publish control; "
    + "keying only on /publish/ missed it entirely and left the library refresh "
    + "unable to publish while reporting a generic 'Could not open publish flow'",
  );
});

test("a case-insensitive fallback survives a wording tweak", () => {
  const body = pinePublishButtonsBody();
  assert.match(
    body,
    /share your script[^"']*" i\]/i,
    "keep a loose, case-insensitive variant alongside the exact title so a "
    + "capitalisation or suffix change does not break publishing again",
  );
});

test("the publish-by-name patterns are kept, not replaced", () => {
  // The relabelling may be partial or reverted, and other surfaces (library vs
  // script) can still use the old wording.
  const body = pinePublishButtonsBody();
  for (const pattern of ["publish script", "publish library"]) {
    assert.ok(body.includes(pattern), `the ${pattern} pattern must stay as a fallback`);
  }
});

test("a structural candidate survives the title strip on reopen", () => {
  // 2026-07-31, publishing smc_context_engine_private v5: the title-keyed
  // candidates are single-use, because apply-common-tooltip strips the title
  // attribute on click. The first open matched, the "Script is not on the
  // chart" gate was cleared, and the reopen missed all candidates — leaving
  // every publish that passes through the gate (all libraries) broken one
  // step later than the #4251 relabelling. The stable structural anchor is
  // TradingView's own class prefix; the hashed suffix must NOT be pinned.
  const body = pinePublishButtonsBody();
  assert.ok(
    body.includes('button[class*="publishButton"]'),
    "pinePublishButtons must keep a class-prefix candidate that does not "
    + "depend on the strip-on-click title attribute",
  );
  // Only selector STRINGS are constrained — the measured hash may (and
  // should) appear in the comment as evidence.
  assert.ok(
    !/["'][^"'\n]*publishButton-[A-Za-z0-9]/.test(body),
    "never pin the hashed class suffix in a selector — it changes on TradingView deploys",
  );
});

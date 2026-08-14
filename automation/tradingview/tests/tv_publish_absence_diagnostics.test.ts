import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

// 2026-07-31 (issue #4238): smc-library-refresh could not publish for two days,
// and the pipeline could not name its own cause either time.
//
// The first cause (#4251) was a relabelled control. The run that carried that
// fix, 30644048525, then failed one step further on: it matched the control,
// opened the publish surface, satisfied the "script is not on the chart" gate —
// and 29 seconds later the SAME candidate list reported no-visible-candidate for
// all 11 entries, while the editor header still showed the right script name.
//
// The cause was the title strip fixed in #4261 — the control carries
// apply-common-tooltip, which removes its title on click, so a title-only match
// works exactly once per session. Getting there took a full ~2h CI cycle and a
// local DOM dump, because a candidate miss traces only a COUNT (never the DOM it
// looked at) and because the publish step shipped no screenshot of its own
// failure: its images went to the default directory, which the artifact upload
// does not collect — the 2026-07-13 incident fix had been applied to the two
// neighbouring steps but not to this one.
//
// From the trace alone the strip was indistinguishable from a `.last()` retarget,
// from TradingView removing the control, and from an undismissed gate dialog.
// All three were plausible; all three were wrong.
//
// These pins keep the evidence channel open. If any of them fails, someone is
// about to re-enter that blind state: fix the diagnostic, do not relax the test.

const _dir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.join(_dir, "..", "..", "..");

function read(relativePath: string): string {
  return fs.readFileSync(path.join(repoRoot, relativePath), "utf-8");
}

function publishPrivateScriptBody(): string {
  const source = read("automation/tradingview/lib/tv_shared.ts");
  const start = source.indexOf("export async function publishPrivateScript(");
  assert.ok(start !== -1, "publishPrivateScript not found in tv_shared.ts");
  const end = source.indexOf("\nexport async function openDataWindow(", start);
  assert.ok(end !== -1, "could not delimit publishPrivateScript");
  return source.slice(start, end);
}

test("both publish-surface failures dump the DOM before throwing", () => {
  const body = publishPrivateScriptBody();

  for (const [label, marker] of [
    ["open", 'throw new Error("Could not open publish flow")'],
    ["reopen", 'throw new Error("Could not reopen publish flow after adding script to chart")'],
  ] as const) {
    const throwIndex = body.indexOf(marker);
    assert.ok(throwIndex !== -1, `the ${label} failure throw is missing — did the message change?`);

    const preceding = body.slice(0, throwIndex);
    const diagnosticIndex = preceding.lastIndexOf("tracePublishSurfaceAbsence(page");
    assert.ok(
      diagnosticIndex !== -1,
      `the ${label} failure must dump the publish-surface DOM before throwing; without it the trace "
      + "reports only a candidate count and the cause cannot be told apart from the alternatives`,
    );
    // Guard against the call drifting above the compile-error branch, which
    // returns a specific message and needs no DOM dump.
    assert.ok(
      throwIndex - diagnosticIndex < 400,
      `the ${label} DOM dump must sit immediately before its throw, not further up the function`,
    );
  }
});

test("the diagnostic separates the mechanisms the trace could not", () => {
  const source = read("automation/tradingview/lib/tv_shared.ts");
  const start = source.indexOf("async function tracePublishSurfaceAbsence(");
  assert.ok(start !== -1, "tracePublishSurfaceAbsence not found");
  const body = source.slice(start, source.indexOf("\nexport async function publishPrivateScript(", start));

  // Retargeting: which nodes the pineDialog set resolves to, and which one
  // .last() picks — a control living in dialog 0 while .last() points at
  // dialog 1 is invisible in every other trace.
  assert.match(body, /isLast/, "report which pine-dialog node .last() resolves to");
  assert.ok(body.includes("publish-absence-pine-dialogs"), "emit the pine-dialog resolution");

  // Removed vs present-but-hidden: a detached or collapsed control has no
  // offsetParent, which separates "TradingView removed it" from "it is there
  // and something is hiding it".
  assert.match(body, /hasOffsetParent/, "report offsetParent so removal and hiding stay distinguishable");
  assert.ok(body.includes("publish-absence-share-controls"), "emit the share-control inventory");

  // The attribute that actually solved #4238: the control was present, visible
  // and unmoved — only its title had been stripped. An inventory that omits the
  // matched attributes cannot show that, and the answer stays invisible.
  assert.match(
    body,
    /getAttribute\("title"\)/,
    "report the title attribute of each share control — a stripped title is what made the "
    + "candidate list miss while the control sat there visible",
  );

  // Undismissed gate/successor modal: its text is the fingerprint.
  assert.ok(body.includes("publish-absence-overlays"), "emit the text of any open overlay");
});

test("a failing publish captures its own screenshot while the page is alive", () => {
  const source = read("scripts/tv_publish_micro_library.ts");
  const publishCall = source.indexOf("await publishPrivateScript(session.page");
  assert.ok(publishCall !== -1, "the publishPrivateScript call site moved");

  const window = source.slice(publishCall, publishCall + 1_200);
  assert.match(
    window,
    /publish-failed/,
    "the publish call must screenshot its own failure at the call site — the outer catch cannot, "
    + "because the enclosing finally has already closed the session by then",
  );
  assert.match(window, /throw publishError/, "the failure screenshot must rethrow, never swallow");
});

test("publish-step screenshots land in the uploaded artifact tree", () => {
  // 2026-08-13 (#4679): the publish phase moved out of smc-library-refresh.yml
  // into its own workflow so it stops holding the TradingView session for the
  // regeneration work. The guard has to follow the step, or it silently stops
  // watching anything -- which is exactly what it did between that merge and
  // this fix.
  const workflow = read(".github/workflows/smc-library-publish.yml");
  const stepStart = workflow.indexOf("- name: Publish library to TradingView");
  assert.ok(stepStart !== -1, "the publish step was renamed or moved workflows again");
  const nextStep = workflow.indexOf("\n      - name:", stepStart + 1);
  const step = workflow.slice(stepStart, nextStep === -1 ? undefined : nextStep);

  assert.match(
    step,
    /TV_SCREENSHOT_DIR:\s*artifacts\/tradingview\/screenshots/,
    "the publish step must write screenshots into artifacts/tradingview/, which the upload collects; "
    + "the default automation/tradingview/reports/screenshots is never uploaded, so failures ship blind "
    + "(2026-07-13 incident, re-hit by #4238 because only the neighbouring steps were fixed)",
  );
});

// 2026-08-14: the same blind state, one step further into the wizard.
//
// openprep-pine-panel-publish has not published since 2026-08-08. The green run
// before that, 31281014931, was a false green — #4581 found its publish surface
// still open showing "Script description is required" — so the honest count is
// that this workflow has not published successfully at all since the update-
// existing path was introduced.
//
// Five selector changes followed on 2026-08-09/10 (#4585, #4587, #4591, #4597,
// #4606). Eight of the ten runs since carry the byte-identical error
// "Could not select existing TradingView script: Open-Prep Daily Panel", so not
// one of the five moved the failure. What every one of them had to work from
// was a screenshot and that sentence: selectExistingPublishScript returned
// false from three different places without recording anything about the page.
//
// The screenshot of run 31805361109 shows the dialog in "Update existing
// script" mode with a "Choose script" control plainly rendered. A screenshot
// cannot say whether that control is a native select, a div with role=listbox,
// or an input carrying the words as a placeholder — and those three want three
// different selectors. The sixth guess is not what is missing. The DOM is.

test("every chooser dead end records the DOM instead of returning a bare false", () => {
  const source = read("automation/tradingview/lib/tv_shared.ts");
  const start = source.indexOf("export async function selectExistingPublishScript(");
  assert.ok(start !== -1, "selectExistingPublishScript not found in tv_shared.ts");
  const body = source.slice(start, source.indexOf("\nexport async function publishPrivateScript(", start));

  const bareReturns = body
    .split("\n")
    .map((line, index) => ({ line: line.trim(), index }))
    .filter((entry) => entry.line === "return false;");

  assert.ok(bareReturns.length >= 3, "the three dead ends were restructured — re-pin this test");

  const lines = body.split("\n");
  for (const entry of bareReturns) {
    const preceding = lines.slice(Math.max(0, entry.index - 6), entry.index).join("\n");
    assert.match(
      preceding,
      /tracePublishChooserAbsence\(page, "[a-z-]+"\)/,
      `a "return false" at body line ${entry.index} ships no DOM evidence; that is the state five `
      + "selector changes were made from, and none of them moved the failure",
    );
  }
});

test("the chooser inventory is scoped wider than the lookup it is explaining", () => {
  const source = read("automation/tradingview/lib/tv_shared.ts");
  const start = source.indexOf("export async function collectPublishChooserInventory(");
  assert.ok(start !== -1, "collectPublishChooserInventory not found");
  const body = source.slice(start, source.indexOf("\n/**", start + 10));

  // Scoping the inventory to publishSurface would inherit its blindness: if the
  // surface is what mis-resolved, the inventory comes back empty and reads as
  // proof that TradingView removed the control.
  assert.ok(
    body.includes('page\n    .locator("#overlap-manager-root")'),
    "the inventory must read the whole overlay root, not the publish surface whose lookup failed",
  );
  assert.ok(
    !body.includes("publishSurfaceProbe"),
    "the inventory must not be filtered by the surface it is diagnosing",
  );

  // The three shapes a screenshot cannot tell apart, each needing a different
  // selector. Omit any one and the next change is a guess again.
  for (const attribute of ["role", "placeholder", "aria-label", "name", "class"]) {
    assert.ok(
      body.includes(`getAttribute("${attribute}")`),
      `the inventory must report ${attribute}: without it a native select, a role-less div and an `
      + "input whose placeholder reads \"Choose script\" stay indistinguishable",
    );
  }
  assert.ok(body.includes("getComputedStyle"), "report display/visibility so hidden and absent stay distinct");
  assert.ok(body.includes("getBoundingClientRect"), "report geometry so a zero-size overlay is visible as such");
});

test("the chooser inventory reads attributes and touches nothing", () => {
  const source = read("automation/tradingview/lib/tv_shared.ts");
  const start = source.indexOf("export async function collectPublishChooserInventory(");
  const body = source.slice(start, source.indexOf("\n/**", start + 10));

  // This runs on a live publish wizard whose Continue button writes to
  // TradingView. A diagnostic that clicks is not a diagnostic.
  for (const forbidden of [".click(", ".fill(", ".press(", ".type(", "dispatchEvent"]) {
    assert.ok(!body.includes(forbidden), `the inventory must not ${forbidden} — it runs on a live publish surface`);
  }
});

test("the chooser failure carries its evidence into the uploaded report", () => {
  const body = publishPrivateScriptBody();
  const marker = "Could not select existing TradingView script:";
  const throwIndex = body.indexOf(marker);
  assert.ok(throwIndex !== -1, "the update-existing failure throw is missing — did the message change?");

  const preceding = body.slice(0, throwIndex);
  const diagnosticIndex = preceding.lastIndexOf("tracePublishChooserAbsence(page");
  assert.ok(diagnosticIndex !== -1, "the update-existing failure must dump the DOM before throwing");
  assert.ok(throwIndex - diagnosticIndex < 400, "the DOM dump must sit immediately before its throw");

  // The trace lives in the run log; the error lives in
  // publish-openprep-panel-*.json, which is the uploaded artifact. Runs
  // 31805361109 and its seven predecessors uploaded a report whose entire
  // account of the failure was one sentence.
  const throwStatement = body.slice(throwIndex - 200, throwIndex + 500);
  assert.match(
    throwStatement,
    /evidence\.controls/,
    "the thrown error must carry the control inventory, or the artifact keeps only the sentence",
  );
  assert.match(
    throwStatement,
    /evidence\.surfaceCount/,
    "the thrown error must report how many nodes the publish surface resolved to — zero and "
    + "\"resolved fine but the control is shaped differently\" are different bugs",
  );
});

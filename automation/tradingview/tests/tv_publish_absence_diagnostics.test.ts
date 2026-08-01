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
  const workflow = read(".github/workflows/smc-library-refresh.yml");
  const stepStart = workflow.indexOf("- name: Publish library to TradingView");
  assert.ok(stepStart !== -1, "the publish step was renamed");
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

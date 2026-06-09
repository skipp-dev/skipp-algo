import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";

import {
  buildScriptNamePatterns,
  countOrderedCodeBlockOccurrences,
  collectVisibleLocatorMetadata,
  editorDiagnosticsSuggestOpenHost,
  indicatorsMyScriptsShowsMatchingPrivateScript,
  openScriptSurfaceLooksReady,
  resolvePublishNoChangeCleanupActions,
  resolveOpenScriptIdentityEvidence,
  resolveOpenScriptSearchNames,
  openScriptSurfaceScopeLooksReady,
  settingsDialogTitleMatchesScriptName,
  resolveTradingViewHeadlessDefault,
  validateTradingViewStorageState,
  containsAnchoredCodeBlockAfterLine,
  containsOrderedCodeBlock,
  detectPublishedVersionFromContextTexts,
  detectPublishedVersionFromBody,
  isScriptVisibleOnChartState,
  parseInputSourceLabels,
  resolvePublishedVersionEvidence,
  scriptNameAppearsInUiText,
  uiTextContainsExactScriptName,
  verifyOpenScriptIdentity,
  ensurePineEditor,
  findLegendRowWrappers,
} from "../lib/tv_shared.js";

const CORE_SCRIPT = "SMC Core";
const DECISION_BOARD_SCRIPT = "SMC Decision Board";
const DECISION_BOARD_TRUNCATED = "SMC Deci Board";

test("generic script-name text alone does not count as chart presence", () => {
  assert.equal(isScriptVisibleOnChartState({
    hasLegendMatch: false,
    hasStrategyReportMatch: false,
    hasScriptNameMatch: true,
  }), false);
});

test("legend or strategy report confirm chart presence", () => {
  assert.equal(isScriptVisibleOnChartState({
    hasLegendMatch: true,
    hasStrategyReportMatch: false,
    hasScriptNameMatch: false,
  }), true);

  assert.equal(isScriptVisibleOnChartState({
    hasLegendMatch: false,
    hasStrategyReportMatch: true,
    hasScriptNameMatch: true,
  }), true);
});

test("bare strategy report without script identity does not count as chart presence", () => {
  assert.equal(isScriptVisibleOnChartState({
    hasLegendMatch: false,
    hasStrategyReportMatch: true,
    hasScriptNameMatch: false,
  }), false);
});

test("editor diagnostics accept toolbar-only Pine editor states", () => {
  assert.equal(editorDiagnosticsSuggestOpenHost({
    textareaCount: { total: 0, visible: 0 },
    contentEditableCount: { total: 0, visible: 0 },
    monacoCount: { total: 0, visible: 0 },
    pineContainerCount: { total: 0, visible: 0 },
    pineButtonCount: 1,
    pineButtons: ["Open script"],
    pineTextCount: 3,
    pineTexts: ["Update on chart", "Open script", "Pine Editor"],
    relevantBodyLines: ["Update on chart", "Pine Editor"],
  }), true);
});

test("ensurePineEditor recovers after closeModal clears a blocking dialog", async () => {
  const browser = await chromium.launch({ headless: true });

  try {
    const page = await browser.newPage();
    await page.setContent(`
      <button type="button" id="pine-open">Pine</button>
      <div id="blocking-modal" role="dialog" style="display:none">
        <button type="button" aria-label="Close" id="blocking-close">Close</button>
      </div>
      <script>
        const pineOpen = document.getElementById("pine-open");
        const blockingModal = document.getElementById("blocking-modal");
        const blockingClose = document.getElementById("blocking-close");

        pineOpen.addEventListener("click", () => {
          blockingModal.style.display = "block";
        });

        blockingClose.addEventListener("click", () => {
          blockingModal.style.display = "none";
          if (!document.querySelector('[data-name="pine-dialog"]')) {
            const host = document.createElement("div");
            host.setAttribute("data-name", "pine-dialog");
            host.textContent = "Pine editor ready";
            document.body.appendChild(host);
          }
        });
      </script>
    `);

    await ensurePineEditor(page);

    assert.equal(await page.locator('[data-name="pine-dialog"]').isVisible(), true);
  } finally {
    await browser.close();
  }
});

test("editor diagnostics reject toolbar-free non-editor states", () => {
  assert.equal(editorDiagnosticsSuggestOpenHost({
    textareaCount: { total: 0, visible: 0 },
    contentEditableCount: { total: 0, visible: 0 },
    monacoCount: { total: 0, visible: 0 },
    pineContainerCount: { total: 0, visible: 0 },
    pineButtonCount: 1,
    pineButtons: ["V2 Save"],
    pineTextCount: 2,
    pineTexts: ["Save", "Publish"],
    relevantBodyLines: ["Save", "Publish"],
  }), false);
});

test("open script surface readiness ignores unrelated global search inputs", () => {
  assert.equal(openScriptSurfaceScopeLooksReady({
    scopedSearchVisible: false,
    scopedMyScriptsVisible: false,
  }), false);
});

test("open script surface readiness accepts scoped picker cues", () => {
  assert.equal(openScriptSurfaceScopeLooksReady({
    scopedSearchVisible: true,
    scopedMyScriptsVisible: false,
  }), true);
  assert.equal(openScriptSurfaceScopeLooksReady({
    scopedSearchVisible: false,
    scopedMyScriptsVisible: true,
  }), true);
});

test("open script surface readiness ignores global fallback cues without a scoped picker", () => {
  assert.equal(openScriptSurfaceLooksReady({
    scopeStates: [{
      scopedSearchVisible: false,
      scopedMyScriptsVisible: false,
    }],
    globalSearchVisible: true,
    globalMyScriptsVisible: true,
  }), false);
});

test("open script surface readiness accepts any scoped ready picker state", () => {
  assert.equal(openScriptSurfaceLooksReady({
    scopeStates: [{
      scopedSearchVisible: false,
      scopedMyScriptsVisible: false,
    }, {
      scopedSearchVisible: true,
      scopedMyScriptsVisible: false,
    }],
    globalSearchVisible: false,
    globalMyScriptsVisible: false,
  }), true);
});

test("open script search names include legacy aliases for renamed scripts", () => {
  assert.deepEqual(resolveOpenScriptSearchNames("SMC Core"), ["SMC Core", "SMC Core Engine"]);
  // Canonical (post-2026-04-22 collision fix) names map back to both layers of legacy saved titles.
  assert.deepEqual(
    resolveOpenScriptSearchNames("SMC Long-Dip Dashboard v7"),
    ["SMC Long-Dip Dashboard v7", "SMC Decision Board", "SMC Dashboard"],
  );
  assert.deepEqual(
    resolveOpenScriptSearchNames("SMC Long-Dip Strategy v7"),
    ["SMC Long-Dip Strategy v7", "SMC Execution", "SMC Long Strategy"],
  );
  // Pre-rename callers continue to work.
  assert.deepEqual(resolveOpenScriptSearchNames("SMC Decision Board"), ["SMC Decision Board", "SMC Dashboard"]);
  assert.deepEqual(resolveOpenScriptSearchNames("SMC Execution"), ["SMC Execution", "SMC Long Strategy"]);
});

test("open script search names normalize whitespace and de-duplicate", () => {
  assert.deepEqual(
    resolveOpenScriptSearchNames("  SMC   Long-Dip   Dashboard   v7  "),
    ["SMC Long-Dip Dashboard v7", "SMC Decision Board", "SMC Dashboard"],
  );
});

test("indicator private script matching requires a visible My scripts row", () => {
  assert.equal(indicatorsMyScriptsShowsMatchingPrivateScript("SMC Dashboard", ["SMC Dashboard", "SMC Core"]), true);
  assert.equal(indicatorsMyScriptsShowsMatchingPrivateScript("SMC Dashboard", ["SMC Core", "SMC Core Engine"]), false);
});

test("TradingView headless default stays headed locally", () => {
  assert.equal(resolveTradingViewHeadlessDefault({}), false);
});

test("TradingView headless default is enabled in CI", () => {
  assert.equal(resolveTradingViewHeadlessDefault({ CI: "true" }), true);
});

test("TradingView headless env override disables CI fallback", () => {
  assert.equal(resolveTradingViewHeadlessDefault({ CI: "true", TV_HEADLESS: "0" }), false);
});

test("TradingView headless env override enables local headless mode", () => {
  assert.equal(resolveTradingViewHeadlessDefault({ TV_HEADLESS: "1" }), true);
});

test("editor diagnostics accept visible Pine editor containers", () => {
  assert.equal(editorDiagnosticsSuggestOpenHost({
    textareaCount: { total: 0, visible: 0 },
    contentEditableCount: { total: 0, visible: 0 },
    monacoCount: { total: 0, visible: 0 },
    pineContainerCount: { total: 1, visible: 1 },
    pineButtonCount: 0,
    pineButtons: [],
    pineTextCount: 0,
    pineTexts: [],
    relevantBodyLines: [],
  }), true);
});

test("parseInputSourceLabels supports arbitrary expressions and nested calls", () => {
  const code = `
indicator("Test")
alpha = input.source(high, "Alpha")
beta = input.source(hlc3, "Beta")
gamma = input.source(nz(request.security(syminfo.tickerid, "15", close), close), "Gamma")
delta = input.source(close, title="Ignored because label is not second positional arg")
epsilon = input.source(open, 'Epsilon')
`;

  assert.deepEqual(parseInputSourceLabels(code), ["Alpha", "Beta", "Gamma", "Epsilon"]);
});

test("ordered code block verification requires exact contiguous lines", () => {
  const haystack = `
import owner/lib/7 as micro
alpha = micro.alpha()
beta = micro.beta()
gamma = micro.gamma()
`;

  assert.equal(containsOrderedCodeBlock(haystack, `
beta = micro.beta()
gamma = micro.gamma()
`), true);
  assert.equal(containsOrderedCodeBlock(haystack, `
alpha = micro.alpha()
gamma = micro.gamma()
`), false);
  assert.equal(countOrderedCodeBlockOccurrences(haystack, `
beta = micro.beta()
gamma = micro.gamma()
`), 1);
});

test("anchored code block verification ignores comment-only matches", () => {
  const haystack = `
// import owner/lib/7 as micro
// beta = micro.beta()
// gamma = micro.gamma()
import owner/lib/7 as micro
alpha = micro.alpha()
`;

  assert.equal(containsAnchoredCodeBlockAfterLine(
    haystack,
    "import owner/lib/7 as micro",
    `
beta = micro.beta()
gamma = micro.gamma()
`,
  ), false);
});

test("anchored code block verification uses the block directly after the matching import anchor", () => {
  const haystack = `
import other/lib/7 as micro
beta = micro.beta()
gamma = micro.gamma()
import owner/lib/7 as micro
beta = micro.beta()
gamma = micro.gamma()
`;

  assert.equal(containsAnchoredCodeBlockAfterLine(
    haystack,
    "import owner/lib/7 as micro",
    `
beta = micro.beta()
gamma = micro.gamma()
`,
  ), true);
});

test("anchored code block verification fails when anchored block is not contiguous", () => {
  const haystack = `
import owner/lib/7 as micro
beta = micro.beta()
delta = micro.delta()
gamma = micro.gamma()
`;

  assert.equal(containsAnchoredCodeBlockAfterLine(
    haystack,
    "import owner/lib/7 as micro",
    `
beta = micro.beta()
gamma = micro.gamma()
`,
  ), false);
});

test("scriptNameAppearsInUiText matches normalized UI text", () => {
  assert.equal(scriptNameAppearsInUiText(CORE_SCRIPT, "Editor tab: SMC   Core"), true);
  assert.equal(scriptNameAppearsInUiText(CORE_SCRIPT, "Editor tab: unrelated script"), false);
});

test("uiTextContainsExactScriptName rejects similar names", () => {
  assert.equal(uiTextContainsExactScriptName(CORE_SCRIPT, CORE_SCRIPT), true);
  assert.equal(uiTextContainsExactScriptName(CORE_SCRIPT, "SMC Core Pro"), false);
  assert.equal(uiTextContainsExactScriptName(CORE_SCRIPT, "SMC Core Suite"), false);
  assert.equal(uiTextContainsExactScriptName(CORE_SCRIPT, "SMC Core Copy"), false);
  assert.equal(uiTextContainsExactScriptName(CORE_SCRIPT, "SMC Core - backup"), false);
});

test("verifyOpenScriptIdentity fails when dialog closes but wrong script is open", () => {
  assert.equal(verifyOpenScriptIdentity(CORE_SCRIPT, {
    dialogStillVisible: false,
    editorContextTexts: [DECISION_BOARD_SCRIPT],
    bodyText: "SMC Core appears in the scripts list",
  }), false);
});

test("verifyOpenScriptIdentity fails for similar-name match only", () => {
  assert.equal(verifyOpenScriptIdentity(CORE_SCRIPT, {
    dialogStillVisible: false,
    editorContextTexts: ["SMC Core Suite"],
    bodyText: CORE_SCRIPT,
  }), false);
});

test("verifyOpenScriptIdentity passes for truncated canonical title", () => {
  assert.equal(verifyOpenScriptIdentity(DECISION_BOARD_SCRIPT, {
    dialogStillVisible: false,
    editorContextTexts: [DECISION_BOARD_TRUNCATED],
    bodyText: `Workspace body ${DECISION_BOARD_SCRIPT}`,
  }), true);
});

test("verifyOpenScriptIdentity passes for exact name in editor context", () => {
  assert.equal(verifyOpenScriptIdentity(CORE_SCRIPT, {
    dialogStillVisible: false,
    editorContextTexts: [CORE_SCRIPT],
    bodyText: `Workspace body ${CORE_SCRIPT}`,
  }), true);
});

test("verifyOpenScriptIdentity tolerates truncated companion context", () => {
  assert.equal(verifyOpenScriptIdentity(DECISION_BOARD_SCRIPT, {
    dialogStillVisible: false,
    editorContextTexts: [DECISION_BOARD_SCRIPT, DECISION_BOARD_TRUNCATED],
    bodyText: `Workspace body ${DECISION_BOARD_SCRIPT}`,
  }), true);
});

test("verifyOpenScriptIdentity tolerates spaced-letter companion context", () => {
  assert.equal(verifyOpenScriptIdentity(CORE_SCRIPT, {
    dialogStillVisible: false,
    editorContextTexts: [CORE_SCRIPT, "S M C C o r e"],
    bodyText: `Workspace body ${CORE_SCRIPT}`,
  }), true);
});

test("verifyOpenScriptIdentity tolerates version-metadata companion context", () => {
  assert.equal(verifyOpenScriptIdentity("smc_micro_profiles_generated", {
    dialogStillVisible: false,
    editorContextTexts: [
      "smc_micro_profiles_generated",
      "s m c _ m i c r o _ p r o f i l e s _ g e n e r a t e d Version: 13.0 (05.04.2026 19:43)",
    ],
    bodyText: "Workspace body smc_micro_profiles_generated",
  }), true);
});

test("verifyOpenScriptIdentity tolerates import-line companion context", () => {
  assert.equal(verifyOpenScriptIdentity("smc_micro_profiles_generated", {
    dialogStillVisible: false,
    editorContextTexts: [
      "smc_micro_profiles_generated",
      "// import preuss_steffen/smc_micro_profiles_generated/1 as mp",
    ],
    bodyText: "Workspace body smc_micro_profiles_generated",
  }), true);
});

test("verifyOpenScriptIdentity tolerates Pine declaration companion context when the shorttitle matches", () => {
  assert.equal(verifyOpenScriptIdentity(CORE_SCRIPT, {
    dialogStillVisible: false,
    editorContextTexts: [
      CORE_SCRIPT,
      'indicator("SMC Core Engine", "SMC Core", overlay = true)',
    ],
    bodyText: `Workspace body ${CORE_SCRIPT}`,
  }), true);
});

test("verifyOpenScriptIdentity tolerates non-identity editor code companion context", () => {
  assert.equal(verifyOpenScriptIdentity(CORE_SCRIPT, {
    dialogStillVisible: false,
    editorContextTexts: [
      CORE_SCRIPT,
      "preuss_steffen/smc_core_types/1",
      "lBreakMode, ct.SignalMode) live in smc_core_types",
    ],
    bodyText: `Workspace body ${CORE_SCRIPT}`,
  }), true);
});

test("verifyOpenScriptIdentity accepts semantic version suffix context", () => {
  assert.equal(verifyOpenScriptIdentity("SkippALGO", {
    dialogStillVisible: false,
    editorContextTexts: ["SkippALGO v6.3.13"],
    bodyText: "Workspace body SkippALGO v6.3.13",
  }), true);
});

test("verifyOpenScriptIdentity fails closed on conflicting canonical editor context", () => {
  assert.equal(verifyOpenScriptIdentity(CORE_SCRIPT, {
    dialogStillVisible: false,
    editorContextTexts: [CORE_SCRIPT, DECISION_BOARD_SCRIPT],
    bodyText: `Workspace body ${CORE_SCRIPT}`,
  }), false);
});

test("verifyOpenScriptIdentity rejects similar suite names", () => {
  assert.equal(verifyOpenScriptIdentity(CORE_SCRIPT, {
    dialogStillVisible: false,
    editorContextTexts: [CORE_SCRIPT, "SMC Core Suite"],
  }), false);
});

test("verifyOpenScriptIdentity treats parenthesized version suffix as conflict", () => {
  assert.equal(verifyOpenScriptIdentity(CORE_SCRIPT, {
    dialogStillVisible: false,
    editorContextTexts: [CORE_SCRIPT, "SMC Core (v2)"],
  }), false);
});

test("verifyOpenScriptIdentity treats lone parenthesized version suffix as conflict", () => {
  assert.equal(verifyOpenScriptIdentity(CORE_SCRIPT, {
    dialogStillVisible: false,
    editorContextTexts: ["SMC Core (v2)"],
    bodyText: `Workspace body ${CORE_SCRIPT}`,
  }), false);
});

test("verifyOpenScriptIdentity treats copy suffix as conflict", () => {
  assert.equal(verifyOpenScriptIdentity(CORE_SCRIPT, {
    dialogStillVisible: false,
    editorContextTexts: [CORE_SCRIPT, "SMC Core - copy"],
  }), false);
});

test("verifyOpenScriptIdentity rejects lone copy suffix", () => {
  assert.equal(verifyOpenScriptIdentity(CORE_SCRIPT, {
    dialogStillVisible: false,
    editorContextTexts: ["SMC Core - copy"],
    bodyText: `Workspace body ${CORE_SCRIPT}`,
  }), false);
});

test("verifyOpenScriptIdentity fails closed for multiple similar conflicting contexts", () => {
  assert.equal(verifyOpenScriptIdentity(CORE_SCRIPT, {
    dialogStillVisible: false,
    editorContextTexts: [CORE_SCRIPT, "SMC Core (v2)", "SMC Core - copy"],
  }), false);
});

test("verifyOpenScriptIdentity fails when body text matches accidentally but editor context is missing", () => {
  assert.equal(verifyOpenScriptIdentity(CORE_SCRIPT, {
    dialogStillVisible: false,
    editorContextTexts: [],
    bodyText: "Search results still mention SMC Core",
  }), false);
});

test("resolveOpenScriptIdentityEvidence reports explicit identity mode", () => {
  assert.deepEqual(resolveOpenScriptIdentityEvidence(CORE_SCRIPT, {
    dialogStillVisible: false,
    editorContextTexts: [CORE_SCRIPT],
  }), {
    verified: true,
    verificationMode: "script_context",
  });
  assert.deepEqual(resolveOpenScriptIdentityEvidence(CORE_SCRIPT, {
    dialogStillVisible: false,
    editorContextTexts: [DECISION_BOARD_SCRIPT],
  }), {
    verified: false,
    verificationMode: "not_verified",
  });
});

test("verifyOpenScriptIdentity accepts publish dialog companion texts", () => {
  // Exact evidence from failed overlay publish run 27170210008:
  // TradingView shows "Update '<name>' library" dialog title alongside the script name.
  assert.equal(verifyOpenScriptIdentity("smc_overlay_generated", {
    dialogStillVisible: false,
    editorContextTexts: ["smc_overlay_generated", "Update 'smc_overlay_generated' library"],
  }), true);

  // With extra "Minimize Close" text appended by TradingView panel chrome
  assert.equal(verifyOpenScriptIdentity("smc_overlay_generated", {
    dialogStillVisible: false,
    editorContextTexts: ["smc_overlay_generated", "Update 'smc_overlay_generated' library Minimize Close"],
  }), true);

  // "Publish '<name>'" pattern
  assert.equal(verifyOpenScriptIdentity("smc_overlay_generated", {
    dialogStillVisible: false,
    editorContextTexts: ["smc_overlay_generated", "Publish 'smc_overlay_generated'"],
  }), true);

  // Curly double quotes around script name (TradingView may use typographic quotes)
  assert.equal(verifyOpenScriptIdentity("smc_overlay_generated", {
    dialogStillVisible: false,
    editorContextTexts: ["smc_overlay_generated", "Update \u201Csmc_overlay_generated\u201D library"],
  }), true);

  // Publish dialog title alone (no separate script-name evidence) — companion only, not identity
  assert.equal(verifyOpenScriptIdentity("smc_overlay_generated", {
    dialogStillVisible: false,
    editorContextTexts: ["Update 'smc_overlay_generated' library"],
  }), false, "dialog title alone is not identity evidence \u2014 it is only a companion");

  // Wrong script name in dialog → still conflicts
  assert.equal(verifyOpenScriptIdentity(CORE_SCRIPT, {
    dialogStillVisible: false,
    editorContextTexts: [CORE_SCRIPT, "Update 'SMC Decision Board' library"],
  }), false, "dialog title naming a different script must still conflict");
});

test("settings dialog identity check rejects mismatched titled dialogs", () => {
  assert.equal(settingsDialogTitleMatchesScriptName(CORE_SCRIPT, DECISION_BOARD_SCRIPT), false);
  assert.equal(settingsDialogTitleMatchesScriptName(CORE_SCRIPT, CORE_SCRIPT), true);
  assert.equal(settingsDialogTitleMatchesScriptName(CORE_SCRIPT, ""), false);
});

test("buildScriptNamePatterns fuzzy does not match word supersets", () => {
  const [, , fuzzyPattern] = buildScriptNamePatterns(CORE_SCRIPT);

  assert.equal(fuzzyPattern.test("SMC Corex"), false);
  assert.equal(fuzzyPattern.test(CORE_SCRIPT), true);
});

test("detectPublishedVersionFromBody anchors version to the target script when provided", () => {
  const bodyText = "Release notes version 99. Published SMC Core version 7 successfully.";

  assert.equal(detectPublishedVersionFromBody(bodyText, CORE_SCRIPT), 7);
  assert.equal(detectPublishedVersionFromBody(bodyText, DECISION_BOARD_SCRIPT), null);
});

test("detectPublishedVersionFromContextTexts only accepts target-script context", () => {
  assert.equal(detectPublishedVersionFromContextTexts([
    "Published SMC Core version 7 successfully.",
  ], CORE_SCRIPT), 7);
  assert.equal(detectPublishedVersionFromContextTexts([
    "Generic publish version 7 successfully.",
  ], CORE_SCRIPT), null);
});

test("detectPublishedVersionFromContextTexts rejects similar-name supersets", () => {
  assert.equal(detectPublishedVersionFromContextTexts([
    "SMC Core Suite version 7",
  ], CORE_SCRIPT), null);
  assert.equal(detectPublishedVersionFromContextTexts([
    "SMC Core (v2) version 7",
  ], CORE_SCRIPT), null);
  assert.equal(detectPublishedVersionFromContextTexts([
    "Published SMC Core version 7 successfully.",
  ], CORE_SCRIPT), 7);
});

test("detectPublishedVersionFromBody rejects similar-name supersets", () => {
  assert.equal(detectPublishedVersionFromBody("SMC Core Suite version 7", CORE_SCRIPT), null);
  assert.equal(detectPublishedVersionFromBody("SMC Core (v2) version 7", CORE_SCRIPT), null);
});

test("detectPublishedVersionFromContextTexts fails closed on multiple target versions", () => {
  assert.equal(detectPublishedVersionFromContextTexts([
    "Published SMC Core version 7 successfully.",
    "Published SMC Core version 8 successfully.",
  ], CORE_SCRIPT), null);
});

test("detectPublishedVersionFromBody fails closed on multiple target versions", () => {
  assert.equal(
    detectPublishedVersionFromBody(
      "Published SMC Core version 7 successfully. Later dialog repeated SMC Core version 8.",
      CORE_SCRIPT,
    ),
    null,
  );
});

test("resolvePublishedVersionEvidence marks generic body-only evidence as fallback", () => {
  assert.deepEqual(resolvePublishedVersionEvidence({
    scriptName: CORE_SCRIPT,
    versionContextTexts: [],
    bodyText: "Release notes version 99. Published SMC Core version 7 successfully.",
  }), {
    publishedVersion: 7,
    verificationMode: "body_fallback",
    fallbackVersion: 7,
  });
});

test("resolvePublishedVersionEvidence prefers script-context version evidence", () => {
  assert.deepEqual(resolvePublishedVersionEvidence({
    scriptName: CORE_SCRIPT,
    versionContextTexts: ["SMC Core version 7"],
    bodyText: "Release notes version 99.",
  }), {
    publishedVersion: 7,
    verificationMode: "version_context",
    fallbackVersion: null,
  });
});

test("resolvePublishedVersionEvidence fails closed when no reliable evidence exists", () => {
  assert.deepEqual(resolvePublishedVersionEvidence({
    scriptName: CORE_SCRIPT,
    versionContextTexts: [],
    bodyText: "Published successfully.",
  }), {
    publishedVersion: null,
    verificationMode: "not_verified",
    fallbackVersion: null,
  });
});

test("resolvePublishedVersionEvidence fails closed on conflicting script-context versions", () => {
  assert.deepEqual(resolvePublishedVersionEvidence({
    scriptName: CORE_SCRIPT,
    versionContextTexts: [
      "Published SMC Core version 7 successfully.",
      "Published SMC Core version 8 successfully.",
    ],
    bodyText: "Release notes version 99.",
  }), {
    publishedVersion: null,
    verificationMode: "not_verified",
    fallbackVersion: null,
  });
});

test("resolvePublishNoChangeCleanupActions keeps no-change cleanup on escape-only fallbacks", () => {
  assert.deepEqual(resolvePublishNoChangeCleanupActions({
    dialogClosed: false,
    publishSurfaceVisible: true,
  }), {
    shouldPressDialogEscape: true,
    shouldDismissPublishSurface: true,
    cleanupComplete: false,
  });

  assert.deepEqual(resolvePublishNoChangeCleanupActions({
    dialogClosed: true,
    publishSurfaceVisible: true,
  }), {
    shouldPressDialogEscape: false,
    shouldDismissPublishSurface: true,
    cleanupComplete: false,
  });

  assert.deepEqual(resolvePublishNoChangeCleanupActions({
    dialogClosed: true,
    publishSurfaceVisible: false,
  }), {
    shouldPressDialogEscape: false,
    shouldDismissPublishSurface: false,
    cleanupComplete: true,
  });
});

test("collectVisibleLocatorMetadata samples all visible candidates instead of first-hit only", async () => {
  const nodes = [
    { visible: true, text: CORE_SCRIPT, ariaLabel: "", title: "" },
    { visible: true, text: DECISION_BOARD_SCRIPT, ariaLabel: "", title: "Decision Board" },
    { visible: false, text: "ignored", ariaLabel: "", title: "" },
  ];
  const locator = {
    count: async () => nodes.length,
    nth: (index: number) => ({
      isVisible: async () => nodes[index].visible,
      innerText: async () => nodes[index].text,
      getAttribute: async (name: string) => {
        if (name === "aria-label") {
          return nodes[index].ariaLabel;
        }
        if (name === "title") {
          return nodes[index].title;
        }
        return "";
      },
    }),
  };

  assert.deepEqual(await collectVisibleLocatorMetadata(locator as never, 5), [
    { text: CORE_SCRIPT, ariaLabel: "", title: "" },
    { text: DECISION_BOARD_SCRIPT, ariaLabel: "", title: "Decision Board" },
  ]);
});

test("TV_SKIP_AUTH_STATE_VALIDATION emits a warning and bypasses validation", () => {
  const previous = process.env.TV_SKIP_AUTH_STATE_VALIDATION;
  const messages: string[] = [];
  const originalError = console.error;

  process.env.TV_SKIP_AUTH_STATE_VALIDATION = "1";
  console.error = (...args: unknown[]) => {
    messages.push(args.map((arg) => String(arg)).join(" "));
  };

  try {
    validateTradingViewStorageState("/path/that/is/not_checked.json");
  } finally {
    console.error = originalError;
    if (previous == null) {
      delete process.env.TV_SKIP_AUTH_STATE_VALIDATION;
    } else {
      process.env.TV_SKIP_AUTH_STATE_VALIDATION = previous;
    }
  }

  assert.equal(messages.some((message) => message.includes("TV_SKIP_AUTH_STATE_VALIDATION=1 is set")), true);
});

// Regression coverage for findLegendRowWrappers. Two production fixes shipped
// during the SMC library-refresh debugging both passed the existing tests yet
// failed in production:
//   * `.//button` matched 123 ancestors (page chrome) — too broad.
//   * `./button`  matched the empty actions-container (depth 1) — too narrow.
// The ancestor-walk implementation must climb from the legend-settings button
// up to the row that actually carries the script-name text. These tests model
// that DOM shape directly so neither failure mode can recur silently.
const LEGEND_BUTTON_SELECTOR = 'button[data-qa-id="legend-settings-action"]';

type FakeAncestor = { __depth: number; innerText: (opts?: unknown) => Promise<string> };
type FakeButton = {
  isVisible: (opts?: unknown) => Promise<boolean>;
  locator: (selector: string) => FakeAncestor;
};

function makeLegendButton(textByDepth: Record<number, string>, visible = true): FakeButton {
  return {
    isVisible: async () => visible,
    locator: (selector: string) => {
      // selector arrives as `xpath=..`, `xpath=../..`, or `xpath=../../..`.
      if (!selector.startsWith("xpath=")) {
        throw new Error(`expected xpath= prefix, got: ${selector}`);
      }
      const xpath = selector.slice("xpath=".length);
      if (!/^(\.\.)(\/\.\.)*$/.test(xpath)) {
        throw new Error(`expected ancestor-only xpath (../.. shape), got: ${xpath}`);
      }
      const depth = xpath.split("/").filter((segment) => segment === "..").length;
      return {
        __depth: depth,
        innerText: async () => textByDepth[depth] ?? "",
      };
    },
  };
}

function makeLegendPage(buttons: FakeButton[]) {
  return {
    locator: (selector: string) => {
      if (selector === LEGEND_BUTTON_SELECTOR) {
        return {
          count: async () => buttons.length,
          nth: (index: number) => buttons[index],
        };
      }
      throw new Error(`unexpected selector in test: ${selector}`);
    },
  };
}

test("findLegendRowWrappers climbs to the legend row when depth-1 is the empty action-container", async () => {
  const scriptName = "SMC Long-Dip Dashboard v7";
  // depth 1 = actions-container (empty) — this is what `./button` wrongly matched.
  const button = makeLegendButton({ 1: "", 2: scriptName, 3: "Chart navigation toolbar chrome" });

  const wrappers = await findLegendRowWrappers(makeLegendPage([button]) as never, scriptName);

  assert.equal(wrappers.length, 1, "should resolve exactly one legend row wrapper");
  assert.equal(
    (wrappers[0] as unknown as FakeAncestor).__depth,
    2,
    "must match the grandparent legend row (depth 2), not the empty action-container (depth 1)",
  );
});

test("findLegendRowWrappers ignores buttons whose ancestors only contain page chrome", async () => {
  const scriptName = "SMC Long-Dip Dashboard v7";
  // None of the ancestor levels carry the script name — this models the broad
  // `.//button` failure where matched wrappers were toolbars / navigation.
  const chromeButton = makeLegendButton({ 1: "", 2: "Indicators templates alerts", 3: "Header toolbar" });

  const wrappers = await findLegendRowWrappers(makeLegendPage([chromeButton]) as never, scriptName);

  assert.equal(wrappers.length, 0, "page-chrome-only ancestors must not be treated as legend rows");
});

test("findLegendRowWrappers returns the shallowest ancestor that carries the script name", async () => {
  const scriptName = "SMC Long-Dip Dashboard v7";
  // When multiple ancestor levels contain the name, the row closest to the
  // button wins so we operate on the tightest legend element, not an outer container.
  const button = makeLegendButton({ 1: scriptName, 2: `${scriptName} extra panel`, 3: `${scriptName} outer` });

  const wrappers = await findLegendRowWrappers(makeLegendPage([button]) as never, scriptName);

  assert.equal(wrappers.length, 1, "should resolve exactly one legend row wrapper");
  assert.equal(
    (wrappers[0] as unknown as FakeAncestor).__depth,
    1,
    "the shallowest matching ancestor (depth 1) must win",
  );
});

test("findLegendRowWrappers skips invisible legend buttons", async () => {
  const scriptName = "SMC Long-Dip Dashboard v7";
  const hiddenButton = makeLegendButton({ 1: "", 2: scriptName }, false);

  const wrappers = await findLegendRowWrappers(makeLegendPage([hiddenButton]) as never, scriptName);

  assert.equal(wrappers.length, 0, "invisible legend buttons must be ignored");
});
import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";

import {
  buildScriptNamePatterns,
  collectTradingViewPageAuthState,
  countOrderedCodeBlockOccurrences,
  collectVisibleLocatorMetadata,
  editorDiagnosticsSuggestOpenHost,
  indicatorsMyScriptsShowsMatchingPrivateScript,
  openScriptSurfaceLooksReady,
  resolvePublishNoChangeCleanupActions,
  resolveOpenScriptIdentityEvidence,
  resolveOpenScriptSearchNames,
  resolveTradingViewPageAuthState,
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
  isLegendTruncatedMatch,
  hasSettingsSurfaceDomHint,
  dismissOverlapManagerOverlay,
  hasAddToChartClickEffect,
  clickVisibleWithFallback,
  MAX_VISIBLE_LEGEND_TEXT_TARGETS,
  VISIBLE_LEGEND_TEXT_SETTINGS_BUDGET_MS,
  visibleLegendTextBudgetExceeded,
  visibleLegendTextTargetCapReached,
  visibleLegendTextTargetKey,
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

test("ensurePineEditor neutralises #overlap-manager-root [data-id] blocker before clicking Pine button (A1 regression)", async () => {
  // Regression for run #27773053223: container-VeoIyDt4 inside overlap-manager-root
  // blocked the Pine editor button. ensurePineEditor must call
  // dismissOverlapManagerOverlay() so the JS pointer-events bypass fires and
  // the Pine button becomes clickable.
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  try {
    await page.setContent(`
      <html><body>
        <button type="button" id="pine-open">Pine</button>
        <div id="overlap-manager-root">
          <div class="container-VeoIyDt4">
            <div data-id="blockingTooltip"
                 style="position:fixed;inset:0;z-index:9999;pointer-events:all">
            </div>
          </div>
        </div>
        <script>
          document.getElementById("pine-open").addEventListener("click", () => {
            if (!document.querySelector('[data-name="pine-dialog"]')) {
              const host = document.createElement("div");
              host.setAttribute("data-name", "pine-dialog");
              host.textContent = "Pine editor ready";
              document.body.appendChild(host);
            }
          });
        </script>
      </body></html>
    `);

    await ensurePineEditor(page);

    // Pine editor must be visible after the overlay was neutralised
    assert.equal(
      await page.locator('[data-name="pine-dialog"]').isVisible(),
      true,
      "Pine editor must open after overlay is neutralised",
    );
    // The [data-id] overlay must have pointer-events:none so it no longer blocks
    const overlayPe = await page
      .locator("#overlap-manager-root [data-id]")
      .evaluate((el) => (el as HTMLElement).style.pointerEvents);
    assert.equal(overlayPe, "none", "[data-id] overlay must be neutralised by JS bypass");
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
  assert.deepEqual(
    resolveOpenScriptSearchNames("SMC Decision Board"),
    ["SMC Decision Board", "SMC Long-Dip Dashboard v7", "SMC Dashboard"],
  );
  assert.deepEqual(
    resolveOpenScriptSearchNames("SMC Execution"),
    ["SMC Execution", "SMC Long-Dip Strategy v7", "SMC Long Strategy"],
  );
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

test("settings dialog identity matches TradingView-truncated titles", () => {
  // Dashboard truncated to "SMC Dash" (observed in run 27215753224)
  assert.equal(settingsDialogTitleMatchesScriptName("SMC Long-Dip Dashboard v7", "SMC Dash"), true);
  // Strategy truncated to "SMC Long Strategy" (observed in run 27215753224)
  assert.equal(settingsDialogTitleMatchesScriptName("SMC Long-Dip Strategy v7", "SMC Long Strategy"), true);
  // Unrelated script must still be rejected
  assert.equal(settingsDialogTitleMatchesScriptName("SMC Long-Dip Dashboard v7", "Vol"), false);
  // Matches valid alias via symmetric lookup now
  assert.equal(settingsDialogTitleMatchesScriptName("SMC Long-Dip Dashboard v7", "SMC Decision Board"), true);
});

test("settings dialog identity matches legacy and candidate search names", () => {
  assert.equal(settingsDialogTitleMatchesScriptName("SMC Decision Board", "SMC Long-Dip Dashboard v7"), true);
  assert.equal(settingsDialogTitleMatchesScriptName("SMC Long-Dip Dashboard v7", "SMC Decision Board"), true);
  assert.equal(settingsDialogTitleMatchesScriptName("SMC Decision Board", "SMC Dashboard"), true);
  assert.equal(settingsDialogTitleMatchesScriptName("SMC Long-Dip Strategy v7", "SMC Execution"), true);
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

test("TradingView page auth state rejects explicit anonymous HTML", () => {
  const state = resolveTradingViewPageAuthState({
    url: "https://www.tradingview.com/chart/",
    htmlClass: "is-not-authenticated theme-light",
    bodyText: "AAPL chart",
    accountProbeStatuses: [403, 403],
    accountProbeAuthenticated: false,
    accountProbeAnonymous: true,
  });

  assert.equal(state.authenticated, false);
  assert.equal(state.explicitlyAnonymous, true);
  assert.equal(state.reason, "html_class_is_not_authenticated");
});

test("TradingView page auth state accepts positive account probe", () => {
  const state = resolveTradingViewPageAuthState({
    url: "https://www.tradingview.com/chart/",
    htmlClass: "theme-light",
    bodyText: "AAPL chart",
    accountProbeStatuses: [200],
    accountProbeAuthenticated: true,
    accountProbeAnonymous: false,
  });

  assert.equal(state.authenticated, true);
  assert.equal(state.explicitlyAnonymous, false);
  assert.equal(state.reason, "account_probe_authenticated");
});

test("TradingView page auth probe emits trace status monitoring", async () => {
  const browser = await chromium.launch({ headless: true });
  const messages: string[] = [];
  const originalError = console.error;

  console.error = (...args: unknown[]) => {
    messages.push(args.map((arg) => String(arg)).join(" "));
  };

  try {
    const page = await browser.newPage();
    await page.route("**/chart/", (route) => route.fulfill({
      contentType: "text/html",
      body: '<!doctype html><html class="theme-light"><body>AAPL chart</body></html>',
    }));
    await page.route("**/api/v1/user/profile/me/", (route) => route.fulfill({
      status: 403,
      contentType: "text/plain",
      body: "authentication credentials missing",
    }));
    await page.route("**/api/v1/users/me/", (route) => route.fulfill({
      status: 403,
      contentType: "text/plain",
      body: "authentication credentials missing",
    }));

    await page.goto("https://www.tradingview.com/chart/");
    const state = await collectTradingViewPageAuthState(page);

    assert.equal(state.authenticated, false);
    assert.equal(state.reason, "account_probe_rejected:403,403");
    assert.equal(messages.some((message) =>
      message.includes("[tv-trace] auth-state-probe")
      && message.includes("accountProbeStatuses=403,403")
      && message.includes("reason=account_probe_rejected:403,403")
    ), true);
  } finally {
    console.error = originalError;
    await browser.close();
  }
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

// --- isLegendTruncatedMatch: TradingView name truncation ---

test("isLegendTruncatedMatch recognises TradingView-truncated Dashboard name", () => {
  // TradingView legend shows "SMC Dash" for "SMC Long-Dip Dashboard v7"
  assert.equal(isLegendTruncatedMatch("SMC Dash", "SMC Long-Dip Dashboard v7"), true);
});

test("isLegendTruncatedMatch recognises truncated name with version suffix", () => {
  // After a duplicate is added TV appends "· 22.0"
  assert.equal(isLegendTruncatedMatch("SMC Dash · 22.0", "SMC Long-Dip Dashboard v7"), true);
});

test("isLegendTruncatedMatch recognises truncated Strategy name", () => {
  assert.equal(isLegendTruncatedMatch("SMC Long Strategy", "SMC Long-Dip Strategy v7"), true);
});

test("isLegendTruncatedMatch rejects unrelated indicators", () => {
  assert.equal(isLegendTruncatedMatch("SMC Core", "SMC Long-Dip Dashboard v7"), false);
  assert.equal(isLegendTruncatedMatch("LuxAlgo - Ultimate RSI", "SMC Long-Dip Dashboard v7"), false);
  assert.equal(isLegendTruncatedMatch("Vol", "SMC Long-Dip Dashboard v7"), false);
  assert.equal(isLegendTruncatedMatch("My script", "SMC Long-Dip Dashboard v7"), false);
});

test("isLegendTruncatedMatch rejects similar but wrong scripts", () => {
  // "SMC Decision Board" must NOT match "SMC Long-Dip Dashboard v7"
  assert.equal(isLegendTruncatedMatch("SMC Decision Board · 31.0", "SMC Long-Dip Dashboard v7"), false);
  assert.equal(isLegendTruncatedMatch("SMC Decision Board", "SMC Long-Dip Dashboard v7"), false);
});

test("isLegendTruncatedMatch requires at least 2 legend words", () => {
  // Single-word legend text must not produce false positives
  assert.equal(isLegendTruncatedMatch("SMC", "SMC Long-Dip Dashboard v7"), false);
  assert.equal(isLegendTruncatedMatch("Dash", "SMC Long-Dip Dashboard v7"), false);
});

test("isLegendTruncatedMatch exact full name matches", () => {
  assert.equal(isLegendTruncatedMatch("SMC Long-Dip Dashboard v7", "SMC Long-Dip Dashboard v7"), true);
  assert.equal(isLegendTruncatedMatch("SMC Core", "SMC Core"), true);
});

// --- dismissOverlapManagerOverlay: #overlap-manager-root blocking overlay ---

test("dismissOverlapManagerOverlay is a no-op when #overlap-manager-root has no [data-id] children", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  try {
    await page.setContent(`
      <html><body>
        <div id="overlap-manager-root">
          <div class="container-VeoIyDt4"><!-- empty: no [data-id] child --></div>
        </div>
      </body></html>`);
    await dismissOverlapManagerOverlay(page);
    // pointer-events must NOT have been touched
    const pe = await page
      .locator("#overlap-manager-root .container-VeoIyDt4")
      .evaluate((el) => (el as HTMLElement).style.pointerEvents);
    assert.equal(pe, "", "pointer-events must not be set when no overlay was present");
  } finally {
    await browser.close();
  }
});

test("dismissOverlapManagerOverlay applies JS pointer-events:none when overlay persists after mouse-move + Escape", async () => {
  // Simulates the 4th-step fallback: a synthetic [data-id] overlay that will NOT
  // disappear after mouse.move(0,0) or Escape (no event listeners in static DOM).
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  try {
    await page.setContent(`
      <html><body>
        <div id="overlap-manager-root">
          <div class="container-VeoIyDt4">
            <div data-id="U5quI2xP71yE1h2MZuK78"
                 style="pointer-events:all;position:fixed;inset:0;z-index:9999">
              <!-- blocking overlay -->
            </div>
          </div>
        </div>
      </body></html>`);
    await dismissOverlapManagerOverlay(page);
    // Bypass must target only the [data-id] element — NOT the portal container
    const overlayPe = await page
      .locator("#overlap-manager-root [data-id]")
      .evaluate((el) => (el as HTMLElement).style.pointerEvents);
    assert.equal(overlayPe, "none", "JS bypass must set pointer-events:none on the blocking [data-id] element");
    // Portal container must be untouched so future dialogs (e.g. Indicators) still render
    const containerPe = await page
      .locator("#overlap-manager-root .container-VeoIyDt4")
      .evaluate((el) => (el as HTMLElement).style.pointerEvents);
    assert.equal(containerPe, "", "portal container pointer-events must remain unchanged — it hosts future dialogs");
  } finally {
    await browser.close();
  }
});

test("dismissOverlapManagerOverlay applies JS bypass for dynamic data-id tooltip pattern", async () => {
  // Regression for runs #27750634938–#27773053223: dynamic data-id across
  // attempts indicates a hover-tooltip. Verify the full 4-step path fires:
  // mouse.move → outerHTML log → Escape (no-op in static DOM) → JS bypass.
  // Only the [data-id] element gets pointer-events:none; container is untouched.
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  try {
    await page.setContent(`
      <html><body>
        <div id="overlap-manager-root">
          <div class="container-VeoIyDt4">
            <div data-id="Od_eqor7i1RFijJcecEWe">tooltip content</div>
          </div>
        </div>
      </body></html>`);
    await dismissOverlapManagerOverlay(page);
    const overlayPe = await page
      .locator("#overlap-manager-root [data-id]")
      .evaluate((el) => (el as HTMLElement).style.pointerEvents);
    assert.equal(overlayPe, "none", "JS bypass must neutralise [data-id] overlay regardless of dynamic data-id value");
    const containerPe = await page
      .locator("#overlap-manager-root .container-VeoIyDt4")
      .evaluate((el) => (el as HTMLElement).style.pointerEvents);
    assert.equal(containerPe, "", "portal container must remain untouched after JS bypass");
  } finally {
    await browser.close();
  }
});

// --- findLegendRowWrappers: truncated legend name regression ---

test("findLegendRowWrappers matches ancestor with truncated TradingView display name", async () => {
  const scriptName = "SMC Long-Dip Dashboard v7";
  // TradingView shows "SMC Dash" — the truncated name — in the legend row
  const button = makeLegendButton({ 1: "", 2: "SMC Dash" });

  const wrappers = await findLegendRowWrappers(makeLegendPage([button]) as never, scriptName);

  assert.equal(wrappers.length, 1, "truncated legend name 'SMC Dash' must match 'SMC Long-Dip Dashboard v7'");
  assert.equal(
    (wrappers[0] as unknown as FakeAncestor).__depth,
    2,
    "must match at depth 2 where the truncated text lives",
  );
});

test("settings surface DOM hint accepts visible settings dialogs and menus", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  try {
    await page.setContent(`
      <html><body>
        <div id="overlap-manager-root">
          <div role="dialog" style="position:absolute;left:40px;top:40px;width:320px;height:180px;background:white">
            <h2>SMC Decision Board</h2>
            <div>Inputs</div>
            <div>Style</div>
            <div>Visibility</div>
          </div>
        </div>
      </body></html>
    `);
    assert.equal(await hasSettingsSurfaceDomHint(page), true);

    await page.setContent(`
      <html><body>
        <div id="overlap-manager-root">
          <div role="menu" style="position:absolute;left:40px;top:40px;width:180px;height:80px;background:white">
            <div role="menuitem">Settings...</div>
          </div>
        </div>
      </body></html>
    `);
    assert.equal(await hasSettingsSurfaceDomHint(page), true);
  } finally {
    await browser.close();
  }
});

test("settings surface DOM hint accepts standalone visible Settings actions", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  try {
    await page.setContent(`
      <html><body>
        <button style="position:absolute;left:40px;top:40px;width:96px;height:32px">Settings...</button>
      </body></html>
    `);

    assert.equal(await hasSettingsSurfaceDomHint(page), true);
  } finally {
    await browser.close();
  }
});

test("settings surface DOM hint ignores hidden or unrelated controls", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  try {
    await page.setContent(`
      <html><body>
        <div id="overlap-manager-root">
          <div role="dialog" style="display:none">
            <div>Inputs Style Visibility</div>
          </div>
        </div>
        <button style="position:absolute;left:40px;top:40px;width:96px;height:32px">Preferences</button>
      </body></html>
    `);

    assert.equal(await hasSettingsSurfaceDomHint(page), false);
  } finally {
    await browser.close();
  }
});

// --- clickVisibleWithFallback: centralised hover-tooltip dismissal (#2849) ---

test("clickVisibleWithFallback dismisses hover-only [data-id] overlay via mouse.move(0,0) without dismissOverlapManagerOverlay", async () => {
  // Regression guard for issue #2849: mouse.move(0,0) at the top of
  // clickVisibleWithFallback must cause a hover-only overlay to disappear so
  // the target button becomes clickable — without needing dismissOverlapManagerOverlay.
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  try {
    await page.setContent(`
      <html><body>
        <button id="target" style="position:absolute;left:100px;top:100px">Click me</button>
        <div id="tooltip" data-id="hoverTooltip"
             style="position:fixed;inset:0;pointer-events:all">hover-only blocking overlay</div>
        <script>
          // Simulate TV hover-tooltip: disappears when cursor moves to (0, 0).
          document.addEventListener("mousemove", function(e) {
            if (e.clientX === 0 && e.clientY === 0) {
              var t = document.getElementById("tooltip");
              if (t) t.remove();
            }
          });
          document.getElementById("target").addEventListener("click", function() {
            document.body.insertAdjacentHTML("beforeend", '<div data-name="clicked">ok</div>');
          });
        </script>
      </body></html>
    `);

    const clicked = await clickVisibleWithFallback(
      page,
      [page.locator("#target")],
      "issue-2849-hover-dismiss",
      2_000,
      100,
    );

    assert.equal(clicked, true, "clickVisibleWithFallback must return true after overlay dismissed by mouse.move");
    assert.equal(
      await page.locator('[data-name="clicked"]').isVisible(),
      true,
      "target button must have received the click after hover overlay was dismissed",
    );
  } finally {
    await browser.close();
  }
});

test("clickVisibleWithFallback keeps trying until the optional effect check passes", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  try {
    await page.setContent(`
      <html><body>
        <button id="target" style="position:absolute;left:100px;top:100px">Click me</button>
        <script>
          window.__clicks = 0;
          document.getElementById("target").addEventListener("click", function() {
            window.__clicks += 1;
            if (window.__clicks >= 3 && !document.querySelector('[data-name="clicked"]')) {
              document.body.insertAdjacentHTML("beforeend", '<div data-name="clicked">ok</div>');
            }
          });
        </script>
      </body></html>
    `);

    const clicked = await clickVisibleWithFallback(
      page,
      [page.locator("#target")],
      "effect-checked-click",
      2_000,
      50,
      async () => page.locator('[data-name="clicked"]').isVisible({ timeout: 50 }).catch(() => false),
    );

    assert.equal(clicked, true, "click fallback must keep trying after no-effect clicks");
    assert.equal(
      await page.locator('[data-name="clicked"]').isVisible(),
      true,
      "target effect must be visible before the fallback reports success",
    );
    assert.ok(
      await page.evaluate(() => (window as unknown as { __clicks: number }).__clicks >= 3),
      "fallback should keep clicking until at least the click that creates the effect",
    );
  } finally {
    await browser.close();
  }
});

test("hasAddToChartClickEffect accepts update state and missing Add button", async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent(`
      <html><body>
        <button>Add to chart</button>
        <button>Update on chart</button>
      </body></html>
    `);
    assert.equal(
      await hasAddToChartClickEffect(page, CORE_SCRIPT),
      true,
      "visible Update on chart control means the add click had an effect",
    );

    await page.setContent(`
      <html><body>
        <main>No add-to-chart action is visible anymore</main>
      </body></html>
    `);
    assert.equal(
      await hasAddToChartClickEffect(page, CORE_SCRIPT),
      true,
      "a disappeared Add to chart control is accepted as click effect",
    );
  } finally {
    await browser.close();
  }
});

test("hasAddToChartClickEffect uses visible chart script state when Add button remains", async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent(`
      <html><body>
        <button>Add to chart</button>
        <section data-name="legend-row" style="position:absolute;left:20px;top:20px;width:260px;height:48px">
          <span>${CORE_SCRIPT}</span>
          <button data-qa-id="legend-settings-action">Settings</button>
        </section>
      </body></html>
    `);
    assert.equal(
      await hasAddToChartClickEffect(page, CORE_SCRIPT),
      true,
      "visible legend evidence for the script confirms the add click effect even while the button remains",
    );

    await page.setContent(`
      <html><body>
        <button>Add to chart</button>
        <section data-name="legend-row" style="position:absolute;left:20px;top:20px;width:260px;height:48px">
          <span>Unrelated Script</span>
          <button data-qa-id="legend-settings-action">Settings</button>
        </section>
      </body></html>
    `);
    assert.equal(
      await hasAddToChartClickEffect(page, CORE_SCRIPT),
      false,
      "visible Add button plus unrelated chart text is not enough",
    );
  } finally {
    await browser.close();
  }
});

test("visible legend text target key follows stable DOM identity before geometry", () => {
  const firstPosition = visibleLegendTextTargetKey({
    text: " SMC Decision   Board ",
    domPath: 'div[data-name="legend"]>span:nth-of-type(1)',
    rect: { x: 10, y: 20, width: 180, height: 24 },
  });
  const afterScroll = visibleLegendTextTargetKey({
    text: "SMC Decision Board",
    domPath: 'div[data-name="legend"]>span:nth-of-type(1)',
    rect: { x: 10, y: 460, width: 180, height: 24 },
  });
  const siblingWithSameTextAndBox = visibleLegendTextTargetKey({
    text: "SMC Decision Board",
    domPath: 'div[data-name="legend"]>span:nth-of-type(2)',
    rect: { x: 10, y: 20, width: 180, height: 24 },
  });

  assert.equal(firstPosition, afterScroll);
  assert.notEqual(firstPosition, siblingWithSameTextAndBox);
});

test("visible legend text target key falls back to geometry when DOM identity is absent", () => {
  const first = visibleLegendTextTargetKey({
    text: "SMC Decision Board",
    rect: { x: 10, y: 20, width: 180, height: 24 },
  });
  const moved = visibleLegendTextTargetKey({
    text: "SMC Decision Board",
    rect: { x: 10, y: 460, width: 180, height: 24 },
  });

  assert.notEqual(first, moved);
});

test("visible legend text duplicate targets do not consume the attempt cap", () => {
  const seen = new Set<string>();
  let attemptedTargets = 0;
  const candidates = [
    {
      text: "SMC Decision Board",
      domPath: 'div[data-name="legend"]>span:nth-of-type(1)',
      rect: { x: 10, y: 20, width: 180, height: 24 },
    },
    {
      text: "SMC Decision Board",
      domPath: 'div[data-name="legend"]>span:nth-of-type(1)',
      rect: { x: 10, y: 460, width: 180, height: 24 },
    },
    {
      text: "SMC Decision Board",
      domPath: 'div[data-name="legend"]>span:nth-of-type(2)',
      rect: { x: 10, y: 20, width: 180, height: 24 },
    },
  ];

  for (const candidate of candidates) {
    const key = visibleLegendTextTargetKey(candidate);
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    attemptedTargets += 1;
  }

  assert.equal(attemptedTargets, 2);
  assert.equal(visibleLegendTextTargetCapReached(attemptedTargets), false);
  assert.equal(visibleLegendTextTargetCapReached(MAX_VISIBLE_LEGEND_TEXT_TARGETS), true);
});

test("visible legend text budget is scoped to the legend-text heuristic", () => {
  const startedAt = 1_000;

  assert.equal(
    visibleLegendTextBudgetExceeded(
      startedAt,
      startedAt + VISIBLE_LEGEND_TEXT_SETTINGS_BUDGET_MS,
    ),
    false,
  );
  assert.equal(
    visibleLegendTextBudgetExceeded(
      startedAt,
      startedAt + VISIBLE_LEGEND_TEXT_SETTINGS_BUDGET_MS + 1,
    ),
    true,
  );
});

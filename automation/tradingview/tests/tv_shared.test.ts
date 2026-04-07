import assert from "node:assert/strict";
import test from "node:test";

import {
  buildScriptNamePatterns,
  countOrderedCodeBlockOccurrences,
  collectVisibleLocatorMetadata,
  resolvePublishNoChangeCleanupActions,
  resolveOpenScriptIdentityEvidence,
  settingsDialogTitleMatchesScriptName,
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
    hasScriptNameMatch: false,
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
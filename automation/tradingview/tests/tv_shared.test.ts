import assert from "node:assert/strict";
import test from "node:test";

import {
  buildScriptNamePatterns,
  collectVisibleLocatorMetadata,
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
  assert.equal(scriptNameAppearsInUiText("SMC Core Engine", "Editor tab: SMC   Core Engine"), true);
  assert.equal(scriptNameAppearsInUiText("SMC Core Engine", "Editor tab: unrelated script"), false);
});

test("uiTextContainsExactScriptName rejects similar names", () => {
  assert.equal(uiTextContainsExactScriptName("SMC Core Engine", "SMC Core Engine"), true);
  assert.equal(uiTextContainsExactScriptName("SMC Core Engine", "SMC Core"), false);
  assert.equal(uiTextContainsExactScriptName("SMC Core", "SMC Core Engine"), false);
  assert.equal(uiTextContainsExactScriptName("SMC Core Engine", "SMC Core Engine Copy"), false);
  assert.equal(uiTextContainsExactScriptName("SMC Core Engine", "SMC Core Engine - backup"), false);
});

test("verifyOpenScriptIdentity fails when dialog closes but wrong script is open", () => {
  assert.equal(verifyOpenScriptIdentity("SMC Core Engine", {
    dialogStillVisible: false,
    editorContextTexts: ["SMC Dashboard"],
    bodyText: "SMC Core Engine appears in the scripts list",
  }), false);
});

test("verifyOpenScriptIdentity fails for similar-name match only", () => {
  assert.equal(verifyOpenScriptIdentity("SMC Core Engine", {
    dialogStillVisible: false,
    editorContextTexts: ["SMC Core"],
    bodyText: "SMC Core Engine",
  }), false);
});

test("verifyOpenScriptIdentity passes for exact name in editor context", () => {
  assert.equal(verifyOpenScriptIdentity("SMC Core Engine", {
    dialogStillVisible: false,
    editorContextTexts: ["SMC Core Engine"],
    bodyText: "Workspace body SMC Core Engine",
  }), true);
});

test("verifyOpenScriptIdentity fails closed on conflicting canonical editor context", () => {
  assert.equal(verifyOpenScriptIdentity("SMC Core Engine", {
    dialogStillVisible: false,
    editorContextTexts: ["SMC Core Engine", "SMC Dashboard"],
    bodyText: "Workspace body SMC Core Engine",
  }), false);
});

test("verifyOpenScriptIdentity rejects similar engineering suite names", () => {
  assert.equal(verifyOpenScriptIdentity("SMC Core Engine", {
    dialogStillVisible: false,
    editorContextTexts: ["SMC Core Engine", "SMC Core Engineering Suite"],
  }), false);
});

test("verifyOpenScriptIdentity treats parenthesized version suffix as conflict", () => {
  assert.equal(verifyOpenScriptIdentity("SMC Core Engine", {
    dialogStillVisible: false,
    editorContextTexts: ["SMC Core Engine", "SMC Core Engine (v2)"],
  }), false);
});

test("verifyOpenScriptIdentity treats lone parenthesized version suffix as conflict", () => {
  assert.equal(verifyOpenScriptIdentity("SMC Core Engine", {
    dialogStillVisible: false,
    editorContextTexts: ["SMC Core Engine (v2)"],
    bodyText: "Workspace body SMC Core Engine",
  }), false);
});

test("verifyOpenScriptIdentity fails when body text matches accidentally but editor context is missing", () => {
  assert.equal(verifyOpenScriptIdentity("SMC Core Engine", {
    dialogStillVisible: false,
    editorContextTexts: [],
    bodyText: "Search results still mention SMC Core Engine",
  }), false);
});

test("resolveOpenScriptIdentityEvidence reports explicit identity mode", () => {
  assert.deepEqual(resolveOpenScriptIdentityEvidence("SMC Core Engine", {
    dialogStillVisible: false,
    editorContextTexts: ["SMC Core Engine"],
  }), {
    verified: true,
    verificationMode: "script_context",
  });
  assert.deepEqual(resolveOpenScriptIdentityEvidence("SMC Core Engine", {
    dialogStillVisible: false,
    editorContextTexts: ["SMC Dashboard"],
  }), {
    verified: false,
    verificationMode: "not_verified",
  });
});

test("settings dialog identity check rejects mismatched titled dialogs", () => {
  assert.equal(settingsDialogTitleMatchesScriptName("SMC Core Engine", "SMC Dashboard"), false);
  assert.equal(settingsDialogTitleMatchesScriptName("SMC Core Engine", "SMC Core Engine"), true);
  assert.equal(settingsDialogTitleMatchesScriptName("SMC Core Engine", ""), true);
});

test("buildScriptNamePatterns fuzzy does not match engineering suite expansion", () => {
  const [, , fuzzyPattern] = buildScriptNamePatterns("SMC Core Engine");

  assert.equal(fuzzyPattern.test("SMC Core Engineering Suite"), false);
  assert.equal(fuzzyPattern.test("SMC Core Engine"), true);
});

test("detectPublishedVersionFromBody anchors version to the target script when provided", () => {
  const bodyText = "Release notes version 99. Published SMC Core Engine version 7 successfully.";

  assert.equal(detectPublishedVersionFromBody(bodyText, "SMC Core Engine"), 7);
  assert.equal(detectPublishedVersionFromBody(bodyText, "SMC Dashboard"), null);
});

test("detectPublishedVersionFromContextTexts only accepts target-script context", () => {
  assert.equal(detectPublishedVersionFromContextTexts([
    "Published SMC Core Engine version 7 successfully.",
  ], "SMC Core Engine"), 7);
  assert.equal(detectPublishedVersionFromContextTexts([
    "Generic publish version 7 successfully.",
  ], "SMC Core Engine"), null);
});

test("detectPublishedVersionFromContextTexts fails closed on multiple target versions", () => {
  assert.equal(detectPublishedVersionFromContextTexts([
    "Published SMC Core Engine version 7 successfully.",
    "Published SMC Core Engine version 8 successfully.",
  ], "SMC Core Engine"), null);
});

test("detectPublishedVersionFromBody fails closed on multiple target versions", () => {
  assert.equal(
    detectPublishedVersionFromBody(
      "Published SMC Core Engine version 7 successfully. Later dialog repeated SMC Core Engine version 8.",
      "SMC Core Engine",
    ),
    null,
  );
});

test("resolvePublishedVersionEvidence marks generic body-only evidence as fallback", () => {
  assert.deepEqual(resolvePublishedVersionEvidence({
    scriptName: "SMC Core Engine",
    versionContextTexts: [],
    bodyText: "Release notes version 99. Published SMC Core Engine version 7 successfully.",
  }), {
    publishedVersion: 7,
    verificationMode: "body_fallback",
    fallbackVersion: 7,
  });
});

test("resolvePublishedVersionEvidence prefers script-context version evidence", () => {
  assert.deepEqual(resolvePublishedVersionEvidence({
    scriptName: "SMC Core Engine",
    versionContextTexts: ["SMC Core Engine version 7"],
    bodyText: "Release notes version 99.",
  }), {
    publishedVersion: 7,
    verificationMode: "version_context",
    fallbackVersion: null,
  });
});

test("resolvePublishedVersionEvidence fails closed when no reliable evidence exists", () => {
  assert.deepEqual(resolvePublishedVersionEvidence({
    scriptName: "SMC Core Engine",
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
    scriptName: "SMC Core Engine",
    versionContextTexts: [
      "Published SMC Core Engine version 7 successfully.",
      "Published SMC Core Engine version 8 successfully.",
    ],
    bodyText: "Release notes version 99.",
  }), {
    publishedVersion: null,
    verificationMode: "not_verified",
    fallbackVersion: null,
  });
});

test("collectVisibleLocatorMetadata samples all visible candidates instead of first-hit only", async () => {
  const nodes = [
    { visible: true, text: "SMC Core Engine", ariaLabel: "", title: "" },
    { visible: true, text: "SMC Dashboard", ariaLabel: "", title: "Dashboard" },
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
    { text: "SMC Core Engine", ariaLabel: "", title: "" },
    { text: "SMC Dashboard", ariaLabel: "", title: "Dashboard" },
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
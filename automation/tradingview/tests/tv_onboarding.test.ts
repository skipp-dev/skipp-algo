import assert from "node:assert/strict";
import test from "node:test";

import {
  browserProfileDirectory,
  browserCandidates,
  classifyBrowserFromPath,
  executeOnboarding,
  OnboardingRunError,
  renderHtmlReport,
  reportSummaryLines,
  saveChangedChartLayout,
  validateChartUrl,
  type OnboardingAdapter,
  type OnboardingConfig,
} from "../../../scripts/tv_onboard_consumers.js";
import {
  CHART_LAYOUT_SAVE_SHORTCUT,
  ChartLayoutSaveError,
  isChartLayoutSaveRequest,
  saveChartLayout,
} from "../lib/tv_layout_save.js";
import type { VerifyConsumerResult } from "../../../scripts/tv_verify_consumer_bindings.js";

const config: OnboardingConfig = {
  schemaVersion: 1,
  producer: { scriptName: "SMC Long-Dip Suite" },
  consumers: [
    {
      id: "one",
      displayName: "Consumer One",
      chartNames: ["Consumer One"],
      savedScriptName: "Consumer One",
      sourcePath: null,
      bindingLabels: ["BUS Armed", "BUS Ready"],
    },
    {
      id: "two",
      displayName: "Consumer Two",
      chartNames: ["Consumer Two", "Consumer Two Legacy"],
      savedScriptName: "Consumer Two",
      sourcePath: null,
      bindingLabels: ["BUS StateCode"],
    },
  ],
};

function result(scriptName: string, labels: string[]): VerifyConsumerResult {
  return {
    ok: true,
    repair: true,
    forceRebind: true,
    repaired: labels,
    unknownParentRuntimeError: false,
    runtimeErrors: [],
    scriptName,
    savedScriptName: scriptName,
    sourcePath: null,
    checked: labels.length,
    mismatches: [],
    bindings: labels.map((label) => ({
      label,
      actual: `SMC Long-Dip Suite: ${label}`,
      expected: `SMC Long-Dip Suite: ${label}`,
      ok: true,
    })),
  };
}

function adapter(options: {
  visible: string[];
  counts?: Record<string, number>;
  sourceAvailable?: boolean;
  fail?: string[];
  calls?: string[];
}): OnboardingAdapter {
  const calls = options.calls ?? [];
  return {
    isScriptVisible: async (name) => options.visible.includes(name),
    countScriptInstances: options.counts ? async (name) => options.counts?.[name] ?? 0 : undefined,
    isSourceOptionAvailable: async (_consumer, chartName) => {
      calls.push(`source:${chartName}`);
      return options.sourceAvailable ?? true;
    },
    bindConsumer: async (consumer, chartName) => {
      calls.push(`bind:${chartName}`);
      if (options.fail?.includes(consumer.id)) throw new Error("controlled binding failure");
      return result(chartName, consumer.bindingLabels);
    },
  };
}

test("missing suite blocks binding but still reports the consumer inventory", async () => {
  const calls: string[] = [];
  const report = await executeOnboarding(config, adapter({ visible: ["Consumer One"], calls }));
  assert.equal(report.outcome, "blocked");
  assert.equal(report.error?.code, "ONB-SUITE-001");
  assert.equal(report.error?.changesMade, false);
  assert.equal(report.summary.detectedConsumers, 1);
  assert.equal(report.summary.missingConsumers, 1);
  assert.deepEqual(calls, []);
});

test("present consumers are rebound while missing consumers produce partial success", async () => {
  const calls: string[] = [];
  const report = await executeOnboarding(config, adapter({
    visible: ["SMC Long-Dip Suite", "Consumer One"],
    calls,
  }));
  assert.equal(report.outcome, "partial");
  assert.equal(report.summary.boundConsumers, 1);
  assert.equal(report.summary.missingConsumers, 1);
  assert.equal(report.summary.checkedBindings, 2);
  assert.deepEqual(calls, ["source:Consumer One", "bind:Consumer One"]);
  assert.match(reportSummaryLines(report).join("\n"), /run SMC Onboarding again/);
});

test("duplicate SMC instances block before the first binding mutation", async () => {
  const calls: string[] = [];
  const report = await executeOnboarding(config, adapter({
    visible: ["SMC Long-Dip Suite", "Consumer One"],
    counts: { "SMC Long-Dip Suite": 2, "Consumer One": 1 },
    calls,
  }));
  assert.equal(report.outcome, "blocked");
  assert.equal(report.error?.code, "ONB-LAYOUT-001");
  assert.equal(report.error?.changesMade, false);
  assert.match(report.error?.nextStep ?? "", /same chart pane/);
  assert.deepEqual(calls, []);
});

test("unavailable suite outputs block before the first binding mutation", async () => {
  const calls: string[] = [];
  const report = await executeOnboarding(config, adapter({
    visible: ["SMC Long-Dip Suite", "Consumer One"],
    sourceAvailable: false,
    calls,
  }));
  assert.equal(report.outcome, "blocked");
  assert.equal(report.error?.code, "ONB-SUITE-002");
  assert.deepEqual(calls, ["source:Consumer One"]);
});

test("a failed detected consumer does not prevent later consumers from binding", async () => {
  const calls: string[] = [];
  const report = await executeOnboarding(config, adapter({
    visible: ["SMC Long-Dip Suite", "Consumer One", "Consumer Two Legacy"],
    fail: ["one"],
    calls,
  }));
  assert.equal(report.outcome, "failed");
  assert.equal(report.summary.failedConsumers, 1);
  assert.equal(report.summary.boundConsumers, 1);
  assert.deepEqual(calls, ["source:Consumer One", "bind:Consumer One", "bind:Consumer Two Legacy"]);
});

test("zero consumers is a partial result with a rerun instruction", async () => {
  const report = await executeOnboarding(config, adapter({ visible: ["SMC Long-Dip Suite"] }));
  assert.equal(report.outcome, "partial");
  assert.equal(report.error?.code, "ONB-CONSUMER-000");
  assert.equal(report.summary.missingConsumers, 2);
});

test("browser candidates cover Windows Chrome/Edge and macOS Chrome/Edge", () => {
  const windows = browserCandidates("win32", {
    PROGRAMFILES: "C:\\Program Files",
    "PROGRAMFILES(X86)": "C:\\Program Files (x86)",
    LOCALAPPDATA: "C:\\Users\\Ada\\AppData\\Local",
  }, "C:\\Users\\Ada");
  assert.ok(windows.some((item) => item.executablePath.endsWith("chrome.exe")));
  assert.ok(windows.some((item) => item.executablePath.endsWith("msedge.exe")));
  const mac = browserCandidates("darwin", {}, "/Users/ada");
  assert.ok(mac.some((item) => item.name === "Google Chrome"));
  assert.ok(mac.some((item) => item.name === "Microsoft Edge"));
});

test("--browser-path classifies platform-specific Chrome and Edge bundle executables", () => {
  // macOS bundle executables have no "msedge"/"chrome.exe" — they are the app
  // display names. Matching only "msedge" misclassified the documented macOS
  // Edge path as a custom browser, giving it a separate hashed profile so the
  // persisted TradingView login was not reused.
  assert.equal(classifyBrowserFromPath("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge").id, "edge");
  assert.equal(classifyBrowserFromPath("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome").id, "chrome");
  assert.equal(classifyBrowserFromPath("C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe").id, "edge");
  assert.equal(classifyBrowserFromPath("C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe").id, "chrome");
  assert.equal(classifyBrowserFromPath("/opt/brave/brave").id, "custom");
});

test("Chrome, Edge, and custom executables cannot share a persistent profile", () => {
  const chrome = browserProfileDirectory("/tmp/profile", { id: "chrome", name: "Chrome", executablePath: "/chrome" });
  const edge = browserProfileDirectory("/tmp/profile", { id: "edge", name: "Edge", executablePath: "/edge" });
  const customA = browserProfileDirectory("/tmp/profile", { id: "custom", name: "A", executablePath: "/custom-a" });
  const customB = browserProfileDirectory("/tmp/profile", { id: "custom", name: "B", executablePath: "/custom-b" });
  assert.notEqual(chrome, edge);
  assert.notEqual(customA, customB);
});

test("chart URL validation is fail-closed", () => {
  assert.match(validateChartUrl("https://www.tradingview.com/chart/abc/"), /tradingview\.com/);
  assert.throws(() => validateChartUrl("https://example.com/chart/abc"), /invalid/i);
  assert.throws(() => validateChartUrl("javascript:alert(1)"), /invalid/i);
});

test("HTML report escapes consumer-controlled text", async () => {
  const report = await executeOnboarding(config, adapter({ visible: ["SMC Long-Dip Suite"] }));
  report.consumers[0]!.message = "<script>alert(1)</script>";
  const html = renderHtmlReport(report);
  assert.doesNotMatch(html, /<script>alert/);
  assert.match(html, /&lt;script&gt;alert/);
});

// ---------------------------------------------------------------------------
// Chart layout save. Every fact below was measured on 2026-10-01 on the
// operator's chart (vWgAWyfC, de.tradingview.com, device emulation OFF):
//
//   * the save button is `button[data-qa-id="save-load-button"]`; the id
//     `header-toolbar-save-load` now sits on a wrapper <div>, so the selector
//     that carried until 2026-08-23 (`button[data-qa-id="header-toolbar-
//     save-load"]`) matches nothing;
//   * the button's label is constant ("Alle Aenderungen speichern") and its
//     state is `aria-disabled` -- the old "All changes saved" label is gone;
//   * Cmd/Ctrl+S answers with `POST /api/v1/charts/save/` -> 200.
//
// 467 run artefacts between 2026-09-01 and 2026-10-01 carry zero
// `layoutSaved: true`: every repair rebound its inputs, failed to find the
// button and lost the rebinds on the next load. The fake page below therefore
// models the REQUEST, not a label: a save counts when TradingView answered it.
// ---------------------------------------------------------------------------

const NEW_SAVE_BUTTON = 'button[data-qa-id="save-load-button"]';
const LEGACY_SAVE_BUTTON = 'button[data-qa-id="header-toolbar-save-load"]';
const SAVE_URL = "https://www.tradingview.com/api/v1/charts/save/";

type FakeSaveButton = { ariaDisabled?: string | null; ariaLabel?: string | null; visible?: boolean };

function fakeSavePage(options: {
  buttons?: Record<string, FakeSaveButton>;
  /** What TradingView does once a save is triggered. `null` = no request at all. */
  answer?: { status: number; url?: string; method?: string } | null;
  /** What `document.activeElement` is after the blur attempt. */
  focus?: { tag: string; editable: boolean; monaco: boolean };
}) {
  const log: string[] = [];
  let settle: ((request: unknown) => void) | null = null;
  let fail: ((error: Error) => void) | null = null;
  let predicate: ((request: unknown) => boolean) | null = null;
  const answer = options.answer === undefined ? { status: 200 } : options.answer;

  const trigger = (how: string) => {
    log.push(how);
    if (!settle || !fail || !predicate) return;
    if (!answer) {
      fail(new Error("Timeout 20000ms exceeded while waiting for event \"request\""));
      return;
    }
    const request = {
      method: () => answer.method ?? "POST",
      url: () => answer.url ?? SAVE_URL,
      response: async () => ({ status: () => answer.status, ok: () => answer.status >= 200 && answer.status < 300 }),
    };
    if (predicate(request)) settle(request);
    else fail(new Error("Timeout 20000ms exceeded while waiting for event \"request\""));
  };

  const page = {
    locator: (selector: string) => {
      const spec = options.buttons?.[selector];
      const button = {
        isVisible: async () => spec?.visible ?? true,
        getAttribute: async (name: string) =>
          name === "aria-disabled" ? (spec?.ariaDisabled ?? null) : name === "aria-label" ? (spec?.ariaLabel ?? null) : null,
        click: async () => trigger(`click:${selector}`),
      };
      return { count: async () => (spec ? 1 : 0), nth: () => button };
    },
    waitForRequest: (candidate: (request: unknown) => boolean) =>
      new Promise((resolve, reject) => {
        predicate = candidate;
        settle = resolve;
        fail = reject;
      }),
    keyboard: { press: async (key: string) => trigger(`key:${key}`) },
    evaluate: async () => options.focus ?? { tag: "BODY", editable: false, monaco: false },
    waitForTimeout: async () => undefined,
  };
  return { page, log };
}

test("the save request is recognised by method and path, on any TradingView host", () => {
  assert.equal(isChartLayoutSaveRequest("POST", "https://de.tradingview.com/api/v1/charts/save/"), true);
  assert.equal(isChartLayoutSaveRequest("POST", "https://www.tradingview.com/api/v1/charts/save/?x=1"), true);
  assert.equal(isChartLayoutSaveRequest("GET", "https://www.tradingview.com/api/v1/charts/save/"), false);
  assert.equal(isChartLayoutSaveRequest("POST", "https://www.tradingview.com/savechart/"), false);
  assert.equal(isChartLayoutSaveRequest("POST", "https://www.tradingview.com/pine-facade/save/"), false);
  assert.equal(isChartLayoutSaveRequest("POST", "https://tradingview.com.evil.example/api/v1/charts/save/"), false);
  assert.equal(isChartLayoutSaveRequest("POST", "not a url"), false);
});

test("an enabled save button is clicked and the save counts once TradingView answered it", async () => {
  const { page, log } = fakeSavePage({ buttons: { [NEW_SAVE_BUTTON]: { ariaDisabled: "false" } } });

  const outcome = await saveChartLayout(page as any);

  assert.deepEqual(log, [`click:${NEW_SAVE_BUTTON}`]);
  assert.equal(outcome.trigger, "click");
  assert.equal(outcome.status, 200);
});

test("a disabled save button is not taken as 'already saved' -- the shortcut forces the save", async () => {
  // The measured idle state. Whether TradingView also disables the button
  // while autosave is on is NOT measured, so "disabled" must never end the
  // run without a request: that would be the silent non-persistence again.
  const { page, log } = fakeSavePage({ buttons: { [NEW_SAVE_BUTTON]: { ariaDisabled: "true" } } });

  const outcome = await saveChartLayout(page as any);

  assert.deepEqual(log, [`key:${CHART_LAYOUT_SAVE_SHORTCUT}`]);
  assert.equal(outcome.trigger, "shortcut");
});

test("a header without any save button still saves through the shortcut", async () => {
  const { page, log } = fakeSavePage({ buttons: {} });

  const outcome = await saveChartLayout(page as any);

  assert.deepEqual(log, [`key:${CHART_LAYOUT_SAVE_SHORTCUT}`]);
  assert.equal(outcome.control, "none");
});

test("the header that carried until 2026-08-23 is still served", async () => {
  const dirty = fakeSavePage({
    buttons: { [LEGACY_SAVE_BUTTON]: { ariaLabel: "Save all charts for all symbols and intervals on your layout" } },
  });
  assert.equal((await saveChartLayout(dirty.page as any)).trigger, "click");
  assert.deepEqual(dirty.log, [`click:${LEGACY_SAVE_BUTTON}`]);

  const clean = fakeSavePage({ buttons: { [LEGACY_SAVE_BUTTON]: { ariaLabel: "All changes saved" } } });
  assert.equal((await saveChartLayout(clean.page as any)).trigger, "shortcut");
});

test("a save TradingView never answered is a failure, and the message says what the header looked like", async () => {
  const { page } = fakeSavePage({ buttons: { [NEW_SAVE_BUTTON]: { ariaDisabled: "true" } }, answer: null });

  await assert.rejects(
    saveChartLayout(page as any),
    (error: unknown) =>
      error instanceof ChartLayoutSaveError
      && error.failure === "unconfirmed"
      && /api\/v1\/charts\/save/.test(error.message)
      && /save-load-button/.test(error.message)
      && /aria-disabled=true/.test(error.message)
      && /open dialogs: /.test(error.message),
  );
});

test("a request that is not the chart save does not confirm anything", async () => {
  const { page } = fakeSavePage({
    buttons: { [NEW_SAVE_BUTTON]: { ariaDisabled: "false" } },
    answer: { status: 200, url: "https://www.tradingview.com/pine-facade/save/" },
  });

  await assert.rejects(
    saveChartLayout(page as any),
    (error: unknown) => error instanceof ChartLayoutSaveError && error.failure === "unconfirmed",
  );
});

test("a save TradingView rejected is a failure that names the status", async () => {
  const { page } = fakeSavePage({ buttons: { [NEW_SAVE_BUTTON]: { ariaDisabled: "false" } }, answer: { status: 403 } });

  await assert.rejects(
    saveChartLayout(page as any),
    (error: unknown) =>
      error instanceof ChartLayoutSaveError && error.failure === "rejected" && /HTTP 403/.test(error.message),
  );
});

test("the shortcut is never pressed into a text field or the Pine editor", async () => {
  // Ctrl+S inside the Pine editor saves the SCRIPT, not the chart -- a live
  // mutation of a saved source. If focus cannot be moved off an editable
  // element the run stops instead of pressing.
  for (const focus of [
    { tag: "TEXTAREA", editable: false, monaco: true },
    { tag: "INPUT", editable: false, monaco: false },
    { tag: "DIV", editable: true, monaco: false },
  ]) {
    const { page, log } = fakeSavePage({ buttons: {}, focus });
    await assert.rejects(
      saveChartLayout(page as any),
      (error: unknown) => error instanceof ChartLayoutSaveError && error.failure === "unsafe-focus",
    );
    assert.deepEqual(log, []);
  }
});

test("onboarding saves through the same path and confirms on the request", async () => {
  const { page, log } = fakeSavePage({ buttons: { [NEW_SAVE_BUTTON]: { ariaDisabled: "false" } } });

  await saveChangedChartLayout(page as any);

  assert.deepEqual(log, [`click:${NEW_SAVE_BUTTON}`]);
});

test("an unconfirmed chart save fails with a user-facing onboarding code", async () => {
  const { page } = fakeSavePage({ buttons: {}, answer: null });

  await assert.rejects(
    saveChangedChartLayout(page as any),
    (error: unknown) => error instanceof OnboardingRunError && error.code === "ONB-SAVE-001",
  );
});

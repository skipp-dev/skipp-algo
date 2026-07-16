import assert from "node:assert/strict";
import test from "node:test";

import {
  browserProfileDirectory,
  browserCandidates,
  executeOnboarding,
  renderHtmlReport,
  reportSummaryLines,
  validateChartUrl,
  type OnboardingAdapter,
  type OnboardingConfig,
} from "../../../scripts/tv_onboard_consumers.js";
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

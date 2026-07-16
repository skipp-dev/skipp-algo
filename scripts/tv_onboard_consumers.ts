#!/usr/bin/env -S node --enable-source-maps

import { spawn } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import readline from "node:readline/promises";
import { fileURLToPath } from "node:url";

import {
  closeTradingViewSession,
  collectTradingViewPageAuthState,
  findLegendRowWrappers,
  gotoChart,
  isScriptVisibleOnChartSurface,
  newTradingViewSession,
  type TradingViewSession,
} from "../automation/tradingview/lib/tv_shared.js";
import {
  isConsumerSourceOptionAvailable,
  parseInputSourceLabels,
  verifyConsumerBindings,
  type VerifyConsumerResult,
  type VerifyConsumerTarget,
} from "./tv_verify_consumer_bindings.js";

export type OnboardingOutcome = "complete" | "partial" | "blocked" | "failed";
export type OnboardingConsumerStatus = "bound" | "missing" | "failed" | "not_checked";

type RawConsumer = {
  id: string;
  displayName: string;
  chartNames: string[];
  savedScriptName: string;
  source?: string;
  bindingLabels?: string[];
};

type RawConfig = {
  schemaVersion: number;
  producer: { scriptName: string };
  consumers: RawConsumer[];
};

export type OnboardingConsumer = Omit<RawConsumer, "source" | "bindingLabels"> & {
  sourcePath: string | null;
  bindingLabels: string[];
};

export type OnboardingConfig = {
  schemaVersion: number;
  producer: { scriptName: string };
  consumers: OnboardingConsumer[];
};

export type OnboardingConsumerReport = {
  id: string;
  name: string;
  chartName: string | null;
  status: OnboardingConsumerStatus;
  bindings: number;
  repaired: number;
  mismatches: number;
  errorCode: string | null;
  message: string | null;
};

export type OnboardingReport = {
  schemaVersion: 1;
  generatedAt: string;
  mode: "onboarding";
  outcome: OnboardingOutcome;
  producer: {
    name: string;
    status: "unknown" | "missing" | "present" | "ready" | "unavailable";
    busOutputsAvailable: boolean | null;
  };
  summary: {
    supportedConsumers: number;
    detectedConsumers: number;
    boundConsumers: number;
    missingConsumers: number;
    failedConsumers: number;
    checkedBindings: number;
    repairedBindings: number;
    failedBindings: number;
  };
  consumers: OnboardingConsumerReport[];
  error: { code: string; message: string; nextStep: string; changesMade: boolean } | null;
};

export type OnboardingAdapter = {
  isScriptVisible(scriptName: string): Promise<boolean>;
  countScriptInstances?(scriptName: string): Promise<number>;
  isSourceOptionAvailable(
    consumer: OnboardingConsumer,
    chartName: string,
    label: string,
    expected: string,
  ): Promise<boolean>;
  bindConsumer(consumer: OnboardingConsumer, chartName: string, producerName: string): Promise<VerifyConsumerResult>;
};

export type BrowserSelection = {
  id: "chrome" | "edge" | "custom";
  name: string;
  executablePath: string;
};

type Cli = {
  browserSmoke: boolean;
  browserPath: string;
  chartUrl: string;
  configPath: string;
  noOpenReport: boolean;
  outDir: string;
  profileDir: string;
  selfTest: boolean;
  waitTimeoutMs: number;
};

export class OnboardingRunError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly nextStep: string,
    readonly changesMade = false,
  ) {
    super(message);
  }
}

function nonEmptyStrings(values: unknown): string[] {
  return Array.isArray(values)
    ? values.filter((value): value is string => typeof value === "string" && value.trim().length > 0)
    : [];
}

export function loadOnboardingConfig(configPath: string): OnboardingConfig {
  const raw = JSON.parse(fs.readFileSync(configPath, "utf-8")) as RawConfig;
  if (raw.schemaVersion !== 1 || !raw.producer?.scriptName || !Array.isArray(raw.consumers)) {
    throw new OnboardingRunError(
      "ONB-CONFIG-001",
      "The onboarding configuration is invalid.",
      "Download a fresh SMC Onboarding package and try again.",
    );
  }
  const seenIds = new Set<string>();
  const consumers = raw.consumers.map((consumer) => {
    if (!consumer.id || seenIds.has(consumer.id) || !consumer.displayName || !consumer.savedScriptName) {
      throw new OnboardingRunError(
        "ONB-CONFIG-001",
        "The onboarding configuration contains an invalid or duplicate consumer.",
        "Download a fresh SMC Onboarding package and try again.",
      );
    }
    seenIds.add(consumer.id);
    const chartNames = nonEmptyStrings(consumer.chartNames);
    if (chartNames.length === 0) {
      throw new OnboardingRunError(
        "ONB-CONFIG-001",
        `The onboarding configuration has no chart name for ${consumer.displayName}.`,
        "Download a fresh SMC Onboarding package and try again.",
      );
    }
    let sourcePath: string | null = null;
    let bindingLabels = nonEmptyStrings(consumer.bindingLabels);
    if (bindingLabels.length === 0 && consumer.source) {
      const candidates = [path.resolve(process.cwd(), consumer.source), path.resolve(path.dirname(configPath), consumer.source)];
      sourcePath = candidates.find((candidate) => fs.existsSync(candidate)) ?? candidates[0] ?? null;
      if (sourcePath && fs.existsSync(sourcePath)) {
        bindingLabels = parseInputSourceLabels(fs.readFileSync(sourcePath, "utf-8"));
      }
    }
    if (bindingLabels.length === 0) {
      throw new OnboardingRunError(
        "ONB-CONFIG-001",
        `No BUS binding contract is available for ${consumer.displayName}.`,
        "Download a fresh SMC Onboarding package and try again.",
      );
    }
    return { ...consumer, chartNames, sourcePath, bindingLabels };
  });
  return { schemaVersion: raw.schemaVersion, producer: raw.producer, consumers };
}

function emptySummary(config: OnboardingConfig): OnboardingReport["summary"] {
  return {
    supportedConsumers: config.consumers.length,
    detectedConsumers: 0,
    boundConsumers: 0,
    missingConsumers: 0,
    failedConsumers: 0,
    checkedBindings: 0,
    repairedBindings: 0,
    failedBindings: 0,
  };
}

function notCheckedConsumers(config: OnboardingConfig): OnboardingConsumerReport[] {
  return config.consumers.map((consumer) => ({
    id: consumer.id,
    name: consumer.displayName,
    chartName: null,
    status: "not_checked",
    bindings: 0,
    repaired: 0,
    mismatches: 0,
    errorCode: null,
    message: null,
  }));
}

export function blockedReport(
  config: OnboardingConfig,
  producerStatus: OnboardingReport["producer"]["status"],
  code: string,
  message: string,
  nextStep: string,
  changesMade = false,
): OnboardingReport {
  return {
    schemaVersion: 1,
    generatedAt: new Date().toISOString(),
    mode: "onboarding",
    outcome: "blocked",
    producer: {
      name: config.producer.scriptName,
      status: producerStatus,
      busOutputsAvailable: producerStatus === "unavailable" ? false : null,
    },
    summary: emptySummary(config),
    consumers: notCheckedConsumers(config),
    error: { code, message, nextStep, changesMade },
  };
}

function addInventoryToBlockedReport(
  report: OnboardingReport,
  config: OnboardingConfig,
  detected: Map<string, string>,
): OnboardingReport {
  report.summary.detectedConsumers = detected.size;
  report.summary.missingConsumers = config.consumers.length - detected.size;
  report.consumers = config.consumers.map((consumer) => {
    const chartName = detected.get(consumer.id) ?? null;
    return {
      id: consumer.id,
      name: consumer.displayName,
      chartName,
      status: chartName ? "not_checked" : "missing",
      bindings: 0,
      repaired: 0,
      mismatches: 0,
      errorCode: null,
      message: chartName
        ? "This consumer was detected, but no bindings were changed because onboarding is blocked."
        : "This supported consumer is not on the chart.",
    };
  });
  return report;
}

export async function executeOnboarding(
  config: OnboardingConfig,
  adapter: OnboardingAdapter,
  progress: (message: string) => void = () => undefined,
): Promise<OnboardingReport> {
  progress(`Checking producer... ${config.producer.scriptName}`);
  const producerVisible = await adapter.isScriptVisible(config.producer.scriptName);
  progress("Checking supported consumers...");
  const detected = new Map<string, string>();
  for (const consumer of config.consumers) {
    for (const chartName of consumer.chartNames) {
      if (await adapter.isScriptVisible(chartName)) {
        detected.set(consumer.id, chartName);
        progress(`Found consumer: ${consumer.displayName}`);
        break;
      }
    }
    if (!detected.has(consumer.id)) progress(`Consumer not found: ${consumer.displayName}`);
  }

  if (adapter.countScriptInstances) {
    const ambiguousNames: string[] = [];
    const producerCount = await adapter.countScriptInstances(config.producer.scriptName);
    if (producerCount > 1) ambiguousNames.push(`${config.producer.scriptName} (${producerCount})`);
    for (const consumer of config.consumers) {
      for (const chartName of consumer.chartNames) {
        const count = await adapter.countScriptInstances(chartName);
        if (count > 1) ambiguousNames.push(`${chartName} (${count})`);
      }
    }
    if (ambiguousNames.length > 0) {
      return addInventoryToBlockedReport(blockedReport(
        config,
        producerVisible ? "present" : "missing",
        "ONB-LAYOUT-001",
        `Multiple SMC script instances make the source selection ambiguous: ${ambiguousNames.join(", ")}. No bindings were changed.`,
        "Keep one SMC Long-Dip Suite and its consumers in the same chart pane, remove duplicate SMC scripts from other panes, and run SMC Onboarding again.",
      ), config, detected);
    }
  }

  if (!producerVisible) {
    return addInventoryToBlockedReport(blockedReport(
      config,
      "missing",
      "ONB-SUITE-001",
      `“${config.producer.scriptName}” was not found on this chart. No bindings were changed.`,
      `Add “${config.producer.scriptName}” to the chart, wait for it to finish loading, and run SMC Onboarding again.`,
    ), config, detected);
  }

  if (detected.size === 0) {
    const consumers = config.consumers.map((consumer): OnboardingConsumerReport => ({
      id: consumer.id,
      name: consumer.displayName,
      chartName: null,
      status: "missing",
      bindings: 0,
      repaired: 0,
      mismatches: 0,
      errorCode: null,
      message: "This supported consumer is not on the chart.",
    }));
    return {
      schemaVersion: 1,
      generatedAt: new Date().toISOString(),
      mode: "onboarding",
      outcome: "partial",
      producer: { name: config.producer.scriptName, status: "present", busOutputsAvailable: null },
      summary: { ...emptySummary(config), missingConsumers: config.consumers.length },
      consumers,
      error: {
        code: "ONB-CONSUMER-000",
        message: `“${config.producer.scriptName}” is present, but no supported consumers were found.`,
        nextStep: "Add at least one supported consumer to the chart and run SMC Onboarding again.",
        changesMade: false,
      },
    };
  }

  const firstConsumer = config.consumers.find((consumer) => detected.has(consumer.id));
  if (!firstConsumer) throw new Error("Detected consumer inventory is inconsistent");
  const firstChartName = detected.get(firstConsumer.id) as string;
  const firstLabel = firstConsumer.bindingLabels[0] as string;
  progress("Checking that the suite exposes live BUS outputs...");
  if (!(await adapter.isSourceOptionAvailable(
    firstConsumer,
    firstChartName,
    firstLabel,
    `${config.producer.scriptName}: ${firstLabel}`,
  ))) {
    return addInventoryToBlockedReport(blockedReport(
      config,
      "unavailable",
      "ONB-SUITE-002",
      `“${config.producer.scriptName}” is present, but its BUS outputs are not available. No consumer bindings were changed.`,
      "Open the suite and resolve its compile or runtime error. Then run SMC Onboarding again.",
    ), config, detected);
  }

  const consumers: OnboardingConsumerReport[] = [];
  for (const consumer of config.consumers) {
    const chartName = detected.get(consumer.id);
    if (!chartName) {
      consumers.push({
        id: consumer.id,
        name: consumer.displayName,
        chartName: null,
        status: "missing",
        bindings: 0,
        repaired: 0,
        mismatches: 0,
        errorCode: null,
        message: "This supported consumer is not on the chart.",
      });
      continue;
    }
    progress(`Connecting ${consumer.displayName}...`);
    try {
      const result = await adapter.bindConsumer(consumer, chartName, config.producer.scriptName);
      if (!result.ok || result.mismatches.length > 0 || result.unknownParentRuntimeError) {
        throw new Error(result.unknownParentRuntimeError
          ? "TradingView still reports unknown parent id after rebinding."
          : `${result.mismatches.length} BUS bindings did not verify.`);
      }
      consumers.push({
        id: consumer.id,
        name: consumer.displayName,
        chartName,
        status: "bound",
        bindings: result.checked,
        repaired: result.repaired.length,
        mismatches: 0,
        errorCode: null,
        message: "All BUS bindings were connected and verified.",
      });
      progress(`Connected ${consumer.displayName}: ${result.checked} bindings verified.`);
    } catch (error) {
      consumers.push({
        id: consumer.id,
        name: consumer.displayName,
        chartName,
        status: "failed",
        bindings: consumer.bindingLabels.length,
        repaired: 0,
        mismatches: consumer.bindingLabels.length,
        errorCode: "ONB-BINDING-001",
        message: error instanceof Error ? error.message : String(error),
      });
      progress(`Could not connect ${consumer.displayName}. Other consumers will still be processed.`);
    }
  }

  const boundConsumers = consumers.filter((consumer) => consumer.status === "bound");
  const missingConsumers = consumers.filter((consumer) => consumer.status === "missing");
  const failedConsumers = consumers.filter((consumer) => consumer.status === "failed");
  const outcome: OnboardingOutcome = failedConsumers.length > 0
    ? "failed"
    : missingConsumers.length > 0
      ? "partial"
      : "complete";
  return {
    schemaVersion: 1,
    generatedAt: new Date().toISOString(),
    mode: "onboarding",
    outcome,
    producer: { name: config.producer.scriptName, status: "ready", busOutputsAvailable: true },
    summary: {
      supportedConsumers: config.consumers.length,
      detectedConsumers: detected.size,
      boundConsumers: boundConsumers.length,
      missingConsumers: missingConsumers.length,
      failedConsumers: failedConsumers.length,
      checkedBindings: boundConsumers.reduce((sum, consumer) => sum + consumer.bindings, 0),
      repairedBindings: boundConsumers.reduce((sum, consumer) => sum + consumer.repaired, 0),
      failedBindings: failedConsumers.reduce((sum, consumer) => sum + consumer.mismatches, 0),
    },
    consumers,
    error: failedConsumers.length > 0
      ? {
          code: "ONB-BINDING-001",
          message: "One or more detected consumers could not be connected.",
          nextStep: "Review the consumer details, correct the reported problem, and run SMC Onboarding again.",
          changesMade: boundConsumers.length > 0,
        }
      : null,
  };
}

function defaultDataDir(platform = process.platform, env = process.env): string {
  if (platform === "win32") return path.join(env.LOCALAPPDATA || os.homedir(), "SMC Onboarding");
  if (platform === "darwin") return path.join(os.homedir(), "Library", "Application Support", "SMC Onboarding");
  return path.join(os.homedir(), ".smc-onboarding");
}

export function browserCandidates(
  platform = process.platform,
  env: NodeJS.ProcessEnv = process.env,
  homeDir = os.homedir(),
): BrowserSelection[] {
  if (platform === "win32") {
    const roots = [env.PROGRAMFILES, env["PROGRAMFILES(X86)"], env.LOCALAPPDATA].filter(Boolean) as string[];
    return [
      ...roots.map((root) => ({ id: "chrome" as const, name: "Google Chrome", executablePath: path.join(root, "Google", "Chrome", "Application", "chrome.exe") })),
      ...roots.map((root) => ({ id: "edge" as const, name: "Microsoft Edge", executablePath: path.join(root, "Microsoft", "Edge", "Application", "msedge.exe") })),
    ];
  }
  if (platform === "darwin") {
    return [
      { id: "chrome", name: "Google Chrome", executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" },
      { id: "edge", name: "Microsoft Edge", executablePath: "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" },
      { id: "chrome", name: "Google Chrome", executablePath: path.join(homeDir, "Applications", "Google Chrome.app", "Contents", "MacOS", "Google Chrome") },
      { id: "edge", name: "Microsoft Edge", executablePath: path.join(homeDir, "Applications", "Microsoft Edge.app", "Contents", "MacOS", "Microsoft Edge") },
    ];
  }
  return [];
}

export function detectSupportedBrowser(browserPath = ""): BrowserSelection {
  if (browserPath) {
    const executablePath = path.resolve(browserPath);
    if (!fs.existsSync(executablePath)) {
      throw new OnboardingRunError(
        "ONB-BROWSER-001",
        `The selected browser executable does not exist: ${executablePath}`,
        "Choose an installed Google Chrome or Microsoft Edge executable and run SMC Onboarding again.",
      );
    }
    const basename = path.basename(executablePath).toLowerCase();
    const id = basename.includes("msedge") ? "edge" : basename.includes("chrome") ? "chrome" : "custom";
    return { id, name: id === "edge" ? "Microsoft Edge" : id === "chrome" ? "Google Chrome" : "Custom Chromium browser", executablePath };
  }
  const browser = browserCandidates().find((candidate) => fs.existsSync(candidate.executablePath));
  if (!browser) {
    throw new OnboardingRunError(
      "ONB-BROWSER-001",
      "No supported browser was found.",
      "Install Google Chrome or Microsoft Edge, then start SMC Onboarding again.",
    );
  }
  return browser;
}

export function browserProfileDirectory(baseDirectory: string, browser: BrowserSelection): string {
  const key = browser.id === "custom"
    ? `custom-${crypto.createHash("sha256").update(browser.executablePath).digest("hex").slice(0, 10)}`
    : browser.id;
  return `${baseDirectory}-${key}`;
}

function parseCli(): Cli {
  const args = process.argv.slice(2);
  const getFlag = (name: string, fallback = "") => {
    const index = args.indexOf(name);
    return index >= 0 && args[index + 1] ? (args[index + 1] as string) : fallback;
  };
  const scriptDir = path.dirname(fileURLToPath(import.meta.url));
  const packagedConfig = path.join(scriptDir, "consumer-onboarding.json");
  const defaultConfig = fs.existsSync(packagedConfig)
    ? packagedConfig
    : path.resolve("automation/tradingview/config/consumer-onboarding.json");
  const dataDir = defaultDataDir();
  return {
    browserSmoke: args.includes("--browser-smoke"),
    browserPath: getFlag("--browser-path"),
    chartUrl: getFlag("--chart-url"),
    configPath: path.resolve(getFlag("--config", defaultConfig)),
    noOpenReport: args.includes("--no-open-report"),
    outDir: path.resolve(getFlag("--out-dir", path.join(dataDir, "reports"))),
    profileDir: path.resolve(getFlag("--profile-dir", path.join(dataDir, "browser-profile"))),
    selfTest: args.includes("--self-test"),
    waitTimeoutMs: Number.parseInt(getFlag("--wait-timeout-ms", "900000"), 10),
  };
}

export function validateChartUrl(raw: string): string {
  try {
    const url = new URL(raw.trim());
    const hostOk = url.hostname === "tradingview.com" || url.hostname.endsWith(".tradingview.com");
    if (url.protocol !== "https:" || !hostOk || !url.pathname.startsWith("/chart")) throw new Error("invalid");
    return url.toString();
  } catch {
    throw new OnboardingRunError(
      "ONB-CHART-001",
      "The TradingView chart URL is invalid.",
      "Open the target chart in TradingView, copy its https://www.tradingview.com/chart/... URL, and try again.",
    );
  }
}

async function resolveChartUrl(cli: Cli): Promise<string> {
  if (cli.chartUrl) return validateChartUrl(cli.chartUrl);
  if (!process.stdin.isTTY) {
    throw new OnboardingRunError(
      "ONB-CHART-001",
      "No TradingView chart URL was provided.",
      "Run SMC Onboarding again with --chart-url followed by the target TradingView chart URL.",
    );
  }
  const prompt = readline.createInterface({ input: process.stdin, output: process.stdout });
  try {
    return validateChartUrl(await prompt.question("Paste the TradingView chart URL: "));
  } finally {
    prompt.close();
  }
}

async function waitForAuthentication(session: TradingViewSession, chartUrl: string, timeoutMs: number): Promise<void> {
  const initial = await collectTradingViewPageAuthState(session.page).catch(() => null);
  if (initial?.authenticated) return;
  console.log("");
  console.log("TradingView sign-in is required.");
  console.log("Sign in in the browser window opened by SMC Onboarding.");
  console.log("Keep the browser window open. Onboarding will continue automatically after sign-in.");
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    await session.page.waitForTimeout(2_000);
    const state = await collectTradingViewPageAuthState(session.page).catch(() => null);
    if (state?.authenticated) {
      if (!session.page.url().startsWith(chartUrl)) await gotoChart(session.page, chartUrl);
      console.log("TradingView sign-in confirmed.");
      return;
    }
  }
  throw new OnboardingRunError(
    "ONB-AUTH-001",
    "TradingView sign-in was not completed before the time limit.",
    "Start SMC Onboarding again, sign in in the opened browser window, and leave that window open.",
  );
}

function playwrightAdapter(session: TradingViewSession): OnboardingAdapter {
  return {
    isScriptVisible: (scriptName) => isScriptVisibleOnChartSurface(session.page, scriptName),
    countScriptInstances: async (scriptName) => (await findLegendRowWrappers(session.page, scriptName)).length,
    isSourceOptionAvailable: (consumer, chartName, label, expected) => isConsumerSourceOptionAvailable(
      session,
      { bindingLabels: consumer.bindingLabels, savedScriptName: consumer.savedScriptName, scriptName: chartName },
      label,
      expected,
    ),
    bindConsumer: (consumer, chartName, producerName) => {
      const target: VerifyConsumerTarget = {
        bindingLabels: consumer.bindingLabels,
        savedScriptName: consumer.savedScriptName,
        scriptName: chartName,
        producerName,
      };
      return verifyConsumerBindings(session, target, true, true);
    },
  };
}

function htmlEscape(value: string): string {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}

export function renderHtmlReport(report: OnboardingReport): string {
  const rows = report.consumers.map((consumer) => `
    <tr><td>${htmlEscape(consumer.name)}</td><td><span class="status ${consumer.status}">${consumer.status}</span></td>
    <td>${consumer.bindings}</td><td>${consumer.message ? htmlEscape(consumer.message) : "—"}</td></tr>`).join("");
  const missing = report.consumers.filter((consumer) => consumer.status === "missing");
  const next = report.error
    ? `<section class="notice"><h2>${htmlEscape(report.error.code)}</h2><p>${htmlEscape(report.error.message)}</p><p><strong>Next step:</strong> ${htmlEscape(report.error.nextStep)}</p></section>`
    : missing.length > 0
      ? `<section class="notice"><h2>Missing consumers</h2><p>${htmlEscape(missing.map((consumer) => consumer.name).join(", "))}</p><p>Add any missing consumers you want to use, then run SMC Onboarding again.</p></section>`
      : "";
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>SMC Onboarding Report</title><style>
  body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;margin:0;background:#f4f6f8;color:#17202a}main{max-width:920px;margin:40px auto;padding:0 20px}
  header,section{background:white;border-radius:12px;padding:24px;margin-bottom:18px;box-shadow:0 2px 10px #0001}h1,h2{margin-top:0}.outcome{font-size:1.15rem;text-transform:uppercase;font-weight:700}
  .complete{color:#08783e}.partial{color:#9a6700}.blocked,.failed{color:#b42318}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:12px;border-bottom:1px solid #e7eaee;vertical-align:top}
  .status{font-weight:700;text-transform:capitalize}.bound{color:#08783e}.missing{color:#9a6700}.failed{color:#b42318}.not_checked{color:#667085}.notice{border-left:5px solid #e0a000}
  </style></head><body><main><header><h1>SMC Onboarding Report</h1><p class="outcome ${report.outcome}">${htmlEscape(report.outcome)}</p>
  <p>Generated ${htmlEscape(report.generatedAt)}</p></header><section><h2>Summary</h2>
  <p><strong>Producer:</strong> ${htmlEscape(report.producer.name)} (${htmlEscape(report.producer.status)})</p>
  <p>${report.summary.boundConsumers} of ${report.summary.supportedConsumers} supported consumers connected; ${report.summary.checkedBindings} BUS bindings verified.</p></section>
  ${next}<section><h2>Consumers</h2><table><thead><tr><th>Consumer</th><th>Status</th><th>Bindings</th><th>Details</th></tr></thead><tbody>${rows}</tbody></table></section>
  <section><p>SMC Onboarding stores this report locally. It does not upload TradingView login data or chart bindings.</p></section></main></body></html>`;
}

function writeReports(report: OnboardingReport, outDir: string): { jsonPath: string; htmlPath: string } {
  fs.mkdirSync(outDir, { recursive: true });
  const stamp = report.generatedAt.replaceAll(":", "-").replaceAll(".", "-");
  const base = path.join(outDir, `smc-onboarding-${stamp}`);
  const jsonPath = `${base}.json`;
  const htmlPath = `${base}.html`;
  fs.writeFileSync(jsonPath, `${JSON.stringify(report, null, 2)}\n`, "utf-8");
  fs.writeFileSync(htmlPath, renderHtmlReport(report), "utf-8");
  return { jsonPath, htmlPath };
}

function openLocalReport(htmlPath: string): void {
  const child = process.platform === "win32"
    ? spawn("cmd.exe", ["/d", "/c", "start", "", htmlPath], { detached: true, stdio: "ignore" })
    : spawn("open", [htmlPath], { detached: true, stdio: "ignore" });
  child.unref();
}

export function reportSummaryLines(report: OnboardingReport): string[] {
  if (report.outcome === "complete") {
    return [`Onboarding complete. ${report.summary.boundConsumers} consumers and ${report.summary.checkedBindings} BUS bindings are connected to “${report.producer.name}”.`];
  }
  if (report.outcome === "partial") {
    const missing = report.consumers.filter((consumer) => consumer.status === "missing").map((consumer) => consumer.name);
    const lines = [`Onboarding completed for ${report.summary.boundConsumers} of ${report.summary.supportedConsumers} supported consumers. All detected consumers were connected successfully.`];
    if (missing.length > 0) {
      lines.push("The following consumers are not on this chart:", ...missing.map((name) => `- ${name}`));
      lines.push("Add any missing consumers you want to use, then run SMC Onboarding again.");
    }
    return lines;
  }
  return report.error
    ? [`${report.error.code}: ${report.error.message}`, `Next step: ${report.error.nextStep}`]
    : ["SMC Onboarding did not complete. Review the local report for details."];
}

async function runSelfTest(config: OnboardingConfig, cli: Cli): Promise<number> {
  const browser = detectSupportedBrowser(cli.browserPath);
  const checkedBindings = config.consumers.reduce((sum, consumer) => sum + consumer.bindingLabels.length, 0);
  let browserLaunchOk: boolean | null = null;
  if (cli.browserSmoke) {
    const smokeProfile = fs.mkdtempSync(path.join(os.tmpdir(), "smc-onboarding-browser-smoke-"));
    process.env.TV_PERSISTENT_PROFILE_DIR = smokeProfile;
    process.env.TV_CHROMIUM_EXECUTABLE_PATH = browser.executablePath;
    delete process.env.TV_BROWSER_CHANNEL;
    process.env.TV_HEADLESS = "1";
    let smokeSession: TradingViewSession | null = null;
    try {
      smokeSession = await newTradingViewSession();
      browserLaunchOk = true;
    } finally {
      if (smokeSession) await closeTradingViewSession(smokeSession);
      fs.rmSync(smokeProfile, { recursive: true, force: true });
    }
  }
  console.log(JSON.stringify({
    ok: true,
    operatingSystem: process.platform,
    architecture: process.arch,
    browser: browser.name,
    browserPath: browser.executablePath,
    browserLaunchOk,
    portableNode: process.execPath,
    supportedConsumers: config.consumers.length,
    bindingContractSize: checkedBindings,
  }));
  return 0;
}

async function runCli(): Promise<number> {
  const cli = parseCli();
  let config: OnboardingConfig;
  try {
    config = loadOnboardingConfig(cli.configPath);
  } catch (error) {
    console.error(`ONB-CONFIG-001: ${error instanceof Error ? error.message : String(error)}`);
    return 1;
  }
  if (cli.selfTest) return runSelfTest(config, cli);

  let session: TradingViewSession | null = null;
  let report: OnboardingReport;
  try {
    if (process.platform !== "win32" && process.platform !== "darwin") {
      throw new OnboardingRunError("ONB-OS-001", `This SMC Onboarding package does not support ${process.platform}.`, "Use a supported Windows or macOS computer.");
    }
    console.log("SMC Onboarding\n==============");
    console.log(`Checking operating system... ${process.platform === "win32" ? "Windows" : "macOS"} detected.`);
    const browser = detectSupportedBrowser(cli.browserPath);
    console.log(`Checking browser... ${browser.name} detected.`);
    const chartUrl = await resolveChartUrl(cli);
    console.log("Checking target chart... URL accepted.");
    const profileDir = browserProfileDirectory(cli.profileDir, browser);
    process.env.TV_PERSISTENT_PROFILE_DIR = profileDir;
    process.env.TV_CHROMIUM_EXECUTABLE_PATH = browser.executablePath;
    delete process.env.TV_BROWSER_CHANNEL;
    process.env.TV_HEADLESS = "0";
    process.env.TV_CHART_URL = chartUrl;
    fs.mkdirSync(path.dirname(profileDir), { recursive: true });
    try {
      session = await newTradingViewSession();
    } catch (error) {
      throw new OnboardingRunError(
        "ONB-BROWSER-002",
        `The browser could not be started: ${error instanceof Error ? error.message : String(error)}`,
        "Close other SMC Onboarding windows and try again. If the problem continues, review the Browser troubleshooting section.",
      );
    }
    await gotoChart(session.page, chartUrl);
    await waitForAuthentication(session, chartUrl, cli.waitTimeoutMs);
    console.log("Checking TradingView login... Signed in.");
    report = await executeOnboarding(config, playwrightAdapter(session), (message) => console.log(message));
  } catch (error) {
    const known = error instanceof OnboardingRunError
      ? error
      : new OnboardingRunError(
          "ONB-UNEXPECTED-001",
          error instanceof Error ? error.message : String(error),
          "Review the local report, then run SMC Onboarding again. If the problem continues, share the report with support.",
        );
    report = blockedReport(config, "unknown", known.code, known.message, known.nextStep, known.changesMade);
  } finally {
    if (session) await closeTradingViewSession(session);
  }

  const paths = writeReports(report, cli.outDir);
  console.log("");
  for (const line of reportSummaryLines(report)) console.log(line);
  console.log(`Detailed report: ${paths.htmlPath}`);
  console.log(`Machine-readable report: ${paths.jsonPath}`);
  if (!cli.noOpenReport) openLocalReport(paths.htmlPath);
  return report.outcome === "complete" || report.outcome === "partial" ? 0 : 1;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runCli().then((code) => { process.exitCode = code; }).catch((error) => {
    console.error(`ONB-UNEXPECTED-001: ${error instanceof Error ? error.message : String(error)}`);
    process.exitCode = 1;
  });
}

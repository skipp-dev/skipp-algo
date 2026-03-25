import fs from "node:fs";
import path from "node:path";
import {
  chromium,
  type Browser,
  type BrowserContext,
  type Locator,
  type Page,
} from "playwright";

import { tvSelectors } from "../selectors.js";
import {
  inspectTradingViewStorageState,
  resolveTradingViewAuthResolution,
  type TradingViewAuthResolution,
  type TradingViewStorageStateInspection,
} from "./tv_validation_model.js";

export type TradingViewSession = {
  browser: Browser;
  context: BrowserContext;
  page: Page;
  authResolution: TradingViewAuthResolution;
};

export type VisibleCount = {
  total: number;
  visible: number;
};

export type EditorDiagnostics = {
  textareaCount: VisibleCount;
  contentEditableCount: VisibleCount;
  monacoCount: VisibleCount;
  pineButtonCount: number;
  pineButtons: string[];
  pineTextCount: number;
  pineTexts: string[];
  relevantBodyLines: string[];
};

export type PageLifecycleEvent = {
  at: string;
  type: string;
  detail?: string;
};

export type PageLifecycleDiagnostics = {
  pageClosed: boolean;
  pageCrashed: boolean;
  contextClosed: boolean;
  browserDisconnected: boolean;
  activeStep: string | null;
  currentUrl: string | null;
  eventCount: number;
  recentEvents: PageLifecycleEvent[];
};

type VisibleDialogSnapshot = {
  title: string;
  text: string;
  labelTexts: string[];
};

export type VisibleChartScriptState = {
  hasLegendMatch: boolean;
  hasStrategyReportMatch: boolean;
  hasScriptNameMatch: boolean;
};

type PageLifecycleTracker = {
  pageClosed: boolean;
  pageCrashed: boolean;
  contextClosed: boolean;
  browserDisconnected: boolean;
  activeStep: string | null;
  stepStack: string[];
  recentEvents: PageLifecycleEvent[];
};

const pageLifecycleTrackers = new WeakMap<Page, PageLifecycleTracker>();

export function mustEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing env: ${name}`);
  }
  return value;
}

export function boolEnv(name: string, fallback: boolean): boolean {
  const raw = process.env[name];
  if (raw == null) {
    return fallback;
  }
  return ["1", "true", "yes", "on"].includes(raw.toLowerCase());
}

export function numEnv(name: string, fallback: number): number {
  const raw = process.env[name];
  if (!raw) {
    return fallback;
  }
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function utcNow(): string {
  return new Date().toISOString();
}

export function readJson<T>(filePath: string): T {
  return JSON.parse(fs.readFileSync(filePath, "utf-8")) as T;
}

export function writeJson(filePath: string, payload: unknown): void {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(payload, null, 2) + "\n", "utf-8");
}

function normalizeUiText(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function compactUiText(value: string): string {
  return normalizeUiText(value).replace(/[^a-z0-9]+/gi, "").toLowerCase();
}

function buildScriptNamePatterns(scriptName: string): RegExp[] {
  const escape = (value: string): string => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const normalizedWords = scriptName
    .split(/\s+/)
    .map((part) => part.trim())
    .filter(Boolean);
  const exact = new RegExp(`^${escape(scriptName)}$`, "i");
  const loose = new RegExp(escape(scriptName), "i");
  const fuzzy = normalizedWords.length > 0
    ? new RegExp(normalizedWords.map((part) => escape(part.slice(0, Math.min(part.length, 4)))).join(".*"), "i")
    : loose;

  return [exact, loose, fuzzy];
}

function validateTradingViewStorageState(storageStatePath: string): void {
  if (boolEnv("TV_SKIP_AUTH_STATE_VALIDATION", false)) {
    return;
  }

  const inspection = inspectTradingViewStorageState(storageStatePath);

  if (inspection.looksAuthenticated) {
    return;
  }

  const cookiePreview = inspection.cookieNames.slice(0, 8).join(", ") || "none";
  const storagePreview = inspection.localStorageKeys.slice(0, 8).join(", ") || "none";
  throw new Error(
    `TV_STORAGE_STATE does not look authenticated. Cookies: ${cookiePreview}. Local storage keys: ${storagePreview}. Refresh it with npm run tv:storage-state after logging in and opening the chart, or set TV_SKIP_AUTH_STATE_VALIDATION=1 to bypass this check.`,
  );
}

function pushLifecycleEvent(tracker: PageLifecycleTracker, type: string, detail?: string): void {
  tracker.recentEvents.push({ at: utcNow(), type, detail });
  if (tracker.recentEvents.length > 25) {
    tracker.recentEvents.splice(0, tracker.recentEvents.length - 25);
  }
}

function attachPageLifecycleTracking(page: Page, context: BrowserContext, browser: Browser): void {
  if (pageLifecycleTrackers.has(page)) {
    return;
  }

  const tracker: PageLifecycleTracker = {
    pageClosed: false,
    pageCrashed: false,
    contextClosed: false,
    browserDisconnected: false,
    activeStep: null,
    stepStack: [],
    recentEvents: [],
  };

  pageLifecycleTrackers.set(page, tracker);
  pushLifecycleEvent(tracker, "page-created", page.url() || undefined);

  page.on("close", () => {
    tracker.pageClosed = true;
    pushLifecycleEvent(tracker, "page-close");
  });

  page.on("crash", () => {
    tracker.pageCrashed = true;
    pushLifecycleEvent(tracker, "page-crash");
  });

  page.on("domcontentloaded", () => {
    pushLifecycleEvent(tracker, "domcontentloaded", page.url() || undefined);
  });

  page.on("framenavigated", (frame) => {
    if (frame === page.mainFrame()) {
      pushLifecycleEvent(tracker, "main-frame-navigated", frame.url() || undefined);
    }
  });

  context.on("close", () => {
    tracker.contextClosed = true;
    pushLifecycleEvent(tracker, "context-close");
  });

  browser.on("disconnected", () => {
    tracker.browserDisconnected = true;
    pushLifecycleEvent(tracker, "browser-disconnected");
  });
}

export function collectPageLifecycleDiagnostics(page: Page): PageLifecycleDiagnostics {
  const tracker = pageLifecycleTrackers.get(page);

  return {
    pageClosed: tracker?.pageClosed ?? page.isClosed(),
    pageCrashed: tracker?.pageCrashed ?? false,
    contextClosed: tracker?.contextClosed ?? false,
    browserDisconnected: tracker?.browserDisconnected ?? false,
    activeStep: tracker?.activeStep ?? null,
    currentUrl: page.isClosed() ? null : page.url() || null,
    eventCount: tracker?.recentEvents.length ?? 0,
    recentEvents: [...(tracker?.recentEvents ?? [])],
  };
}

function setActiveStep(page: Page, stepName: string | null): void {
  const tracker = pageLifecycleTrackers.get(page);
  if (tracker) {
    tracker.activeStep = stepName;
  }
}

function pushActiveStep(page: Page, stepName: string): void {
  const tracker = pageLifecycleTrackers.get(page);
  if (!tracker) {
    return;
  }
  tracker.stepStack.push(stepName);
  tracker.activeStep = tracker.stepStack[tracker.stepStack.length - 1] ?? null;
}

function popActiveStep(page: Page, stepName: string): void {
  const tracker = pageLifecycleTrackers.get(page);
  if (!tracker) {
    return;
  }

  const index = tracker.stepStack.lastIndexOf(stepName);
  if (index !== -1) {
    tracker.stepStack.splice(index, 1);
  }
  tracker.activeStep = tracker.stepStack[tracker.stepStack.length - 1] ?? null;
}

function stepTimeoutMs(): number {
  return numEnv("TV_STEP_TIMEOUT_MS", 45_000);
}

async function runTrackedStep<T>(
  page: Page,
  stepName: string,
  action: () => Promise<T>,
  timeoutMs = stepTimeoutMs(),
): Promise<T> {
  const tracker = pageLifecycleTrackers.get(page);
  const startedAt = Date.now();
  pushActiveStep(page, stepName);
  if (tracker) {
    pushLifecycleEvent(tracker, "step-start", stepName);
  }
  console.error(`[tv-step] start ${stepName}`);

  let timeoutId: NodeJS.Timeout | undefined;

  try {
    const result = await Promise.race<T>([
      action(),
      new Promise<T>((_, reject) => {
        timeoutId = setTimeout(() => {
          const diagnostics = collectPageLifecycleDiagnostics(page);
          reject(
            new Error(
              `Timed out after ${timeoutMs}ms during ${stepName}; lifecycle ${formatPageLifecycleDiagnostics(diagnostics)}`,
            ),
          );
        }, timeoutMs);
      }),
    ]);

    const durationMs = Date.now() - startedAt;
    if (tracker) {
      pushLifecycleEvent(tracker, "step-ok", `${stepName} (${durationMs}ms)`);
    }
    console.error(`[tv-step] ok ${stepName} (${durationMs}ms)`);
    return result;
  } catch (error: unknown) {
    const durationMs = Date.now() - startedAt;
    const message = error instanceof Error ? error.message : String(error);
    if (tracker) {
      pushLifecycleEvent(tracker, "step-error", `${stepName} (${durationMs}ms): ${message}`);
    }
    console.error(`[tv-step] error ${stepName} (${durationMs}ms): ${message}`);
    throw error;
  } finally {
    if (timeoutId) {
      clearTimeout(timeoutId);
    }
    popActiveStep(page, stepName);
  }
}

function tracePageEvent(page: Page, type: string, detail?: string): void {
  const tracker = pageLifecycleTrackers.get(page);
  if (tracker) {
    pushLifecycleEvent(tracker, type, detail);
  }
  console.error(detail ? `[tv-trace] ${type} ${detail}` : `[tv-trace] ${type}`);
}

export function parseInputSourceLabels(code: string): string[] {
  const labels: string[] = [];
  const needle = "input.source(";
  let cursor = 0;

  while (cursor < code.length) {
    const start = code.indexOf(needle, cursor);
    if (start === -1) {
      break;
    }

    const openParenIndex = start + needle.length - 1;
    const call = readBalancedParenthesizedSegment(code, openParenIndex);
    if (!call) {
      cursor = start + needle.length;
      continue;
    }

    const parts = splitTopLevelArguments(call.inner);
    if (parts.length >= 2) {
      const label = readStringLiteral(parts[1]);
      if (label) {
        labels.push(label);
      }
    }

    cursor = call.nextIndex;
  }

  return labels;
}

function readBalancedParenthesizedSegment(
  text: string,
  openParenIndex: number,
): { inner: string; nextIndex: number } | null {
  if (text[openParenIndex] !== "(") {
    return null;
  }

  let depth = 0;
  let quote: '"' | "'" | null = null;
  let escaped = false;

  for (let index = openParenIndex; index < text.length; index += 1) {
    const char = text[index];

    if (quote) {
      if (escaped) {
        escaped = false;
        continue;
      }
      if (char === "\\") {
        escaped = true;
        continue;
      }
      if (char === quote) {
        quote = null;
      }
      continue;
    }

    if (char === '"' || char === "'") {
      quote = char;
      continue;
    }
    if (char === "(") {
      depth += 1;
      continue;
    }
    if (char === ")") {
      depth -= 1;
      if (depth === 0) {
        return {
          inner: text.slice(openParenIndex + 1, index),
          nextIndex: index + 1,
        };
      }
    }
  }

  return null;
}

function splitTopLevelArguments(argumentList: string): string[] {
  const parts: string[] = [];
  let start = 0;
  let depth = 0;
  let quote: '"' | "'" | null = null;
  let escaped = false;

  for (let index = 0; index < argumentList.length; index += 1) {
    const char = argumentList[index];

    if (quote) {
      if (escaped) {
        escaped = false;
        continue;
      }
      if (char === "\\") {
        escaped = true;
        continue;
      }
      if (char === quote) {
        quote = null;
      }
      continue;
    }

    if (char === '"' || char === "'") {
      quote = char;
      continue;
    }
    if (char === "(") {
      depth += 1;
      continue;
    }
    if (char === ")") {
      depth = Math.max(0, depth - 1);
      continue;
    }
    if (char === "," && depth === 0) {
      parts.push(argumentList.slice(start, index).trim());
      start = index + 1;
    }
  }

  const tail = argumentList.slice(start).trim();
  if (tail) {
    parts.push(tail);
  }
  return parts;
}

function readStringLiteral(value: string): string | null {
  const trimmed = value.trim();
  if (trimmed.length < 2) {
    return null;
  }
  const quote = trimmed[0];
  if ((quote !== '"' && quote !== "'") || trimmed[trimmed.length - 1] !== quote) {
    return null;
  }
  return trimmed.slice(1, -1);
}

export function containsOrderedCodeBlock(haystack: string, snippet: string): boolean {
  const haystackLines = significantCodeLines(haystack);
  const snippetLines = significantCodeLines(snippet);

  if (snippetLines.length === 0) {
    return false;
  }

  for (let start = 0; start <= haystackLines.length - snippetLines.length; start += 1) {
    const blockMatches = snippetLines.every((line, offset) => haystackLines[start + offset] === line);
    if (blockMatches) {
      return true;
    }
  }

  return false;
}

export function containsAnchoredCodeBlockAfterLine(haystack: string, anchorLine: string, snippet: string): boolean {
  const haystackLines = significantCodeLines(haystack);
  const normalizedAnchor = significantCodeLines(anchorLine)[0] ?? "";
  const snippetLines = significantCodeLines(snippet);

  if (!normalizedAnchor || snippetLines.length === 0) {
    return false;
  }

  for (let index = 0; index < haystackLines.length; index += 1) {
    if (haystackLines[index] !== normalizedAnchor) {
      continue;
    }

    const candidateBlock = haystackLines.slice(index + 1, index + 1 + snippetLines.length);
    return candidateBlock.length === snippetLines.length
      && candidateBlock.every((line, offset) => line === snippetLines[offset]);
  }

  return false;
}

export function scriptNameAppearsInUiText(scriptName: string, uiText: string): boolean {
  const normalizedText = normalizeUiText(uiText);
  const compactText = compactUiText(uiText);
  const compactScriptName = compactUiText(scriptName);

  return buildScriptNamePatterns(scriptName).some((pattern) => pattern.test(normalizedText))
    || compactText.includes(compactScriptName);
}

export function uiTextContainsExactScriptName(scriptName: string, uiText: string): boolean {
  const normalizedScriptName = normalizeUiText(scriptName);
  if (!normalizedScriptName) {
    return false;
  }

  return normalizeUiText(uiText)
    .toLowerCase()
    .includes(normalizedScriptName.toLowerCase());
}

function stripInlineComment(line: string): string {
  let quote: '"' | "'" | null = null;
  let escaped = false;

  for (let index = 0; index < line.length; index += 1) {
    const current = line[index];
    const next = line[index + 1];

    if (quote) {
      if (escaped) {
        escaped = false;
        continue;
      }
      if (current === "\\") {
        escaped = true;
        continue;
      }
      if (current === quote) {
        quote = null;
      }
      continue;
    }

    if (current === '"' || current === "'") {
      quote = current;
      continue;
    }

    if (current === "/" && next === "/") {
      return line.slice(0, index).trim();
    }
  }

  return line.trim();
}

function significantCodeLines(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => stripInlineComment(line))
    .map((line) => line.trim())
    .filter((line) => Boolean(line) && !line.startsWith("//"));
}

export function verifyOpenScriptIdentity(scriptName: string, options: {
  dialogStillVisible: boolean;
  editorContextTexts: string[];
  bodyText?: string;
}): boolean {
  if (options.dialogStillVisible) {
    return false;
  }

  const exactEditorMatch = options.editorContextTexts.some((candidate) =>
    uiTextContainsExactScriptName(scriptName, candidate)
  );
  if (!exactEditorMatch) {
    return false;
  }

  const bodyText = options.bodyText ?? "";
  if (bodyText && !scriptNameAppearsInUiText(scriptName, bodyText)) {
    return false;
  }

  return true;
}

export function detectPublishedVersionFromBody(bodyText: string, scriptName?: string): number | null {
  const normalizedBody = normalizeUiText(bodyText);
  if (!scriptName) {
    const genericMatch = normalizedBody.match(/\bversion\s+(\d+)\b/i);
    if (!genericMatch) {
      return null;
    }
    const genericVersion = Number(genericMatch[1]);
    return Number.isFinite(genericVersion) ? genericVersion : null;
  }

  const normalizedScriptName = normalizeUiText(scriptName);
  const scriptIndex = normalizedBody.toLowerCase().indexOf(normalizedScriptName.toLowerCase());
  if (scriptIndex === -1) {
    return null;
  }

  const afterScript = normalizedBody.slice(scriptIndex, scriptIndex + 240);
  const versionAfterScript = afterScript.match(/\bversion\s+(\d+)\b/i);
  if (versionAfterScript) {
    const version = Number(versionAfterScript[1]);
    if (Number.isFinite(version)) {
      return version;
    }
  }

  return null;
}

export function detectPublishedVersionFromContextTexts(contextTexts: string[], scriptName?: string): number | null {
  const normalizedTexts = contextTexts.map((text) => normalizeUiText(text)).filter(Boolean);
  if (normalizedTexts.length === 0) {
    return null;
  }

  if (!scriptName) {
    for (const candidate of normalizedTexts) {
      const match = candidate.match(/\bversion\s+(\d+)\b/i);
      if (!match) {
        continue;
      }
      const version = Number(match[1]);
      if (Number.isFinite(version)) {
        return version;
      }
    }
    return null;
  }

  for (const candidate of normalizedTexts) {
    if (!uiTextContainsExactScriptName(scriptName, candidate)) {
      continue;
    }
    const normalizedScriptName = normalizeUiText(scriptName);
    const scriptIndex = candidate.toLowerCase().indexOf(normalizedScriptName.toLowerCase());
    if (scriptIndex === -1) {
      continue;
    }
    const afterScript = candidate.slice(scriptIndex, scriptIndex + 240);
    const match = afterScript.match(/\bversion\s+(\d+)\b/i);
    if (!match) {
      continue;
    }
    const version = Number(match[1]);
    if (Number.isFinite(version)) {
      return version;
    }
  }

  return null;
}

export function resolvePublishedVersionEvidence(options: {
  scriptName: string;
  contextTexts: string[];
  bodyText: string;
}): {
  publishedVersion: number | null;
  verificationMode: "script_context" | "body_fallback" | "not_verified";
  fallbackVersion: number | null;
} {
  const contextVersion = detectPublishedVersionFromContextTexts(options.contextTexts, options.scriptName);
  if (contextVersion !== null) {
    return {
      publishedVersion: contextVersion,
      verificationMode: "script_context",
      fallbackVersion: null,
    };
  }

  const fallbackVersion = detectPublishedVersionFromBody(options.bodyText, options.scriptName);
  if (fallbackVersion !== null) {
    return {
      publishedVersion: fallbackVersion,
      verificationMode: "body_fallback",
      fallbackVersion,
    };
  }

  return {
    publishedVersion: null,
    verificationMode: "not_verified",
    fallbackVersion: null,
  };
}

export async function newTradingViewSession(): Promise<TradingViewSession> {
  const authResolution = resolveTradingViewAuthResolution(process.env);
  const launchOptions = {
    headless: boolEnv("TV_HEADLESS", false),
  };

  let browser: Browser;
  let context: BrowserContext;

  if (authResolution.authMode === "persistent_profile") {
    if (!authResolution.authSourcePath) {
      throw new Error("TradingView auth resolution selected persistent_profile without a path");
    }

    fs.mkdirSync(authResolution.authSourcePath, { recursive: true });
    context = await chromium.launchPersistentContext(authResolution.authSourcePath, {
      ...launchOptions,
      viewport: { width: 1600, height: 1200 },
    });
    const launchedBrowser = context.browser();
    if (!launchedBrowser) {
      throw new Error(`Could not resolve browser for persistent TradingView profile: ${authResolution.authSourcePath}`);
    }
    browser = launchedBrowser;
  } else if (authResolution.authMode === "storage_state") {
    if (!authResolution.authSourcePath) {
      throw new Error("TradingView auth resolution selected storage_state without a path");
    }

    const storageStatePath = authResolution.authSourcePath;
    validateTradingViewStorageState(storageStatePath);

    browser = await chromium.launch(launchOptions);
    context = await browser.newContext({
      storageState: storageStatePath,
      viewport: { width: 1600, height: 1200 },
    });
  } else {
    throw new Error(
      "No reusable TradingView auth source configured. Provide a valid TV_STORAGE_STATE or TV_PERSISTENT_PROFILE_DIR before running TradingView automation.",
    );
  }

  const chartOrigin = new URL(process.env.TV_CHART_URL || "https://www.tradingview.com/chart/").origin;
  await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin: chartOrigin }).catch(() => undefined);

  const page = context.pages()[0] ?? await context.newPage();
  page.setDefaultTimeout(numEnv("TV_TIMEOUT_MS", 25_000));
  attachPageLifecycleTracking(page, context, browser);

  return { browser, context, page, authResolution };
}

export async function closeTradingViewSession(session: TradingViewSession): Promise<void> {
  await session.context.close().catch(() => undefined);
  await session.browser.close().catch(() => undefined);
}

export async function gotoChart(page: Page): Promise<void> {
  await page.goto(process.env.TV_CHART_URL || "https://www.tradingview.com/chart/", {
    waitUntil: "domcontentloaded",
  });
  await page.waitForTimeout(3_000);
}

export async function takeScreenshot(
  page: Page,
  runId: string,
  name: string,
  collectedPaths?: string[],
): Promise<string> {
  const dir = process.env.TV_SCREENSHOT_DIR || "automation/tradingview/reports/screenshots";
  fs.mkdirSync(dir, { recursive: true });

  const filePath = path.join(dir, `${runId}-${name}.png`);
  await page.screenshot({ path: filePath, fullPage: true });

  if (collectedPaths) {
    collectedPaths.push(filePath);
  }

  return filePath;
}

async function countVisible(page: Page, selector: string): Promise<VisibleCount> {
  const locator = page.locator(selector);
  const total = await locator.count().catch(() => 0);
  let visible = 0;

  for (let index = 0; index < total; index += 1) {
    try {
      if (await locator.nth(index).isVisible({ timeout: 250 })) {
        visible += 1;
      }
    } catch {
      // Ignore detached nodes during dynamic UI updates.
    }
  }

  return { total, visible };
}

function compactTexts(values: string[], limit: number): string[] {
  return values.map((value) => value.trim()).filter(Boolean).slice(0, limit);
}

export async function collectEditorDiagnostics(page: Page): Promise<EditorDiagnostics> {
  const textareaCount = await countVisible(page, "textarea");
  const contentEditableCount = await countVisible(page, '[contenteditable="true"]');
  const monacoCount = await countVisible(
    page,
    '.monaco-editor, [class*="monaco-editor"], [data-name*="editor"]',
  );
  const pineButtons = compactTexts(
    await page.getByRole("button", { name: /pine|editor|save|publish/i }).allInnerTexts().catch(() => []),
    20,
  );
  const pineTexts = compactTexts(
    await page.getByText(/pine|editor|save|publish|cookie|accept/i).allInnerTexts().catch(() => []),
    20,
  );
  const bodyText = await page.locator("body").innerText().catch(() => "");
  const relevantBodyLines = compactTexts(
    bodyText
      .split(/\n+/)
      .filter((line) => /pine|editor|save|publish|cookie|accept/i.test(line)),
    40,
  );

  return {
    textareaCount,
    contentEditableCount,
    monacoCount,
    pineButtonCount: pineButtons.length,
    pineButtons,
    pineTextCount: pineTexts.length,
    pineTexts,
    relevantBodyLines,
  };
}

function hasVisibleEditorHost(diagnostics: EditorDiagnostics): boolean {
  return (
    diagnostics.textareaCount.visible > 0 ||
    diagnostics.contentEditableCount.visible > 0 ||
    diagnostics.monacoCount.visible > 0
  );
}

function formatEditorDiagnostics(diagnostics: EditorDiagnostics): string {
  return [
    `textarea visible ${diagnostics.textareaCount.visible}/${diagnostics.textareaCount.total}`,
    `contenteditable visible ${diagnostics.contentEditableCount.visible}/${diagnostics.contentEditableCount.total}`,
    `monaco visible ${diagnostics.monacoCount.visible}/${diagnostics.monacoCount.total}`,
    `pine buttons ${diagnostics.pineButtonCount}`,
    `pine texts ${diagnostics.pineTextCount}`,
  ].join(", ");
}

function formatPageLifecycleDiagnostics(diagnostics: PageLifecycleDiagnostics): string {
  return [
    `pageClosed ${diagnostics.pageClosed}`,
    `pageCrashed ${diagnostics.pageCrashed}`,
    `contextClosed ${diagnostics.contextClosed}`,
    `browserDisconnected ${diagnostics.browserDisconnected}`,
    diagnostics.activeStep ? `activeStep ${diagnostics.activeStep}` : "activeStep none",
    `events ${diagnostics.eventCount}`,
    diagnostics.currentUrl ? `url ${diagnostics.currentUrl}` : "url unavailable",
  ].join(", ");
}

async function firstVisibleLocator(locator: Locator, timeoutMs = 2_500): Promise<Locator | null> {
  const total = await locator.count().catch(() => 0);

  for (let index = 0; index < total; index += 1) {
    const candidate = locator.nth(index);
    try {
      if (await candidate.isVisible({ timeout: timeoutMs })) {
        return candidate;
      }
    } catch {
      // continue scanning dynamic nodes
    }
  }

  return null;
}

export async function collectOpenScriptIdentityTexts(page: Page, scriptName: string): Promise<string[]> {
  const texts: string[] = [];

  for (const candidate of tvSelectors.openScriptIdentity(page, scriptName)) {
    const visible = await firstVisibleLocator(candidate, 750);
    if (!visible) {
      continue;
    }
    const text = await visible.innerText().catch(() => "");
    const ariaLabel = await visible.getAttribute("aria-label").catch(() => "");
    const title = await visible.getAttribute("title").catch(() => "");
    for (const value of [text, ariaLabel ?? "", title ?? ""]) {
      const normalized = normalizeUiText(value);
      if (normalized) {
        texts.push(normalized);
      }
    }
  }

  return [...new Set(texts)];
}

async function firstVisibleLocatorFast(locator: Locator, timeoutMs = 500): Promise<Locator | null> {
  const startedAt = Date.now();

  while (Date.now() - startedAt < timeoutMs) {
    const total = await locator.count().catch(() => 0);

    for (let index = 0; index < total; index += 1) {
      const candidate = locator.nth(index);
      try {
        if (await candidate.isVisible({ timeout: 50 })) {
          return candidate;
        }
      } catch {
        // continue scanning dynamic nodes
      }
    }

    await new Promise((resolve) => setTimeout(resolve, 50));
  }

  return null;
}

export async function clickFirst(candidates: Locator[], timeoutMs = 2_500): Promise<boolean> {
  for (const locator of candidates) {
    const candidate = await firstVisibleLocator(locator, timeoutMs);
    if (candidate) {
      await candidate.click();
      return true;
    }
  }

  return false;
}

export async function fillFirst(value: string, candidates: Locator[], timeoutMs = 2_500): Promise<boolean> {
  for (const locator of candidates) {
    const candidate = await firstVisibleLocator(locator, timeoutMs);
    if (candidate) {
      await candidate.fill(value);
      return true;
    }
  }

  return false;
}

async function clickVisibleWithFallback(
  page: Page,
  candidates: Locator[],
  tracePrefix: string,
  timeoutMs = 2_000,
  settleMs = 500,
): Promise<boolean> {
  for (const [index, locator] of candidates.entries()) {
    const candidate = await firstVisibleLocator(locator, timeoutMs);
    if (!candidate) {
      tracePageEvent(page, `${tracePrefix}-candidate-missing`, `candidate:${index}`);
      continue;
    }

    tracePageEvent(page, `${tracePrefix}-candidate-visible`, `candidate:${index}`);

    try {
      await candidate.scrollIntoViewIfNeeded().catch(() => undefined);
      await candidate.hover({ timeout: timeoutMs }).catch(() => undefined);
      await candidate.click({ timeout: timeoutMs + 1_000 });
      await page.waitForTimeout(settleMs);
      return true;
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      tracePageEvent(page, `${tracePrefix}-click-error`, `candidate:${index}:${message}`);
    }

    try {
      await candidate.click({ timeout: timeoutMs, force: true });
      await page.waitForTimeout(settleMs);
      return true;
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      tracePageEvent(page, `${tracePrefix}-force-error`, `candidate:${index}:${message}`);
    }

    const box = await candidate.boundingBox().catch(() => null);
    if (box && box.width > 6 && box.height > 6) {
      tracePageEvent(page, `${tracePrefix}-offset-start`, `candidate:${index}:${Math.round(box.width)}x${Math.round(box.height)}`);
      const offsetPositions = [
        { x: 4, y: Math.max(3, Math.min(box.height / 2, box.height - 3)) },
        { x: Math.max(3, box.width - 4), y: Math.max(3, Math.min(box.height / 2, box.height - 3)) },
        { x: Math.max(3, Math.min(box.width / 2, box.width - 3)), y: 3 },
        { x: Math.max(3, Math.min(box.width / 2, box.width - 3)), y: Math.max(3, box.height - 4) },
      ];

      for (const [positionIndex, position] of offsetPositions.entries()) {
        try {
          await candidate.click({ timeout: timeoutMs, position });
          await page.waitForTimeout(settleMs);
          return true;
        } catch (error: unknown) {
          const message = error instanceof Error ? error.message : String(error);
          tracePageEvent(page, `${tracePrefix}-offset-error`, `candidate:${index}:${positionIndex}:${message}`);
        }
      }
    }

    if (!box) {
      tracePageEvent(page, `${tracePrefix}-offset-skip`, `candidate:${index}:no-box`);
      continue;
    }

    try {
      const pointerBypassed = await candidate.evaluate((node) => {
        const element = node as HTMLElement;
        const rect = element.getBoundingClientRect();
        const x = rect.left + Math.max(2, Math.min(rect.width / 2, rect.width - 2));
        const y = rect.top + Math.max(2, Math.min(rect.height / 2, rect.height - 2));
        const patched: Array<{ element: HTMLElement; value: string }> = [];

        let hit = document.elementFromPoint(x, y) as HTMLElement | null;
        while (hit && hit !== element && !element.contains(hit) && patched.length < 6) {
          patched.push({ element: hit, value: hit.style.pointerEvents });
          hit.style.pointerEvents = "none";
          hit = document.elementFromPoint(x, y) as HTMLElement | null;
        }

        const targetReady = hit === element || Boolean(hit && element.contains(hit));
        if (targetReady) {
          element.dispatchEvent(
            new MouseEvent("click", {
              bubbles: true,
              cancelable: true,
              composed: true,
              clientX: x,
              clientY: y,
              view: window,
            }),
          );
          element.click();
        }

        for (const entry of patched.reverse()) {
          entry.element.style.pointerEvents = entry.value;
        }

        return targetReady;
      });
      if (pointerBypassed) {
        tracePageEvent(page, `${tracePrefix}-pointer-bypass-ok`, `candidate:${index}`);
        await page.waitForTimeout(settleMs);
        return true;
      }
      tracePageEvent(page, `${tracePrefix}-pointer-bypass-miss`, `candidate:${index}`);
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      tracePageEvent(page, `${tracePrefix}-pointer-bypass-error`, `candidate:${index}:${message}`);
    }

    try {
      await candidate.evaluate((node) => {
        const element = node as HTMLElement;
        element.scrollIntoView({ block: "center", inline: "center" });
        for (const eventType of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
          element.dispatchEvent(
            new MouseEvent(eventType, {
              bubbles: true,
              cancelable: true,
              composed: true,
              view: window,
            }),
          );
        }
        element.click();
      });
      tracePageEvent(page, `${tracePrefix}-dom-ok`, `candidate:${index}`);
      await page.waitForTimeout(settleMs);
      return true;
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      tracePageEvent(page, `${tracePrefix}-dom-error`, `candidate:${index}:${message}`);
    }
  }

  return false;
}

async function clickVisibleWithFallbackOutsidePineDialog(
  page: Page,
  candidates: Locator[],
  tracePrefix: string,
  timeoutMs = 2_000,
  settleMs = 500,
  requireVisibleSurface = false,
): Promise<boolean> {
  for (const [index, locator] of candidates.entries()) {
    const total = await locator.count().catch(() => 0);
    tracePageEvent(page, `${tracePrefix}-locator-count`, `candidate:${index}:${total}`);

    for (let itemIndex = 0; itemIndex < total; itemIndex += 1) {
      const candidate = locator.nth(itemIndex);
      let visible = false;
      try {
        visible = await candidate.isVisible({ timeout: timeoutMs });
      } catch {
        visible = false;
      }
      if (!visible) {
        tracePageEvent(page, `${tracePrefix}-item-hidden`, `candidate:${index}:${itemIndex}`);
        continue;
      }

      const insidePineDialog = await candidate
        .evaluate((node) => Boolean(node.closest('[data-name="pine-dialog"]')))
        .catch(() => false);
      if (insidePineDialog) {
        tracePageEvent(page, `${tracePrefix}-item-skip-pine-dialog`, `candidate:${index}:${itemIndex}`);
        continue;
      }

      tracePageEvent(page, `${tracePrefix}-item-visible`, `candidate:${index}:${itemIndex}`);

      try {
        await candidate.scrollIntoViewIfNeeded().catch(() => undefined);
        await candidate.hover({ timeout: timeoutMs }).catch(() => undefined);
        await candidate.click({ timeout: timeoutMs + 1_000 });
        await page.waitForTimeout(settleMs);
        if (requireVisibleSurface && !(await waitForSettingsSurface(page, 750))) {
          tracePageEvent(page, `${tracePrefix}-click-no-surface`, `candidate:${index}:${itemIndex}`);
        } else {
          return true;
        }
      } catch (error: unknown) {
        const message = error instanceof Error ? error.message : String(error);
        tracePageEvent(page, `${tracePrefix}-click-error`, `candidate:${index}:${itemIndex}:${message}`);
      }

      try {
        await candidate.click({ timeout: timeoutMs, force: true });
        await page.waitForTimeout(settleMs);
        if (requireVisibleSurface && !(await waitForSettingsSurface(page, 750))) {
          tracePageEvent(page, `${tracePrefix}-force-no-surface`, `candidate:${index}:${itemIndex}`);
        } else {
          return true;
        }
      } catch (error: unknown) {
        const message = error instanceof Error ? error.message : String(error);
        tracePageEvent(page, `${tracePrefix}-force-error`, `candidate:${index}:${itemIndex}:${message}`);
      }

      const box = await candidate.boundingBox().catch(() => null);
      if (box && box.width > 6 && box.height > 6) {
        tracePageEvent(page, `${tracePrefix}-offset-start`, `candidate:${index}:${itemIndex}:${Math.round(box.width)}x${Math.round(box.height)}`);
        const offsetPositions = [
          { x: 4, y: Math.max(3, Math.min(box.height / 2, box.height - 3)) },
          { x: Math.max(3, box.width - 4), y: Math.max(3, Math.min(box.height / 2, box.height - 3)) },
          { x: Math.max(3, Math.min(box.width / 2, box.width - 3)), y: 3 },
          { x: Math.max(3, Math.min(box.width / 2, box.width - 3)), y: Math.max(3, box.height - 4) },
        ];

        for (const [positionIndex, position] of offsetPositions.entries()) {
          try {
            await candidate.click({ timeout: timeoutMs, position });
            await page.waitForTimeout(settleMs);
            if (requireVisibleSurface && !(await waitForSettingsSurface(page, 750))) {
              tracePageEvent(page, `${tracePrefix}-offset-no-surface`, `candidate:${index}:${itemIndex}:${positionIndex}`);
            } else {
              return true;
            }
          } catch (error: unknown) {
            const message = error instanceof Error ? error.message : String(error);
            tracePageEvent(page, `${tracePrefix}-offset-error`, `candidate:${index}:${itemIndex}:${positionIndex}:${message}`);
          }
        }
      }

      if (!box) {
        tracePageEvent(page, `${tracePrefix}-offset-skip`, `candidate:${index}:${itemIndex}:no-box`);
      }

      try {
        const pointerBypassed = await candidate.evaluate((node) => {
          const element = node as HTMLElement;
          const rect = element.getBoundingClientRect();
          const x = rect.left + Math.max(2, Math.min(rect.width / 2, rect.width - 2));
          const y = rect.top + Math.max(2, Math.min(rect.height / 2, rect.height - 2));
          const patched: Array<{ element: HTMLElement; value: string }> = [];

          let hit = document.elementFromPoint(x, y) as HTMLElement | null;
          while (hit && hit !== element && !element.contains(hit) && patched.length < 6) {
            patched.push({ element: hit, value: hit.style.pointerEvents });
            hit.style.pointerEvents = "none";
            hit = document.elementFromPoint(x, y) as HTMLElement | null;
          }

          const targetReady = hit === element || Boolean(hit && element.contains(hit));
          if (targetReady) {
            element.dispatchEvent(
              new MouseEvent("click", {
                bubbles: true,
                cancelable: true,
                composed: true,
                clientX: x,
                clientY: y,
                view: window,
              }),
            );
            element.click();
          }

          for (const entry of patched.reverse()) {
            entry.element.style.pointerEvents = entry.value;
          }

          return targetReady;
        });
        if (pointerBypassed) {
          tracePageEvent(page, `${tracePrefix}-pointer-bypass-ok`, `candidate:${index}:${itemIndex}`);
          await page.waitForTimeout(settleMs);
          if (requireVisibleSurface && !(await waitForSettingsSurface(page, 750))) {
            tracePageEvent(page, `${tracePrefix}-pointer-bypass-no-surface`, `candidate:${index}:${itemIndex}`);
          } else {
            return true;
          }
        }
        tracePageEvent(page, `${tracePrefix}-pointer-bypass-miss`, `candidate:${index}:${itemIndex}`);
      } catch (error: unknown) {
        const message = error instanceof Error ? error.message : String(error);
        tracePageEvent(page, `${tracePrefix}-pointer-bypass-error`, `candidate:${index}:${itemIndex}:${message}`);
      }

      try {
        await candidate.evaluate((node) => {
          const element = node as HTMLElement;
          element.scrollIntoView({ block: "center", inline: "center" });
          for (const eventType of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
            element.dispatchEvent(
              new MouseEvent(eventType, {
                bubbles: true,
                cancelable: true,
                composed: true,
                view: window,
              }),
            );
          }
          element.click();
        });
        tracePageEvent(page, `${tracePrefix}-dom-ok`, `candidate:${index}:${itemIndex}`);
        await page.waitForTimeout(settleMs);
        if (requireVisibleSurface && !(await waitForSettingsSurface(page, 750))) {
          tracePageEvent(page, `${tracePrefix}-dom-no-surface`, `candidate:${index}:${itemIndex}`);
        } else {
          return true;
        }
      } catch (error: unknown) {
        const message = error instanceof Error ? error.message : String(error);
        tracePageEvent(page, `${tracePrefix}-dom-error`, `candidate:${index}:${itemIndex}:${message}`);
      }
    }
  }

  return false;
}

async function hasVisibleLocator(candidates: Locator[], timeoutMs = 500): Promise<boolean> {
  for (const locator of candidates) {
    const candidate = await firstVisibleLocator(locator, timeoutMs);
    if (candidate) {
      return true;
    }
  }

  return false;
}

async function hasVisibleLocatorFast(candidates: Locator[], timeoutMs = 500): Promise<boolean> {
  for (const locator of candidates) {
    const candidate = await firstVisibleLocatorFast(locator, timeoutMs);
    if (candidate) {
      return true;
    }
  }

  return false;
}

async function dispatchDomMouseGesture(container: Locator, gesture: "click" | "dblclick"): Promise<boolean> {
  return container.evaluate((node, currentGesture) => {
    const element = node as HTMLElement | null;
    if (!element) {
      return false;
    }

    element.scrollIntoView({ block: "center", inline: "center" });
    const eventTypes = currentGesture === "dblclick"
      ? ["pointerdown", "mousedown", "pointerup", "mouseup", "click", "pointerdown", "mousedown", "pointerup", "mouseup", "click", "dblclick"]
      : ["pointerdown", "mousedown", "pointerup", "mouseup", "click"];

    for (const eventType of eventTypes) {
      element.dispatchEvent(
        new MouseEvent(eventType, {
          bubbles: true,
          cancelable: true,
          composed: true,
          view: window,
        }),
      );
    }

    if (currentGesture === "click") {
      element.click();
    }

    return true;
  }, gesture).catch(() => false);
}

async function snapshotDialog(dialog: Locator): Promise<VisibleDialogSnapshot> {
  const titleLocator = dialog.locator('h1, h2, h3, [role="heading"], [data-name*="title" i], [class*="title" i]').first();
  const title = normalizeUiText((await titleLocator.innerText().catch(() => "")) || "");
  const text = normalizeUiText((await dialog.innerText().catch(() => "")) || "");

  const labelLocator = dialog.locator('label, [class*="label" i], [data-name*="label" i]');
  const labelCount = await labelLocator.count().catch(() => 0);
  const labelTexts: string[] = [];
  for (let index = 0; index < Math.min(labelCount, 80); index += 1) {
    const labelText = normalizeUiText((await labelLocator.nth(index).innerText().catch(() => "")) || "");
    if (labelText) {
      labelTexts.push(labelText);
    }
  }

  return {
    title,
    text,
    labelTexts,
  };
}

async function collectVisibleDialogSnapshots(page: Page): Promise<VisibleDialogSnapshot[]> {
  const roots = [
    page.locator('[role="dialog"]'),
    page.locator('[data-name*="dialog" i], [class*="dialog" i], [class*="modal" i]'),
  ];
  const snapshots: VisibleDialogSnapshot[] = [];
  const seenTexts = new Set<string>();

  for (const root of roots) {
    const total = await root.count().catch(() => 0);
    for (let index = 0; index < total; index += 1) {
      const dialog = root.nth(index);
      const visible = await dialog.isVisible({ timeout: 250 }).catch(() => false);
      if (!visible) {
        continue;
      }

      const snapshot = await snapshotDialog(dialog).catch(() => null);
      if (!snapshot) {
        continue;
      }

      const key = `${snapshot.title}\n${snapshot.text.slice(0, 500)}`;
      if (seenTexts.has(key)) {
        continue;
      }
      seenTexts.add(key);
      snapshots.push(snapshot);
    }
  }

  return snapshots;
}

async function collectVisibleDialogSnapshot(page: Page): Promise<VisibleDialogSnapshot | null> {
  const dialogs = await collectVisibleDialogSnapshots(page);
  return dialogs[0] ?? null;
}

async function findIndicatorSettingsDialog(page: Page, timeoutMs = 750): Promise<Locator | null> {
  const candidates = [
    page.locator('[role="dialog"]').filter({ hasText: /\binputs\b/i }).filter({ hasText: /\b(style|properties|visibility)\b/i }),
    page.locator('[data-name*="dialog" i], [class*="dialog" i], [class*="modal" i]').filter({ hasText: /\binputs\b/i }).filter({ hasText: /\b(style|properties|visibility)\b/i }),
    page.locator('[role="dialog"]'),
    page.locator('[data-name*="dialog" i], [class*="dialog" i], [class*="modal" i]'),
  ];

  for (const candidate of candidates) {
    const visible = await firstVisibleLocatorFast(candidate, timeoutMs);
    if (visible) {
      const snapshot = await snapshotDialog(visible).catch(() => null);
      if (isIndicatorSettingsDialogSnapshot(snapshot)) {
        return visible;
      }
    }
  }

  return null;
}

function isIndicatorSettingsDialogSnapshot(dialog: VisibleDialogSnapshot | null | undefined): boolean {
  if (!dialog) {
    return false;
  }

  const text = normalizeUiText(dialog.text || "");
  const compactText = compactUiText(text);
  const compactLabels = compactUiText((dialog.labelTexts ?? []).join(" "));
  const hasInputsTab = /\binputs\b/i.test(text) || compactText.includes("inputs") || compactLabels.includes("inputs");
  const hasVisibilityTab = /\bvisibility\b/i.test(text) || compactText.includes("visibility") || compactLabels.includes("visibility");
  const hasIndicatorTab = /\b(style|properties)\b/i.test(text)
    || compactText.includes("style")
    || compactText.includes("properties")
    || compactLabels.includes("style")
    || compactLabels.includes("properties");
  const title = normalizeUiText(dialog.title || "");
  const compactTitle = compactUiText(title);
  const isGenericChartSettings = (/^settings$/i.test(title) || compactTitle === "settings")
    && (compactText.includes("symbolstatuslinescalesandlinescanvas") || /symbol status line scales and lines canvas/i.test(text));

  if (isGenericChartSettings) {
    return false;
  }

  return hasInputsTab && (hasVisibilityTab || hasIndicatorTab);
}

async function hasIndicatorSettingsDialog(page: Page): Promise<boolean> {
  return Boolean(await findIndicatorSettingsDialog(page, 400));
}

async function hasQuickVisibleScriptSettingsSurface(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    const compact = (value: string): string => value.replace(/\s+/g, " ").trim().replace(/[^a-z0-9]+/gi, "").toLowerCase();
    const isVisible = (element: Element): boolean => {
      const node = element as HTMLElement;
      const style = window.getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
    };

    const surfaceSelectors = [
      '[role="dialog"]',
      '[role="menu"]',
      '[data-name*="dialog" i]',
      '[class*="dialog" i]',
      '[class*="modal" i]',
      '[class*="popover" i]',
      '[data-name*="popover" i]',
    ].join(", ");
    const tabSelectors = [
      '[role="tab"]',
      '[data-name*="tab" i]',
      'button',
      '[role="button"]',
    ].join(", ");

    const surfaceTexts = Array.from(document.querySelectorAll(surfaceSelectors))
      .filter((element) => isVisible(element) && !(element as HTMLElement).closest('[data-name="pine-dialog"]'))
      .map((element) => compact((element as HTMLElement).innerText || ""));
    const tabTexts = Array.from(document.querySelectorAll(tabSelectors))
      .filter((element) => isVisible(element) && !(element as HTMLElement).closest('[data-name="pine-dialog"]'))
      .map((element) => compact((element as HTMLElement).innerText || (element as HTMLElement).getAttribute('aria-label') || ""))
      .filter(Boolean);

    const hasTabSet = tabTexts.some((text) => text.includes('inputs'))
      && tabTexts.some((text) => text.includes('style') || text.includes('properties') || text.includes('visibility'));
    const hasSurfaceText = surfaceTexts.some((text) =>
      text.includes('inputs') && (text.includes('style') || text.includes('properties') || text.includes('visibility')),
    );
    const hasGenericChartSettings = surfaceTexts.some((text) => text.includes('symbolstatuslinescalesandlinescanvas'));

    return (hasTabSet || hasSurfaceText) && !hasGenericChartSettings;
  }).catch(() => false);
}

async function hasScriptSettingsInputsSurface(page: Page): Promise<boolean> {
  return (await hasQuickVisibleScriptSettingsSurface(page))
    || (await hasIndicatorSettingsDialog(page))
    || (await hasVisibleLocatorFast(tvSelectors.inputsTab(page), 250));
}

async function waitForScriptSettingsInputsSurface(page: Page, timeoutMs = 2_000): Promise<boolean> {
  const startedAt = Date.now();

  while (Date.now() - startedAt < timeoutMs) {
    if (await hasQuickVisibleScriptSettingsSurface(page)) {
      return true;
    }
    await page.waitForTimeout(100);
  }

  return hasScriptSettingsInputsSurface(page);
}

async function findVisibleDialogByText(page: Page, pattern: RegExp, timeoutMs = 750): Promise<Locator | null> {
  const candidates = [
    page.locator('[role="dialog"]').filter({ hasText: pattern }),
    page.locator('[data-name*="dialog" i], [class*="dialog" i], [class*="modal" i]').filter({ hasText: pattern }),
  ];

  for (const candidate of candidates) {
    const visible = await firstVisibleLocator(candidate, timeoutMs);
    if (visible) {
      return visible;
    }
  }

  return null;
}

async function isSettingsSurfaceVisible(page: Page, timeoutMs = 500): Promise<boolean> {
  return (
    (await hasQuickVisibleScriptSettingsSurface(page))
    || (await hasVisibleLocatorFast(tvSelectors.settingsAction(page), timeoutMs))
    || (await hasVisibleLocatorFast(tvSelectors.inputsTab(page), timeoutMs))
  );
}

async function waitForSettingsSurface(page: Page, timeoutMs = 2_000): Promise<boolean> {
  const startedAt = Date.now();

  while (Date.now() - startedAt < timeoutMs) {
    if (await isSettingsSurfaceVisible(page, 250)) {
      return true;
    }
    await page.waitForTimeout(100);
  }

  return isSettingsSurfaceVisible(page, 250);
}

async function resolveOpenedSettingsSurfaceToIndicatorDialog(
  page: Page,
  tracePrefix: string,
  timeoutMs = 1_500,
): Promise<boolean> {
  if (await waitForScriptSettingsInputsSurface(page, Math.min(timeoutMs, 900))) {
    tracePageEvent(page, `${tracePrefix}-script-settings-visible`);
    return true;
  }

  if (!(await waitForSettingsSurface(page, timeoutMs))) {
    tracePageEvent(page, `${tracePrefix}-surface-miss`);
    return false;
  }

  const clickedSettings = await clickVisibleWithFallback(
    page,
    tvSelectors.settingsAction(page),
    `${tracePrefix}-action`,
    1_200,
    350,
  );
  tracePageEvent(page, `${tracePrefix}-action-result`, String(clickedSettings));
  if (clickedSettings && (await waitForScriptSettingsInputsSurface(page, 1_500))) {
    tracePageEvent(page, `${tracePrefix}-script-settings-after-action`);
    return true;
  }

  const dialog = await collectVisibleDialogSnapshot(page).catch(() => null);
  if (dialog) {
    tracePageEvent(
      page,
      `${tracePrefix}-dialog-snapshot`,
      normalizeUiText(`${dialog.title} ${dialog.text}`).slice(0, 180),
    );
  }
  await closeModal(page).catch(() => undefined);
  return false;
}

export async function collectVisibleChartScriptState(page: Page, scriptName: string): Promise<VisibleChartScriptState> {
  const [, scriptNamePattern, fuzzyPattern] = buildScriptNamePatterns(scriptName);
  const strategyPattern = /strategy report/i;

  const legendWrappers = await findLegendRowWrappers(page, scriptName).catch(() => []);
  const hasLegendMatch = legendWrappers.length > 0;
  const hasStrategyReportMatch = await hasVisibleLocator([
    page.getByText(strategyPattern),
    page.getByRole("button", { name: strategyPattern }),
  ], 500);
  const hasScriptNameMatch = await hasVisibleLocator([
    page.getByText(scriptNamePattern),
    page.getByText(fuzzyPattern),
    page.getByRole("button", { name: scriptNamePattern }),
    page.getByRole("button", { name: fuzzyPattern }),
    page.getByRole("link", { name: scriptNamePattern }),
    page.getByRole("link", { name: fuzzyPattern }),
  ], 500);

  return {
    hasLegendMatch,
    hasStrategyReportMatch,
    hasScriptNameMatch,
  };
}

function isScriptVisibleOnChart(state: VisibleChartScriptState): boolean {
  return state.hasLegendMatch || state.hasStrategyReportMatch;
}

export function isScriptVisibleOnChartState(state: VisibleChartScriptState): boolean {
  return isScriptVisibleOnChart(state);
}

export async function isScriptVisibleOnChartSurface(page: Page, scriptName: string): Promise<boolean> {
  const state = await collectVisibleChartScriptState(page, scriptName);
  return isScriptVisibleOnChart(state);
}

async function findLegendRowWrappers(page: Page, scriptName: string): Promise<Locator[]> {
  const [, loosePattern, fuzzyPattern] = buildScriptNamePatterns(scriptName);
  const wrappers = page.locator('xpath=//*[.//button[@data-qa-id="legend-settings-action"] or .//button[@data-qa-id="legend-more-action"]]');
  const total = await wrappers.count().catch(() => 0);
  const matches: Array<{ locator: Locator; textLength: number }> = [];

  for (let index = 0; index < Math.min(total, 80); index += 1) {
    const candidate = wrappers.nth(index);
    const visible = await candidate.isVisible({ timeout: 250 }).catch(() => false);
    if (!visible) {
      continue;
    }

    const text = normalizeUiText((await candidate.innerText().catch(() => "")) || "");
    if (!text || text.length > 240) {
      continue;
    }
    if (!loosePattern.test(text) && !fuzzyPattern.test(text)) {
      continue;
    }

    matches.push({ locator: candidate, textLength: text.length });
  }

  matches.sort((left, right) => left.textLength - right.textLength);
  return matches.slice(0, 6).map((entry) => entry.locator);
}

async function tryOpenScriptSettingsByDoubleClick(
  page: Page,
  box: { x: number; y: number; width: number; height: number } | null,
  traceStartEvent: string,
  traceOkEvent: string,
  traceDetail: string,
): Promise<boolean> {
  if (!box) {
    return false;
  }

  const doubleClickX = box.x + Math.max(16, Math.min(56, box.width * 0.25));
  const doubleClickY = box.y + Math.max(6, Math.min(box.height / 2, Math.max(box.height - 6, 6)));
  tracePageEvent(page, traceStartEvent, traceDetail);
  await page.mouse.dblclick(doubleClickX, doubleClickY).catch(() => undefined);
  await page.waitForTimeout(350);
  if (await waitForScriptSettingsInputsSurface(page, 1_500)) {
    tracePageEvent(page, traceOkEvent, traceDetail);
    return true;
  }

  await closeModal(page).catch(() => undefined);
  return false;
}

async function openSettingsFromLegendContainer(page: Page, scriptName: string): Promise<boolean> {
  tracePageEvent(page, "script-settings-legend-container-start", scriptName);
  const [, loosePattern, fuzzyPattern] = buildScriptNamePatterns(scriptName);
  const directWrappers = await findLegendRowWrappers(page, scriptName).catch(() => []);

  for (const wrapper of directWrappers) {
    const wrapperText = normalizeUiText((await wrapper.innerText().catch(() => "")) || "");
    tracePageEvent(page, "script-settings-legend-wrapper-visible", wrapperText.slice(0, 160));

    await wrapper.scrollIntoViewIfNeeded().catch(() => undefined);
    await wrapper.hover({ timeout: 1_000 }).catch(() => undefined);

    const wrapperBox = await wrapper.boundingBox().catch(() => null);
    if (await tryOpenScriptSettingsByDoubleClick(
      page,
      wrapperBox,
      "script-settings-legend-wrapper-dblclick-start",
      "script-settings-legend-wrapper-dblclick-ok",
      scriptName,
    )) {
      return true;
    }

    const clickedDirectSettings = await clickVisibleWithFallback(
      page,
      tvSelectors.legendSettingsButtons(wrapper),
      "script-settings-legend-wrapper-direct",
      1_200,
      300,
    );
    if (clickedDirectSettings) {
      tracePageEvent(page, "script-settings-legend-wrapper-direct-clicked", scriptName);
      if (await waitForScriptSettingsInputsSurface(page, 1_500)) {
        return true;
      }
      if (await resolveOpenedSettingsSurfaceToIndicatorDialog(page, "script-settings-legend-wrapper-direct")) {
        return true;
      }
    }

    const clickedMenu = await clickVisibleWithFallback(
      page,
      tvSelectors.legendMenuButtons(wrapper),
      "script-settings-legend-wrapper-menu",
      1_200,
      300,
    );
    if (clickedMenu) {
      tracePageEvent(page, "script-settings-legend-wrapper-menu-clicked", scriptName);
      if (await resolveOpenedSettingsSurfaceToIndicatorDialog(page, "script-settings-legend-wrapper-menu")) {
        return true;
      }
    }
  }

  for (const locator of tvSelectors.scriptLegendContainers(page, scriptName)) {
    const container = await firstVisibleLocator(locator, 1_200);
    if (!container) {
      continue;
    }

    const containerText = normalizeUiText(await container.innerText().catch(() => ""));
    if (!loosePattern.test(containerText) && !fuzzyPattern.test(containerText)) {
      continue;
    }
    tracePageEvent(page, "script-settings-legend-container-visible", containerText.slice(0, 160));

    const containersToTry: Locator[] = [];
    const actionableWrapper = container.locator(
      'xpath=ancestor::*[.//button[@data-qa-id="legend-settings-action"] or .//button[@data-qa-id="legend-more-action"] or .//*[@aria-label="Settings"] or .//*[@aria-label="More"]][1]',
    ).first();
    for (const target of [actionableWrapper, container]) {
      const visible = await target.isVisible({ timeout: 500 }).catch(() => false);
      if (!visible) {
        continue;
      }
      containersToTry.push(target);
    }

    for (const [containerIndex, targetContainer] of containersToTry.entries()) {
      const targetVisible = await targetContainer.isVisible({ timeout: 500 }).catch(() => false);
      if (!targetVisible) {
        continue;
      }

      await targetContainer.scrollIntoViewIfNeeded().catch(() => undefined);
      await targetContainer.hover({ timeout: 1_000 }).catch(() => undefined);

      const targetBox = await targetContainer.boundingBox().catch(() => null);
      if (await tryOpenScriptSettingsByDoubleClick(
        page,
        targetBox,
        "script-settings-legend-container-dblclick-start",
        "script-settings-legend-container-dblclick-ok",
        `${scriptName}:${containerIndex}`,
      )) {
        return true;
      }

      const clickedDirectSettings = await clickVisibleWithFallback(
        page,
        tvSelectors.legendSettingsButtons(targetContainer),
        "script-settings-legend-direct",
        1_200,
        300,
      );
      if (clickedDirectSettings) {
        tracePageEvent(page, "script-settings-legend-direct-clicked", `${scriptName}:${containerIndex}`);
        await page.waitForTimeout(250);
        if (await waitForScriptSettingsInputsSurface(page, 1_500)) {
          return true;
        }
        if (await resolveOpenedSettingsSurfaceToIndicatorDialog(page, `script-settings-legend-direct:${scriptName}:${containerIndex}`)) {
          return true;
        }
        tracePageEvent(page, "script-settings-legend-direct-no-surface", `${scriptName}:${containerIndex}`);
      }

      const clickedMenu = await clickVisibleWithFallback(
        page,
        tvSelectors.legendMenuButtons(targetContainer),
        "script-settings-legend",
        1_200,
        300,
      );
      if (clickedMenu) {
        tracePageEvent(page, "script-settings-legend-container-clicked", `${scriptName}:${containerIndex}`);
        await page.waitForTimeout(250);
        if (await resolveOpenedSettingsSurfaceToIndicatorDialog(page, `script-settings-legend-menu:${scriptName}:${containerIndex}`)) {
          return true;
        }
        tracePageEvent(page, "script-settings-legend-container-no-surface", `${scriptName}:${containerIndex}`);
      }

      const box = targetBox ?? await targetContainer.boundingBox().catch(() => null);
      if (box) {
        const targetX = Math.max(box.x + 8, box.x + box.width - 14);
        const targetY = box.y + Math.max(6, Math.min(box.height / 2, Math.max(box.height - 6, 6)));

        await page.mouse.move(targetX, targetY).catch(() => undefined);
        await page.waitForTimeout(100);
        await page.mouse.click(targetX, targetY).catch(() => undefined);
        await page.waitForTimeout(350);
        if (await resolveOpenedSettingsSurfaceToIndicatorDialog(page, `script-settings-legend-mouse:${scriptName}:${containerIndex}`)) {
          tracePageEvent(page, "script-settings-legend-container-mouse-ok", `${scriptName}:${containerIndex}`);
          return true;
        }

        await page.mouse.click(targetX, targetY, { button: "right" }).catch(() => undefined);
        await page.waitForTimeout(350);
        if (await resolveOpenedSettingsSurfaceToIndicatorDialog(page, `script-settings-legend-rightclick:${scriptName}:${containerIndex}`)) {
          tracePageEvent(page, "script-settings-legend-container-rightclick-ok", `${scriptName}:${containerIndex}`);
          return true;
        }
      }

      await targetContainer.click({ button: "right", force: true, timeout: 1_000 }).catch(() => undefined);
      await page.waitForTimeout(350);
      if (await resolveOpenedSettingsSurfaceToIndicatorDialog(page, `script-settings-legend-force-rightclick:${scriptName}:${containerIndex}`)) {
        tracePageEvent(page, "script-settings-legend-container-force-rightclick-ok", `${scriptName}:${containerIndex}`);
        return true;
      }
    }
  }

  tracePageEvent(page, "script-settings-legend-container-miss", scriptName);

  return false;
}

async function openSettingsFromScriptText(page: Page, scriptName: string): Promise<boolean> {
  tracePageEvent(page, "script-settings-text-start", scriptName);
  for (const locator of tvSelectors.scriptRow(page, scriptName)) {
    const scriptText = await firstVisibleLocator(locator, 1_200);
    if (!scriptText) {
      continue;
    }

    const scriptTextValue = await scriptText.innerText().catch(() => "");
    tracePageEvent(page, "script-settings-text-visible", scriptTextValue.slice(0, 160));

    const inPineDialog = await scriptText
      .evaluate((node) => Boolean(node.closest('[data-name="pine-dialog"]')))
      .catch(() => false);
    if (inPineDialog) {
      tracePageEvent(page, "script-settings-text-skip-pine-dialog", scriptName);
      continue;
    }

    await scriptText.scrollIntoViewIfNeeded().catch(() => undefined);
    await scriptText.hover({ timeout: 1_000 }).catch(() => undefined);

    for (let level = 1; level <= 5; level += 1) {
      const ancestor = scriptText.locator(`xpath=ancestor::div[${level}]`).first();
      const visible = await ancestor.isVisible({ timeout: 750 }).catch(() => false);
      if (!visible) {
        continue;
      }

      await ancestor.scrollIntoViewIfNeeded().catch(() => undefined);
      await ancestor.hover({ timeout: 750 }).catch(() => undefined);
      const ancestorBox = await ancestor.boundingBox().catch(() => null);
      if (await tryOpenScriptSettingsByDoubleClick(
        page,
        ancestorBox,
        "script-settings-text-ancestor-dblclick-start",
        "script-settings-text-ancestor-dblclick-ok",
        `${scriptName}:${level}`,
      )) {
        return true;
      }

      const clickedDirectSettings = await clickVisibleWithFallback(
        page,
        tvSelectors.legendSettingsButtons(ancestor),
        "script-settings-text-ancestor-direct",
        1_000,
        300,
      );
      if (clickedDirectSettings) {
        if (await waitForScriptSettingsInputsSurface(page, 1_500)) {
          tracePageEvent(page, "script-settings-text-ancestor-direct-ok", `${scriptName}:${level}`);
          return true;
        }
        if (await resolveOpenedSettingsSurfaceToIndicatorDialog(page, `script-settings-text-ancestor-direct:${scriptName}:${level}`)) {
          tracePageEvent(page, "script-settings-text-ancestor-direct-ok", `${scriptName}:${level}`);
          return true;
        }
      }

      const clickedMenu = await clickVisibleWithFallback(
        page,
        tvSelectors.legendMenuButtons(ancestor),
        "script-settings-text-ancestor-menu",
        1_000,
        300,
      );
      if (clickedMenu && (await resolveOpenedSettingsSurfaceToIndicatorDialog(page, `script-settings-text-ancestor-menu:${scriptName}:${level}`))) {
        tracePageEvent(page, "script-settings-text-ancestor-menu-ok", `${scriptName}:${level}`);
        return true;
      }
    }

    const textBox = await scriptText.boundingBox().catch(() => null);
    if (textBox) {
      const textX = textBox.x + Math.max(6, Math.min(18, Math.max(textBox.width - 6, 6)));
      const textY = textBox.y + Math.max(4, Math.min(textBox.height / 2, Math.max(textBox.height - 4, 4)));

      await page.mouse.move(textX, textY).catch(() => undefined);
      await page.waitForTimeout(100);
      await page.mouse.click(textX, textY, { button: "right" }).catch(() => undefined);
      await page.waitForTimeout(350);
      if (await resolveOpenedSettingsSurfaceToIndicatorDialog(page, `script-settings-text-rightclick:${scriptName}`)) {
        tracePageEvent(page, "script-settings-text-rightclick-ok", scriptName);
        return true;
      }
    }

    await scriptText.click({ button: "right", force: true, timeout: 1_000 }).catch(() => undefined);
    await page.waitForTimeout(350);
    if (await resolveOpenedSettingsSurfaceToIndicatorDialog(page, `script-settings-text-force-rightclick:${scriptName}`)) {
      tracePageEvent(page, "script-settings-text-force-rightclick-ok", scriptName);
      return true;
    }

    for (let level = 1; level <= 4; level += 1) {
      const ancestor = scriptText.locator(`xpath=ancestor::div[${level}]`).first();
      const visible = await ancestor.isVisible({ timeout: 750 }).catch(() => false);
      if (!visible) {
        continue;
      }

      await ancestor.scrollIntoViewIfNeeded().catch(() => undefined);
      await ancestor.hover({ timeout: 750 }).catch(() => undefined);
      await ancestor.click({ button: "right", force: true, timeout: 1_000 }).catch(() => undefined);
      await page.waitForTimeout(350);
      if (await resolveOpenedSettingsSurfaceToIndicatorDialog(page, `script-settings-text-ancestor-rightclick:${scriptName}:${level}`)) {
        tracePageEvent(page, "script-settings-text-ancestor-rightclick-ok", `${scriptName}:${level}`);
        return true;
      }
    }
  }

  tracePageEvent(page, "script-settings-text-miss", scriptName);

  return false;
}

async function openSettingsFromChartSurfaceControls(page: Page): Promise<boolean> {
  tracePageEvent(page, "script-settings-surface-start", "chart-surface");
  const clickedSettings = await clickVisibleWithFallbackOutsidePineDialog(
    page,
    tvSelectors.chartSurfaceSettingsButtons(page),
    "script-settings-surface-settings",
    1_200,
    650,
    true,
  );
  if (clickedSettings) {
    tracePageEvent(page, "script-settings-surface-settings-clicked", "chart-surface");
    if (await waitForSettingsSurface(page, 2_000)) {
      tracePageEvent(page, "script-settings-surface-settings-ok", "chart-surface");
      return true;
    }
    tracePageEvent(page, "script-settings-surface-settings-no-surface", "chart-surface");
    await closeModal(page);
  }

  const clickedMore = await clickVisibleWithFallbackOutsidePineDialog(
    page,
    tvSelectors.chartSurfaceMoreButtons(page),
    "script-settings-surface-more",
    1_200,
    650,
    true,
  );
  if (clickedMore) {
    tracePageEvent(page, "script-settings-surface-more-clicked", "chart-surface");
    if (await waitForSettingsSurface(page, 2_000)) {
      tracePageEvent(page, "script-settings-surface-more-ok", "chart-surface");
      return true;
    }
    tracePageEvent(page, "script-settings-surface-more-no-surface", "chart-surface");
    await closeModal(page);
  }

  tracePageEvent(page, "script-settings-surface-miss", "chart-surface");

  return false;
}

export async function isSignInModalVisible(page: Page): Promise<boolean> {
  const candidates = [
    page.getByText(/^sign in$/i),
    page.getByText(/^sign in with email$/i),
    page.getByText(/continue with google/i),
    page.getByText(/show more options/i),
    page.getByText(/remember me/i),
  ];

  for (const candidate of candidates) {
    const visible = await firstVisibleLocator(candidate, 500);
    if (visible) {
      return true;
    }
  }

  return false;
}

async function dismissSignInModal(page: Page): Promise<boolean> {
  if (!(await isSignInModalVisible(page))) {
    return false;
  }

  tracePageEvent(page, "sign-in-modal", "visible");
  await page.keyboard.press("Escape").catch(() => undefined);
  await page.waitForTimeout(250);
  if (!(await isSignInModalVisible(page))) {
    tracePageEvent(page, "sign-in-modal", "dismissed:escape");
    return true;
  }

  const closeCandidates = [
    page.getByRole("button", { name: /close/i }),
    page.locator('button[aria-label*="close" i]'),
    page.locator('[data-name*="close" i]'),
    page.locator('[title*="close" i]'),
    page.locator('button[aria-label="Cancel"]'),
  ];
  const clickedClose = await clickVisibleWithFallback(page, closeCandidates, "sign-in-modal-close", 1_000, 350);
  if (clickedClose && !(await isSignInModalVisible(page))) {
    tracePageEvent(page, "sign-in-modal", "dismissed:close");
    return true;
  }

  const viewport = page.viewportSize();
  if (viewport) {
    await page.mouse.click(viewport.width - 48, 48).catch(() => undefined);
    await page.waitForTimeout(350);
    if (!(await isSignInModalVisible(page))) {
      tracePageEvent(page, "sign-in-modal", "dismissed:corner-click");
      return true;
    }
  }

  tracePageEvent(page, "sign-in-modal", "still-visible");
  return false;
}

export async function dismissCookieBanner(page: Page): Promise<boolean> {
  let dismissed = false;

  for (let attempt = 0; attempt < 3; attempt += 1) {
    const clicked = await clickFirst(tvSelectors.cookieAccept(page), 1_000);
    if (!clicked) {
      break;
    }

    dismissed = true;
    await page.waitForTimeout(800);
  }

  return dismissed;
}

export async function ensurePineEditor(page: Page): Promise<void> {
  await runTrackedStep(page, "ensurePineEditor", async () => {
    await dismissSignInModal(page);
    await dismissCookieBanner(page);

    const initialDiagnostics = await collectEditorDiagnostics(page);
    if (hasVisibleEditorHost(initialDiagnostics)) {
      await restoreHistoricalScriptVersionIfNeeded(page);
      return;
    }

    for (let attempt = 0; attempt < 4; attempt += 1) {
      await clickFirst(tvSelectors.pineEditor(page), 2_500);
      await page.waitForTimeout(1_000);
      await dismissCookieBanner(page);

      const diagnostics = await collectEditorDiagnostics(page);
      if (hasVisibleEditorHost(diagnostics)) {
        await restoreHistoricalScriptVersionIfNeeded(page);
        return;
      }
    }

    const diagnostics = await collectEditorDiagnostics(page);
    throw new Error(`Pine editor host not visible after Pine entry: ${formatEditorDiagnostics(diagnostics)}`);
  });
}

async function restoreHistoricalScriptVersionIfNeeded(page: Page): Promise<void> {
  const readOnlySignals = [
    page.getByText(/historical version of the script/i),
    page.getByText(/this script is read-only/i),
  ];
  const hasReadOnlyBanner = await hasVisibleLocator(readOnlySignals, 500);
  if (!hasReadOnlyBanner) {
    return;
  }

  tracePageEvent(page, "pine-editor-read-only", "historical-version");

  const restored = await clickVisibleWithFallback(
    page,
    [
      page.getByRole("link", { name: /restore this version/i }),
      page.getByRole("button", { name: /restore this version/i }),
      page.getByText(/restore this version/i),
    ],
    "pine-editor-restore-version",
    1_500,
    500,
  ).catch(() => false);

  if (restored) {
    await page.waitForTimeout(1_000);
    await dismissSignInModal(page);
  }

  const stillReadOnly = await hasVisibleLocator(readOnlySignals, 500);
  tracePageEvent(page, stillReadOnly ? "pine-editor-read-only-still-visible" : "pine-editor-read-only-cleared");
}

async function closePineEditorIfVisible(page: Page): Promise<void> {
  const dialog = await firstVisibleLocator(
    page.locator('#pine-editor-dialog, [data-name="pine-dialog"], [id*="pine-editor" i]'),
    500,
  );
  if (!dialog) {
    return;
  }

  tracePageEvent(page, "pine-editor-close-start");

  const closeCandidates = [
    dialog.getByRole("button", { name: /close/i }),
    dialog.locator('button[aria-label="Close"], button[title="Close"], [role="button"][aria-label="Close"], [data-name*="close" i]'),
  ];
  const clickedClose = await clickVisibleWithFallback(page, closeCandidates, "pine-editor-close", 1_000, 400).catch(() => false);
  if (!clickedClose) {
    await page.keyboard.press("Escape").catch(() => undefined);
    await page.waitForTimeout(400);
  }

  const dialogStillVisible = await dialog.isVisible({ timeout: 500 }).catch(() => false);
  if (!dialogStillVisible) {
    tracePageEvent(page, "pine-editor-close-ok");
    return;
  }

  const box = await dialog.boundingBox().catch(() => null);
  if (box) {
    await page.mouse.click(box.x + box.width - 18, box.y + 18).catch(() => undefined);
    await page.waitForTimeout(400);
  }

  const stillVisibleAfterCorner = await dialog.isVisible({ timeout: 500 }).catch(() => false);
  tracePageEvent(page, stillVisibleAfterCorner ? "pine-editor-close-still-visible" : "pine-editor-close-ok");
}

export async function openExistingScript(page: Page, scriptName: string): Promise<boolean> {
  return runTrackedStep(page, `openExistingScript:${scriptName}`, async () => {
    const openedDialog = await clickFirst(tvSelectors.openScript(page), 2_000);
    if (!openedDialog) {
      return false;
    }

    await clickFirst(tvSelectors.myScriptsTab(page), 1_500);
    await fillFirst(scriptName, tvSelectors.scriptSearch(page), 1_500);

    const clickedScript = await clickFirst(tvSelectors.scriptRow(page, scriptName), 3_000);
    await page.waitForTimeout(1_500);

    if (!clickedScript) {
      return false;
    }

    const dialogStillVisible = await hasVisibleLocator([
      ...tvSelectors.scriptSearch(page),
      ...tvSelectors.myScriptsTab(page),
    ], 750);
    const editorContextTexts = await collectOpenScriptIdentityTexts(page, scriptName);
    const bodyText = await page.locator("body").innerText().catch(() => "");

    return verifyOpenScriptIdentity(scriptName, {
      dialogStillVisible,
      editorContextTexts,
      bodyText,
    });
  });
}

export async function setEditorContent(page: Page, code: string): Promise<void> {
  await runTrackedStep(page, `setEditorContent:${code.length}`, async () => {
    const runEditorSubstep = async <T>(name: string, action: () => Promise<T>, timeoutMs = 12_000): Promise<T> =>
      runTrackedStep(page, `editor:${name}`, action, timeoutMs);
    const keyboardChunkSize = numEnv("TV_EDITOR_CHUNK_CHARS", 25_000);
    const keyboardMaxChars = numEnv("TV_EDITOR_KEYBOARD_MAX_CHARS", 5_000);
    const normalizeEditorText = (value: string): string => value.replace(/\r\n/g, "\n");
    const matchesExpectedEditorText = (value: string): boolean => normalizeEditorText(value) === normalizeEditorText(code);

    tracePageEvent(page, "editor-trace", "prepare:start");
    await runEditorSubstep("prepare", async () => {
      await dismissCookieBanner(page);
      await ensurePineEditor(page);
    });
    tracePageEvent(page, "editor-trace", "prepare:ok");

    const writeViaKeyboard = async (input: Locator): Promise<boolean> => {
      tracePageEvent(page, "editor-trace", "keyboard:focus:start");
      const focused = await runEditorSubstep(
        "keyboard-focus",
        () => input.focus().then(() => true).catch(() => false),
        5_000,
      ).catch(() => false);

      if (!focused) {
        tracePageEvent(page, "editor-trace", "keyboard:focus:false");
        return false;
      }

      tracePageEvent(page, "editor-trace", "keyboard:focus:true");

      const mod = process.platform === "darwin" ? "Meta" : "Control";
      await runEditorSubstep(
        "keyboard-select-all",
        () => page.keyboard.press(`${mod}+A`).catch(() => undefined),
        4_000,
      );
      await runEditorSubstep(
        "keyboard-clear",
        () => page.keyboard.press("Backspace").catch(() => undefined),
        4_000,
      );

      tracePageEvent(page, "editor-trace", `keyboard:insert:start:${code.length}`);
      const totalChunks = Math.max(1, Math.ceil(code.length / keyboardChunkSize));
      for (let start = 0; start < code.length; start += keyboardChunkSize) {
        const chunkIndex = Math.floor(start / keyboardChunkSize) + 1;
        const chunk = code.slice(start, start + keyboardChunkSize);
        tracePageEvent(page, "editor-trace", `keyboard:insert:chunk:${chunkIndex}/${totalChunks}:${chunk.length}`);
        await runEditorSubstep(
          `keyboard-insert-${chunkIndex}-of-${totalChunks}`,
          async () => {
            await page.keyboard.insertText(chunk);
            await page.waitForTimeout(5);
          },
          8_000,
        );
      }

      const valueLength = await runEditorSubstep(
        "keyboard-readback",
        () => input.inputValue().then((value) => value.length).catch(() => 0),
        4_000,
      ).catch(() => 0);
      const actualValue = await input.inputValue().catch(() => "");
      tracePageEvent(page, "editor-trace", `keyboard:value-length:${valueLength}`);
      const matches = matchesExpectedEditorText(actualValue);
      tracePageEvent(page, "editor-trace", `keyboard:value-match:${matches}`);
      return matches;
    };

    const writeWithMonaco = async (): Promise<boolean> =>
      page
        .evaluate(async (nextCode) => {
          const w = window as unknown as {
            monaco?: {
              editor?: {
                getModels?: () => Array<{ setValue: (value: string) => void }>;
              };
            };
            require?: (...args: unknown[]) => void;
            requirejs?: (...args: unknown[]) => void;
            webpackChunktradingview?: unknown[] & {
              push?: (...args: unknown[]) => unknown;
              pop?: () => unknown;
            };
          };

          type MonacoLike = {
            editor?: {
              getModels?: () => Array<{ setValue: (value: string) => void }>;
            };
          };

          const setFromMonaco = (monaco: MonacoLike | null | undefined): boolean => {
            const models = monaco?.editor?.getModels?.();
            if (!models || models.length === 0) {
              return false;
            }

            models[0].setValue(nextCode);
            return true;
          };

          const findMonacoInValue = (value: unknown, seen: Set<unknown>): MonacoLike | null => {
            if (!value || (typeof value !== "object" && typeof value !== "function") || seen.has(value)) {
              return null;
            }

            seen.add(value);

            const direct = value as MonacoLike;
            if (typeof direct.editor?.getModels === "function") {
              return direct;
            }

            const container = value as Record<string, unknown>;
            for (const nested of Object.values(container)) {
              const found = findMonacoInValue(nested, seen);
              if (found) {
                return found;
              }
            }

            return null;
          };

          const getWebpackRequire = (): { c?: Record<string, { exports?: unknown }> } | null => {
            const chunk = w.webpackChunktradingview;
            if (!chunk || typeof chunk.push !== "function") {
              return null;
            }

            let webpackRequire: { c?: Record<string, { exports?: unknown }> } | null = null;

            try {
              const chunkId = `tv-monaco-probe-${Date.now()}`;
              chunk.push([
                [chunkId],
                {},
                (requireFn: { c?: Record<string, { exports?: unknown }> }) => {
                  webpackRequire = requireFn;
                },
              ]);
              if (typeof chunk.pop === "function") {
                chunk.pop();
              }
            } catch {
              return null;
            }

            return webpackRequire;
          };

          const setFromWebpackMonaco = (): boolean => {
            const webpackRequire = getWebpackRequire();
            const moduleCache = webpackRequire?.c;
            if (!moduleCache) {
              return false;
            }

            const seen = new Set<unknown>();
            for (const moduleRecord of Object.values(moduleCache)) {
              const found = findMonacoInValue(moduleRecord?.exports, seen);
              if (found && setFromMonaco(found)) {
                return true;
              }
            }

            return false;
          };

          if (setFromMonaco(w.monaco)) {
            return true;
          }

          const amdRequire = w.require ?? w.requirejs;
          if (typeof amdRequire === "function") {
            const resolved = await new Promise<boolean>((resolve) => {
              try {
                amdRequire(
                  ["vs/editor/editor.main"],
                  () => resolve(setFromMonaco(w.monaco)),
                  () => resolve(false),
                );
              } catch {
                resolve(false);
              }
            });

            if (resolved) {
              return true;
            }
          }

          if (setFromWebpackMonaco()) {
            return true;
          }

          return false;
        }, code)
        .catch(() => false);

    const writeViaFill = async (input: Locator): Promise<boolean> => {
      await input.fill(code, { timeout: 10_000 });
      const actualValue = await input.inputValue().catch(() => "");
      const valueLength = actualValue.length;
      tracePageEvent(page, "editor-trace", `fill:value-length:${valueLength}`);
      const matches = matchesExpectedEditorText(actualValue);
      tracePageEvent(page, "editor-trace", `fill:value-match:${matches}`);
      return matches;
    };

    const normalizeClipboardText = normalizeEditorText;

    const writeViaClipboardPaste = async (input: Locator): Promise<boolean> => {
      const focused = await input.focus().then(() => true).catch(() => false);
      if (!focused) {
        tracePageEvent(page, "editor-trace", "clipboard:focus:false");
        return false;
      }

      const mod = process.platform === "darwin" ? "Meta" : "Control";
      await page.keyboard.press(`${mod}+A`).catch(() => undefined);
      await page.keyboard.press("Backspace").catch(() => undefined);

      const wroteClipboard = await page
        .evaluate(async (nextCode) => {
          try {
            await navigator.clipboard.writeText(nextCode);
            return true;
          } catch {
            return false;
          }
        }, code)
        .catch(() => false);
      tracePageEvent(page, "editor-trace", `clipboard:write:${wroteClipboard}`);
      if (!wroteClipboard) {
        return false;
      }

      await page.keyboard.press(`${mod}+V`).catch(() => undefined);
      await page.waitForTimeout(Math.min(2_500, 250 + Math.ceil(code.length / 100)));

      await page.keyboard.press(`${mod}+A`).catch(() => undefined);
      await page.keyboard.press(`${mod}+C`).catch(() => undefined);
      await page.waitForTimeout(150);

      const copiedBack = await page
        .evaluate(async () => {
          try {
            return await navigator.clipboard.readText();
          } catch {
            return "";
          }
        })
        .catch(() => "");

      const normalizedExpected = normalizeClipboardText(code);
      const normalizedActual = normalizeClipboardText(copiedBack);
      const matches =
        normalizedActual === normalizedExpected ||
        (normalizedActual.length === normalizedExpected.length &&
          normalizedActual.slice(0, 200) === normalizedExpected.slice(0, 200) &&
          normalizedActual.slice(-200) === normalizedExpected.slice(-200));
      tracePageEvent(page, "editor-trace", `clipboard:readback:${normalizedActual.length}:${matches}`);
      return matches;
    };

    const writeViaDirectInput = async (input: Locator): Promise<boolean> =>
      input
        .evaluate((node, nextCode) => {
          const dispatchTextEvents = (target: HTMLElement) => {
            target.dispatchEvent(new Event("input", { bubbles: true }));
            target.dispatchEvent(new Event("change", { bubbles: true }));
          };

          if (node instanceof HTMLTextAreaElement) {
            node.value = nextCode;
            dispatchTextEvents(node);
            return true;
          }

          if (node instanceof HTMLElement && node.isContentEditable) {
            node.textContent = nextCode;
            dispatchTextEvents(node);
            return true;
          }

          const textarea = node.querySelector("textarea");
          if (textarea instanceof HTMLTextAreaElement) {
            textarea.value = nextCode;
            dispatchTextEvents(textarea);
            return true;
          }

          const contentEditable = node.querySelector('[contenteditable="true"]');
          if (contentEditable instanceof HTMLElement) {
            contentEditable.textContent = nextCode;
            dispatchTextEvents(contentEditable);
            return true;
          }

          return false;
        }, code)
        .catch(() => false);

    tracePageEvent(page, "editor-trace", "monaco:initial:start");
    const usedMonaco = await runEditorSubstep("monaco-initial", writeWithMonaco, 8_000).catch(() => false);
    if (usedMonaco) {
      tracePageEvent(page, "editor-trace", "monaco:initial:ok");
      await page.waitForTimeout(250);
      return;
    }
    tracePageEvent(page, "editor-trace", "monaco:initial:false");

    const editorCandidates = tvSelectors.editorHosts(page);

    for (const [index, candidate] of editorCandidates.entries()) {
      tracePageEvent(page, "editor-trace", `candidate:${index}:resolve:start`);
      const editor = await runEditorSubstep(
        `candidate-${index}-resolve`,
        () => firstVisibleLocator(candidate, 2_000),
        5_000,
      ).catch(() => null);
      if (!editor) {
        tracePageEvent(page, "editor-trace", `candidate:${index}:resolve:none`);
        continue;
      }

      tracePageEvent(page, "editor-trace", `candidate:${index}:resolve:visible`);

      try {
        await runEditorSubstep(
          `candidate-${index}-click`,
          () => editor.click({ timeout: 5_000, force: true }).catch(() => undefined),
          7_000,
        );
        await page.waitForTimeout(250);

        const tagName = await editor.evaluate((node) => node.tagName.toLowerCase()).catch(() => "");
        tracePageEvent(page, "editor-trace", `candidate:${index}:tag:${tagName || "unknown"}`);
        if (tagName === "textarea") {
          const usedTextareaMonaco = await runEditorSubstep(
            `candidate-${index}-textarea-monaco`,
            writeWithMonaco,
            8_000,
          ).catch(() => false);
          if (!usedTextareaMonaco) {
            if (code.length > keyboardMaxChars) {
              tracePageEvent(page, "editor-trace", `candidate:${index}:textarea-clipboard:start`);
              const wroteViaClipboard = await runEditorSubstep(
                `candidate-${index}-textarea-clipboard`,
                () => writeViaClipboardPaste(editor),
                20_000,
              ).catch(() => false);
              if (wroteViaClipboard) {
                tracePageEvent(page, "editor-trace", `candidate:${index}:textarea:ok`);
                await page.waitForTimeout(250);
                return;
              }
              tracePageEvent(page, "editor-trace", `candidate:${index}:textarea-clipboard:false`);

              tracePageEvent(page, "editor-trace", `candidate:${index}:textarea-direct:start`);
              const wroteDirectly = await runEditorSubstep(
                `candidate-${index}-textarea-direct`,
                () => writeViaDirectInput(editor),
                10_000,
              ).catch(() => false);
              if (wroteDirectly) {
                tracePageEvent(page, "editor-trace", `candidate:${index}:textarea:ok`);
                await page.waitForTimeout(250);
                return;
              }
              tracePageEvent(page, "editor-trace", `candidate:${index}:textarea-direct:false`);
            } else {
              const wroteViaKeyboard = await runEditorSubstep(
                `candidate-${index}-textarea-keyboard`,
                () => writeViaKeyboard(editor),
                15_000,
              );
              if (wroteViaKeyboard) {
                tracePageEvent(page, "editor-trace", `candidate:${index}:textarea:ok`);
                await page.waitForTimeout(250);
                return;
              }

              tracePageEvent(page, "editor-trace", `candidate:${index}:textarea-fill:start`);
              const wroteViaFill = await runEditorSubstep(
                `candidate-${index}-textarea-fill`,
                () => writeViaFill(editor),
                15_000,
              ).catch(() => false);
              if (wroteViaFill) {
                tracePageEvent(page, "editor-trace", `candidate:${index}:textarea:ok`);
                await page.waitForTimeout(250);
                return;
              }

              tracePageEvent(page, "editor-trace", `candidate:${index}:textarea-clipboard-fallback:start`);
              const wroteViaClipboard = await runEditorSubstep(
                `candidate-${index}-textarea-clipboard-fallback`,
                () => writeViaClipboardPaste(editor),
                20_000,
              ).catch(() => false);
              if (wroteViaClipboard) {
                tracePageEvent(page, "editor-trace", `candidate:${index}:textarea:ok`);
                await page.waitForTimeout(250);
                return;
              }

              tracePageEvent(page, "editor-trace", `candidate:${index}:textarea-fill:false`);
              tracePageEvent(page, "editor-trace", `candidate:${index}:textarea-clipboard-fallback:false`);
            }
          }
          if (usedTextareaMonaco) {
            tracePageEvent(page, "editor-trace", `candidate:${index}:textarea:ok`);
            await page.waitForTimeout(250);
            return;
          }
        }

        const descendantTextarea = await runEditorSubstep(
          `candidate-${index}-descendant-textarea`,
          () => firstVisibleLocator(editor.locator("textarea"), 1_000),
          4_000,
        ).catch(() => null);
        if (descendantTextarea) {
          tracePageEvent(page, "editor-trace", `candidate:${index}:descendant-textarea:visible`);
          await runEditorSubstep(
            `candidate-${index}-descendant-click`,
            () => descendantTextarea.click({ timeout: 5_000, force: true }).catch(() => undefined),
            7_000,
          );
          const usedDescendantMonaco = await runEditorSubstep(
            `candidate-${index}-descendant-monaco`,
            writeWithMonaco,
            8_000,
          ).catch(() => false);
          if (!usedDescendantMonaco) {
            if (code.length > keyboardMaxChars) {
              tracePageEvent(page, "editor-trace", `candidate:${index}:descendant-clipboard:start`);
              const wroteViaClipboard = await runEditorSubstep(
                `candidate-${index}-descendant-clipboard`,
                () => writeViaClipboardPaste(descendantTextarea),
                20_000,
              ).catch(() => false);
              if (wroteViaClipboard) {
                tracePageEvent(page, "editor-trace", `candidate:${index}:descendant-textarea:ok`);
                await page.waitForTimeout(250);
                return;
              }
              tracePageEvent(page, "editor-trace", `candidate:${index}:descendant-clipboard:false`);

              tracePageEvent(page, "editor-trace", `candidate:${index}:descendant-direct:start`);
              const wroteDirectly = await runEditorSubstep(
                `candidate-${index}-descendant-direct`,
                () => writeViaDirectInput(editor),
                10_000,
              ).catch(() => false);
              if (wroteDirectly) {
                tracePageEvent(page, "editor-trace", `candidate:${index}:descendant-textarea:ok`);
                await page.waitForTimeout(250);
                return;
              }
              tracePageEvent(page, "editor-trace", `candidate:${index}:descendant-direct:false`);
            } else {
              const wroteViaKeyboard = await runEditorSubstep(
                `candidate-${index}-descendant-keyboard`,
                () => writeViaKeyboard(descendantTextarea),
                15_000,
              );
              if (wroteViaKeyboard) {
                tracePageEvent(page, "editor-trace", `candidate:${index}:descendant-textarea:ok`);
                await page.waitForTimeout(250);
                return;
              }

              tracePageEvent(page, "editor-trace", `candidate:${index}:descendant-fill:start`);
              const wroteViaFill = await runEditorSubstep(
                  `candidate-${index}-descendant-fill`,
                  () => writeViaFill(descendantTextarea),
                  15_000,
              ).catch(() => false);
              if (wroteViaFill) {
                tracePageEvent(page, "editor-trace", `candidate:${index}:descendant-textarea:ok`);
                await page.waitForTimeout(250);
                return;
              }

              tracePageEvent(page, "editor-trace", `candidate:${index}:descendant-clipboard-fallback:start`);
              const wroteViaClipboard = await runEditorSubstep(
                `candidate-${index}-descendant-clipboard-fallback`,
                () => writeViaClipboardPaste(descendantTextarea),
                20_000,
              ).catch(() => false);
              if (wroteViaClipboard) {
                tracePageEvent(page, "editor-trace", `candidate:${index}:descendant-textarea:ok`);
                await page.waitForTimeout(250);
                return;
              }

              tracePageEvent(page, "editor-trace", `candidate:${index}:descendant-fill:false`);
              tracePageEvent(page, "editor-trace", `candidate:${index}:descendant-clipboard-fallback:false`);
            }
          }
          if (usedDescendantMonaco) {
            tracePageEvent(page, "editor-trace", `candidate:${index}:descendant-textarea:ok`);
            await page.waitForTimeout(250);
            return;
          }
        }

        tracePageEvent(page, "editor-trace", `candidate:${index}:monaco-focused:start`);
        const usedFocusedMonaco = await runEditorSubstep(
          `candidate-${index}-monaco-focused`,
          writeWithMonaco,
          8_000,
        ).catch(() => false);
        if (usedFocusedMonaco) {
          tracePageEvent(page, "editor-trace", `candidate:${index}:monaco-focused:ok`);
          await page.waitForTimeout(250);
          return;
        }
        tracePageEvent(page, "editor-trace", `candidate:${index}:monaco-focused:false`);

        const wroteDirectly = await runEditorSubstep(
          `candidate-${index}-direct-write`,
          () => writeViaDirectInput(editor),
          10_000,
        ).catch(() => false);

        if (wroteDirectly) {
          tracePageEvent(page, "editor-trace", `candidate:${index}:direct-write:ok`);
          await page.waitForTimeout(250);
          return;
        }
        tracePageEvent(page, "editor-trace", `candidate:${index}:direct-write:false`);
      } catch (error: unknown) {
        const message = error instanceof Error ? error.message : String(error);
        tracePageEvent(page, "editor-candidate-error", `candidate:${index}:${message}`);
        // try next candidate
      }
    }

    const runId = utcNow().replace(/[:.]/g, "-");
    const screenshotPath = await takeScreenshot(page, runId, "editor-focus-failure").catch(() => "");
    const diagnostics = await collectEditorDiagnostics(page);
    const lifecycleDiagnostics = collectPageLifecycleDiagnostics(page);
    const screenshotMessage = screenshotPath ? `, screenshot ${screenshotPath}` : "";
    throw new Error(
      `Could not write Pine editor content via visible hosts: ${formatEditorDiagnostics(diagnostics)}; lifecycle ${formatPageLifecycleDiagnostics(lifecycleDiagnostics)}${screenshotMessage}`,
    );
  });
}

export async function saveScript(page: Page, scriptName: string): Promise<void> {
  await runTrackedStep(page, `saveScript:${scriptName}`, async () => {
    await dismissSignInModal(page);
    const mod = process.platform === "darwin" ? "Meta" : "Control";
    await page.keyboard.press(`${mod}+S`);
    await page.waitForTimeout(750);

    if (!(await findVisibleDialogByText(page, /save script/i, 400))) {
      await page.keyboard.press(`${mod}+Shift+S`).catch(() => undefined);
      await page.waitForTimeout(750);
    }

    for (let attempt = 0; attempt < 3; attempt += 1) {
      const saveDialog = await findVisibleDialogByText(page, /save script/i, 500);
      const named = saveDialog
        ? await fillFirst(
          scriptName,
          [
            saveDialog.getByRole("textbox", { name: /script name|name|title/i }),
            saveDialog.getByRole("textbox"),
            saveDialog.locator('input[type="text"], input:not([type]), textarea'),
          ],
          750,
        )
        : await fillFirst(scriptName, tvSelectors.saveNameInput(page), 750);
      if (!named) {
        break;
      }

      if (saveDialog) {
        const clickedDialogSave = await clickFirst(
          [
            saveDialog.getByRole("button", { name: /^save$/i }),
            saveDialog.getByText(/^save$/i),
            saveDialog.locator('button:has-text("Save")'),
          ],
          1_500,
        ).catch(() => false);
        if (!clickedDialogSave) {
          throw new Error(`Could not click Save inside save dialog for script: ${scriptName}`);
        }
      } else {
        await clickFirst(tvSelectors.saveButtons(page), 1_500);
      }

      await page.waitForTimeout(1_250);
      const saveDialogStillVisible = Boolean(await findVisibleDialogByText(page, /save script/i, 350));
      if (!saveDialogStillVisible) {
        break;
      }
    }

    await page.waitForTimeout(1_250);
    const saveDialogStillVisible = Boolean(await findVisibleDialogByText(page, /save script/i, 350));
    if (saveDialogStillVisible) {
      throw new Error(`Save dialog remained open after save attempts for script: ${scriptName}`);
    }

    await dismissSignInModal(page);

    const untitledStillVisible = await hasVisibleLocator([
      page.getByText(/^untitled script$/i),
      page.getByRole("button", { name: /^untitled script$/i }),
      page.getByRole("link", { name: /^untitled script$/i }),
    ], 500);
    if (untitledStillVisible) {
      throw new Error(`Save did not persist script name for ${scriptName}; TradingView still shows Untitled script`);
    }
  });
}

async function getVisibleCompileErrorMarker(page: Page): Promise<string | null> {
  const bodyText = normalizeUiText((await page.locator("body").innerText().catch(() => "")) || "").toLowerCase();

  const markers = [
    "syntax error",
    "compilation error",
    "script could not be translated",
    "error at ",
    "error on bar",
    "undeclared identifier",
    "mismatched input",
  ];

  return markers.find((marker) => bodyText.includes(marker)) ?? null;
}

export async function waitForPostSaveCompileSettlement(page: Page, scriptName: string): Promise<void> {
  await runTrackedStep(page, `waitForPostSaveCompileSettlement:${scriptName}`, async () => {
    const timeoutMs = 7_000;
    const pollMs = 250;
    const startedAt = Date.now();

    while (Date.now() - startedAt < timeoutMs) {
      const saveDialogStillVisible = Boolean(await findVisibleDialogByText(page, /save script/i, 150));
      if (saveDialogStillVisible) {
        await page.waitForTimeout(pollMs);
        continue;
      }

      const compileErrorMarker = await getVisibleCompileErrorMarker(page);
      if (compileErrorMarker) {
        throw new Error(`Visible compile error detected after save for ${scriptName}: ${compileErrorMarker}`);
      }

      await page.waitForTimeout(pollMs);
    }

    const finalCompileErrorMarker = await getVisibleCompileErrorMarker(page);
    if (finalCompileErrorMarker) {
      throw new Error(`Visible compile error detected after save for ${scriptName}: ${finalCompileErrorMarker}`);
    }
  });
}

export async function assertNoVisibleCompileError(page: Page): Promise<void> {
  const hit = await getVisibleCompileErrorMarker(page);
  if (hit) {
    throw new Error(`Visible compile error detected: ${hit}`);
  }
}

export async function addCurrentScriptToChart(page: Page, scriptName?: string): Promise<void> {
  await runTrackedStep(page, "addCurrentScriptToChart", async () => {
    await dismissSignInModal(page);
    if (scriptName) {
      const initialState = await collectVisibleChartScriptState(page, scriptName).catch(() => null);
      if (initialState && isScriptVisibleOnChart(initialState)) {
        tracePageEvent(page, "add-to-chart-already-present", `${scriptName}:${JSON.stringify(initialState)}`);
        return;
      }
    }

    const clicked = await clickVisibleWithFallback(page, tvSelectors.addToChart(page), "add-to-chart", 2_000, 2_500);
    if (clicked) {
      await dismissSignInModal(page);
      if (scriptName) {
        const stateAfterClick = await collectVisibleChartScriptState(page, scriptName).catch(() => null);
        if (stateAfterClick && isScriptVisibleOnChart(stateAfterClick)) {
          tracePageEvent(page, "add-to-chart-visible-after-click", `${scriptName}:${JSON.stringify(stateAfterClick)}`);
        }
      }
      return;
    }

    const mod = process.platform === "darwin" ? "Meta" : "Control";
    tracePageEvent(page, "add-to-chart-hotkey", `${mod}+Enter`);
    await page.keyboard.press(`${mod}+Enter`).catch(() => undefined);
    await page.waitForTimeout(2_500);
    await dismissSignInModal(page);

    if (scriptName) {
      const stateAfterHotkey = await collectVisibleChartScriptState(page, scriptName).catch(() => null);
      if (stateAfterHotkey && isScriptVisibleOnChart(stateAfterHotkey)) {
        tracePageEvent(page, "add-to-chart-visible-after-hotkey", `${scriptName}:${JSON.stringify(stateAfterHotkey)}`);
        return;
      }
    }

    const diagnostics = await collectEditorDiagnostics(page).catch(() => undefined);
    if (await isSignInModalVisible(page)) {
      throw new Error("TradingView sign-in modal is blocking add-to-chart");
    }
    throw new Error(
      diagnostics
        ? `Could not add script to chart after click, force-click, and hotkey fallback: ${formatEditorDiagnostics(diagnostics)}`
        : 'Could not add script to chart after click, force-click, and hotkey fallback',
    );
  });
}

export async function openSettingsForScript(page: Page, scriptName: string): Promise<void> {
  await runTrackedStep(page, `openSettingsForScript:${scriptName}`, async () => {
    await dismissSignInModal(page);
    await closePineEditorIfVisible(page);
    tracePageEvent(page, "script-settings-open-start", scriptName);
    let openedMenu = await openSettingsFromLegendContainer(page, scriptName);
    tracePageEvent(page, "script-settings-open-legend-result", `${scriptName}:${openedMenu}`);
    if (!openedMenu) {
      openedMenu = await openSettingsFromScriptText(page, scriptName);
      tracePageEvent(page, "script-settings-open-text-result", `${scriptName}:${openedMenu}`);
    }
    if (!openedMenu) {
      openedMenu = await clickVisibleWithFallback(
        page,
        tvSelectors.settingsForScript(page, scriptName),
        "script-settings-anchor",
        400,
        150,
      );
      if (openedMenu && !(await isSettingsSurfaceVisible(page, 350))) {
        tracePageEvent(page, "script-settings-open-anchor-no-surface", scriptName);
        openedMenu = false;
      }
      tracePageEvent(page, "script-settings-open-anchor-result", `${scriptName}:${openedMenu}`);
    }
    if (!openedMenu) {
      openedMenu = await openSettingsFromChartSurfaceControls(page);
      tracePageEvent(page, "script-settings-open-surface-result", `${scriptName}:${openedMenu}`);
    }
    if (!openedMenu) {
      if (await isSignInModalVisible(page)) {
        throw new Error(`TradingView sign-in modal is blocking settings for script: ${scriptName}`);
      }
      throw new Error(`Could not open script menu for settings: ${scriptName}`);
    }

    if (await waitForScriptSettingsInputsSurface(page, 750)) {
      tracePageEvent(page, "script-settings-open-indicator-dialog-visible", scriptName);
      return;
    }

    await dismissSignInModal(page);
    const clickedSettings = await clickVisibleWithFallback(
      page,
      tvSelectors.settingsAction(page),
      "script-settings-action",
      2_500,
      1_500,
    );
    tracePageEvent(page, "script-settings-open-menu-action-result", `${scriptName}:${clickedSettings}`);
    if (clickedSettings && (await waitForScriptSettingsInputsSurface(page, 2_000))) {
      tracePageEvent(page, "script-settings-open-indicator-dialog-after-action", scriptName);
      return;
    }

    await closeModal(page).catch(() => undefined);
    if (!clickedSettings) {
      if (await isSignInModalVisible(page)) {
        throw new Error(`TradingView sign-in modal is blocking settings action for script: ${scriptName}`);
      }
      throw new Error(`Could not open settings for script: ${scriptName}`);
    }

    throw new Error(`Opened generic settings instead of indicator settings for script: ${scriptName}`);
  });
}

export async function openInputsTab(page: Page): Promise<void> {
  await runTrackedStep(page, "openInputsTab", async () => {
    const ok = await clickFirst(tvSelectors.inputsTab(page), 2_500);
    if (!ok) {
      throw new Error("Could not open Inputs tab");
    }

    await page.waitForTimeout(1_000);
  });
}

export async function assertInputLabelsVisible(
  page: Page,
  expectedLabels: string[],
  minCount: number,
): Promise<void> {
  const directIndicatorDialog = await findIndicatorSettingsDialog(page, 750);
  const effectiveDialogs = directIndicatorDialog
    ? [await snapshotDialog(directIndicatorDialog)]
    : await collectVisibleDialogSnapshots(page);

  let bestDialog: VisibleDialogSnapshot | null = null;
  let bestFound = -1;

  for (const dialog of effectiveDialogs) {
    const dialogText = normalizeUiText(dialog.text || "");
    const labelTexts = dialog.labelTexts ?? [];
    let found = 0;

    for (const label of expectedLabels) {
      if (dialogText.includes(label) || labelTexts.some((candidate) => candidate.includes(label))) {
        found += 1;
      }
    }

    if (found > bestFound) {
      bestFound = found;
      bestDialog = dialog;
    }
  }

  if (bestFound < minCount) {
    const title = bestDialog?.title || "unknown";
    const preview = normalizeUiText(bestDialog?.text || "").slice(0, 220) || "no visible dialog text";
    throw new Error(
      `Only found ${Math.max(bestFound, 0)}/${expectedLabels.length} expected input labels in settings modal (title: ${JSON.stringify(title)}, preview: ${JSON.stringify(preview)})`,
    );
  }
}

export async function collectVisibleInputLabels(page: Page, expectedLabels: string[] = []): Promise<string[]> {
  const directIndicatorDialog = await findIndicatorSettingsDialog(page, 750);
  const effectiveDialogs = directIndicatorDialog
    ? [await snapshotDialog(directIndicatorDialog)]
    : await collectVisibleDialogSnapshots(page);
  const labels = new Set<string>();

  for (const dialog of effectiveDialogs) {
    const dialogText = normalizeUiText(dialog.text || "");

    for (const label of dialog.labelTexts ?? []) {
      const normalized = normalizeUiText(label);
      if (normalized) {
        labels.add(normalized);
      }
    }

    for (const expectedLabel of expectedLabels) {
      const normalized = normalizeUiText(expectedLabel);
      if (normalized && dialogText.includes(normalized)) {
        labels.add(normalized);
      }
    }
  }

  return [...labels];
}

export async function probeRuntimeSmoke(
  page: Page,
  scriptName: string,
): Promise<{
  ok: boolean;
  scriptVisible: boolean;
  signInModalVisible: boolean;
  compileError: string | null;
}> {
  const scriptVisible = await isScriptVisibleOnChartSurface(page, scriptName).catch(() => false);
  const signInModalVisible = await isSignInModalVisible(page).catch(() => false);
  const compileError = await getVisibleCompileErrorMarker(page).catch(() => "runtime_smoke_probe_failed");

  return {
    ok: scriptVisible && !signInModalVisible && !compileError,
    scriptVisible,
    signInModalVisible,
    compileError,
  };
}

export async function closeModal(page: Page): Promise<void> {
  if (page.isClosed()) {
    tracePageEvent(page, "closeModal-skip", "page-already-closed");
    return;
  }

  await runTrackedStep(
    page,
    "closeModal",
    async () => {
      await clickFirst(tvSelectors.closeModal(page), 400).catch(() => false);
      await page.keyboard.press("Escape").catch(() => undefined);
      await page.waitForTimeout(150).catch(() => undefined);
    },
    2_000,
  ).catch(() => undefined);
}

export async function publishPrivateScript(
  page: Page,
  options: {
    title?: string;
    description?: string;
  } = {},
): Promise<void> {
  const clickedPublish = await clickFirst(tvSelectors.publishButtons(page), 4_000);
  if (!clickedPublish) {
    throw new Error("Could not open publish flow");
  }

  await page.waitForTimeout(1_500);

  if (options.title) {
    await fillFirst(options.title, tvSelectors.publishTitleInput(page), 1_000);
  }

  if (options.description) {
    await fillFirst(options.description, tvSelectors.publishDescriptionInput(page), 1_000);
  }

  await clickFirst(tvSelectors.privateVisibility(page), 1_000);

  const confirmed = await clickFirst(tvSelectors.confirmPublish(page), 4_000);
  if (!confirmed) {
    throw new Error("Could not confirm publish");
  }

  await page.waitForTimeout(4_000);
}

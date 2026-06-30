import fs from "node:fs";
import path from "node:path";
import {
  chromium,
  type Browser,
  type BrowserContext,
  type Locator,
  type Page,
} from "playwright";

import { tvSelectors, type PineDraftKind } from "../selectors.js";
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

export type TradingViewPageAuthEvidence = {
  url: string;
  htmlClass: string;
  bodyText: string;
  accountProbeStatuses: number[];
  accountProbeAuthenticated: boolean;
  accountProbeAnonymous: boolean;
};

export type TradingViewPageAuthState = {
  authenticated: boolean;
  explicitlyAnonymous: boolean;
  reason: string;
  evidence: TradingViewPageAuthEvidence;
};

export type VisibleCount = {
  total: number;
  visible: number;
};

export type EditorDiagnostics = {
  textareaCount: VisibleCount;
  contentEditableCount: VisibleCount;
  monacoCount: VisibleCount;
  pineContainerCount: VisibleCount;
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

export type InputContractDiagnosis = {
  expectedCount: number;
  observedCount: number;
  overlapCount: number;
  missingCount: number;
  legacyLabels: string[];
  likelyDrift: boolean;
  likelyPartialSurface: boolean;
};

export type AddToChartOptions = {
  forceInsert?: boolean;
  tolerateFailure?: boolean;
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

export function resolveTradingViewHeadlessDefault(env: NodeJS.ProcessEnv = process.env): boolean {
  const raw = env.TV_HEADLESS;
  if (raw != null) {
    return ["1", "true", "yes", "on"].includes(raw.toLowerCase());
  }
  return ["1", "true", "yes", "on"].includes((env.CI || "").toLowerCase());
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

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function buildScriptNamePatterns(scriptName: string): RegExp[] {
  const normalizedWords = scriptName
    .split(/\s+/)
    .map((part) => part.trim())
    .filter(Boolean);
  const exact = new RegExp(`^${escapeRegex(scriptName)}$`, "i");
  const loose = new RegExp(escapeRegex(scriptName), "i");
  const fuzzy = normalizedWords.length > 0
    ? new RegExp(
      normalizedWords
        .map((part) => {
          const fullWord = escapeRegex(part);
          const truncatedWord = escapeRegex(part.slice(0, Math.min(part.length, 4)));
          return `(^|[^a-z0-9])(?:${fullWord}|${truncatedWord})(?=$|[^a-z0-9])`;
        })
        .join(".*"),
      "i",
    )
    : loose;

  return [exact, loose, fuzzy];
}

/**
 * Check whether {@link legendText} is a truncated rendering of {@link scriptName}.
 *
 * TradingView truncates indicator names in the chart legend – it may drop
 * entire words and abbreviate the remaining ones to their first few
 * characters.  For example "SMC Long-Dip Dashboard v7" can appear as
 * "SMC Dash" in the legend.
 *
 * The function returns `true` when every space-separated word in the
 * legend text (after stripping a trailing "· N.N" version suffix) is a
 * case-insensitive prefix of some word in {@link scriptName}, with the
 * matches preserving left-to-right order and at least two legend words
 * matching.
 */
export function isLegendTruncatedMatch(legendText: string, scriptName: string): boolean {
  const cleanLegend = legendText.replace(/\s*·\s*[\d.]+\s*$/, "").trim();
  const legendWords = cleanLegend.split(/\s+/).filter((w) => w.length >= 2);
  const scriptWords = scriptName.split(/\s+/).filter(Boolean);
  if (legendWords.length < 2) return false;

  let si = 0;
  for (const lw of legendWords) {
    const ll = lw.toLowerCase();
    let found = false;
    while (si < scriptWords.length) {
      const sl = scriptWords[si].toLowerCase();
      si += 1;
      if (sl.startsWith(ll)) {
        found = true;
        break;
      }
    }
    if (!found) return false;
  }
  return true;
}

export function validateTradingViewStorageState(storageStatePath: string): void {
  if (boolEnv("TV_SKIP_AUTH_STATE_VALIDATION", false)) {
    console.error("[tv-auth] WARNING: TV_SKIP_AUTH_STATE_VALIDATION=1 is set. Storage state validation is bypassed.");
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

export function resolveTradingViewPageAuthState(evidence: TradingViewPageAuthEvidence): TradingViewPageAuthState {
  const htmlClass = normalizeUiText(evidence.htmlClass).toLowerCase();
  const bodyText = normalizeUiText(evidence.bodyText).toLowerCase();
  const hasAnonymousClass = /(?:^|\s)is-not-authenticated(?:\s|$)/.test(htmlClass);
  const hasAuthenticatedClass = /(?:^|\s)is-authenticated(?:\s|$)/.test(htmlClass);
  const hasSignInSignals = /sign in|log in|email|password|continue with google/i.test(bodyText);
  const explicitlyAnonymous = hasAnonymousClass
    || hasSignInSignals
    || (evidence.accountProbeAnonymous && !evidence.accountProbeAuthenticated);

  if (explicitlyAnonymous) {
    const reason = hasAnonymousClass
      ? "html_class_is_not_authenticated"
      : hasSignInSignals
        ? "signin_signals_visible"
        : `account_probe_rejected:${evidence.accountProbeStatuses.join(",") || "unknown"}`;
    return {
      authenticated: false,
      explicitlyAnonymous: true,
      reason,
      evidence,
    };
  }

  if (evidence.accountProbeAuthenticated) {
    return {
      authenticated: true,
      explicitlyAnonymous: false,
      reason: "account_probe_authenticated",
      evidence,
    };
  }

  if (hasAuthenticatedClass) {
    return {
      authenticated: true,
      explicitlyAnonymous: false,
      reason: "html_class_is_authenticated",
      evidence,
    };
  }

  return {
    authenticated: false,
    explicitlyAnonymous: false,
    reason: `no_positive_auth_evidence:${evidence.accountProbeStatuses.join(",") || "no_probe"}`,
    evidence,
  };
}

export async function collectTradingViewPageAuthState(page: Page): Promise<TradingViewPageAuthState> {
  const pageEvidence = await page.evaluate(() => ({
    url: location.href,
    htmlClass: String(document.documentElement?.className || ""),
    bodyText: String(document.body?.innerText || "").replace(/\s+/g, " ").trim().slice(0, 2_000),
  }));

  const probeEndpoints = [
    "/api/v1/user/profile/me/",
    "/api/v1/users/me/",
  ];
  const probeResults = await page.evaluate(async (endpoints) => {
    const results: Array<{ status: number; contentType: string; preview: string }> = [];
    for (const endpoint of endpoints) {
      try {
        const response = await fetch(endpoint, {
          credentials: "include",
          headers: { accept: "application/json, text/plain, */*" },
        });
        const contentType = response.headers.get("content-type") || "";
        const preview = (await response.text()).slice(0, 500);
        results.push({ status: response.status, contentType, preview });
      } catch {
        results.push({ status: 0, contentType: "", preview: "" });
      }
    }
    return results;
  }, probeEndpoints).catch(() => []);

  const accountProbeStatuses = probeResults.map((result) => result.status);
  const accountProbeAuthenticated = probeResults.some((result) => result.status >= 200 && result.status < 300);
  const accountProbeAnonymous = probeResults.some((result) =>
    result.status === 401
    || result.status === 403
    || /is-not-authenticated|authentication credentials|not authenticated|login required|sign in/i.test(result.preview)
  );

  const state = resolveTradingViewPageAuthState({
    url: pageEvidence.url,
    htmlClass: pageEvidence.htmlClass,
    bodyText: pageEvidence.bodyText,
    accountProbeStatuses,
    accountProbeAuthenticated,
    accountProbeAnonymous,
  });
  const statusSummary = accountProbeStatuses.length > 0 ? accountProbeStatuses.join(",") : "no_probe";
  tracePageEvent(
    page,
    "auth-state-probe",
    `authenticated=${state.authenticated}; explicitlyAnonymous=${state.explicitlyAnonymous}; reason=${state.reason}; accountProbeStatuses=${statusSummary}; accountProbeAuthenticated=${accountProbeAuthenticated}; accountProbeAnonymous=${accountProbeAnonymous}`,
  );
  return state;
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
              `Step timed out after ${timeoutMs}ms: ${stepName}; lifecycle ${formatPageLifecycleDiagnostics(diagnostics)}`,
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

const LEGACY_INPUT_CONTRACT_LABELS = [
  "BUS HardGatesPackA",
  "BUS HardGatesPackB",
  "BUS QualityPackA",
  "BUS QualityPackB",
  "BUS QualityBoundsPack",
  "BUS ModulePackA",
  "BUS ModulePackB",
];

const LOCAL_INPUT_TOGGLE_LABELS = [
  "Show Dashboard",
  "Show Trigger/Invalidation",
  "State Background",
];

function extractLikelyInputLabelsFromDialogText(dialogText: string): string[] {
  const normalizedDialogText = normalizeUiText(dialogText);
  if (!normalizedDialogText) {
    return [];
  }

  const labels = new Set<string>();

  for (const match of normalizedDialogText.matchAll(/\bBUS\s+[A-Za-z][A-Za-z0-9/]*\b/g)) {
    const label = normalizeUiText(match[0]);
    if (label) {
      labels.add(label);
    }
  }

  for (const label of LOCAL_INPUT_TOGGLE_LABELS) {
    if (normalizedDialogText.includes(label)) {
      labels.add(label);
    }
  }

  return [...labels];
}

export function diagnoseInputContract(
  expectedLabels: string[],
  observedLabels: string[],
): InputContractDiagnosis {
  const expectedSet = new Set(expectedLabels.map((label) => normalizeUiText(label)).filter(Boolean));
  const observedSet = new Set(observedLabels.map((label) => normalizeUiText(label)).filter(Boolean));
  let overlapCount = 0;

  for (const label of expectedSet) {
    if (observedSet.has(label)) {
      overlapCount += 1;
    }
  }

  const legacySet = new Set(LEGACY_INPUT_CONTRACT_LABELS.map((label) => normalizeUiText(label)));
  const legacyLabels = observedLabels
    .map((label) => normalizeUiText(label))
    .filter((label, index, values) => legacySet.has(label) && values.indexOf(label) === index);
  const expectedCount = expectedSet.size;
  const observedCount = observedSet.size;
  const missingCount = Math.max(expectedCount - overlapCount, 0);
  const likelyDrift = legacyLabels.length >= 2 && missingCount > 0;

  return {
    expectedCount,
    observedCount,
    overlapCount,
    missingCount,
    legacyLabels,
    likelyDrift,
    likelyPartialSurface: !likelyDrift && overlapCount > 0 && missingCount > 0,
  };
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

export function countOrderedCodeBlockOccurrences(haystack: string, snippet: string): number {
  const haystackLines = significantCodeLines(haystack);
  const snippetLines = significantCodeLines(snippet);

  if (snippetLines.length === 0) {
    return 0;
  }

  let matches = 0;
  for (let start = 0; start <= haystackLines.length - snippetLines.length; start += 1) {
    const blockMatches = snippetLines.every((line, offset) => haystackLines[start + offset] === line);
    if (blockMatches) {
      matches += 1;
    }
  }

  return matches;
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

function canonicalSemanticVersionSuffixMatch(scriptName: string, uiText: string): boolean {
  const normalizedScriptName = normalizeUiText(scriptName);
  const normalizedCandidate = normalizeUiText(uiText);

  if (!normalizedScriptName || !normalizedCandidate || normalizedCandidate === normalizedScriptName) {
    return false;
  }

  if (!normalizedCandidate.startsWith(`${normalizedScriptName} `)) {
    return false;
  }

  const suffix = normalizedCandidate.slice(normalizedScriptName.length).trim();
  return /^(?:v\d+(?:\.\d+){1,3}|version\s+\d+(?:\.\d+){1,3})$/i.test(suffix);
}

function canonicalOrTruncatedScriptIdentityMatch(scriptName: string, uiText: string): boolean {
  if (uiTextContainsExactScriptName(scriptName, uiText)) {
    return true;
  }
  if (compactUiText(scriptName) === compactUiText(uiText)) {
    return true;
  }
  if (canonicalSemanticVersionSuffixMatch(scriptName, uiText)) {
    return true;
  }
  if (canonicalVersionMetadataMatch(scriptName, uiText)) {
    return true;
  }

  const scriptWords = normalizeUiText(scriptName).toLowerCase().match(/[a-z0-9]+/g) ?? [];
  const candidateWords = normalizeUiText(uiText).toLowerCase().match(/[a-z0-9]+/g) ?? [];

  if (scriptWords.length === 0 || candidateWords.length !== scriptWords.length) {
    return false;
  }

  let sawTruncation = false;
  for (let index = 0; index < scriptWords.length; index += 1) {
    const scriptWord = scriptWords[index] ?? "";
    const candidateWord = candidateWords[index] ?? "";

    if (!scriptWord || !candidateWord) {
      return false;
    }
    if (candidateWord === scriptWord) {
      continue;
    }
    if (candidateWord.length < Math.min(3, scriptWord.length)) {
      return false;
    }
    if (!scriptWord.startsWith(candidateWord)) {
      return false;
    }
    sawTruncation = true;
  }

  return sawTruncation;
}

function canonicalPrefixAliasMatch(scriptName: string, uiText: string): boolean {
  const normalizedScriptName = normalizeUiText(scriptName).toLowerCase();
  const normalizedCandidate = normalizeUiText(uiText).toLowerCase();

  if (!normalizedScriptName || !normalizedCandidate || normalizedCandidate.length < 8) {
    return false;
  }
  if (normalizedCandidate === normalizedScriptName) {
    return false;
  }
  if (!normalizedScriptName.startsWith(normalizedCandidate)) {
    return false;
  }

  const scriptWords = normalizedScriptName.match(/[a-z0-9]+/g) ?? [];
  const candidateWords = normalizedCandidate.match(/[a-z0-9]+/g) ?? [];

  return candidateWords.length >= 2 && candidateWords.length < scriptWords.length;
}

function canonicalVersionMetadataMatch(scriptName: string, uiText: string): boolean {
  const compactScriptName = compactUiText(scriptName);
  const compactCandidate = compactUiText(uiText);

  if (!compactScriptName || !compactCandidate.startsWith(compactScriptName) || compactCandidate === compactScriptName) {
    return false;
  }

  const compactSuffix = compactCandidate.slice(compactScriptName.length);
  // Match "version\d" (e.g. "smc_utils version 4") or plain digits (e.g. "smc_utils · 4.0" → compact "40")
  return /^(?:version)?\d/.test(compactSuffix);
}

function legacyOpenScriptNames(scriptName: string): string[] {
  // Back-compat aliases: when callers pass the new canonical name, also try
  // the older saved names so any TradingView account still on the pre-rename
  // saved title resolves. When callers pass an even-older legacy name, keep
  // the old fallback chain so deployments mid-rename keep working.
  // See PREFLIGHT_*_TARGETS rationale in scripts/smc_bus_manifest.py.
  switch (normalizeUiText(scriptName).toLowerCase()) {
    case "smc core":
      return ["SMC Core Engine"];
    case "smc core engine":
      return ["SMC Core"];
    case "smc long-dip dashboard v7":
      return ["SMC Decision Board", "SMC Dashboard"];
    case "smc decision board":
      return ["SMC Long-Dip Dashboard v7", "SMC Dashboard"];
    case "smc long-dip strategy v7":
      return ["SMC Execution", "SMC Long Strategy"];
    case "smc execution":
      return ["SMC Long-Dip Strategy v7", "SMC Long Strategy"];
    default:
      return [];
  }
}

export function resolveOpenScriptSearchNames(scriptName: string): string[] {
  return uniqueNormalizedTexts([scriptName, ...legacyOpenScriptNames(scriptName)]);
}

function openScriptIdentityNames(scriptName: string): string[] {
  return resolveOpenScriptSearchNames(scriptName);
}

function pineDeclarationCompanionMatch(scriptName: string, uiText: string): boolean {
  const normalizedCandidate = normalizeUiText(uiText);
  if (!/^(?:indicator|strategy|library)\s*\(/i.test(normalizedCandidate)) {
    return false;
  }

  const declarationLabels = [...normalizedCandidate.matchAll(/["']([^"']+)["']/g)]
    .map((match) => normalizeUiText(match[1] ?? ""))
    .filter(Boolean);
  const compactScriptName = compactUiText(scriptName);

  return declarationLabels.some((label) =>
    uiTextContainsExactScriptName(scriptName, label)
    || (compactScriptName.length > 0 && compactUiText(label) === compactScriptName)
    || canonicalSemanticVersionSuffixMatch(scriptName, label)
    || canonicalVersionMetadataMatch(scriptName, label)
  );
}

function importReferenceCompanionMatch(scriptName: string, uiText: string): boolean {
  const normalizedCandidate = normalizeUiText(uiText);
  if (!/^(?:\/\/\s*)?import\s+/i.test(normalizedCandidate)) {
    return false;
  }

  const compactScriptName = compactUiText(scriptName);
  return Boolean(compactScriptName) && compactUiText(normalizedCandidate).includes(compactScriptName);
}

/**
 * Matches TradingView publish/update dialog titles that embed the script name,
 * e.g. "Update 'smc_overlay_generated' library" or
 *      "Update 'smc_overlay_generated' library Minimize Close".
 * These are non-identity companion texts that should not be flagged as
 * conflicting editor context.
 */
function publishDialogCompanionMatch(scriptName: string, uiText: string): boolean {
  const normalizedScriptName = normalizeUiText(scriptName).toLowerCase();
  const normalizedCandidate = normalizeUiText(uiText).toLowerCase();
  if (!normalizedScriptName || !normalizedCandidate) {
    return false;
  }
  // "update '<name>' library", "publish '<name>'", "update '<name>' ..."
  // Allow optional trailing words (Minimize, Close, etc.)
  const escaped = escapeRegex(normalizedScriptName);
  return new RegExp(
    `^(?:update|publish)\\s+['\u2018\u2019\u201C\u201D"]?${escaped}['\u2018\u2019\u201C\u201D"]?(?:\\s|$)`,
    "i",
  ).test(normalizedCandidate);
}

function nonIdentityEditorCompanionMatch(uiText: string): boolean {
  const normalizedCandidate = normalizeUiText(uiText);
  if (!normalizedCandidate) {
    return false;
  }
  if (/^[a-z0-9_.-]+(?:\/[a-z0-9_.-]+){2,}$/i.test(normalizedCandidate)) {
    return true;
  }
  if (/\b[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*\b/i.test(normalizedCandidate) && /[_/]/.test(normalizedCandidate)) {
    return true;
  }
  if (/[()\[\]{}]/.test(normalizedCandidate) && /[_/]/.test(normalizedCandidate)) {
    return true;
  }

  return false;
}

function buildAnchoredScriptNamePattern(scriptName: string): RegExp | null {
  const normalizedScriptName = normalizeUiText(scriptName);
  if (!normalizedScriptName) {
    return null;
  }

  return new RegExp(`(^|[^a-z0-9])${escapeRegex(normalizedScriptName)}(?=$|[^a-z0-9])`, "i");
}

function uniqueNormalizedTexts(values: string[]): string[] {
  return [...new Set(values.map((value) => normalizeUiText(value)).filter(Boolean))];
}

function buildExactPublishedVersionEvidencePattern(scriptName: string): RegExp | null {
  const normalizedScriptName = normalizeUiText(scriptName);
  if (!normalizedScriptName) {
    return null;
  }

  return new RegExp(
    `(^|[^a-z0-9])${escapeRegex(normalizedScriptName)}(?:\\s*[:,-]?\\s*)version\\s+(\\d+)\\b`,
    "gi",
  );
}

function collectExactPublishedVersions(text: string, scriptName?: string): number[] {
  const normalizedText = normalizeUiText(text);
  if (!normalizedText) {
    return [];
  }

  const versions = new Set<number>();
  if (!scriptName) {
    for (const match of normalizedText.matchAll(/\bversion\s+(\d+)\b/gi)) {
      const version = Number(match[1]);
      if (Number.isFinite(version)) {
        versions.add(version);
      }
    }
    return [...versions];
  }

  const versionPattern = buildExactPublishedVersionEvidencePattern(scriptName);
  if (!versionPattern) {
    return [];
  }

  for (const match of normalizedText.matchAll(versionPattern)) {
    const version = Number(match[2]);
    if (Number.isFinite(version)) {
      versions.add(version);
    }
  }

  return [...versions];
}

function collectPublishedVersionsFromBody(bodyText: string, scriptName?: string): number[] {
  return collectExactPublishedVersions(bodyText, scriptName);
}

function collectPublishedVersionsFromContextTexts(contextTexts: string[], scriptName?: string): number[] {
  const normalizedTexts = uniqueNormalizedTexts(contextTexts);
  if (normalizedTexts.length === 0) {
    return [];
  }

  const versions = new Set<number>();
  for (const candidate of normalizedTexts) {
    for (const version of collectExactPublishedVersions(candidate, scriptName)) {
      if (Number.isFinite(version)) {
        versions.add(Number(version));
      }
    }
  }

  return [...versions];
}

function hasConflictingCanonicalEditorContext(scriptName: string, editorContextTexts: string[]): boolean {
  const normalizedScriptName = normalizeUiText(scriptName).toLowerCase();
  if (!normalizedScriptName) {
    return false;
  }

  const isObviousGenericUiText = (candidate: string): boolean => {
    const trimmed = normalizeUiText(candidate);
    if (trimmed.length <= 2 || trimmed.length > 120) {
      return true;
    }
    if (!/\w/.test(trimmed)) {
      return true;
    }
    if (/https?:\/\/|www\./i.test(trimmed)) {
      return true;
    }
    if (/^\d+(?:[ .:/-]\d+)*$/.test(trimmed)) {
      return true;
    }
    if (trimmed.split(/\s+/).length > 12) {
      return true;
    }
    if (/^[a-z]{1,2}$/i.test(trimmed)) {
      return true;
    }
    return false;
  };

  return uniqueNormalizedTexts(editorContextTexts).some((candidate) => {
    const normalizedCandidate = normalizeUiText(candidate).toLowerCase();
    if (!normalizedCandidate || normalizedCandidate === normalizedScriptName) {
      return false;
    }
    if (canonicalOrTruncatedScriptIdentityMatch(scriptName, candidate)) {
      return false;
    }
    if (canonicalPrefixAliasMatch(scriptName, candidate)) {
      return false;
    }
    if (canonicalVersionMetadataMatch(scriptName, candidate)) {
      return false;
    }
    if (pineDeclarationCompanionMatch(scriptName, candidate)) {
      return false;
    }
    if (importReferenceCompanionMatch(scriptName, candidate)) {
      return false;
    }
    if (publishDialogCompanionMatch(scriptName, candidate)) {
      return false;
    }
    if (nonIdentityEditorCompanionMatch(candidate)) {
      return false;
    }
    if (isObviousGenericUiText(candidate)) {
      return false;
    }
    return true;
  });
}

export function uiTextContainsExactScriptName(scriptName: string, uiText: string): boolean {
  const normalizedScriptName = normalizeUiText(scriptName);
  if (!normalizedScriptName) {
    return false;
  }

  return normalizeUiText(uiText).toLowerCase() === normalizedScriptName.toLowerCase();
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
    canonicalOrTruncatedScriptIdentityMatch(scriptName, candidate)
  );
  if (!exactEditorMatch) {
    return false;
  }

  if (hasConflictingCanonicalEditorContext(scriptName, options.editorContextTexts)) {
    return false;
  }

  return true;
}

export function resolveOpenScriptIdentityEvidence(scriptName: string, options: {
  dialogStillVisible: boolean;
  editorContextTexts: string[];
  bodyText?: string;
}): {
  verified: boolean;
  verificationMode: "script_context" | "not_verified";
} {
  const verified = verifyOpenScriptIdentity(scriptName, options);
  return {
    verified,
    verificationMode: verified ? "script_context" : "not_verified",
  };
}

async function waitForAnyOpenScriptIdentity(page: Page, scriptNames: string[], timeoutMs = 4_000): Promise<boolean> {
  const normalizedNames = uniqueNormalizedTexts(scriptNames);
  const startedAt = Date.now();

  while (Date.now() - startedAt < timeoutMs) {
    const dialogStillVisible = await hasVisibleOpenScriptSurface(page, 500);
    const bodyText = await page.locator("body").innerText().catch(() => "");

    for (const scriptName of normalizedNames) {
      const editorContextTexts = await collectOpenScriptIdentityTexts(page, scriptName);
      if (verifyOpenScriptIdentity(scriptName, {
        dialogStillVisible,
        editorContextTexts,
        bodyText,
      })) {
        return true;
      }
    }

    await page.waitForTimeout(250);
  }

  return false;
}

function openScriptSurfaceScopes(page: Page): Locator[] {
  return [
    page.locator('[data-name="indicators-dialog"]'),
    page.locator('[role="dialog"]'),
    page.locator('[data-name="menu-inner"]'),
  ];
}

type OpenScriptSurfaceScopeState = {
  scopedSearchVisible: boolean;
  scopedMyScriptsVisible: boolean;
};

export function openScriptSurfaceScopeLooksReady(state: OpenScriptSurfaceScopeState): boolean {
  return state.scopedSearchVisible || state.scopedMyScriptsVisible;
}

export function openScriptSurfaceLooksReady(options: {
  scopeStates: OpenScriptSurfaceScopeState[];
  globalSearchVisible?: boolean;
  globalMyScriptsVisible?: boolean;
}): boolean {
  return options.scopeStates.some((state) => openScriptSurfaceScopeLooksReady(state));
}

function openScriptSurfaceSearchLocators(scope: Locator): Locator[] {
  return [
    scope.getByRole("textbox", { name: /search/i }),
    scope.getByPlaceholder(/search/i),
    scope.locator('input[type="search"], input[placeholder*="Search" i]'),
  ];
}

async function fillOpenScriptSearch(page: Page, value: string): Promise<boolean> {
  for (const scope of openScriptSurfaceScopes(page)) {
    let candidate: Locator | null = null;

    for (const locator of openScriptSurfaceSearchLocators(scope)) {
      candidate = await firstVisibleLocator(locator, 750);
      if (candidate) {
        break;
      }
    }

    if (!candidate) {
      continue;
    }

    await candidate.fill(value);
    await candidate.press("End").catch(() => undefined);
    tracePageEvent(page, "open-script-search-fill", value);
    await page.waitForTimeout(1_000);
    return true;
  }

  tracePageEvent(page, "open-script-search-missing", value);
  return false;
}

function openScriptSurfaceMyScriptsLocatorsForScope(scope: Locator): Locator[] {
  const myScriptsText = scope
    .locator('[class*="title" i], [data-name*="title" i], [class*="label" i], [data-name*="label" i]')
    .filter({ hasText: /^my scripts$/i })
    .first();

  return [
    scope.getByRole("tab", { name: /my scripts/i }),
    scope.getByRole("button", { name: /my scripts/i }),
    scope.getByRole("link", { name: /my scripts/i }),
    scope.getByRole("menuitem", { name: /my scripts/i }),
    myScriptsText,
    myScriptsText.locator('xpath=ancestor::*[@data-id or @role="tab" or @role="button" or @role="link" or @role="menuitem" or contains(@class, "item")][1]'),
    scope.getByText(/^personal$/i),
  ];
}

function openScriptSurfaceMyScriptsLocators(page: Page): Locator[] {
  return openScriptSurfaceScopes(page).flatMap((scope) => openScriptSurfaceMyScriptsLocatorsForScope(scope));
}

async function activateOpenScriptMyScriptsSection(page: Page): Promise<boolean> {
  const clicked = await clickVisibleWithFallback(page, openScriptSurfaceMyScriptsLocators(page), "open-script-myscripts", 1_500, 600);

  for (const scope of openScriptSurfaceScopes(page)) {
    const textCandidate = await firstVisibleLocator(
      scope
        .locator('[class*="title" i], [data-name*="title" i], [class*="label" i], [data-name*="label" i]')
        .filter({ hasText: /^my scripts$/i })
        .first(),
      500,
    );
    if (!textCandidate) {
      continue;
    }

    const box = await textCandidate.boundingBox().catch(() => null);
    if (!box || box.width <= 4 || box.height <= 4) {
      continue;
    }

    const clickX = Math.max(4, Math.round(box.x - 24));
    const clickY = Math.round(box.y + Math.max(3, Math.min(box.height / 2, box.height - 3)));

    try {
      await page.mouse.click(clickX, clickY);
      await page.waitForTimeout(900);
      return true;
    } catch {
      // Fall through to the generic click result.
    }
  }

  return clicked;
}

async function hasVisibleOpenScriptSurface(page: Page, timeoutMs = 500): Promise<boolean> {
  return hasVisibleLocator(openScriptSurfaceMyScriptsLocators(page), timeoutMs);
}

export function detectPublishedVersionFromBody(bodyText: string, scriptName?: string): number | null {
  const versions = collectPublishedVersionsFromBody(bodyText, scriptName);
  return versions.length === 1 ? versions[0] : null;
}

export function detectPublishedVersionFromContextTexts(contextTexts: string[], scriptName?: string): number | null {
  const versions = collectPublishedVersionsFromContextTexts(contextTexts, scriptName);
  return versions.length === 1 ? versions[0] : null;
}

export function resolvePublishedVersionEvidence(options: {
  scriptName: string;
  versionContextTexts: string[];
  bodyText: string;
}): {
  publishedVersion: number | null;
  verificationMode: "version_context" | "body_fallback" | "not_verified";
  fallbackVersion: number | null;
} {
  const contextVersions = collectPublishedVersionsFromContextTexts(options.versionContextTexts, options.scriptName);
  if (contextVersions.length === 1) {
    return {
      publishedVersion: contextVersions[0],
      verificationMode: "version_context",
      fallbackVersion: null,
    };
  }

  if (contextVersions.length > 1) {
    return {
      publishedVersion: null,
      verificationMode: "not_verified",
      fallbackVersion: null,
    };
  }

  const fallbackVersions = collectPublishedVersionsFromBody(options.bodyText, options.scriptName);
  if (fallbackVersions.length === 1) {
    return {
      publishedVersion: fallbackVersions[0],
      verificationMode: "body_fallback",
      fallbackVersion: fallbackVersions[0],
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
    headless: resolveTradingViewHeadlessDefault(process.env),
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
  const pineContainerCount = await countVisible(
    page,
    '#pine-editor-dialog, [data-name="pine-dialog"], [id*="pine-editor" i]',
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
    pineContainerCount,
    pineButtonCount: pineButtons.length,
    pineButtons,
    pineTextCount: pineTexts.length,
    pineTexts,
    relevantBodyLines,
  };
}

export function editorDiagnosticsSuggestOpenHost(diagnostics: EditorDiagnostics): boolean {
  if (diagnostics.pineContainerCount.visible > 0) {
    return true;
  }

  const toolbarSignals = [
    ...diagnostics.pineButtons,
    ...diagnostics.pineTexts,
    ...diagnostics.relevantBodyLines,
  ].map((value) => compactUiText(value));
  const hasScriptToolbarSignal = toolbarSignals.some((value) =>
    value.includes("pineeditor")
    || value.includes("openscript")
    || value.includes("updateonchart")
    || value.includes("addtochart")
    || value.includes("publishscript")
  );

  return hasScriptToolbarSignal;
}

function hasVisibleEditorHost(diagnostics: EditorDiagnostics): boolean {
  return (
    diagnostics.textareaCount.visible > 0 ||
    diagnostics.contentEditableCount.visible > 0 ||
    diagnostics.monacoCount.visible > 0 ||
    editorDiagnosticsSuggestOpenHost(diagnostics)
  );
}

function formatEditorDiagnostics(diagnostics: EditorDiagnostics): string {
  return [
    `textarea visible ${diagnostics.textareaCount.visible}/${diagnostics.textareaCount.total}`,
    `contenteditable visible ${diagnostics.contentEditableCount.visible}/${diagnostics.contentEditableCount.total}`,
    `monaco visible ${diagnostics.monacoCount.visible}/${diagnostics.monacoCount.total}`,
    `pine containers visible ${diagnostics.pineContainerCount.visible}/${diagnostics.pineContainerCount.total}`,
    `pine buttons ${diagnostics.pineButtonCount}`,
    `pine texts ${diagnostics.pineTextCount}`,
    `toolbar host ${editorDiagnosticsSuggestOpenHost(diagnostics)}`,
  ].join(", ");
}

function formatPageLifecycleDiagnostics(diagnostics: PageLifecycleDiagnostics): string {
  // Build a compact type-frequency map from recent events so a timeout message
  // surfaces *which* events fired (e.g. "tv-trace×18 step-start×4 step-error×3")
  // rather than just a raw count.  Entries are space-separated and sorted by
  // frequency descending.  This makes closeModal timeouts immediately
  // actionable without having to download a trace archive.
  const typeCounts = new Map<string, number>();
  for (const ev of diagnostics.recentEvents) {
    typeCounts.set(ev.type, (typeCounts.get(ev.type) ?? 0) + 1);
  }
  const eventBreakdown =
    typeCounts.size > 0
      ? [...typeCounts.entries()]
          .sort((a, b) => b[1] - a[1])
          .map(([t, n]) => `${t}×${n}`)
          .join(" ")
      : "none";

  return [
    `pageClosed ${diagnostics.pageClosed}`,
    `pageCrashed ${diagnostics.pageCrashed}`,
    `contextClosed ${diagnostics.contextClosed}`,
    `browserDisconnected ${diagnostics.browserDisconnected}`,
    diagnostics.activeStep ? `activeStep ${diagnostics.activeStep}` : "activeStep none",
    `events ${diagnostics.eventCount} [${eventBreakdown}]`,
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

export async function collectVisibleLocatorMetadata(locator: Locator, timeoutMs = 750): Promise<Array<{
  text: string;
  ariaLabel: string;
  title: string;
}>> {
  const results: Array<{ text: string; ariaLabel: string; title: string }> = [];
  const total = await locator.count().catch(() => 0);

  for (let index = 0; index < total; index += 1) {
    const candidate = locator.nth(index);
    try {
      if (!(await candidate.isVisible({ timeout: timeoutMs }))) {
        continue;
      }
    } catch {
      continue;
    }

    results.push({
      text: await candidate.innerText().catch(() => ""),
      ariaLabel: (await candidate.getAttribute("aria-label").catch(() => "")) ?? "",
      title: (await candidate.getAttribute("title").catch(() => "")) ?? "",
    });
  }

  return results;
}

function normalizeVisibleEvidenceValues(entries: Array<{
  text: string;
  ariaLabel: string;
  title: string;
}>): string[] {
  const texts: string[] = [];
  for (const entry of entries) {
    for (const value of [entry.text, entry.ariaLabel, entry.title]) {
      const normalized = normalizeUiText(value);
      if (normalized) {
        texts.push(normalized);
      }
    }
  }
  return uniqueNormalizedTexts(texts);
}

export async function collectOpenScriptIdentityTexts(page: Page, scriptName: string): Promise<string[]> {
  const texts: string[] = [];

  for (const candidate of tvSelectors.openScriptIdentity(page, scriptName)) {
    texts.push(...normalizeVisibleEvidenceValues(await collectVisibleLocatorMetadata(candidate, 750)));
  }

  return uniqueNormalizedTexts(texts);
}

export async function collectPublishedVersionContextTexts(page: Page, scriptName: string): Promise<string[]> {
  const texts: string[] = [];

  for (const candidate of tvSelectors.publishedVersionContext(page, scriptName)) {
    texts.push(...normalizeVisibleEvidenceValues(await collectVisibleLocatorMetadata(candidate, 750)));
  }

  return uniqueNormalizedTexts(texts);
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
      await candidate.click({ timeout: timeoutMs }).catch(() => undefined);
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

export async function clickVisibleWithFallback(
  page: Page,
  candidates: Locator[],
  tracePrefix: string,
  timeoutMs = 2_000,
  settleMs = 500,
  effectCheck?: () => Promise<boolean>,
): Promise<boolean> {
  // Centralised hover-tooltip dismissal (issue #2849).
  // Moving to (0, 0) before the first candidate loop causes TradingView to
  // close any hover-only [data-id] overlay so it does not intercept clicks.
  await page.mouse.move(0, 0).catch(() => undefined);

  let missingCandidates = 0;
  const settleClickEffect = async (effectDetail: string): Promise<boolean> => {
    await page.waitForTimeout(settleMs);
    if (!effectCheck) {
      return true;
    }

    const effectVisible = await effectCheck().catch(() => false);
    if (effectVisible) {
      tracePageEvent(page, `${tracePrefix}-effect-ok`, effectDetail);
      return true;
    }

    tracePageEvent(page, `${tracePrefix}-no-effect`, effectDetail);
    return false;
  };

  for (const [index, locator] of candidates.entries()) {
    const candidate = await firstVisibleLocator(locator, timeoutMs);
    if (!candidate) {
      missingCandidates += 1;
      continue;
    }

    if (missingCandidates > 0) {
      tracePageEvent(page, `${tracePrefix}-candidate-miss-summary`, `count:${missingCandidates}`);
    }
    tracePageEvent(page, `${tracePrefix}-candidate-visible`, `candidate:${index}`);
    if (tracePrefix.startsWith("publish-open")) {
      const candidateMeta = await candidate.evaluate((node) => {
        const element = node as HTMLElement;
        const rect = element.getBoundingClientRect();
        return JSON.stringify({
          tag: element.tagName,
          role: element.getAttribute("role") || "",
          ariaLabel: element.getAttribute("aria-label") || "",
          title: element.getAttribute("title") || "",
          dataName: element.getAttribute("data-name") || "",
          dataTooltip: element.getAttribute("data-tooltip") || "",
          className: element.className || "",
          text: (element.innerText || element.textContent || "").replace(/\s+/g, " ").trim().slice(0, 120),
          rect: {
            x: Math.round(rect.x),
            y: Math.round(rect.y),
            width: Math.round(rect.width),
            height: Math.round(rect.height),
          },
        });
      }).catch(() => "unavailable");
      tracePageEvent(page, `${tracePrefix}-candidate-meta`, `candidate:${index}:${candidateMeta}`);
    }

    try {
      await candidate.scrollIntoViewIfNeeded().catch(() => undefined);
      await candidate.click({ timeout: timeoutMs + 1_000 });
      if (await settleClickEffect(`candidate:${index}:click`)) {
        return true;
      }
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      tracePageEvent(page, `${tracePrefix}-click-error`, `candidate:${index}:${message}`);
    }

    try {
      await candidate.hover({ timeout: timeoutMs }).catch(() => undefined);
      await candidate.click({ timeout: timeoutMs + 1_000 });
      if (await settleClickEffect(`candidate:${index}:hover-click`)) {
        return true;
      }
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      tracePageEvent(page, `${tracePrefix}-hover-click-error`, `candidate:${index}:${message}`);
    }

    try {
      await candidate.click({ timeout: timeoutMs, force: true });
      if (await settleClickEffect(`candidate:${index}:force`)) {
        return true;
      }
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
          if (await settleClickEffect(`candidate:${index}:offset:${positionIndex}`)) {
            return true;
          }
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
        if (await settleClickEffect(`candidate:${index}:pointer-bypass`)) {
          return true;
        }
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
      if (await settleClickEffect(`candidate:${index}:dom`)) {
        return true;
      }
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      tracePageEvent(page, `${tracePrefix}-dom-error`, `candidate:${index}:${message}`);
    }
  }

  if (missingCandidates > 0) {
    tracePageEvent(page, `${tracePrefix}-candidate-miss-summary`, `count:${missingCandidates}:no-visible-candidate`);
  }

  return false;
}

async function doubleClickVisible(page: Page, candidates: Locator[], tracePrefix: string, timeoutMs = 2_000, settleMs = 750): Promise<boolean> {
  let missingCandidates = 0;

  for (const [index, locator] of candidates.entries()) {
    const candidate = await firstVisibleLocator(locator, timeoutMs);
    if (!candidate) {
      missingCandidates += 1;
      continue;
    }

    if (missingCandidates > 0) {
      tracePageEvent(page, `${tracePrefix}-candidate-miss-summary`, `count:${missingCandidates}`);
    }
    tracePageEvent(page, `${tracePrefix}-candidate-visible`, `candidate:${index}`);

    try {
      await candidate.scrollIntoViewIfNeeded().catch(() => undefined);
      await candidate.dblclick({ timeout: timeoutMs + 1_000 });
      await page.waitForTimeout(settleMs);
      return true;
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      tracePageEvent(page, `${tracePrefix}-dblclick-error`, `candidate:${index}:${message}`);
    }

    try {
      await candidate.dblclick({ timeout: timeoutMs, force: true });
      await page.waitForTimeout(settleMs);
      return true;
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      tracePageEvent(page, `${tracePrefix}-force-error`, `candidate:${index}:${message}`);
    }
  }

  if (missingCandidates > 0) {
    tracePageEvent(page, `${tracePrefix}-candidate-miss-summary`, `count:${missingCandidates}:no-visible-candidate`);
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
        await candidate.hover({ timeout: timeoutMs }).catch(() => undefined);
        await candidate.click({ timeout: timeoutMs + 1_000 });
        await page.waitForTimeout(settleMs);
        if (requireVisibleSurface && !(await waitForSettingsSurface(page, 750))) {
          tracePageEvent(page, `${tracePrefix}-hover-click-no-surface`, `candidate:${index}:${itemIndex}`);
        } else {
          return true;
        }
      } catch (error: unknown) {
        const message = error instanceof Error ? error.message : String(error);
        tracePageEvent(page, `${tracePrefix}-hover-click-error`, `candidate:${index}:${itemIndex}:${message}`);
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


type ChartSurfaceActionKind = "settings" | "more";

function chartSurfaceCandidateWords(name: string): string[] {
  return normalizeUiText(name)
    .toLowerCase()
    .split(/\s+/)
    .filter((part) => part.length > 0 && !/^v\d+(?:\.\d+)*$/.test(part));
}

function chartSurfaceTextMatchesName(text: string, name: string): boolean {
  const normalizedText = normalizeUiText(text).toLowerCase();
  const normalizedName = normalizeUiText(name).toLowerCase();
  if (!normalizedText || !normalizedName) {
    return false;
  }
  if (normalizedText.includes(normalizedName)) {
    return true;
  }

  const words = chartSurfaceCandidateWords(name);
  if (words.length < 2) {
    return false;
  }
  return words.every((word) => (
    normalizedText.includes(word)
    || normalizedText.includes(word.slice(0, Math.min(word.length, 4)))
  ));
}

export async function findChartSurfaceActionButtonsForScript(
  page: Page,
  scriptName: string,
  actionKind: ChartSurfaceActionKind,
): Promise<Locator[]> {
  const candidateNames = resolveOpenScriptSearchNames(scriptName);
  const selectors = actionKind === "settings"
    ? [
      'button[data-qa-id="legend-settings-action"]',
      'button[aria-label="Settings"]:not([data-name="header-toolbar-properties"])',
      'button[title="Settings"]:not([data-name="header-toolbar-properties"])',
      '[role="button"][aria-label="Settings"]:not([data-name="header-toolbar-properties"])',
      '[role="button"][title="Settings"]:not([data-name="header-toolbar-properties"])',
    ]
    : [
      'button[data-qa-id="legend-more-action"]',
      'button[aria-label="More"]',
      'button[title="More"]',
      '[role="button"][aria-label="More"]',
      '[role="button"][title="More"]',
    ];
  const matches: Array<{ locator: Locator; depth: number; text: string }> = [];
  const seen = new Set<string>();

  for (const selector of selectors) {
    const locator = page.locator(selector);
    const total = await locator.count().catch(() => 0);

    for (let index = 0; index < Math.min(total, 80); index += 1) {
      const candidate = locator.nth(index);
      const visible = await candidate.isVisible({ timeout: 150 }).catch(() => false);
      if (!visible) {
        continue;
      }

      let match: { depth: number; text: string } | null = null;
      for (let depth = 1; depth <= 8; depth += 1) {
        const xpath = new Array(depth).fill("..").join("/");
        const ancestor = candidate.locator(`xpath=${xpath}`);
        const ancestorHandle = await ancestor.elementHandle({ timeout: 120 }).catch(() => null);
        if (!ancestorHandle) {
          continue;
        }
        const meta = await ancestorHandle.evaluate((node) => {
          if (!(node instanceof Element)) {
            return { tagName: "", text: "" };
          }
          const element = node as HTMLElement;
          return {
            tagName: element.tagName.toLowerCase(),
            text: (element.innerText || element.textContent || ""),
          };
        }).catch(() => ({ tagName: "", text: "" })).finally(async () => {
          await ancestorHandle.dispose().catch(() => undefined);
        });
        const tagName = meta.tagName;
        if (tagName === "body" || tagName === "html") {
          break;
        }
        const text = normalizeUiText(meta.text || "");
        if (!text || text.length > 420) {
          continue;
        }
        if (candidateNames.some((name) => chartSurfaceTextMatchesName(text, name))) {
          match = { depth, text: text.slice(0, 180) };
          break;
        }
      }

      if (!match) {
        continue;
      }

      const key = `${selector}:${index}:${match.depth}:${match.text}`;
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      matches.push({ locator: candidate, depth: match.depth, text: match.text });
    }
  }

  matches.sort((left, right) => left.depth - right.depth || left.text.length - right.text.length);
  return matches.slice(0, 8).map((entry) => entry.locator);
}

async function clickLegendControlWithFallback(
  page: Page,
  candidates: Locator[],
  tracePrefix: string,
  timeoutMs = 500,
  settleMs = 150,
  effectCheck?: () => Promise<boolean>,
): Promise<boolean> {
  const settleLegendControlEffect = async (effectDetail: string): Promise<boolean> => {
    await page.waitForTimeout(settleMs);
    if (!effectCheck) {
      return true;
    }

    const effectVisible = await effectCheck().catch(() => false);
    if (effectVisible) {
      tracePageEvent(page, `${tracePrefix}-effect-ok`, effectDetail);
      return true;
    }

    tracePageEvent(page, `${tracePrefix}-no-effect`, effectDetail);
    return false;
  };

  for (const [index, locator] of candidates.entries()) {
    const candidate = await firstVisibleLocatorFast(locator, timeoutMs);
    if (!candidate) {
      tracePageEvent(page, `${tracePrefix}-candidate-missing`, `candidate:${index}`);
      continue;
    }

    tracePageEvent(page, `${tracePrefix}-candidate-visible`, `candidate:${index}`);
    await candidate.scrollIntoViewIfNeeded().catch(() => undefined);
    await candidate.hover({ timeout: timeoutMs }).catch(() => undefined);

    try {
      await candidate.click({ timeout: timeoutMs, force: true });
      tracePageEvent(page, `${tracePrefix}-force-ok`, `candidate:${index}`);
      if (await settleLegendControlEffect(`candidate:${index}:force`)) {
        return true;
      }
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      tracePageEvent(page, `${tracePrefix}-force-error`, `candidate:${index}:${message}`);
    }

    const box = await candidate.boundingBox().catch(() => null);
    if (box && box.width > 6 && box.height > 6) {
      tracePageEvent(page, `${tracePrefix}-offset-start`, `candidate:${index}:${Math.round(box.width)}x${Math.round(box.height)}`);
      const offsetPositions = [
        { x: Math.max(3, box.width - 4), y: Math.max(3, Math.min(box.height / 2, box.height - 3)) },
        { x: 4, y: Math.max(3, Math.min(box.height / 2, box.height - 3)) },
        { x: Math.max(3, Math.min(box.width / 2, box.width - 3)), y: 3 },
        { x: Math.max(3, Math.min(box.width / 2, box.width - 3)), y: Math.max(3, box.height - 4) },
      ];

      for (const [positionIndex, position] of offsetPositions.entries()) {
        try {
          await candidate.click({ timeout: timeoutMs, position, force: true });
          tracePageEvent(page, `${tracePrefix}-offset-ok`, `candidate:${index}:${positionIndex}`);
          if (await settleLegendControlEffect(`candidate:${index}:offset:${positionIndex}`)) {
            return true;
          }
        } catch (error: unknown) {
          const message = error instanceof Error ? error.message : String(error);
          tracePageEvent(page, `${tracePrefix}-offset-error`, `candidate:${index}:${positionIndex}:${message}`);
        }
      }
    } else {
      tracePageEvent(page, `${tracePrefix}-offset-skip`, `candidate:${index}:no-box`);
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
          hit.style.pointerEvents = 'none';
          hit = document.elementFromPoint(x, y) as HTMLElement | null;
        }

        const targetReady = hit === element || Boolean(hit && element.contains(hit));
        if (targetReady) {
          for (const eventType of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
            element.dispatchEvent(
              new MouseEvent(eventType, {
                bubbles: true,
                cancelable: true,
                composed: true,
                clientX: x,
                clientY: y,
                view: window,
              }),
            );
          }
          element.click();
        }

        for (const entry of patched.reverse()) {
          entry.element.style.pointerEvents = entry.value;
        }

        return targetReady;
      });
      if (pointerBypassed) {
        tracePageEvent(page, `${tracePrefix}-pointer-bypass-ok`, `candidate:${index}`);
        if (await settleLegendControlEffect(`candidate:${index}:pointer-bypass`)) {
          return true;
        }
      }
      tracePageEvent(page, `${tracePrefix}-pointer-bypass-miss`, `candidate:${index}`);
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      tracePageEvent(page, `${tracePrefix}-pointer-bypass-error`, `candidate:${index}:${message}`);
    }

    try {
      await candidate.evaluate((node) => {
        const element = node as HTMLElement;
        element.scrollIntoView({ block: 'center', inline: 'center' });
        for (const eventType of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
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
      if (await settleLegendControlEffect(`candidate:${index}:dom`)) {
        return true;
      }
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      tracePageEvent(page, `${tracePrefix}-dom-error`, `candidate:${index}:${message}`);
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

export async function openFreshUntitledPineDraft(page: Page, kind: PineDraftKind = "indicator"): Promise<void> {
  await runTrackedStep(page, "openFreshUntitledPineDraft", async () => {
    await dismissSignInModal(page).catch(() => undefined);
    await ensurePineEditor(page);

    const untitledSignals = [
      page.getByText(/^untitled script$/i),
      page.getByRole("button", { name: /^untitled script$/i }),
      page.getByRole("link", { name: /^untitled script$/i }),
    ];
    if (await hasVisibleLocator(untitledSignals, 500)) {
      tracePageEvent(page, "open-fresh-untitled", "already-visible");
      return;
    }

    for (let attempt = 0; attempt < 3; attempt += 1) {
      const openedDirectly = await clickVisibleWithFallback(
        page,
        tvSelectors.openScript(page),
        `open-fresh-untitled-${attempt}`,
        2_000,
        1_000,
      );
      if (openedDirectly && await hasVisibleLocator(untitledSignals, 1_000)) {
        tracePageEvent(page, "open-fresh-untitled", `ok:${attempt}`);
        return;
      }

      const openedMenu = await clickVisibleWithFallback(
        page,
        tvSelectors.currentScriptMenu(page),
        `open-fresh-current-script-menu-${attempt}`,
        1_500,
        500,
      );
      if (!openedMenu) {
        continue;
      }

      const createdNew = await clickVisibleWithFallback(
        page,
        tvSelectors.createNewScript(page),
        `open-fresh-create-new-${attempt}`,
        1_500,
        500,
      );
      if (!createdNew) {
        await page.keyboard.press("Escape").catch(() => undefined);
        continue;
      }

      const pickedKind = await clickVisibleWithFallback(
        page,
        tvSelectors.createNewScriptKind(page, kind),
        `open-fresh-create-kind-${kind}-${attempt}`,
        1_500,
        1_000,
      );
      if (pickedKind && await hasVisibleLocator(untitledSignals, 1_500)) {
        tracePageEvent(page, "open-fresh-untitled", `created-${kind}:${attempt}`);
        return;
      }

      await page.keyboard.press("Escape").catch(() => undefined);
    }

    const bodyText = normalizeUiText((await page.locator("body").innerText().catch(() => "")) || "");
    throw new Error(`Could not open a fresh untitled Pine draft; body preview: ${bodyText.slice(0, 240)}`);
  });
}

async function openScriptSelectionSurface(page: Page): Promise<boolean> {
  const directOpen = await clickVisibleWithFallback(page, tvSelectors.openScript(page), "open-script-surface-direct", 2_000, 750);
  if (directOpen) {
    const directSurfaceReady = await waitForScriptSearchSurface(page, 1_500);
    if (directSurfaceReady) {
      tracePageEvent(page, "open-script-surface-direct-ready");
      return true;
    }

    tracePageEvent(page, "open-script-surface-direct-no-surface");
    await page.keyboard.press("Escape").catch(() => undefined);
  }

  const openedMenu = await clickVisibleWithFallback(page, tvSelectors.currentScriptMenu(page), "open-script-surface-menu", 1_500, 400);
  if (!openedMenu) {
    return false;
  }

   if (await waitForScriptSearchSurface(page, 1_200)) {
    tracePageEvent(page, "open-script-surface-menu-direct");
    return true;
  }

  const openedFromMenu = await clickVisibleWithFallback(page, tvSelectors.openScriptAction(page), "open-script-surface-action", 1_500, 750);
  if (!openedFromMenu) {
    await page.keyboard.press("Escape").catch(() => undefined);
    return false;
  }

  return waitForScriptSearchSurface(page, 1_500);
}

async function waitForScriptSearchSurface(page: Page, timeoutMs = 2_000): Promise<boolean> {
  const startedAt = Date.now();

  while (Date.now() - startedAt < timeoutMs) {
    const scopeStates: OpenScriptSurfaceScopeState[] = [];
    for (const scope of openScriptSurfaceScopes(page)) {
      const scopeState: OpenScriptSurfaceScopeState = {
        scopedSearchVisible: await hasVisibleLocator(openScriptSurfaceSearchLocators(scope), 200),
        scopedMyScriptsVisible: await hasVisibleLocator(openScriptSurfaceMyScriptsLocatorsForScope(scope), 200),
      };
      scopeStates.push(scopeState);
    }

    if (openScriptSurfaceLooksReady({ scopeStates })) {
      return true;
    }

    await page.waitForTimeout(100);
  }

  // Do not fall back to global search or tab locators here. The chart/watchlist
  // surface can keep unrelated search inputs alive, which causes a false-positive
  // open-script surface and skips the actual "Open script" action in CI.
  return false;
}

export function indicatorsMyScriptsShowsMatchingPrivateScript(
  scriptName: string,
  visiblePrivateScripts: string[],
): boolean {
  const patterns = buildScriptNamePatterns(scriptName);
  return visiblePrivateScripts.some((candidate) => {
    const normalizedCandidate = normalizeUiText(candidate);
    return patterns.some((pattern) => pattern.test(normalizedCandidate));
  });
}

/**
 * Dismiss any blocking overlay in TradingView's #overlap-manager-root before
 * attempting pointer-event-driven interactions (e.g. opening the Indicators dialog).
 *
 * Uses a 4-step strategy (mouse-move → outerHTML log → Escape → JS bypass):
 * 1. Move mouse to (0,0) — dismisses hover-triggered tooltips/popovers.
 * 2. Log .container-VeoIyDt4 outerHTML for artifact observability.
 * 3. Press Escape — dismisses conventional modal-style overlays.
 * 4. Set pointer-events:none via JS — last resort for Escape-resistant overlays.
 *
 * Call sites: addScriptToChartViaIndicators, ensurePineEditor (×2).
 * TODO(#2849 — after ≥2 green smc-library-refresh runs): centralise step 1
 * (mouse.move) into clickVisibleWithFallback to cover all future entry-points
 * automatically without requiring explicit call sites.
 *
 * TradingView renders modals, dropdowns, and popups into a portal div
 * (#overlap-manager-root > .container-VeoIyDt4). When a stale overlay from a
 * previous interaction lingers, its pointer-events intercept ALL clicks on the
 * chart surface, causing Playwright's locator.click() to time out with:
 *   "<div class=\"container-VeoIyDt4\">…</div> subtree intercepts pointer events"
 *
 * Investigation (runs #27750634938 → #27773053223) found the blocker is a
 * hover-triggered tooltip/popover (data-id changes across attempts) that is NOT
 * dismissed by Escape and has no close button. The 4-step strategy below handles
 * both the tooltip/popover class and conventional modal overlays.
 */
export async function dismissOverlapManagerOverlay(page: Page): Promise<void> {
  if (page.isClosed()) return;

  const overlayLocator = page.locator("#overlap-manager-root [data-id]");

  // Fast-path: skip the 200 ms mouse.move wait entirely if no overlay is present.
  // ensurePineEditor calls this function twice per invocation, so the early-exit
  // avoids 400 ms of unnecessary latency in the common (no-overlay) case.
  const initialCount = await overlayLocator.count().catch(() => 0);
  if (initialCount === 0) return;

  // Step 1: Move mouse to a neutral position (0,0) — dismisses hover-triggered
  // tooltips / popovers that appear when the mouse hovers over TV UI elements.
  // The dynamic data-id across attempts strongly suggests a hover-sensitive element.
  await page.mouse.move(0, 0).catch(() => undefined);
  await page.waitForTimeout(200).catch(() => undefined);

  const countAfterMove = await overlayLocator.count().catch(() => 0);
  if (countAfterMove === 0) return; // mouse.move was sufficient

  // Step 2: Log the overlay's outerHTML for artifact observability so future
  // failures can identify the exact TV element without another manual RCA.
  const overlayHtml = await page
    .locator("#overlap-manager-root .container-VeoIyDt4")
    .first()
    .evaluate((el) => el.outerHTML)
    .catch(() => "");
  tracePageEvent(page, "dismiss-overlap-manager-overlay-found", overlayHtml.slice(0, 500));

  // Step 3: Try Escape — works for conventional modal-style overlays.
  await page.keyboard.press("Escape").catch(() => undefined);
  await page.waitForTimeout(300).catch(() => undefined);

  const countAfterEscape = await overlayLocator.count().catch(() => 0);
  if (countAfterEscape === 0) {
    tracePageEvent(page, "dismiss-overlap-manager-overlay-done", "escape-worked");
    return;
  }

  // Step 4: Last resort — neutralise pointer-events via JavaScript for overlays
  // that cannot be dismissed interactively (no close button, Escape-resistant).
  // This does NOT remove the element, so TV's own cleanup still fires normally.
  tracePageEvent(page, "dismiss-overlap-manager-overlay-js-bypass", String(countAfterEscape));
  await page
    .evaluate(() => {
      // Target only the blocking [data-id] overlay elements — NOT the portal
      // container (.container-VeoIyDt4), which TradingView reuses for ALL future
      // dialogs (including the Indicators dialog opened immediately after).
      document
        .querySelectorAll("#overlap-manager-root [data-id]")
        .forEach((el) => ((el as HTMLElement).style.pointerEvents = "none"));
    })
    .catch(() => undefined);
  await page.waitForTimeout(100).catch(() => undefined);

  const remaining = await overlayLocator.count().catch(() => -1);
  tracePageEvent(page, "dismiss-overlap-manager-overlay-done", `js-bypass:remaining=${remaining}`);
}

async function collectVisibleIndicatorMyScriptNames(page: Page, limit = 8): Promise<string[]> {
  return page
    .locator('[data-name="indicators-dialog"] [data-id^="USER;"]')
    .evaluateAll((nodes, maxResults) => {
      const maxCount = typeof maxResults === "number" ? maxResults : 8;
      const results: string[] = [];

      for (const node of nodes) {
        const element = node as HTMLElement;
        const style = window.getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        const text = (element.innerText || element.textContent || "").replace(/\s+/g, " ").trim();

        if (!text || style.display === "none" || style.visibility === "hidden" || rect.width < 4 || rect.height < 4) {
          continue;
        }

        if (!results.includes(text)) {
          results.push(text);
        }
        if (results.length >= maxCount) {
          break;
        }
      }

      return results;
    }, limit)
    .catch(() => []);
}

export type AddExistingScriptToChartViaIndicatorsAttempt = {
  searchName: string;
  matchingPrivateScriptVisible: boolean;
  visiblePrivateScripts: string[];
  addedToChart: boolean;
};

export type AddExistingScriptToChartViaIndicatorsResult = {
  added: boolean;
  matchedSearchName: string | null;
  attempts: AddExistingScriptToChartViaIndicatorsAttempt[];
};

async function addScriptToChartViaIndicators(page: Page, scriptName: string): Promise<AddExistingScriptToChartViaIndicatorsAttempt> {
  tracePageEvent(page, "add-to-chart-indicators-start", scriptName);
  await dismissSignInModal(page);
  await closePineEditorIfVisible(page).catch(() => undefined);
  // Dismiss any lingering #overlap-manager-root overlay (e.g. container-VeoIyDt4
  // blocking pointer events) before clicking the Indicators button.
  await dismissOverlapManagerOverlay(page);

  const attempt: AddExistingScriptToChartViaIndicatorsAttempt = {
    searchName: scriptName,
    matchingPrivateScriptVisible: false,
    visiblePrivateScripts: [],
    addedToChart: false,
  };

  const openedSurface = await clickVisibleWithFallbackOutsidePineDialog(
    page,
    tvSelectors.indicators(page),
    "add-to-chart-indicators-open",
    2_500,
    900,
  ).catch(() => false);
  if (!openedSurface) {
    tracePageEvent(page, "add-to-chart-indicators-open-miss", scriptName);
    return attempt;
  }

  const searchSurfaceVisible = await waitForScriptSearchSurface(page, 2_500);
  tracePageEvent(page, "add-to-chart-indicators-surface", `${scriptName}:${searchSurfaceVisible}`);
  if (!searchSurfaceVisible) {
    await closeModal(page).catch(() => undefined);
    return attempt;
  }

  await clickFirst(tvSelectors.myScriptsTab(page), 1_500).catch(() => false);
  const searchFilled = await fillFirst(scriptName, tvSelectors.scriptSearch(page), 1_500).catch(() => false);
  tracePageEvent(page, "add-to-chart-indicators-search", `${scriptName}:${searchFilled}`);
  // Wait for the first USER script row to become visible before collecting.
  // TradingView loads "My scripts" via an async API call; the previous fixed
  // 500ms was too short on 2026-06-17 (TV UI change introduced lazy rendering).
  // Poll for up to 3 s, then proceed regardless so we log the exact state.
  const allScriptRowsLocator = page.locator(
    '[data-name="indicators-dialog"] [data-id^="USER;"]',
  );
  const firstScriptRowLocator = allScriptRowsLocator.first();
  await firstScriptRowLocator
    .waitFor({ state: "visible", timeout: 3_000 })
    .catch(() => undefined);
  tracePageEvent(
    page,
    "add-to-chart-indicators-rows-ready",
    String(await allScriptRowsLocator.count()),
  );
  attempt.visiblePrivateScripts = await collectVisibleIndicatorMyScriptNames(page);
  attempt.matchingPrivateScriptVisible = indicatorsMyScriptsShowsMatchingPrivateScript(scriptName, attempt.visiblePrivateScripts);

  let selectedRow = await clickVisibleWithFallback(
    page,
    tvSelectors.scriptRow(page, scriptName, { strict: true }),
    "add-to-chart-indicators-row",
    3_000,
    1_000,
  ).catch(() => false);

  if (!selectedRow) {
    await page.keyboard.press("ArrowDown").catch(() => undefined);
    await page.keyboard.press("Enter").catch(() => undefined);
    await page.waitForTimeout(1_000);
    selectedRow = true;
    tracePageEvent(page, "add-to-chart-indicators-keyboard", scriptName);
  }

  const surfaceStillVisible = await waitForScriptSearchSurface(page, 600);
  if (surfaceStillVisible) {
    await closeModal(page).catch(() => undefined);
  }

  const settled = await settleChartSurfaceAfterInsert(page, scriptName, "indicators", false);
  tracePageEvent(page, settled ? "add-to-chart-indicators-ok" : "add-to-chart-indicators-no-visible-script", scriptName);
  return {
    ...attempt,
    addedToChart: settled,
  };
}

async function hasPublishSurface(page: Page, timeoutMs = 500): Promise<boolean> {
  if (
    await hasVisibleLocatorFast(tvSelectors.publishTitleInput(page), timeoutMs)
    || await hasVisibleLocatorFast(tvSelectors.publishDescriptionInput(page), timeoutMs)
    || await hasVisibleLocatorFast(tvSelectors.privateVisibility(page), timeoutMs)
  ) {
    return true;
  }

  const publishSurface = page
    .locator('#overlap-manager-root [role="dialog"], #overlap-manager-root [data-id], #overlap-manager-root [data-name*="dialog" i], #overlap-manager-root [class*="dialog" i], #overlap-manager-root [class*="modal" i]')
    .filter({ hasText: /script is not on the chart|your new publication will use the current chart|continue|publish private library|publish private|update .*library|title|description|final touches|privacy settings|category|tags & signature|show more/i });

  return Boolean(await firstVisibleLocatorFast(publishSurface, timeoutMs));
}

async function waitForPublishSurface(page: Page, timeoutMs = 2_000): Promise<boolean> {
  const startedAt = Date.now();

  while (Date.now() - startedAt < timeoutMs) {
    if (await hasPublishSurface(page, 250)) {
      return true;
    }

    await page.waitForTimeout(100);
  }

  return hasPublishSurface(page, 500);
}

async function collectVisibleOverlayTextSnippets(page: Page, timeoutMs = 500): Promise<string[]> {
  const overlays = page.locator([
    '#overlap-manager-root [role="dialog"]',
    '#overlap-manager-root [role="menu"]',
    '#overlap-manager-root [data-name*="dialog" i]',
    '#overlap-manager-root [data-name*="menu" i]',
    '#overlap-manager-root [class*="dialog" i]',
    '#overlap-manager-root [class*="modal" i]',
    '#overlap-manager-root [class*="menu" i]',
  ].join(', '));
  const count = await overlays.count().catch(() => 0);
  const snippets: string[] = [];

  for (let index = 0; index < count; index += 1) {
    const overlay = overlays.nth(index);
    const visible = await overlay.isVisible({ timeout: timeoutMs }).catch(() => false);
    if (!visible) {
      continue;
    }

    const text = await overlay.innerText().catch(() => "");
    const normalized = text.replace(/\s+/g, " ").trim();
    if (normalized) {
      snippets.push(normalized.slice(0, 240));
    }
  }

  return snippets.slice(0, 5);
}

async function getVisibleCompileErrorDetails(page: Page, timeoutMs = 500): Promise<string | null> {
  const compileDialog = await findVisibleDialogByText(page, /compilation error|cannot compile due to an error|view error/i, timeoutMs);
  if (!compileDialog) {
    const bodyText = normalizeUiText((await page.locator("body").innerText().catch(() => "")) || "");
    if (!bodyText) {
      return null;
    }

    const genericMarkers = [
      "syntax error",
      "compilation error",
      "the script cannot compile due to an error",
      "script could not be translated",
      "error at ",
      "error on bar",
      "undeclared identifier",
      "mismatched input",
    ];
    const lowered = bodyText.toLowerCase();
    return genericMarkers.some((marker) => lowered.includes(marker)) ? bodyText.slice(0, 400) : null;
  }

  let dialogText = normalizeUiText((await compileDialog.innerText().catch(() => "")) || "");
  const clickedViewError = await clickVisibleWithFallback(
    page,
    [
      compileDialog.getByRole("button", { name: /view error/i }),
      compileDialog.getByText(/view error/i),
      compileDialog.locator('button:has-text("View error")'),
    ],
    "compile-error-view",
    1_000,
    350,
  ).catch(() => false);

  if (clickedViewError) {
    await page.waitForTimeout(500).catch(() => undefined);
    const compileDetailScreenshot = await takeScreenshot(
      page,
      utcNow().replace(/[:.]/g, "-"),
      "compile-error-detail",
    ).catch(() => "");
    if (compileDetailScreenshot) {
      tracePageEvent(page, "compile-error-view-screenshot", compileDetailScreenshot);
    }

    const overlaySnippets = await collectVisibleOverlayTextSnippets(page, 250).catch(() => []);
    const overlayDetail = overlaySnippets.find((snippet) => /line\s+\d+|error at|undeclared identifier|mismatched input|syntax error|cannot call/i.test(snippet));
    if (overlayDetail) {
      dialogText = overlayDetail;
    }

    const detailDialog = await firstVisibleLocator(
      page
        .locator('[role="dialog"], [data-name*="dialog" i], [class*="dialog" i], [class*="modal" i]')
        .filter({ hasText: /line\s+\d+|error at|undeclared identifier|mismatched input|syntax error|cannot call|no viable alternative/i }),
      1_000,
    ).catch(() => null);
    const detailText = normalizeUiText((await detailDialog?.innerText().catch(() => "")) || "");
    if (detailText) {
      dialogText = detailText;
    }
  }

  return dialogText || null;
}

async function openPublishSurface(page: Page, timeoutMs = 4_000): Promise<boolean> {
  const openedMenu = await clickVisibleWithFallback(
    page,
    tvSelectors.currentScriptMenu(page),
    "publish-open-menu",
    1_500,
    400,
  );
  if (openedMenu) {
    const openedAction = await clickVisibleWithFallback(
      page,
      tvSelectors.publishScriptAction(page),
      "publish-open-action",
      2_000,
      750,
    );
    if (openedAction && await waitForPublishSurface(page, 2_000)) {
      tracePageEvent(page, "publish-open", "surface-visible:menu-action");
      return true;
    }

    tracePageEvent(page, "publish-open", `no-surface:menu-action:${openedAction}`);
    await page.keyboard.press("Escape").catch(() => undefined);
  }

  const openedPineDialogButton = await clickVisibleWithFallback(
    page,
    tvSelectors.pinePublishButtons(page),
    "publish-open-pine-dialog",
    timeoutMs,
    750,
  );
  if (openedPineDialogButton && await waitForPublishSurface(page, 2_000)) {
    tracePageEvent(page, "publish-open", "surface-visible:pine-dialog");
    return true;
  }

  if (openedPineDialogButton) {
    const compileErrorDetails = await getVisibleCompileErrorDetails(page, 750).catch(() => null);
    if (compileErrorDetails) {
      throw new Error(`TradingView reported a compile error while opening publish: ${compileErrorDetails}`);
    }

    const overlaySnippets = await collectVisibleOverlayTextSnippets(page, 250).catch(() => []);
    tracePageEvent(page, "publish-open-pine-dialog-overlays", JSON.stringify(overlaySnippets));
  }

  tracePageEvent(page, "publish-open", `no-surface:pine-dialog:${openedPineDialogButton}`);

  await closePineEditorIfVisible(page).catch(() => undefined);
  const openedOutsidePine = await clickVisibleWithFallbackOutsidePineDialog(
    page,
    tvSelectors.publishButtons(page),
    "publish-open-outside-pine",
    timeoutMs,
    750,
  );
  if (openedOutsidePine && await waitForPublishSurface(page, 2_000)) {
    tracePageEvent(page, "publish-open", "surface-visible:outside-pine");
    return true;
  }

  tracePageEvent(page, "publish-open", `no-surface:outside-pine:${openedOutsidePine}`);

  for (const [index, locator] of tvSelectors.publishButtons(page).entries()) {
    const clicked = await clickVisibleWithFallback(
      page,
      [locator],
      `publish-open-candidate-${index}`,
      timeoutMs,
      750,
    );
    if (!clicked) {
      continue;
    }

    if (await waitForPublishSurface(page, 2_000)) {
      tracePageEvent(page, "publish-open", `surface-visible:candidate:${index}`);
      return true;
    }

    tracePageEvent(page, "publish-open", `no-surface:candidate:${index}`);
  }

  return false;
}

async function hasPublishAddToChartGate(page: Page, timeoutMs = 500): Promise<boolean> {
  return Boolean(
    await firstVisibleLocatorFast(
      page
        .locator('#overlap-manager-root [role="dialog"], #overlap-manager-root [data-id], #overlap-manager-root [data-name*="dialog" i], #overlap-manager-root [class*="dialog" i], #overlap-manager-root [class*="modal" i]')
        .filter({ hasText: /script is not on the chart/i }),
      timeoutMs,
    ),
  );
}

export function resolvePublishNoChangeCleanupActions(options: {
  dialogClosed: boolean;
  publishSurfaceVisible: boolean;
}): {
  shouldPressDialogEscape: boolean;
  shouldDismissPublishSurface: boolean;
  cleanupComplete: boolean;
} {
  return {
    shouldPressDialogEscape: !options.dialogClosed,
    shouldDismissPublishSurface: options.publishSurfaceVisible,
    cleanupComplete: options.dialogClosed && !options.publishSurfaceVisible,
  };
}

async function waitForDialogByTextToClose(page: Page, pattern: RegExp, timeoutMs = 1_500): Promise<boolean> {
  const startedAt = Date.now();

  while (Date.now() - startedAt < timeoutMs) {
    if (!(await findVisibleDialogByText(page, pattern, 150))) {
      return true;
    }

    await page.waitForTimeout(100).catch(() => undefined);
  }

  return !(await findVisibleDialogByText(page, pattern, 150));
}

async function dismissPublishCancelConfirmation(page: Page, timeoutMs = 500): Promise<boolean> {
  const cancelDialog = await findVisibleDialogByText(page, /cancel publication/i, timeoutMs);
  if (!cancelDialog) {
    return false;
  }

  tracePageEvent(page, "publish-no-change", "cancel-confirm-visible");
  const confirmed = await clickVisibleWithFallback(
    page,
    [
      cancelDialog.getByRole("button", { name: /^yes$/i }),
      cancelDialog.getByText(/^yes$/i),
      cancelDialog.locator('button:has-text("Yes")'),
    ],
    "publish-no-change-cancel-confirm",
    1_500,
    500,
  ).catch(() => false);

  if (!confirmed) {
    await page.keyboard.press("Enter").catch(() => undefined);
  }

  const dialogClosed = await waitForDialogByTextToClose(page, /cancel publication/i, 1_500);
  tracePageEvent(page, "publish-no-change", dialogClosed ? "cancel-confirm-dismissed" : "cancel-confirm-still-visible");
  return dialogClosed;
}

async function dismissPublishSurfaceAfterNoChange(page: Page): Promise<boolean> {
  if (!(await hasPublishSurface(page, 150))) {
    tracePageEvent(page, "publish-no-change", "surface-dismissed");
    return true;
  }

  for (let attempt = 0; attempt < 3; attempt += 1) {
    if (!(await hasPublishSurface(page, 150))) {
      tracePageEvent(page, "publish-no-change", `surface-dismissed:${attempt}`);
      return true;
    }

    await clickVisibleWithFallback(
      page,
      tvSelectors.closeModal(page),
      `publish-no-change-surface-close-${attempt}`,
      600,
      150,
    ).catch(() => false);
    if (!(await hasPublishSurface(page, 150))) {
      tracePageEvent(page, "publish-no-change", `surface-dismissed:close:${attempt}`);
      return true;
    }

    await page.keyboard.press("Escape").catch(() => undefined);
    await page.waitForTimeout(150).catch(() => undefined);
    await dismissPublishCancelConfirmation(page, 500).catch(() => false);
  }

  const surfaceStillVisible = await hasPublishSurface(page, 250);
  tracePageEvent(page, "publish-no-change", surfaceStillVisible ? "surface-still-visible" : "surface-dismissed");
  return !surfaceStillVisible;
}

async function capturePublishConfirmationEvidence(page: Page, scriptName?: string, timeoutMs = 4_000): Promise<{
  versionContextTexts: string[];
  bodyText: string;
  publishSurfaceClosed: boolean;
}> {
  const startedAt = Date.now();
  let bodyText = "";
  let versionContextTexts: string[] = [];
  let publishSurfaceClosed = false;

  while (Date.now() - startedAt < timeoutMs) {
    if (scriptName) {
      versionContextTexts = await collectPublishedVersionContextTexts(page, scriptName).catch(() => []);
    }
    bodyText = await page.locator("body").innerText().catch(() => "");
    publishSurfaceClosed = publishSurfaceClosed || !(await hasPublishSurface(page, 150));

    if (
      (scriptName && detectPublishedVersionFromContextTexts(versionContextTexts, scriptName) !== null)
      || detectPublishedVersionFromBody(bodyText, scriptName) !== null
    ) {
      break;
    }

    await page.waitForTimeout(250).catch(() => undefined);
  }

  tracePageEvent(
    page,
    "publish-confirm-evidence",
    `surface_closed=${publishSurfaceClosed}:version_contexts=${versionContextTexts.length}:body_len=${bodyText.length}`,
  );

  return { versionContextTexts, bodyText, publishSurfaceClosed };
}

async function handlePublishNoChangeDialog(page: Page, timeoutMs = 500): Promise<boolean> {
  const noChangeDialog = await findVisibleDialogByText(page, /nothing to update/i, timeoutMs);
  if (!noChangeDialog) {
    return false;
  }

  tracePageEvent(page, "publish-no-change", "visible");
  await clickVisibleWithFallback(
    page,
    [
      noChangeDialog.getByRole("button", { name: /^ok$/i }),
      noChangeDialog.getByText(/^ok$/i),
      noChangeDialog.locator('button:has-text("OK")'),
    ],
    "publish-no-change-ok",
    1_500,
    500,
  ).catch(() => false);
  const dialogClosed = await waitForDialogByTextToClose(page, /nothing to update/i, 1_500);
  tracePageEvent(page, "publish-no-change", dialogClosed ? "dialog-dismissed" : "dialog-still-visible");
  const cleanupActions = resolvePublishNoChangeCleanupActions({
    dialogClosed,
    publishSurfaceVisible: await hasPublishSurface(page, 250),
  });
  if (cleanupActions.shouldPressDialogEscape) {
    await page.keyboard.press("Escape").catch(() => undefined);
    await page.waitForTimeout(150).catch(() => undefined);
  }
  if (cleanupActions.shouldDismissPublishSurface) {
    await dismissPublishSurfaceAfterNoChange(page).catch(() => false);
  }
  return true;
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

const MAX_RECENT_DIALOG_SCAN = 16;

function dialogCandidateLocators(page: Page): Locator[] {
  return [
    page.locator('#overlap-manager-root [role="dialog"]'),
    page.locator('#overlap-manager-root [data-name*="dialog" i], #overlap-manager-root [class*="dialog" i], #overlap-manager-root [class*="modal" i], #overlap-manager-root [class*="popover" i], #overlap-manager-root [data-name*="popover" i]'),
    page.locator('[role="dialog"][aria-modal="true"]'),
    page.locator('[role="dialog"]'),
  ];
}

async function collectRecentVisibleDialogs(
  locator: Locator,
  timeoutMs = 500,
  maxScan = MAX_RECENT_DIALOG_SCAN,
): Promise<Locator[]> {
  const startedAt = Date.now();

  while (Date.now() - startedAt < timeoutMs) {
    const total = await locator.count().catch(() => 0);
    const matches: Locator[] = [];
    const scanCount = Math.min(total, maxScan);

    for (let offset = 0; offset < scanCount; offset += 1) {
      const index = total - 1 - offset;
      const candidate = locator.nth(index);
      const visible = await candidate.isVisible({ timeout: 40 }).catch(() => false);
      if (!visible) {
        continue;
      }

      const insidePineDialog = await candidate
        .evaluate((node) => Boolean((node as HTMLElement).closest('[data-name="pine-dialog"]')))
        .catch(() => false);
      if (insidePineDialog) {
        continue;
      }

      matches.push(candidate);
    }

    if (matches.length > 0) {
      return matches;
    }

    await new Promise((resolve) => setTimeout(resolve, 50));
  }

  return [];
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

async function computeDialogScrollPlan(dialog: Locator): Promise<{ positions: number[]; restoreTop: number }> {
  return dialog.evaluate((node) => {
    const root = node as HTMLElement;
    const candidates = [root, ...Array.from(root.querySelectorAll<HTMLElement>("*"))];
    const scroller = candidates
      .filter((element) => {
        const style = window.getComputedStyle(element);
        const overflowY = style.overflowY;
        return (overflowY === "auto" || overflowY === "scroll" || overflowY === "overlay" || element.scrollHeight > element.clientHeight + 24)
          && element.scrollHeight > element.clientHeight + 24;
      })
      .sort((left, right) => (right.scrollHeight - right.clientHeight) - (left.scrollHeight - left.clientHeight))[0];

    if (!scroller) {
      return { positions: [0], restoreTop: 0 };
    }

    const maxScroll = Math.max(scroller.scrollHeight - scroller.clientHeight, 0);
    const step = Math.max(160, Math.floor(scroller.clientHeight * 0.8));
    const positions = [0];
    for (let top = step; top < maxScroll; top += step) {
      positions.push(top);
    }
    if (maxScroll > 0 && positions[positions.length - 1] !== maxScroll) {
      positions.push(maxScroll);
    }

    return {
      positions,
      restoreTop: scroller.scrollTop,
    };
  }).catch(() => ({ positions: [0], restoreTop: 0 }));
}

async function scrollDialogTo(dialog: Locator, scrollTop: number): Promise<void> {
  await dialog.evaluate((node, targetTop) => {
    const root = node as HTMLElement;
    const candidates = [root, ...Array.from(root.querySelectorAll<HTMLElement>("*"))];
    const scroller = candidates
      .filter((element) => {
        const style = window.getComputedStyle(element);
        const overflowY = style.overflowY;
        return (overflowY === "auto" || overflowY === "scroll" || overflowY === "overlay" || element.scrollHeight > element.clientHeight + 24)
          && element.scrollHeight > element.clientHeight + 24;
      })
      .sort((left, right) => (right.scrollHeight - right.clientHeight) - (left.scrollHeight - left.clientHeight))[0];

    if (scroller) {
      scroller.scrollTop = targetTop;
    }
  }, scrollTop).catch(() => undefined);
}

async function snapshotDialogAcrossScroll(page: Page, dialog: Locator): Promise<VisibleDialogSnapshot> {
  const plan = await computeDialogScrollPlan(dialog);
  const titles = new Set<string>();
  const texts = new Set<string>();
  const labelTexts = new Set<string>();
  const dialogBox = await dialog.boundingBox().catch(() => null);
  let previousPosition = 0;

  for (const position of plan.positions) {
    await scrollDialogTo(dialog, position);
    if (plan.positions.length > 1) {
      if (dialogBox) {
        await page.mouse.move(dialogBox.x + dialogBox.width / 2, dialogBox.y + Math.min(dialogBox.height / 2, Math.max(dialogBox.height - 24, 24))).catch(() => undefined);
        await page.mouse.wheel(0, position - previousPosition).catch(() => undefined);
      }
      await page.waitForTimeout(80);
    }
    previousPosition = position;

    const snapshot = await snapshotDialog(dialog).catch(() => null);
    if (!snapshot) {
      continue;
    }

    if (snapshot.title) {
      titles.add(snapshot.title);
    }
    if (snapshot.text) {
      texts.add(snapshot.text);
    }
    for (const labelText of snapshot.labelTexts ?? []) {
      if (labelText) {
        labelTexts.add(labelText);
      }
    }
  }

  await scrollDialogTo(dialog, plan.restoreTop);

  return {
    title: [...titles][0] ?? "",
    text: [...texts].join(" "),
    labelTexts: [...labelTexts],
  };
}

async function verifyOpenedSettingsDialogIdentity(page: Page, scriptName: string, tracePrefix: string): Promise<boolean> {
  tracePageEvent(page, `${tracePrefix}-identity-start`, scriptName);
  if (await hasScriptSettingsInputsSurface(page)) {
    const dialogs = await collectVisibleDialogSnapshots(page).catch(() => []);
    const titledDialog = dialogs.find((dialog) => normalizeUiText(dialog.title).length > 0);
    if (!titledDialog) {
      tracePageEvent(page, `${tracePrefix}-identity-implicit-surface`, scriptName);
      return true;
    }
    if (settingsDialogTitleMatchesScriptName(scriptName, titledDialog.title)) {
      tracePageEvent(page, `${tracePrefix}-identity-title-match`, titledDialog.title);
      return true;
    }
    tracePageEvent(page, `${tracePrefix}-identity-mismatch`, `${scriptName} != ${titledDialog.title}`);
    await closeModal(page).catch(() => undefined);
    return false;
  }

  const dialogs = await collectVisibleDialogSnapshots(page).catch(() => []);
  const titledDialog = dialogs.find((dialog) => normalizeUiText(dialog.title).length > 0);
  if (!titledDialog) {
    tracePageEvent(page, `${tracePrefix}-identity-missing-title`, scriptName);
    throw new Error(`Opened settings dialog without an identifiable script title for: ${scriptName}`);
  }
  if (settingsDialogTitleMatchesScriptName(scriptName, titledDialog.title)) {
    return true;
  }
  tracePageEvent(page, `${tracePrefix}-identity-mismatch`, `${scriptName} != ${titledDialog.title}`);
  throw new Error(`Opened settings dialog for wrong script: expected ${scriptName}, got ${titledDialog.title}`);
}

export function settingsDialogTitleMatchesScriptName(scriptName: string, dialogTitle?: string | null): boolean {
  const normalizedTitle = normalizeUiText(dialogTitle ?? "");
  if (!normalizedTitle) {
    return false;
  }
  const candidates = resolveOpenScriptSearchNames(scriptName);
  for (const candidate of candidates) {
    if (scriptNameAppearsInUiText(candidate, normalizedTitle)
      || isLegendTruncatedMatch(normalizedTitle, candidate)) {
      return true;
    }
  }
  return false;
}

/**
 * Strict (not loose / not substring) check that `actualTitle` matches at least
 * one of the candidate script names exactly (case-insensitive, after whitespace
 * normalization, with optional trailing version suffix like " v1.2" or
 * " version 3"). Used by the preflight identity assertion to catch the
 * 2026-04-22 substring-collision class where a third-party public script
 * shared a prefix with one of our preflight targets.
 *
 * Returns false on any candidate that is empty/whitespace-only.
 */
export function isExactScriptNameMatch(actualTitle: string, ...candidateNames: string[]): boolean {
  const normalizedActual = normalizeUiText(actualTitle);
  if (!normalizedActual) {
    return false;
  }
  for (const candidate of candidateNames) {
    if (!candidate) continue;
    if (uiTextContainsExactScriptName(candidate, actualTitle)) {
      return true;
    }
    if (canonicalSemanticVersionSuffixMatch(candidate, actualTitle)) {
      return true;
    }
  }
  return false;
}

/**
 * Reads the visible TradingView indicator-settings dialog title, or null when
 * no titled dialog is present. Intended for post-openSettingsForScript
 * identity assertions in preflight runs.
 */
export async function readOpenedScriptIdentity(page: Page): Promise<string | null> {
  const dialogs = await collectVisibleDialogSnapshots(page).catch(() => []);
  const titledDialog = dialogs.find((dialog) => normalizeUiText(dialog.title).length > 0);
  return titledDialog ? titledDialog.title : null;
}

async function collectVisibleDialogSnapshots(page: Page): Promise<VisibleDialogSnapshot[]> {
  const snapshots: VisibleDialogSnapshot[] = [];
  const seenTexts = new Set<string>();

  for (const root of dialogCandidateLocators(page)) {
    const dialogs = await collectRecentVisibleDialogs(root, 350);
    for (const dialog of dialogs) {
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

function indicatorSettingsDialogLocators(page: Page): Locator[] {
  return [
    page.locator('#overlap-manager-root [role="dialog"]').filter({ hasText: /\binputs\b/i }).filter({ hasText: /\b(style|properties|visibility)\b/i }),
    page.locator('#overlap-manager-root [data-name*="dialog" i], #overlap-manager-root [class*="dialog" i], #overlap-manager-root [class*="modal" i], #overlap-manager-root [class*="popover" i], #overlap-manager-root [data-name*="popover" i]').filter({ hasText: /\binputs\b/i }).filter({ hasText: /\b(style|properties|visibility)\b/i }),
  ];
}

async function findIndicatorSettingsDialog(page: Page, timeoutMs = 750): Promise<Locator | null> {
  for (const candidate of indicatorSettingsDialogLocators(page)) {
    const visible = await firstVisibleLocatorFast(candidate, Math.min(timeoutMs, 150));
    if (visible) {
      return visible;
    }
  }

  const candidates = dialogCandidateLocators(page);

  for (const candidate of candidates) {
    const visibleDialogs = await collectRecentVisibleDialogs(candidate, timeoutMs);
    for (const visible of visibleDialogs) {
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
  if (await hasVisibleLocatorFast(tvSelectors.inputsTab(page), 120)) {
    return true;
  }

  for (const candidate of indicatorSettingsDialogLocators(page)) {
    const visible = await firstVisibleLocatorFast(candidate, 120);
    if (visible) {
      return true;
    }
  }

  return false;
}

export async function hasSettingsSurfaceDomHint(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    // Keep this page-context probe free of local helper functions; TS transforms
    // can inject Node-side helpers that are unavailable inside the browser.
    const surfaceTextPattern = /\b(?:inputs|style|visibility|settings)\b/i;
    const settingsActionPattern = /^settings(?:\.\.\.)?$/i;
    const surfaceSelectors = [
      '#overlap-manager-root [role="dialog"]',
      '#overlap-manager-root [data-name*="dialog" i]',
      '#overlap-manager-root [class*="dialog" i]',
      '#overlap-manager-root [class*="modal" i]',
      '#overlap-manager-root [role="menu"]',
      '#overlap-manager-root [data-name*="menu" i]',
      '#overlap-manager-root [class*="menu" i]',
      '[role="dialog"]',
      '[role="menu"]',
    ];

    for (const selector of surfaceSelectors) {
      for (const element of Array.from(document.querySelectorAll(selector)).slice(-8)) {
        const htmlElement = element as HTMLElement;
        const rect = htmlElement.getBoundingClientRect();
        const style = window.getComputedStyle(htmlElement);
        const text = (htmlElement.innerText || element.textContent || "").trim();
        const visible = rect.width > 0
          && rect.height > 0
          && style.visibility !== "hidden"
          && style.display !== "none"
          && Number(style.opacity || "1") > 0.01;
        if (visible && surfaceTextPattern.test(text)) {
          return true;
        }
      }
    }

    const actionSelectors = [
      '[role="menuitem"]',
      '[role="button"]',
      'button',
      '[role="tab"]',
    ];
    for (const selector of actionSelectors) {
      for (const element of Array.from(document.querySelectorAll(selector)).slice(-80)) {
        const htmlElement = element as HTMLElement;
        const rect = htmlElement.getBoundingClientRect();
        const style = window.getComputedStyle(htmlElement);
        const text = (htmlElement.innerText || element.textContent || "").trim();
        const visible = rect.width > 0
          && rect.height > 0
          && style.visibility !== "hidden"
          && style.display !== "none"
          && Number(style.opacity || "1") > 0.01;
        if (visible && settingsActionPattern.test(text)) {
          return true;
        }
      }
    }

    return false;
  }).catch((error: unknown) => {
    tracePageEvent(page, "settings-surface-dom-hint-error", String(error));
    return false;
  });
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
    if (await hasVisibleLocatorFast(tvSelectors.inputsTab(page), 120)) {
      return true;
    }
    await page.waitForTimeout(100);
  }

  if (await hasQuickVisibleScriptSettingsSurface(page)) {
    return true;
  }
  if (await hasVisibleLocatorFast(tvSelectors.inputsTab(page), 150)) {
    return true;
  }

  return Boolean(await findIndicatorSettingsDialog(page, Math.min(250, Math.max(100, timeoutMs))));
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

async function isSettingsSurfaceVisibleFast(page: Page): Promise<boolean> {
  return (
    (await hasQuickVisibleScriptSettingsSurface(page))
    || (await hasSettingsSurfaceDomHint(page))
    || (await hasVisibleLocatorFast(tvSelectors.settingsAction(page), 120))
    || (await hasVisibleLocatorFast(tvSelectors.inputsTab(page), 120))
  );
}

async function waitForSettingsSurface(page: Page, timeoutMs = 2_000): Promise<boolean> {
  const startedAt = Date.now();

  while (Date.now() - startedAt < timeoutMs) {
    if (await isSettingsSurfaceVisibleFast(page)) {
      return true;
    }
    await page.waitForTimeout(100);
  }

  return isSettingsSurfaceVisible(page, Math.min(250, Math.max(100, timeoutMs)));
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

  const actionClickTimeoutMs = Math.max(250, Math.min(600, timeoutMs));
  const actionSettleMs = Math.max(100, Math.min(250, Math.floor(actionClickTimeoutMs / 2)));
  const actionEffectTimeoutMs = Math.max(250, Math.min(600, timeoutMs));
  const clickedSettings = await clickVisibleWithFallback(
    page,
    tvSelectors.settingsAction(page),
    `${tracePrefix}-action`,
    actionClickTimeoutMs,
    actionSettleMs,
    async () => waitForScriptSettingsInputsSurface(page, actionEffectTimeoutMs),
  );
  tracePageEvent(page, `${tracePrefix}-action-result`, String(clickedSettings));
  if (clickedSettings) {
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

type VisibleChartScriptStateProbeOptions = {
  locatorTimeoutMs?: number;
  legendButtonLimit?: number;
  legendVisibleTimeoutMs?: number;
  legendAncestorTextTimeoutMs?: number;
};

export async function collectVisibleChartScriptState(
  page: Page,
  scriptName: string,
  options: VisibleChartScriptStateProbeOptions = {},
): Promise<VisibleChartScriptState> {
  const [, scriptNamePattern, fuzzyPattern] = buildScriptNamePatterns(scriptName);
  const strategyPattern = /strategy report/i;
  const locatorTimeoutMs = options.locatorTimeoutMs ?? 500;

  const legendWrappers = await findLegendRowWrappers(page, scriptName, options).catch(() => []);
  const hasLegendMatch = legendWrappers.length > 0;
  const hasStrategyReportMatch = await hasVisibleLocator([
    page.getByText(strategyPattern),
    page.getByRole("button", { name: strategyPattern }),
  ], locatorTimeoutMs);
  const hasScriptNameMatch = await hasVisibleLocator([
    page.getByText(scriptNamePattern),
    page.getByText(fuzzyPattern),
    page.getByRole("button", { name: scriptNamePattern }),
    page.getByRole("button", { name: fuzzyPattern }),
    page.getByRole("link", { name: scriptNamePattern }),
    page.getByRole("link", { name: fuzzyPattern }),
  ], locatorTimeoutMs);

  return {
    hasLegendMatch,
    hasStrategyReportMatch,
    hasScriptNameMatch,
  };
}

function isScriptVisibleOnChart(state: VisibleChartScriptState): boolean {
  return state.hasLegendMatch || (state.hasStrategyReportMatch && state.hasScriptNameMatch);
}

export function isScriptVisibleOnChartState(state: VisibleChartScriptState): boolean {
  return isScriptVisibleOnChart(state);
}

export async function isScriptVisibleOnChartSurface(page: Page, scriptName: string): Promise<boolean> {
  const state = await collectVisibleChartScriptState(page, scriptName);
  if (isScriptVisibleOnChart(state)) {
    return true;
  }
  if (state.hasScriptNameMatch) {
    const diagnostics = await collectEditorDiagnostics(page).catch(() => null);
    if (diagnostics && !hasVisibleEditorHost(diagnostics)) {
      tracePageEvent(page, "chart-visibility-text-match-only", scriptName);
      return true;
    }
  }
  return false;
}

async function isScriptStrictlyVisibleOnChartSurface(page: Page, scriptName: string): Promise<boolean> {
  const state = await collectVisibleChartScriptState(page, scriptName);
  return isScriptVisibleOnChart(state);
}

export async function findLegendRowWrappers(
  page: Page,
  scriptName: string,
  options: VisibleChartScriptStateProbeOptions = {},
): Promise<Locator[]> {
  const candidateNames = resolveOpenScriptSearchNames(scriptName);
  const patternsList = candidateNames.map((name) => buildScriptNamePatterns(name));
  const buttonLimit = options.legendButtonLimit ?? 40;
  const visibleTimeoutMs = options.legendVisibleTimeoutMs ?? 250;
  const ancestorTextTimeoutMs = options.legendAncestorTextTimeoutMs ?? 300;

  // Start from the known legend-action buttons and walk UP the ancestor
  // chain to find the enclosing legend row.  TradingView wraps the buttons
  // inside an inner actions-container div, so the direct parent (depth 1)
  // typically has no indicator-name text.  The actual legend row is at
  // depth 2–5 depending on the TradingView DOM version.  This replaces
  // the previous XPath wrapper approach that either matched too many
  // ancestors (.//button) or only the empty action-container (./button).
  const buttons = page.locator('button[data-qa-id="legend-settings-action"]');
  const buttonCount = await buttons.count().catch(() => 0);
  const matches: Array<{ locator: Locator; textLength: number }> = [];
  const seenKeys = new Set<string>();

  for (let i = 0; i < Math.min(buttonCount, buttonLimit); i += 1) {
    const btn = buttons.nth(i);
    const visible = await btn.isVisible({ timeout: visibleTimeoutMs }).catch(() => false);
    if (!visible) continue;

    for (const depth of [1, 2, 3, 4, 5]) {
      const xpath = new Array(depth).fill("..").join("/");
      const ancestor = btn.locator(`xpath=${xpath}`);
      const text = normalizeUiText((await ancestor.innerText({ timeout: ancestorTextTimeoutMs }).catch(() => "")) || "");
      if (!text || text.length > 300) continue;

      let matched = false;
      for (const [index, candidate] of candidateNames.entries()) {
        const [, loosePattern, fuzzyPattern] = patternsList[index];
        if (loosePattern.test(text) || fuzzyPattern.test(text) || isLegendTruncatedMatch(text, candidate)) {
          matched = true;
          break;
        }
      }

      if (matched) {
        const key = `${depth}:${text.slice(0, 60)}`;
        if (!seenKeys.has(key)) {
          seenKeys.add(key);
          matches.push({ locator: ancestor, textLength: text.length });
        }
        break;
      }
    }
  }

  matches.sort((left, right) => left.textLength - right.textLength);
  return matches.slice(0, 6).map((entry) => entry.locator);
}

function legendMoreActionLocators(wrapper: Locator): Locator[] {
  return [
    wrapper.locator('button[data-qa-id="legend-more-action"]'),
    wrapper.locator('[aria-haspopup="menu"]'),
    wrapper.locator('button[aria-label*="more" i]'),
    wrapper.locator('[role="button"][aria-label*="more" i]'),
    wrapper.locator('button[title*="more" i]'),
    wrapper.locator('[role="button"][title*="more" i]'),
    wrapper.locator('button[aria-label*="menu" i]'),
    wrapper.locator('[role="button"][aria-label*="menu" i]'),
    wrapper.locator('[data-name*="menu" i]'),
  ];
}

function legendDeleteActionLocators(wrapper: Locator): Locator[] {
  return [
    wrapper.locator('button[data-qa-id*="delete" i]'),
    wrapper.locator('button[data-qa-id*="remove" i]'),
    wrapper.locator('[role="button"][data-qa-id*="delete" i]'),
    wrapper.locator('[role="button"][data-qa-id*="remove" i]'),
    wrapper.locator('button[aria-label*="delete" i]'),
    wrapper.locator('button[aria-label*="remove" i]'),
    wrapper.locator('[role="button"][aria-label*="delete" i]'),
    wrapper.locator('[role="button"][aria-label*="remove" i]'),
    wrapper.locator('button[title*="delete" i]'),
    wrapper.locator('button[title*="remove" i]'),
    wrapper.locator('[role="button"][title*="delete" i]'),
    wrapper.locator('[role="button"][title*="remove" i]'),
  ];
}

function scriptRemovalActionLocators(page: Page): Locator[] {
  const activeMenu = page.locator('#overlap-manager-root [role="menu"], #overlap-manager-root [data-name*="menu" i], #overlap-manager-root [class*="menu" i]').last();

  return [
    activeMenu.getByRole("menuitem", { name: /^(remove|delete)\b/i }),
    activeMenu.getByRole("button", { name: /^(remove|delete)\b/i }),
    activeMenu.locator('[role="menuitem"], [role="button"], button, [data-name*="item" i]').filter({ hasText: /^(remove|delete)\b/i }),
    page.locator('[role="menu"] [role="menuitem"], [role="menu"] [role="button"], [data-name*="menu" i] [role="menuitem"], [data-name*="menu" i] button').filter({ hasText: /^(remove|delete)\b/i }),
  ];
}

function scriptRemovalConfirmActionLocators(page: Page): Locator[] {
  const activeDialog = page.locator('#overlap-manager-root [role="dialog"], #overlap-manager-root [data-name*="dialog" i], #overlap-manager-root [class*="dialog" i], #overlap-manager-root [class*="modal" i]').last();

  return [
    activeDialog.getByRole("button", { name: /^(remove|delete|yes|ok)$/i }),
    activeDialog.getByText(/^(remove|delete|yes|ok)$/i),
    activeDialog.locator('button').filter({ hasText: /^(remove|delete|yes|ok)$/i }),
    page.locator('[role="dialog"] [role="button"], [role="dialog"] button').filter({ hasText: /^(remove|delete|yes|ok)$/i }),
  ];
}

async function tryKeyboardRemoveScriptInstance(page: Page, wrapper: Locator, scriptName: string, attempt: number): Promise<boolean> {
  await wrapper.scrollIntoViewIfNeeded().catch(() => undefined);
  await wrapper.hover({ timeout: 1_000 }).catch(() => undefined);

  const wrapperBox = await wrapper.boundingBox().catch(() => null);
  if (wrapperBox) {
    const focusX = wrapperBox.x + Math.max(16, Math.min(56, wrapperBox.width * 0.25));
    const focusY = wrapperBox.y + Math.max(6, Math.min(wrapperBox.height / 2, Math.max(wrapperBox.height - 6, 6)));
    await page.mouse.click(focusX, focusY).catch(() => undefined);
  } else {
    await wrapper.click({ force: true, timeout: 1_000 }).catch(() => undefined);
  }

  await page.waitForTimeout(200);

  for (const key of ["Backspace", "Delete"] as const) {
    await page.keyboard.press(key).catch(() => undefined);
    await page.waitForTimeout(250);
    await clickVisibleWithFallback(
      page,
      scriptRemovalConfirmActionLocators(page),
      `script-remove-keyboard-confirm-${key.toLowerCase()}`,
      800,
      250,
    ).catch(() => false);

    const stillVisible = await isScriptStrictlyVisibleOnChartSurface(page, scriptName).catch(() => true);
    tracePageEvent(page, "script-remove-keyboard", `${scriptName}:${attempt}:${key}:${!stillVisible}`);
    if (!stillVisible) {
      return true;
    }
  }

  return false;
}

async function waitForLegendWrapperCountChange(
  page: Page,
  scriptName: string,
  previousCount: number,
  timeoutMs = 2_500,
): Promise<number> {
  const startedAt = Date.now();

  while (Date.now() - startedAt < timeoutMs) {
    const nextCount = (await findLegendRowWrappers(page, scriptName).catch(() => [])).length;
    if (nextCount < previousCount) {
      return nextCount;
    }
    await page.waitForTimeout(125);
  }

  return (await findLegendRowWrappers(page, scriptName).catch(() => [])).length;
}

async function openLegendRemovalMenu(page: Page, wrapper: Locator, scriptName: string, attempt: number): Promise<boolean> {
  await wrapper.scrollIntoViewIfNeeded().catch(() => undefined);
  await wrapper.hover({ timeout: 1_000 }).catch(() => undefined);

  const clickedMenu = await clickVisibleWithFallback(
    page,
    legendMoreActionLocators(wrapper),
    "script-remove-menu",
    1_200,
    300,
  );
  if (clickedMenu && (await hasVisibleLocator(scriptRemovalActionLocators(page), 500))) {
    tracePageEvent(page, "script-remove-menu-opened", `${scriptName}:${attempt}:button`);
    return true;
  }

  const wrapperBox = await wrapper.boundingBox().catch(() => null);
  if (wrapperBox) {
    const rightClickX = wrapperBox.x + Math.max(16, Math.min(56, wrapperBox.width * 0.25));
    const rightClickY = wrapperBox.y + Math.max(8, Math.min(wrapperBox.height / 2, Math.max(wrapperBox.height - 8, 8)));
    await page.mouse.click(rightClickX, rightClickY, { button: "right" }).catch(() => undefined);
    await page.waitForTimeout(250);
    if (await hasVisibleLocator(scriptRemovalActionLocators(page), 500)) {
      tracePageEvent(page, "script-remove-menu-opened", `${scriptName}:${attempt}:rightclick`);
      return true;
    }
  }

  await wrapper.click({ button: "right", force: true, timeout: 1_000 }).catch(() => undefined);
  await page.waitForTimeout(250);
  const hasRemovalAction = await hasVisibleLocator(scriptRemovalActionLocators(page), 500);
  tracePageEvent(page, "script-remove-menu-opened", `${scriptName}:${attempt}:force-rightclick:${hasRemovalAction}`);
  return hasRemovalAction;
}

export async function removeVisibleChartScriptInstances(page: Page, scriptName: string, maxRemovals = 4): Promise<number> {
  return runTrackedStep(page, `removeVisibleChartScriptInstances:${scriptName}`, async () => {
    let removedCount = 0;

    for (let attempt = 0; attempt < maxRemovals; attempt += 1) {
      await dismissSignInModal(page);
      await closePineEditorIfVisible(page);

      const wrappers = await findLegendRowWrappers(page, scriptName).catch(() => []);
      if (wrappers.length === 0) {
        break;
      }

      const targetWrapper = wrappers[0] ?? wrappers[wrappers.length - 1];
      const previousCount = wrappers.length;
      await targetWrapper.scrollIntoViewIfNeeded().catch(() => undefined);
      await targetWrapper.hover({ timeout: 1_000 }).catch(() => undefined);

      const clickedDirectDelete = await clickVisibleWithFallback(
        page,
        legendDeleteActionLocators(targetWrapper),
        "script-remove-direct",
        1_200,
        300,
      ).catch(() => false);
      if (clickedDirectDelete) {
        tracePageEvent(page, "script-remove-direct-clicked", `${scriptName}:${attempt}`);
        await clickVisibleWithFallback(
          page,
          scriptRemovalConfirmActionLocators(page),
          "script-remove-direct-confirm",
          1_000,
          300,
        ).catch(() => false);

        const remainingCount = await waitForLegendWrapperCountChange(page, scriptName, previousCount);
        if (remainingCount < previousCount) {
          removedCount += previousCount - remainingCount;
          tracePageEvent(page, "script-remove-ok", `${scriptName}:${previousCount}->${remainingCount}:direct`);
          await page.waitForTimeout(250);
          continue;
        }

        const stillVisibleAfterDirectDelete = await isScriptStrictlyVisibleOnChartSurface(page, scriptName).catch(() => false);
        if (!stillVisibleAfterDirectDelete) {
          removedCount += 1;
          tracePageEvent(page, "script-remove-ok", `${scriptName}:cleared:direct`);
          break;
        }

        tracePageEvent(page, "script-remove-direct-no-change", `${scriptName}:${attempt}`);
        await closeModal(page).catch(() => undefined);
      }

      const removedViaKeyboard = await tryKeyboardRemoveScriptInstance(page, targetWrapper, scriptName, attempt);
      if (removedViaKeyboard) {
        const remainingCount = await waitForLegendWrapperCountChange(page, scriptName, previousCount);
        if (remainingCount < previousCount) {
          removedCount += previousCount - remainingCount;
          tracePageEvent(page, "script-remove-ok", `${scriptName}:${previousCount}->${remainingCount}:keyboard`);
          await page.waitForTimeout(250);
          continue;
        }

        removedCount += 1;
        tracePageEvent(page, "script-remove-ok", `${scriptName}:cleared:keyboard`);
        break;
      }

      const removalMenuOpened = await openLegendRemovalMenu(page, targetWrapper, scriptName, attempt);
      if (!removalMenuOpened) {
        tracePageEvent(page, "script-remove-menu-miss", `${scriptName}:${attempt}`);
        break;
      }

      const clickedRemove = await clickVisibleWithFallback(
        page,
        scriptRemovalActionLocators(page),
        "script-remove-action",
        1_200,
        300,
      );
      if (!clickedRemove) {
        tracePageEvent(page, "script-remove-action-miss", `${scriptName}:${attempt}`);
        await closeModal(page).catch(() => undefined);
        break;
      }

      const remainingCount = await waitForLegendWrapperCountChange(page, scriptName, previousCount);
      if (remainingCount < previousCount) {
        removedCount += previousCount - remainingCount;
        tracePageEvent(page, "script-remove-ok", `${scriptName}:${previousCount}->${remainingCount}`);
        await page.waitForTimeout(250);
        continue;
      }

      const stillVisible = await isScriptStrictlyVisibleOnChartSurface(page, scriptName).catch(() => false);
      if (!stillVisible) {
        removedCount += 1;
        tracePageEvent(page, "script-remove-ok", `${scriptName}:cleared`);
        break;
      }

      tracePageEvent(page, "script-remove-no-change", `${scriptName}:${attempt}`);
      await closeModal(page).catch(() => undefined);
      break;
    }

    return removedCount;
  });
}

export async function refreshChartScriptInstance(page: Page, scriptName: string): Promise<number> {
  return runTrackedStep(page, `refreshChartScriptInstance:${scriptName}`, async () => {
    const initiallyVisible = await isScriptStrictlyVisibleOnChartSurface(page, scriptName).catch(() => false);
    const removedCount = await removeVisibleChartScriptInstances(page, scriptName).catch(() => 0);
    const stillVisible = await isScriptStrictlyVisibleOnChartSurface(page, scriptName).catch(() => false);

    if (initiallyVisible && stillVisible) {
      throw new Error(`Could not clear stale chart instance before refresh for ${scriptName}`);
    }

    await ensurePineEditor(page).catch(() => undefined);
    await openExistingScript(page, scriptName).catch(() => undefined);
    await addCurrentScriptToChart(page, scriptName, { forceInsert: true });
    await page.waitForTimeout(1_250);
    return removedCount;
  });
}

async function tryOpenScriptSettingsByDoubleClick(
  page: Page,
  target: Locator,
  traceStartEvent: string,
  traceOkEvent: string,
  traceDetail: string,
): Promise<boolean> {
  const quickInputsSurfaceTimeoutMs = 150;

  const settleSettingsOpen = async (): Promise<boolean> => {
    await page.waitForTimeout(200).catch(() => undefined);
    if (await hasQuickVisibleScriptSettingsSurface(page)) {
      tracePageEvent(page, `${traceOkEvent}-quick-surface`, traceDetail);
      return true;
    }

    if (await hasVisibleLocatorFast(tvSelectors.inputsTab(page), quickInputsSurfaceTimeoutMs)) {
      tracePageEvent(page, traceOkEvent, traceDetail);
      return true;
    }

    return false;
  };

  const box = await target.boundingBox().catch(() => null);
  if (!box) {
    return false;
  }

  const doubleClickX = box.x + Math.max(16, Math.min(56, box.width * 0.25));
  const doubleClickY = box.y + Math.max(6, Math.min(box.height / 2, Math.max(box.height - 6, 6)));
  tracePageEvent(page, traceStartEvent, traceDetail);
  await page.mouse.dblclick(doubleClickX, doubleClickY).catch(() => undefined);
  await page.waitForTimeout(350);
  if (await settleSettingsOpen()) {
    return true;
  }

  const domDblClicked = await dispatchDomMouseGesture(target, "dblclick").catch(() => false);
  if (domDblClicked) {
    tracePageEvent(page, `${traceStartEvent}-dom`, traceDetail);
    await page.waitForTimeout(350);
    if (await settleSettingsOpen()) {
      tracePageEvent(page, `${traceOkEvent}-dom`, traceDetail);
      return true;
    }
  }

  await target.click({ force: true, clickCount: 2, timeout: 1_000 }).catch(() => undefined);
  await page.waitForTimeout(350);
  if (await settleSettingsOpen()) {
    tracePageEvent(page, `${traceOkEvent}-force`, traceDetail);
    return true;
  }

  await closeModal(page).catch(() => undefined);
  return false;
}


export const VISIBLE_LEGEND_TEXT_SETTINGS_BUDGET_MS = 8_000;
export const MAX_VISIBLE_LEGEND_TEXT_TARGETS = 3;

export type VisibleLegendTextTargetMeta = {
  text: string;
  rect: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
  domPath?: string | null;
};

export function visibleLegendTextBudgetExceeded(startedAtMs: number, nowMs: number = Date.now()): boolean {
  return nowMs - startedAtMs > VISIBLE_LEGEND_TEXT_SETTINGS_BUDGET_MS;
}

export function visibleLegendTextTargetCapReached(attemptedTargets: number): boolean {
  return attemptedTargets >= MAX_VISIBLE_LEGEND_TEXT_TARGETS;
}

export function visibleLegendTextTargetKey(targetMeta: VisibleLegendTextTargetMeta): string {
  const normalizedText = normalizeUiText(targetMeta.text);
  const domPath = normalizeUiText(targetMeta.domPath ?? "");
  const stableIdentity = domPath
    || [
      targetMeta.rect.x,
      targetMeta.rect.y,
      targetMeta.rect.width,
      targetMeta.rect.height,
    ].join(":");
  return `${stableIdentity}:${normalizedText}`;
}

async function legendTextWrapperHasNearbyAction(wrapper: Locator, target: Locator): Promise<boolean> {
  const [wrapperBox, targetBox] = await Promise.all([
    wrapper.boundingBox().catch(() => null),
    target.boundingBox().catch(() => null),
  ]);
  if (!wrapperBox || !targetBox || wrapperBox.height > 180) {
    return false;
  }

  const actionLocators = [
    ...tvSelectors.legendSettingsButtons(wrapper),
    ...tvSelectors.legendMenuButtons(wrapper),
  ];
  const targetCenterY = targetBox.y + targetBox.height / 2;

  for (const locator of actionLocators) {
    const count = await locator.count().catch(() => 0);
    for (let index = 0; index < Math.min(count, 4); index += 1) {
      const button = locator.nth(index);
      const visible = await button.isVisible({ timeout: 120 }).catch(() => false);
      if (!visible) {
        continue;
      }
      const buttonBox = await button.boundingBox().catch(() => null);
      if (!buttonBox) {
        continue;
      }
      const buttonCenterY = buttonBox.y + buttonBox.height / 2;
      if (Math.abs(buttonCenterY - targetCenterY) <= 44) {
        return true;
      }
    }
  }

  return false;
}

export async function openSettingsFromVisibleLegendText(page: Page, scriptName: string): Promise<boolean> {
  tracePageEvent(page, "script-settings-legend-text-start", scriptName);
  // This budget deliberately applies only to the visible legend-text heuristic.
  // Earlier cleanup inside openSettingsForScriptOnce and later fallback paths
  // keep their own step-level timeout budget.
  const startedAt = Date.now();
  let attemptedTargets = 0;
  const seenTargets = new Set<string>();
  const candidateNames = resolveOpenScriptSearchNames(scriptName);
  const patternsList = candidateNames.map((name) => buildScriptNamePatterns(name));

  for (const [candidateIndex, candidate] of candidateNames.entries()) {
    const [exactPattern, loosePattern, fuzzyPattern] = patternsList[candidateIndex];
    const locators = [
      page.getByText(exactPattern),
      page.getByText(loosePattern),
      page.getByText(fuzzyPattern),
      page.locator('[title], [aria-label]').filter({ hasText: loosePattern }),
    ];

    for (const [locatorIndex, locator] of locators.entries()) {
      if (visibleLegendTextBudgetExceeded(startedAt)) {
        tracePageEvent(page, "script-settings-legend-text-budget-exhausted", `${scriptName}:${attemptedTargets}`);
        return false;
      }

      const total = await locator.count().catch(() => 0);
      for (let itemIndex = 0; itemIndex < Math.min(total, 12); itemIndex += 1) {
        if (visibleLegendTextTargetCapReached(attemptedTargets)) {
          tracePageEvent(page, "script-settings-legend-text-target-cap-exhausted", `${scriptName}:${attemptedTargets}`);
          return false;
        }
        if (visibleLegendTextBudgetExceeded(startedAt)) {
          tracePageEvent(page, "script-settings-legend-text-budget-exhausted", `${scriptName}:${attemptedTargets}`);
          return false;
        }

        const target = locator.nth(itemIndex);
        const visible = await target.isVisible({ timeout: 250 }).catch(() => false);
        if (!visible) {
          continue;
        }

        const targetMeta = await target.evaluate((node) => {
          const element = node as HTMLElement;
          const text = (element.innerText || element.textContent || "").replace(/\s+/g, " ").trim();
          const rect = element.getBoundingClientRect();
          const pathParts: string[] = [];
          let current: HTMLElement | null = element;
          while (current && current !== document.body && pathParts.length < 8) {
            const parent: HTMLElement | null = current.parentElement;
            const tagName = current.tagName.toLowerCase();
            const currentTagName = current.tagName;
            const siblingIndex = parent
              ? Array.from(parent.children)
                .filter((child: Element) => child.tagName === currentTagName)
                .indexOf(current) + 1
              : 1;
            const stableAttrs = [
              current.id ? `#${current.id}` : "",
              current.getAttribute("data-name") ? `[data-name="${current.getAttribute("data-name")}"]` : "",
              current.getAttribute("data-qa-id") ? `[data-qa-id="${current.getAttribute("data-qa-id")}"]` : "",
              current.getAttribute("role") ? `[role="${current.getAttribute("role")}"]` : "",
            ].join("");
            pathParts.push(`${tagName}${stableAttrs}:nth-of-type(${siblingIndex})`);
            current = parent;
          }
          return {
            text,
            rect: {
              x: Math.round(rect.x),
              y: Math.round(rect.y),
              width: Math.round(rect.width),
              height: Math.round(rect.height),
            },
            domPath: pathParts.reverse().join(">"),
            inPineDialog: Boolean(element.closest('[data-name="pine-dialog"]')),
            inDialog: Boolean(element.closest('[role="dialog"], [data-name*="dialog" i], [class*="modal" i]')),
            inMenu: Boolean(element.closest('[role="menu"], [data-name*="menu" i]')),
          };
        }).catch(() => null);
        if (!targetMeta || targetMeta.inPineDialog || targetMeta.inDialog || targetMeta.inMenu) {
          tracePageEvent(page, "script-settings-legend-text-skip-surface", `${scriptName}:${candidateIndex}:${locatorIndex}:${itemIndex}`);
          continue;
        }

        const normalizedText = normalizeUiText(targetMeta.text);
        if (!normalizedText || normalizedText.length > 220) {
          continue;
        }
        if (!(loosePattern.test(normalizedText) || fuzzyPattern.test(normalizedText) || isLegendTruncatedMatch(normalizedText, candidate))) {
          continue;
        }

        const targetKey = visibleLegendTextTargetKey(targetMeta);
        if (seenTargets.has(targetKey)) {
          tracePageEvent(page, "script-settings-legend-text-duplicate-skip", `${scriptName}:${candidateIndex}:${locatorIndex}:${itemIndex}`);
          continue;
        }
        seenTargets.add(targetKey);
        attemptedTargets += 1;

        tracePageEvent(
          page,
          "script-settings-legend-text-visible",
          `${scriptName}:${candidateIndex}:${locatorIndex}:${itemIndex}:${normalizedText.slice(0, 140)}`,
        );
        await target.scrollIntoViewIfNeeded().catch(() => undefined);
        await target.hover({ timeout: 750 }).catch(() => undefined);

        const actionableWrapper = target.locator(
          'xpath=ancestor::*[.//button[@data-qa-id="legend-settings-action"] or .//button[@data-qa-id="legend-more-action"]][1]',
        ).first();
        const wrapperVisible = await actionableWrapper.isVisible({ timeout: 250 }).catch(() => false);
        if (!wrapperVisible || !(await legendTextWrapperHasNearbyAction(actionableWrapper, target))) {
          tracePageEvent(page, "script-settings-legend-text-skip-unscoped", `${scriptName}:${candidateIndex}:${locatorIndex}:${itemIndex}`);
          continue;
        }

        if (await tryOpenScriptSettingsByDoubleClick(
          page,
          target,
          "script-settings-legend-text-dblclick-start",
          "script-settings-legend-text-dblclick-ok",
          `${scriptName}:${candidateIndex}:${locatorIndex}:${itemIndex}`,
        )) {
          return verifyOpenedSettingsDialogIdentity(page, scriptName, "script-settings-legend-text-dblclick");
        }

        await actionableWrapper.hover({ timeout: 750 }).catch(() => undefined);
        const clickedDirectSettings = await clickLegendControlWithFallback(
          page,
          tvSelectors.legendSettingsButtons(actionableWrapper),
          "script-settings-legend-text-direct",
          400,
          120,
          async () => hasSettingsSurfaceDomHint(page),
        );
        if (clickedDirectSettings) {
          tracePageEvent(page, "script-settings-legend-text-direct-clicked", `${scriptName}:${candidateIndex}:${locatorIndex}:${itemIndex}`);
          if (await waitForScriptSettingsInputsSurface(page, 350)) {
            return verifyOpenedSettingsDialogIdentity(page, scriptName, "script-settings-legend-text-direct-surface");
          }
          if (await resolveOpenedSettingsSurfaceToIndicatorDialog(page, "script-settings-legend-text-direct", 350)) {
            return verifyOpenedSettingsDialogIdentity(page, scriptName, "script-settings-legend-text-direct-dialog");
          }
        }
      }
    }
  }

  tracePageEvent(page, "script-settings-legend-text-miss", scriptName);
  return false;
}

async function openSettingsFromLegendContainer(page: Page, scriptName: string): Promise<boolean> {
  tracePageEvent(page, "script-settings-legend-container-start", scriptName);
  const candidateNames = resolveOpenScriptSearchNames(scriptName);
  const patternsList = candidateNames.map((name) => buildScriptNamePatterns(name));
  const directWrappers = await findLegendRowWrappers(page, scriptName).catch(() => []);

  for (const wrapper of directWrappers) {
    const wrapperText = normalizeUiText((await wrapper.innerText().catch(() => "")) || "");
    tracePageEvent(page, "script-settings-legend-wrapper-visible", wrapperText.slice(0, 160));

    await wrapper.scrollIntoViewIfNeeded().catch(() => undefined);
    await wrapper.hover({ timeout: 1_000 }).catch(() => undefined);

    if (await tryOpenScriptSettingsByDoubleClick(
      page,
      wrapper,
      "script-settings-legend-wrapper-dblclick-start",
      "script-settings-legend-wrapper-dblclick-ok",
      scriptName,
    )) {
      return verifyOpenedSettingsDialogIdentity(page, scriptName, "script-settings-legend-wrapper-dblclick");
    }

    const clickedDirectSettings = await clickLegendControlWithFallback(
      page,
      tvSelectors.legendSettingsButtons(wrapper),
      "script-settings-legend-wrapper-direct",
      500,
      150,
      async () => hasSettingsSurfaceDomHint(page),
    );
    if (clickedDirectSettings) {
      tracePageEvent(page, "script-settings-legend-wrapper-direct-clicked", scriptName);
      if (await waitForScriptSettingsInputsSurface(page, 350)) {
        return verifyOpenedSettingsDialogIdentity(page, scriptName, "script-settings-legend-wrapper-direct-surface");
      }
      if (await resolveOpenedSettingsSurfaceToIndicatorDialog(page, "script-settings-legend-wrapper-direct", 350)) {
        return verifyOpenedSettingsDialogIdentity(page, scriptName, "script-settings-legend-wrapper-direct-dialog");
      }
    }

    const clickedMenu = await clickLegendControlWithFallback(
      page,
      tvSelectors.legendMenuButtons(wrapper),
      "script-settings-legend-wrapper-menu",
      500,
      150,
      async () => hasSettingsSurfaceDomHint(page),
    );
    if (clickedMenu) {
      tracePageEvent(page, "script-settings-legend-wrapper-menu-clicked", scriptName);
      if (await resolveOpenedSettingsSurfaceToIndicatorDialog(page, "script-settings-legend-wrapper-menu", 350)) {
        return verifyOpenedSettingsDialogIdentity(page, scriptName, "script-settings-legend-wrapper-menu-dialog");
      }
    }
  }

  for (const candidate of candidateNames) {
    for (const locator of tvSelectors.scriptLegendContainers(page, candidate)) {
      const container = await firstVisibleLocator(locator, 1_200);
      if (!container) {
        continue;
      }

      const containerText = normalizeUiText(await container.innerText().catch(() => ""));
      let matched = false;
      for (let index = 0; index < candidateNames.length; index++) {
        const [, loosePattern, fuzzyPattern] = patternsList[index];
        if (loosePattern.test(containerText) || fuzzyPattern.test(containerText)) {
          matched = true;
          break;
        }
      }
      if (!matched) {
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

        if (await tryOpenScriptSettingsByDoubleClick(
          page,
          targetContainer,
          "script-settings-legend-container-dblclick-start",
          "script-settings-legend-container-dblclick-ok",
          `${scriptName}:${containerIndex}:${candidate}`,
        )) {
          return verifyOpenedSettingsDialogIdentity(page, scriptName, "script-settings-legend-container-dblclick");
        }

        const clickedDirectSettings = await clickLegendControlWithFallback(
          page,
          tvSelectors.legendSettingsButtons(targetContainer),
          "script-settings-legend-direct",
          500,
          150,
          async () => hasSettingsSurfaceDomHint(page),
        );
        if (clickedDirectSettings) {
          tracePageEvent(page, "script-settings-legend-direct-clicked", `${scriptName}:${containerIndex}:${candidate}`);
          await page.waitForTimeout(150);
          if (await waitForScriptSettingsInputsSurface(page, 350)) {
            return verifyOpenedSettingsDialogIdentity(page, scriptName, "script-settings-legend-direct-surface");
          }
          if (await resolveOpenedSettingsSurfaceToIndicatorDialog(page, `script-settings-legend-direct:${scriptName}:${containerIndex}:${candidate}`, 350)) {
            return verifyOpenedSettingsDialogIdentity(page, scriptName, "script-settings-legend-direct-dialog");
          }
          tracePageEvent(page, "script-settings-legend-direct-no-surface", `${scriptName}:${containerIndex}:${candidate}`);
        }

        const clickedMenu = await clickLegendControlWithFallback(
          page,
          tvSelectors.legendMenuButtons(targetContainer),
          "script-settings-legend",
          500,
          150,
          async () => hasSettingsSurfaceDomHint(page),
        );
        if (clickedMenu) {
          tracePageEvent(page, "script-settings-legend-container-clicked", `${scriptName}:${containerIndex}:${candidate}`);
          await page.waitForTimeout(150);
          if (await resolveOpenedSettingsSurfaceToIndicatorDialog(page, `script-settings-legend-menu:${scriptName}:${containerIndex}:${candidate}`, 350)) {
            return verifyOpenedSettingsDialogIdentity(page, scriptName, "script-settings-legend-menu-dialog");
          }
          tracePageEvent(page, "script-settings-legend-container-no-surface", `${scriptName}:${containerIndex}:${candidate}`);
        }

        const box = await targetContainer.boundingBox().catch(() => null);
        if (box) {
          const targetX = Math.max(box.x + 8, box.x + box.width - 14);
          const targetY = box.y + Math.max(6, Math.min(box.height / 2, Math.max(box.height - 6, 6)));

          await page.mouse.move(targetX, targetY).catch(() => undefined);
          await page.waitForTimeout(100);
          await page.mouse.click(targetX, targetY).catch(() => undefined);
          await page.waitForTimeout(350);
          if (await resolveOpenedSettingsSurfaceToIndicatorDialog(page, `script-settings-legend-mouse:${scriptName}:${containerIndex}:${candidate}`)) {
            tracePageEvent(page, "script-settings-legend-container-mouse-ok", `${scriptName}:${containerIndex}:${candidate}`);
            return verifyOpenedSettingsDialogIdentity(page, scriptName, "script-settings-legend-mouse-dialog");
          }

          await page.mouse.click(targetX, targetY, { button: "right" }).catch(() => undefined);
          await page.waitForTimeout(350);
          if (await resolveOpenedSettingsSurfaceToIndicatorDialog(page, `script-settings-legend-rightclick:${scriptName}:${containerIndex}:${candidate}`)) {
            tracePageEvent(page, "script-settings-legend-container-rightclick-ok", `${scriptName}:${containerIndex}:${candidate}`);
            return verifyOpenedSettingsDialogIdentity(page, scriptName, "script-settings-legend-rightclick-dialog");
          }
        }

        await targetContainer.click({ button: "right", force: true, timeout: 1_000 }).catch(() => undefined);
        await page.waitForTimeout(350);
        if (await resolveOpenedSettingsSurfaceToIndicatorDialog(page, `script-settings-legend-force-rightclick:${scriptName}:${containerIndex}:${candidate}`)) {
          tracePageEvent(page, "script-settings-legend-container-force-rightclick-ok", `${scriptName}:${containerIndex}:${candidate}`);
          return verifyOpenedSettingsDialogIdentity(page, scriptName, "script-settings-legend-force-rightclick-dialog");
        }
      }
    }
  }

  tracePageEvent(page, "script-settings-legend-container-miss", scriptName);

  return false;
}

async function openSettingsFromScriptText(page: Page, scriptName: string): Promise<boolean> {
  tracePageEvent(page, "script-settings-text-start", scriptName);
  const candidateNames = resolveOpenScriptSearchNames(scriptName);
  for (const candidate of candidateNames) {
    for (const locator of tvSelectors.scriptRow(page, candidate, { strict: true })) {
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
        if (await tryOpenScriptSettingsByDoubleClick(
          page,
          ancestor,
          "script-settings-text-ancestor-dblclick-start",
          "script-settings-text-ancestor-dblclick-ok",
          `${scriptName}:${level}:${candidate}`,
        )) {
          return verifyOpenedSettingsDialogIdentity(page, scriptName, "script-settings-text-ancestor-dblclick");
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
            tracePageEvent(page, "script-settings-text-ancestor-direct-ok", `${scriptName}:${level}:${candidate}`);
            return verifyOpenedSettingsDialogIdentity(page, scriptName, "script-settings-text-ancestor-direct-surface");
          }
          if (await resolveOpenedSettingsSurfaceToIndicatorDialog(page, `script-settings-text-ancestor-direct:${scriptName}:${level}:${candidate}`)) {
            tracePageEvent(page, "script-settings-text-ancestor-direct-ok", `${scriptName}:${level}:${candidate}`);
            return verifyOpenedSettingsDialogIdentity(page, scriptName, "script-settings-text-ancestor-direct-dialog");
          }
        }

        const clickedMenu = await clickVisibleWithFallback(
          page,
          tvSelectors.legendMenuButtons(ancestor),
          "script-settings-text-ancestor-menu",
          1_000,
          300,
        );
        if (clickedMenu && (await resolveOpenedSettingsSurfaceToIndicatorDialog(page, `script-settings-text-ancestor-menu:${scriptName}:${level}:${candidate}`))) {
          tracePageEvent(page, "script-settings-text-ancestor-menu-ok", `${scriptName}:${level}:${candidate}`);
          return verifyOpenedSettingsDialogIdentity(page, scriptName, "script-settings-text-ancestor-menu-dialog");
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
        if (await resolveOpenedSettingsSurfaceToIndicatorDialog(page, `script-settings-text-rightclick:${scriptName}:${candidate}`)) {
          tracePageEvent(page, "script-settings-text-rightclick-ok", `${scriptName}:${candidate}`);
          return verifyOpenedSettingsDialogIdentity(page, scriptName, "script-settings-text-rightclick-dialog");
        }
      }

      await scriptText.click({ button: "right", force: true, timeout: 1_000 }).catch(() => undefined);
      await page.waitForTimeout(350);
      if (await resolveOpenedSettingsSurfaceToIndicatorDialog(page, `script-settings-text-force-rightclick:${scriptName}:${candidate}`)) {
        tracePageEvent(page, "script-settings-text-force-rightclick-ok", `${scriptName}:${candidate}`);
        return verifyOpenedSettingsDialogIdentity(page, scriptName, "script-settings-text-force-rightclick-dialog");
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
        if (await resolveOpenedSettingsSurfaceToIndicatorDialog(page, `script-settings-text-ancestor-rightclick:${scriptName}:${level}:${candidate}`)) {
          tracePageEvent(page, "script-settings-text-ancestor-rightclick-ok", `${scriptName}:${level}:${candidate}`);
          return verifyOpenedSettingsDialogIdentity(page, scriptName, "script-settings-text-ancestor-rightclick-dialog");
        }
      }
    }
  }

  tracePageEvent(page, "script-settings-text-miss", scriptName);

  return false;
}

async function openSettingsFromChartSurfaceControls(page: Page, scriptName: string): Promise<boolean> {
  tracePageEvent(page, "script-settings-surface-start", scriptName);
  const scopedSettingsButtons = await findChartSurfaceActionButtonsForScript(page, scriptName, "settings");
  tracePageEvent(page, "script-settings-surface-settings-scoped-count", `${scriptName}:${scopedSettingsButtons.length}`);
  const clickedSettings = await clickVisibleWithFallbackOutsidePineDialog(
    page,
    scopedSettingsButtons,
    "script-settings-surface-settings",
    1_200,
    650,
    true,
  );
  if (clickedSettings) {
    tracePageEvent(page, "script-settings-surface-settings-clicked", scriptName);
    if (await waitForSettingsSurface(page, 2_000)) {
      tracePageEvent(page, "script-settings-surface-settings-ok", scriptName);
      return true;
    }
    tracePageEvent(page, "script-settings-surface-settings-no-surface", scriptName);
    await closeModal(page);
  }

  const scopedMoreButtons = await findChartSurfaceActionButtonsForScript(page, scriptName, "more");
  tracePageEvent(page, "script-settings-surface-more-scoped-count", `${scriptName}:${scopedMoreButtons.length}`);
  const clickedMore = await clickVisibleWithFallbackOutsidePineDialog(
    page,
    scopedMoreButtons,
    "script-settings-surface-more",
    1_200,
    650,
    true,
  );
  if (clickedMore) {
    tracePageEvent(page, "script-settings-surface-more-clicked", scriptName);
    if (await waitForSettingsSurface(page, 2_000)) {
      tracePageEvent(page, "script-settings-surface-more-ok", scriptName);
      return true;
    }
    tracePageEvent(page, "script-settings-surface-more-no-surface", scriptName);
    await closeModal(page);
  }

  tracePageEvent(page, "script-settings-surface-miss", scriptName);

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

  for (let attempt = 0; attempt < 5; attempt += 1) {
    // Use clickVisibleWithFallback (which includes force + JS dispatchEvent) so
    // that a Monaco editor margin-view-overlays div covering the Accept button
    // does not cause a Playwright actionability timeout (observed 2026-06-15:
    // margin-view-overlays focused intercepts pointer events on fresh page load).
    const clicked = await clickVisibleWithFallback(
      page,
      tvSelectors.cookieAccept(page),
      "cookie-accept",
      1_000,
      400,
    );
    if (!clicked) {
      break;
    }

    dismissed = true;
    await page.waitForTimeout(800);

    // Verify the banner is actually gone. Playwright's force:true click can return
    // without throwing even when the React synthetic event handler is not triggered
    // (observed 2026-06-16: cookie-accept-click-error + hover-click-error exhaust
    // the first two attempts, force:true then "succeeds" but the banner stays
    // visible because TradingView's consent banner listens to React synthetic
    // events, not raw browser events). If the banner is still up, try an explicit
    // DOM-level dispatch that bubbles through React's event delegation.
    const bannerGone = !(await hasVisibleLocator(tvSelectors.cookieAccept(page), 400));
    if (bannerGone) {
      // Banner confirmed gone — return early with an explicit true so that the
      // caller (and post-mortem reader) see a clean success signal rather than
      // falling through to the terminal-verdict check below.
      return true;
    }
    tracePageEvent(page, "cookie-accept-banner-still-visible", `attempt:${attempt}`);

    try {
      const domClicked = await page.evaluate((): boolean => {
        const textPattern = /accept all|accept|agree|^ok$/i;
        const containerSelectors = [
          '[class*="acceptAll" i]',
          '[id*="accept-all" i]',
          '[id*="acceptAll" i]',
          '[class*="cookie" i]',
          '[class*="consent" i]',
          '[id*="cookie" i]',
          '[id*="consent" i]',
        ];
        let target: HTMLElement | null = null;
        for (const sel of containerSelectors) {
          const buttons = Array.from(
            document.querySelectorAll<HTMLElement>(`${sel} button, ${sel} [role="button"]`),
          );
          const match = buttons.find((el) => {
            const rect = el.getBoundingClientRect();
            return (
              rect.width > 4 &&
              rect.height > 4 &&
              textPattern.test((el.innerText || el.textContent || "").trim())
            );
          });
          if (match) {
            target = match;
            break;
          }
        }
        // Fallback: any visible button with accept text anywhere in the page
        if (!target) {
          const allButtons = Array.from(document.querySelectorAll<HTMLElement>("button, [role='button']"));
          target = allButtons.find((el) => {
            const rect = el.getBoundingClientRect();
            return (
              rect.width > 4 &&
              rect.height > 4 &&
              textPattern.test((el.innerText || el.textContent || "").trim())
            );
          }) ?? null;
        }
        if (!target) {
          return false;
        }
        target.scrollIntoView({ block: "center", inline: "center" });
        for (const eventType of ["pointerover", "pointerenter", "mouseover", "mouseenter", "pointermove", "mousemove", "pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
          target.dispatchEvent(
            new MouseEvent(eventType, {
              bubbles: true,
              cancelable: true,
              composed: true,
              view: window,
            }),
          );
        }
        target.click();
        return true;
      });
      if (domClicked) {
        tracePageEvent(page, "cookie-accept-dom-dispatch-ok", `attempt:${attempt}`);
        await page.waitForTimeout(800);
        const bannerGoneAfterDom = !(await hasVisibleLocator(tvSelectors.cookieAccept(page), 400));
        if (bannerGoneAfterDom) {
          return true;
        }
        tracePageEvent(page, "cookie-accept-dom-dispatch-banner-still-visible", `attempt:${attempt}`);
      } else {
        tracePageEvent(page, "cookie-accept-dom-dispatch-no-target", `attempt:${attempt}`);
      }
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      tracePageEvent(page, "cookie-accept-dom-dispatch-error", `attempt:${attempt}:${message}`);
    }
  }

  // Terminal-verdict check (observability 2026-06-17): if we exhausted all
  // attempts and the banner is still visible, emit a single greppable marker so
  // a post-mortem reader does not have to count per-attempt events. Return false
  // to signal the caller that dismissal did not succeed, enabling future
  // callers to gate on the result rather than silently continuing into a
  // blocked ensurePineEditor flow.
  const stillVisible = await hasVisibleLocator(tvSelectors.cookieAccept(page), 400);
  if (dismissed && stillVisible) {
    tracePageEvent(page, "cookie-accept-exhausted-still-visible", "attempts:5");
    return false;
  }
  return dismissed;
}

export async function ensurePineEditor(page: Page): Promise<void> {
  await runTrackedStep(page, "ensurePineEditor", async () => {
    // Press Escape before any dismiss calls: if the Monaco editor's
    // margin-view-overlays is focused and intercepting pointer events (observed
    // 2026-06-15 — page loads with Pine editor already open, its gutter overlay
    // covers toolbar buttons), a single Escape unfocuses it without closing the
    // editor. Harmless when the overlay is not present.
    await page.keyboard.press("Escape").catch(() => undefined);
    await page.waitForTimeout(300);

    await dismissSignInModal(page);
    await dismissCookieBanner(page);
    // Dismiss any #overlap-manager-root blocker before clicking the Pine editor
    // button. The overlay also blocks ensurePineEditor (run #27773053223 RCA).
    await dismissOverlapManagerOverlay(page);

    const initialDiagnostics = await collectEditorDiagnostics(page);
    if (hasVisibleEditorHost(initialDiagnostics)) {
      await restoreHistoricalScriptVersionIfNeeded(page);
      return;
    }

    for (let attempt = 0; attempt < 4; attempt += 1) {
      // Use clickVisibleWithFallback instead of clickFirst so that the force +
      // JS dispatchEvent chain is available when the Monaco overlay intercepts.
      await clickVisibleWithFallback(page, tvSelectors.pineEditor(page), "pine-editor-open", 2_500, 500);
      await page.waitForTimeout(1_000);
      await dismissSignInModal(page);
      await dismissCookieBanner(page);

      let diagnostics = await collectEditorDiagnostics(page);
      if (hasVisibleEditorHost(diagnostics)) {
        await restoreHistoricalScriptVersionIfNeeded(page);
        return;
      }

      tracePageEvent(page, "pine-editor-recovery-attempt", `close-modal:${attempt + 1}`);
      await closeModal(page).catch(() => undefined);
      await dismissSignInModal(page);
      await dismissCookieBanner(page);
      await dismissOverlapManagerOverlay(page);

      diagnostics = await collectEditorDiagnostics(page);
      if (hasVisibleEditorHost(diagnostics)) {
        tracePageEvent(page, "pine-editor-recovery-ok", `close-modal:${attempt + 1}`);
        await restoreHistoricalScriptVersionIfNeeded(page);
        return;
      }

      // A script pinned to an older saved version (historical/read-only view)
      // can present WITHOUT a visible editor host — the surface shows only the
      // version button plus Save/Publish and no Monaco/textarea. The earlier
      // host-gated restore calls never fire in that state, so attempt the
      // restore here before giving up. This is purely additive recovery: it
      // no-ops when no restore affordance is present.
      await restoreHistoricalScriptVersionIfNeeded(page).catch(() => undefined);
      await dismissSignInModal(page);
      diagnostics = await collectEditorDiagnostics(page);
      if (hasVisibleEditorHost(diagnostics)) {
        tracePageEvent(page, "pine-editor-recovery-ok", `restore-version:${attempt + 1}`);
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
  // The "restore this version" control is itself a reliable signal that the
  // editor is pinned to an older saved version. TradingView has shown this
  // control without the read-only banner text (the surface collapses to just a
  // version button + Save/Publish), so detect on either signal instead of
  // gating solely on the banner text, which is the fragile part.
  const restoreControls = [
    page.getByRole("link", { name: /restore this version/i }),
    page.getByRole("button", { name: /restore this version/i }),
    page.getByText(/restore this version/i),
  ];
  const hasReadOnlyBanner = await hasVisibleLocator(readOnlySignals, 500);
  const hasRestoreControl = hasReadOnlyBanner
    ? true
    : await hasVisibleLocator(restoreControls, 500);
  if (!hasReadOnlyBanner && !hasRestoreControl) {
    return;
  }

  tracePageEvent(
    page,
    "pine-editor-read-only",
    hasReadOnlyBanner ? "historical-version" : "restore-control-only",
  );

  const restored = await clickVisibleWithFallback(
    page,
    restoreControls,
    "pine-editor-restore-version",
    1_500,
    500,
  ).catch(() => false);

  if (restored) {
    await page.waitForTimeout(1_000);
    await dismissSignInModal(page);
  }

  const stillReadOnly =
    (await hasVisibleLocator(readOnlySignals, 500)) ||
    (await hasVisibleLocator(restoreControls, 500));
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
  const clickedClose = await clickVisibleWithFallback(
    page,
    closeCandidates,
    "pine-editor-close",
    1_000,
    400,
    async () => {
      const dialogStillVisible = await dialog.isVisible({ timeout: 250 }).catch(() => true);
      return !dialogStillVisible;
    },
  ).catch(() => false);
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
    const identityNames = openScriptIdentityNames(scriptName);
    const searchNames = resolveOpenScriptSearchNames(scriptName);
    const totalAttempts = Math.max(2, searchNames.length);
    const alreadyOpen = await waitForAnyOpenScriptIdentity(page, identityNames, 750).catch(() => false);
    if (alreadyOpen) {
      tracePageEvent(page, "open-script-identity-current", scriptName);
      return true;
    }

    for (let attempt = 0; attempt < totalAttempts; attempt += 1) {
      const searchName = searchNames[Math.min(attempt, searchNames.length - 1)] ?? scriptName;
      const openedDialog = await openScriptSelectionSurface(page);
      if (!openedDialog) {
        if (attempt === 0) {
          await ensurePineEditor(page).catch(() => undefined);
          await page.waitForTimeout(400);
          continue;
        }
        return false;
      }

      await activateOpenScriptMyScriptsSection(page);
      await fillOpenScriptSearch(page, searchName);

      const clickedScript = await clickVisibleWithFallback(
        page,
        tvSelectors.openScriptRow(page, searchName),
        "open-script-row",
        3_000,
        1_000,
      );
      await page.waitForTimeout(750);

      let dialogStillVisible = await hasVisibleOpenScriptSurface(page, 750);

      if (dialogStillVisible && clickedScript) {
        await doubleClickVisible(page, tvSelectors.openScriptRow(page, searchName), "open-script-row-confirm", 2_000, 1_000);
        dialogStillVisible = await hasVisibleOpenScriptSurface(page, 750);
      }

      if ((!clickedScript || dialogStillVisible)) {
        await page.keyboard.press("ArrowDown").catch(() => undefined);
        await page.keyboard.press("Enter").catch(() => undefined);
        await page.waitForTimeout(1_000);
      }

      const identityVerified = await waitForAnyOpenScriptIdentity(page, identityNames);
      if (identityVerified) {
        if (searchName !== scriptName) {
          tracePageEvent(page, "open-script-legacy-alias", `${scriptName}<=${searchName}`);
        }
        return true;
      }

      tracePageEvent(page, "open-script-identity-retry", `${scriptName}:attempt=${attempt + 1}:search=${searchName}`);
      await page.keyboard.press("Escape").catch(() => undefined);
      await ensurePineEditor(page).catch(() => undefined);
      await page.waitForTimeout(500);
    }

    return false;
  });
}

export async function addExistingScriptToChartViaIndicators(
  page: Page,
  scriptName: string,
): Promise<AddExistingScriptToChartViaIndicatorsResult> {
  return runTrackedStep(page, `addExistingScriptToChartViaIndicators:${scriptName}`, async () => {
    const attempts: AddExistingScriptToChartViaIndicatorsAttempt[] = [];

    for (const searchName of resolveOpenScriptSearchNames(scriptName)) {
      const attempt = await addScriptToChartViaIndicators(page, searchName);
      attempts.push(attempt);

      if (!attempt.addedToChart) {
        continue;
      }

      if (normalizeUiText(searchName) !== normalizeUiText(scriptName)) {
        tracePageEvent(page, "add-existing-script-legacy-alias", `${scriptName}<=${searchName}`);
      }
      return {
        added: true,
        matchedSearchName: searchName,
        attempts,
      };
    }

    return {
      added: false,
      matchedSearchName: null,
      attempts,
    };
  });
}

export async function setEditorContent(page: Page, code: string): Promise<void> {
  // Timeout contract: CI sets TV_STEP_TIMEOUT_MS and leaves the editor-specific
  // env vars unset, so these fallbacks raise slow editor operations with the
  // active step budget while keeping a 90s content floor and 45s prepare floor.
  // Explicit TV_SET_EDITOR_CONTENT_TIMEOUT_MS / TV_EDITOR_PREPARE_TIMEOUT_MS
  // values are operator overrides and intentionally win over the fallback.
  const editorContentTimeoutMs = numEnv("TV_SET_EDITOR_CONTENT_TIMEOUT_MS", Math.max(stepTimeoutMs(), 90_000));
  await runTrackedStep(page, `setEditorContent:${code.length}`, async () => {
    const editorPrepareTimeoutMs = numEnv("TV_EDITOR_PREPARE_TIMEOUT_MS", Math.max(stepTimeoutMs(), 45_000));
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
    }, editorPrepareTimeoutMs);
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
  }, editorContentTimeoutMs);
}

export async function saveScript(page: Page, scriptName: string): Promise<void> {
  await runTrackedStep(page, `saveScript:${scriptName}`, async () => {
    await dismissSignInModal(page);
    const untitledSignals = [
      page.getByText(/^untitled script$/i),
      page.getByRole("button", { name: /^untitled script$/i }),
      page.getByRole("link", { name: /^untitled script$/i }),
    ];
    const resolveSaveDialog = async (timeoutMs = 1_200): Promise<Locator | null> => {
      const directDialog = await findVisibleDialogByText(page, /save script|script name/i, timeoutMs);
      if (directDialog) {
        return directDialog;
      }

      return firstVisibleLocator(
        page.locator('[role="dialog"], [data-name*="dialog" i], [class*="dialog" i], [class*="modal" i]').filter({ hasText: /script name/i }),
        timeoutMs,
      );
    };

    const mod = process.platform === "darwin" ? "Meta" : "Control";
    await page.keyboard.press(`${mod}+S`);
    await page.waitForTimeout(750);

    if (!(await resolveSaveDialog(600))) {
      await page.keyboard.press(`${mod}+Shift+S`).catch(() => undefined);
      await page.waitForTimeout(750);
    }

    for (let attempt = 0; attempt < 3; attempt += 1) {
      const saveDialog = await resolveSaveDialog(1_200);
      const named = saveDialog
        ? await fillFirst(
          scriptName,
          [
            saveDialog.getByRole("textbox", { name: /script name|name|title/i }),
            saveDialog.getByRole("textbox"),
            saveDialog.locator('input[type="text"], input:not([type]), textarea'),
          ],
          1_500,
        )
        : await fillFirst(scriptName, tvSelectors.saveNameInput(page), 1_500);
      if (!named) {
        await page.waitForTimeout(350);
        continue;
      }

      if (saveDialog) {
        const clickedDialogSave = await clickVisibleWithFallback(
          page,
          [
            saveDialog.getByRole("button", { name: /^save$/i }),
            saveDialog.getByRole("button", { name: /save/i }),
            saveDialog.getByText(/^save$/i),
            saveDialog.locator('button:has-text("Save")'),
          ],
          "save-script-dialog",
          1_500,
          750,
        ).catch(() => false);
        if (!clickedDialogSave) {
          await page.keyboard.press("Enter").catch(() => undefined);
        }
      } else {
        const clickedGlobalSave = await clickVisibleWithFallback(
          page,
          [
            ...tvSelectors.saveButtons(page),
            page.getByRole("button", { name: /save/i }),
          ],
          "save-script-global",
          1_500,
          750,
        ).catch(() => false);
        if (!clickedGlobalSave) {
          await page.keyboard.press("Enter").catch(() => undefined);
        }
      }

      await clickVisibleWithFallback(
        page,
        [
          page.getByRole("button", { name: /^yes$/i }),
          page.getByText(/^yes$/i),
          page.getByRole("button", { name: /^ok$/i }),
          page.getByText(/^ok$/i),
        ],
        "save-script-confirm",
        1_000,
        750,
      ).catch(() => false);

      await page.waitForTimeout(1_250);
      const saveDialogStillVisible = Boolean(await resolveSaveDialog(500));
      if (!saveDialogStillVisible) {
        break;
      }
    }

    const finalSaveDialog = await resolveSaveDialog(750);
    if (finalSaveDialog) {
      await clickVisibleWithFallback(
        page,
        [
          finalSaveDialog.getByRole("button", { name: /^save$/i }),
          finalSaveDialog.getByRole("button", { name: /save/i }),
          finalSaveDialog.getByText(/^save$/i),
          finalSaveDialog.locator('button:has-text("Save")'),
        ],
        "save-script-dialog-final",
        1_200,
        500,
      ).catch(() => false);
      await page.keyboard.press("Enter").catch(() => undefined);
      await page.waitForTimeout(1_000);
    }

    await page.waitForTimeout(1_250);
    const saveDialogStillVisible = Boolean(await resolveSaveDialog(500));
    if (saveDialogStillVisible) {
      throw new Error(`Save dialog remained open after save attempts for script: ${scriptName}`);
    }

    await dismissSignInModal(page);

    for (let attempt = 0; attempt < 4; attempt += 1) {
      const dialogStillVisible = Boolean(await resolveSaveDialog(300));
      const identityTexts = await collectOpenScriptIdentityTexts(page, scriptName).catch(() => []);
      const bodyText = await page.locator("body").innerText().catch(() => "");
      const identityEvidence = resolveOpenScriptIdentityEvidence(scriptName, {
        dialogStillVisible,
        editorContextTexts: identityTexts,
        bodyText,
      });
      if (identityEvidence.verified) {
        return;
      }

      const untitledStillVisible = await hasVisibleLocator(untitledSignals, 400);
      if (!untitledStillVisible && identityTexts.some((candidate) => scriptNameAppearsInUiText(scriptName, candidate))) {
        return;
      }

      if (attempt === 1) {
        const reopened = await openExistingScript(page, scriptName).catch(() => false);
        if (reopened) {
          return;
        }
      }

      await page.waitForTimeout(750);
    }

    throw new Error(`Save did not persist script name for ${scriptName}; TradingView did not expose an exact saved-script context`);
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

export async function hasAddToChartClickEffect(page: Page, scriptName?: string): Promise<boolean> {
  const updateOnChartVisible = await hasVisibleLocatorFast([
    page.getByRole("button", { name: /update on chart/i }),
    page.getByText(/update on chart/i),
  ], 250);
  if (updateOnChartVisible) {
    return true;
  }

  const addToChartStillVisible = await hasVisibleLocatorFast(tvSelectors.addToChart(page), 250);
  if (!addToChartStillVisible) {
    return true;
  }

  if (!scriptName) {
    return false;
  }

  const state = await collectVisibleChartScriptState(page, scriptName, {
    locatorTimeoutMs: 150,
    legendButtonLimit: 12,
    legendVisibleTimeoutMs: 80,
    legendAncestorTextTimeoutMs: 120,
  }).catch(() => null);
  return Boolean(state && isScriptVisibleOnChart(state));
}

async function settleChartSurfaceAfterInsert(page: Page, scriptName: string, phase: string, allowTextMatchOnly = true): Promise<boolean> {
  for (let attempt = 0; attempt < 4; attempt += 1) {
    await dismissSignInModal(page);

    // On the first attempt, capture compile errors BEFORE closing the Pine editor
    if (attempt === 0) {
      const editorDiag = await collectEditorDiagnostics(page).catch(() => null);
      if (editorDiag && hasVisibleEditorHost(editorDiag)) {
        tracePageEvent(page, `add-to-chart-${phase}-editor-state`, `${scriptName}:${formatEditorDiagnostics(editorDiag)}`);
      }
    }

    await closePineEditorIfVisible(page);
    if (attempt > 0) {
      await page.keyboard.press("Escape").catch(() => undefined);
    }
    await page.waitForTimeout(700 + attempt * 300);

    const state = await collectVisibleChartScriptState(page, scriptName).catch(() => null);
    tracePageEvent(
      page,
      `add-to-chart-${phase}-settle`,
      `${scriptName}:attempt=${attempt}:${state ? JSON.stringify(state) : "no-state"}`,
    );
    if (state && isScriptVisibleOnChart(state)) {
      return true;
    }
    if (allowTextMatchOnly && state?.hasScriptNameMatch) {
      const diagnostics = await collectEditorDiagnostics(page).catch(() => null);
      if (diagnostics && !hasVisibleEditorHost(diagnostics)) {
        tracePageEvent(page, `add-to-chart-${phase}-text-match-only`, scriptName);
        return true;
      }
    }

    // On the last attempt, dump the button-ancestor chain for diagnostics.
    // Walk up from each legend-settings button and report tag, data-name/class,
    // and innerText at each depth so the correct wrapper level is visible.
    if (attempt === 3) {
      const diagButtons = page.locator('button[data-qa-id="legend-settings-action"]');
      const diagCount = await diagButtons.count().catch(() => 0);
      const diagEntries: string[] = [];
      for (let i = 0; i < Math.min(diagCount, 20); i += 1) {
        const btn = diagButtons.nth(i);
        const btnVisible = await btn.isVisible({ timeout: 200 }).catch(() => false);
        const levels: string[] = [];
        for (const depth of [1, 2, 3, 4, 5]) {
          const xpath = new Array(depth).fill("..").join("/");
          const anc = btn.locator(`xpath=${xpath}`);
          const tag = await anc.evaluate((el) => el.tagName.toLowerCase()).catch(() => "?");
          const dn = await anc.evaluate((el) => el.getAttribute("data-name") || "").catch(() => "");
          const txt = normalizeUiText(await anc.innerText({ timeout: 200 }).catch(() => "")).slice(0, 50);
          levels.push(`d${depth}:${tag}${dn ? `[${dn}]` : ""}="${txt}"`);
        }
        diagEntries.push(`btn[${i}${btnVisible ? "" : ",hidden"}]:{${levels.join(",")}}`);
      }
      tracePageEvent(
        page,
        `add-to-chart-${phase}-legend-dump`,
        `${scriptName}:buttons=${diagCount}:${diagEntries.join(" | ") || "(none)"}`,
      );

      // Also check for TradingView error/notification toasts
      const toastLocator = page.locator(
        '[role="status"], [role="alert"], [aria-live="polite"], [aria-live="assertive"], [data-name*="toast" i], [class*="toast" i], [class*="notification" i]',
      );
      const toastCount = await toastLocator.count().catch(() => 0);
      if (toastCount > 0) {
        const toastTexts: string[] = [];
        for (let i = 0; i < Math.min(toastCount, 5); i += 1) {
          const raw = await toastLocator.nth(i).innerText({ timeout: 300 }).catch(() => "");
          if (raw) {
            toastTexts.push(normalizeUiText(raw).slice(0, 120));
          }
        }
        if (toastTexts.length > 0) {
          tracePageEvent(page, `add-to-chart-${phase}-toasts`, toastTexts.join(" | "));
        } else {
          tracePageEvent(page, `add-to-chart-${phase}-toasts`, `(${toastCount} elements, all empty)`);
        }
      }

      // Additional diagnostic: search for any text containing key parts of the
      // script name on the entire page.  This helps diagnose cases where the
      // script IS on the chart but with a different/truncated display name.
      const nameWords = scriptName.split(/\s+/).filter((w) => w.length > 3);
      if (nameWords.length > 0) {
        const wordPattern = new RegExp(nameWords.map(escapeRegex).join("|"), "i");
        const matchLocator = page.locator(`:text-matches("${nameWords.map(escapeRegex).join("|")}", "i")`);
        const matchCount = await matchLocator.count().catch(() => 0);
        const matchTexts: string[] = [];
        for (let m = 0; m < Math.min(matchCount, 10); m += 1) {
          const mt = normalizeUiText(await matchLocator.nth(m).innerText({ timeout: 200 }).catch(() => ""));
          if (mt && wordPattern.test(mt)) {
            matchTexts.push(mt.slice(0, 80));
          }
        }
        tracePageEvent(
          page,
          `add-to-chart-${phase}-name-search`,
          `${scriptName}:words=${nameWords.join(",")}:matches=${matchCount}:texts=${matchTexts.join(" | ") || "(none)"}`,
        );
      }
    }
  }

  return false;
}

export async function addCurrentScriptToChart(page: Page, scriptName?: string, options: AddToChartOptions = {}): Promise<void> {
  await runTrackedStep(page, "addCurrentScriptToChart", async () => {
    await dismissSignInModal(page);
    if (scriptName && !options.forceInsert) {
      const initialState = await collectVisibleChartScriptState(page, scriptName).catch(() => null);
      if (initialState && isScriptVisibleOnChart(initialState)) {
        tracePageEvent(page, "add-to-chart-already-present", `${scriptName}:${JSON.stringify(initialState)}`);
        return;
      }
    }

    const clicked = await clickVisibleWithFallback(
      page,
      tvSelectors.addToChart(page),
      "add-to-chart",
      2_000,
      2_500,
      scriptName ? async () => hasAddToChartClickEffect(page, scriptName) : undefined,
    );
    if (clicked) {
      if (!scriptName) {
        await dismissSignInModal(page);
        return;
      }

      if (await settleChartSurfaceAfterInsert(page, scriptName, "click", !options.forceInsert)) {
        return;
      }

      tracePageEvent(page, "add-to-chart-click-no-visible-script", scriptName);
    }

    const mod = process.platform === "darwin" ? "Meta" : "Control";
    await ensurePineEditor(page).catch(() => undefined);
    await clickFirst(tvSelectors.editorHosts(page), 1_000).catch(() => false);
    await page.waitForTimeout(150);
    tracePageEvent(page, "add-to-chart-hotkey", `${mod}+Enter`);
    await page.keyboard.press(`${mod}+Enter`).catch(() => undefined);
    await page.waitForTimeout(2_500);
    if (scriptName) {
      if (await settleChartSurfaceAfterInsert(page, scriptName, "hotkey", !options.forceInsert)) {
        tracePageEvent(page, "add-to-chart-visible-after-hotkey", scriptName);
        return;
      }

      const indicatorsAttempt = await addScriptToChartViaIndicators(page, scriptName);
      if (indicatorsAttempt.addedToChart) {
        tracePageEvent(page, "add-to-chart-visible-after-indicators", scriptName);
        return;
      }
    }

    await dismissSignInModal(page);

    const diagnostics = await collectEditorDiagnostics(page).catch(() => undefined);
    if (await isSignInModalVisible(page)) {
      throw new Error("TradingView sign-in modal is blocking add-to-chart");
    }
    const errorMsg = diagnostics
      ? `Could not add script to chart after click, force-click, and hotkey fallback: ${formatEditorDiagnostics(diagnostics)}`
      : 'Could not add script to chart after click, force-click, and hotkey fallback';
    if (options.tolerateFailure) {
      tracePageEvent(page, "add-to-chart-tolerated-failure", `${scriptName ?? "(unnamed)"}:${errorMsg}`);
      return;
    }
    throw new Error(errorMsg);
  });
}

async function openSettingsForScriptOnce(page: Page, scriptName: string): Promise<boolean> {
  await dismissSignInModal(page);
  await closePineEditorIfVisible(page);
  tracePageEvent(page, "script-settings-open-start", scriptName);
  let openedMenu = await openSettingsFromVisibleLegendText(page, scriptName);
  tracePageEvent(page, "script-settings-open-legend-text-result", `${scriptName}:${openedMenu}`);
  if (!openedMenu) {
    openedMenu = await openSettingsFromLegendContainer(page, scriptName);
    tracePageEvent(page, "script-settings-open-legend-result", `${scriptName}:${openedMenu}`);
  }
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
    openedMenu = await openSettingsFromChartSurfaceControls(page, scriptName);
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
    return verifyOpenedSettingsDialogIdentity(page, scriptName, "script-settings-open-visible-dialog");
  }

  await dismissSignInModal(page);
  const clickedSettings = await clickVisibleWithFallback(
    page,
    tvSelectors.settingsAction(page),
    "script-settings-action",
    2_500,
    1_500,
    async () => waitForScriptSettingsInputsSurface(page, 2_000),
  );
  tracePageEvent(page, "script-settings-open-menu-action-result", `${scriptName}:${clickedSettings}`);
  if (clickedSettings) {
    tracePageEvent(page, "script-settings-open-indicator-dialog-after-action", scriptName);
    return verifyOpenedSettingsDialogIdentity(page, scriptName, "script-settings-open-action-dialog");
  }

  await closeModal(page).catch(() => undefined);
  if (!clickedSettings) {
    if (await isSignInModalVisible(page)) {
      throw new Error(`TradingView sign-in modal is blocking settings action for script: ${scriptName}`);
    }
    throw new Error(`Could not open settings for script: ${scriptName}`);
  }

  throw new Error(`Opened generic settings instead of indicator settings for script: ${scriptName}`);
}

export async function openSettingsForScript(
  page: Page,
  scriptName: string,
  options: { allowChartRefresh?: boolean } = {},
): Promise<boolean> {
  const allowChartRefresh = options.allowChartRefresh === true;
  // Both modes retry the settings-menu open once. The open is inherently flaky:
  // the TradingView chart legend races with pointer-intercepting overlays (e.g.
  // the "publish" menu item), so a single attempt fails transiently. The
  // mutating path recovers by destructively refreshing the chart instance; the
  // readonly path (post-release validation) must NOT mutate the chart, so it
  // retries with a non-destructive settle instead. Without a readonly retry a
  // single transient flake hard-failed post-release validation and escalated to
  // a blocking release gate (smc-library-refresh run 628, 2026-06-30).
  const maxAttempts = 2;
  const totalTimeoutMs = allowChartRefresh
    ? Math.max(stepTimeoutMs(), 70_000)
    : Math.max(stepTimeoutMs(), 60_000);

  return runTrackedStep(page, `openSettingsForScript:${scriptName}`, async () => {
    let lastError: unknown;

    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      if (attempt > 0) {
        tracePageEvent(page, "script-settings-open-retry-start", `${scriptName}:attempt=${attempt + 1}`);
        await closeModal(page).catch(() => undefined);
        await dismissSignInModal(page).catch(() => undefined);
        if (allowChartRefresh) {
          const removedCount = await refreshChartScriptInstance(page, scriptName);
          tracePageEvent(page, "script-settings-open-refresh-ok", `${scriptName}:removed=${removedCount}`);
          const visibleAfterRefresh = await isScriptVisibleOnChartSurface(page, scriptName).catch(() => false);
          if (!visibleAfterRefresh) {
            throw new Error(`Script was not visible on chart after refresh before reopening settings: ${scriptName}`);
          }
        } else {
          // Readonly retry: settle the surface and reopen the menu without
          // mutating chart state (no instance refresh / re-add).
          tracePageEvent(page, "script-settings-open-readonly-retry", `${scriptName}:attempt=${attempt + 1}`);
          await page.waitForTimeout(750);
        }
      }

      try {
        tracePageEvent(page, "script-settings-open-attempt-start", `${scriptName}:attempt=${attempt + 1}`);
        const opened = await openSettingsForScriptOnce(page, scriptName);
        if (opened === true) {
          return true;
        }
        throw new Error(`Settings opened for the wrong TradingView script: ${scriptName}`);
      } catch (error: unknown) {
        lastError = error;
        const message = error instanceof Error ? error.message : String(error);
        tracePageEvent(page, "script-settings-open-attempt-error", `${scriptName}:attempt=${attempt + 1}:${message}`);
        await closeModal(page).catch(() => undefined);
      }
    }

    throw lastError instanceof Error
      ? lastError
      : new Error(`Could not open settings for script after retries: ${scriptName}`);
  }, totalTimeoutMs);
}

export async function openInputsTab(page: Page): Promise<void> {
  await runTrackedStep(page, "openInputsTab", async () => {
    const ok = await clickFirst(tvSelectors.inputsTab(page), 2_500);
    if (!ok) {
      throw new Error("Could not open Inputs tab");
    }
  });
}

export async function assertExpectedInputLabels(
  page: Page,
  expectedLabels: string[],
  minCount: number,
): Promise<void> {
  const directIndicatorDialog = await findIndicatorSettingsDialog(page, 750);
  const effectiveDialogs = directIndicatorDialog
    ? [await snapshotDialogAcrossScroll(page, directIndicatorDialog)]
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
    ? [await snapshotDialogAcrossScroll(page, directIndicatorDialog)]
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

    for (const label of extractLikelyInputLabelsFromDialogText(dialogText)) {
      labels.add(label);
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
      // Press Escape first — works even when an overlay blocks pointer events
      await page.keyboard.press("Escape").catch(() => undefined);
      await page.waitForTimeout(200).catch(() => undefined);
      // Then try clicking the close button for dialogs where Escape doesn't dismiss
      await clickFirst(tvSelectors.closeModal(page), 400).catch(() => false);
      await page.waitForTimeout(150).catch(() => undefined);
    },
    3_000,  // increased from 2_000: clickFirst tries 3 locators × 400ms + Escape + waits
  ).catch(() => undefined);
}

export async function publishPrivateScript(
  page: Page,
  options: {
    scriptName?: string;
    title?: string;
    description?: string;
  } = {},
): Promise<{
  noChangeDetected: boolean;
  publishConfirmed: boolean;
  publishSurfaceClosedAfterConfirm: boolean;
  versionContextTexts: string[];
  bodyText: string;
}> {
  await dismissSignInModal(page).catch(() => undefined);
  await ensurePineEditor(page).catch(() => undefined);
  let noChangeDetected = false;

  let clickedPublish = await openPublishSurface(page, 4_000);
  if (!clickedPublish) {
    const compileErrorDetails = await getVisibleCompileErrorDetails(page, 500).catch(() => null);
    if (compileErrorDetails) {
      throw new Error(`Could not open publish flow because TradingView reported a compile error: ${compileErrorDetails}`);
    }
    throw new Error("Could not open publish flow");
  }

  if (await hasPublishAddToChartGate(page, 750)) {
    tracePageEvent(page, "publish-gate", "script-not-on-chart");

    // Try clicking the "Add to chart" button inside the dialog first (works for libraries)
    const dialogAddButton = page
      .locator('#overlap-manager-root [role="dialog"], #overlap-manager-root [data-id], #overlap-manager-root [data-name*="dialog" i], #overlap-manager-root [class*="dialog" i], #overlap-manager-root [class*="modal" i]')
      .filter({ hasText: /script is not on the chart/i })
      .locator('button, [role="button"]')
      .filter({ hasText: /add to chart/i });
    const clickedDialogAdd = await clickFirst([dialogAddButton], 1_500).catch(() => false);
    tracePageEvent(page, "publish-gate-dialog-add", `clicked=${clickedDialogAdd}`);
    if (clickedDialogAdd) {
      await page.waitForTimeout(2_000);
    } else {
      // Dismiss the dialog first, then force-add the script
      await page.keyboard.press("Escape").catch(() => undefined);
      await page.waitForTimeout(500);
      await addCurrentScriptToChart(page, options.scriptName, { forceInsert: true });
      await page.waitForTimeout(1_500);
    }

    // Re-open Pine editor (addCurrentScriptToChart may have closed it)
    await ensurePineEditor(page).catch(() => undefined);
    await page.waitForTimeout(500);

    clickedPublish = await openPublishSurface(page, 4_000);
    if (!clickedPublish) {
      const compileErrorDetails = await getVisibleCompileErrorDetails(page, 500).catch(() => null);
      if (compileErrorDetails) {
        throw new Error(`Could not reopen publish flow after adding script to chart because TradingView reported a compile error: ${compileErrorDetails}`);
      }
      throw new Error("Could not reopen publish flow after adding script to chart");
    }
  }

  await page.waitForTimeout(750);
  const openSurfaceBodyText = await page.locator("body").innerText().catch(() => "");

  if (options.title) {
    await fillFirst(options.title, tvSelectors.publishTitleInput(page), 1_000);
  }

  if (options.description) {
    await fillFirst(options.description, tvSelectors.publishDescriptionInput(page), 1_000);
  }

  for (let stepIndex = 0; stepIndex < 8; stepIndex += 1) {
    const continued = await clickVisibleWithFallback(
      page,
      tvSelectors.publishContinue(page),
      `publish-continue-${stepIndex}`,
      2_000,
      1_000,
    );
    if (!continued) {
      break;
    }

    if (await handlePublishNoChangeDialog(page, 750)) {
      noChangeDetected = true;
      await ensurePineEditor(page).catch(() => undefined);
      return {
        noChangeDetected,
        publishConfirmed: false,
        publishSurfaceClosedAfterConfirm: false,
        versionContextTexts: [],
        bodyText: await page.locator("body").innerText().catch(() => ""),
      };
    }
  }

  const confirmed = await clickVisibleWithFallback(
    page,
    tvSelectors.confirmPublish(page),
    "publish-confirm",
    4_000,
    1_000,
  );
  if (!confirmed) {
    // Re-check for "Script is not on the chart" gate that may have appeared after the initial surface detection
    if (await hasPublishAddToChartGate(page, 500)) {
      tracePageEvent(page, "publish-gate-late", "script-not-on-chart");
      const dialogAddButton = page
        .locator('#overlap-manager-root [role="dialog"], #overlap-manager-root [data-id], #overlap-manager-root [data-name*="dialog" i], #overlap-manager-root [class*="dialog" i], #overlap-manager-root [class*="modal" i]')
        .filter({ hasText: /script is not on the chart/i })
        .locator('button, [role="button"]')
        .filter({ hasText: /add to chart/i });
      const clickedDialogAdd = await clickFirst([dialogAddButton], 1_500).catch(() => false);
      tracePageEvent(page, "publish-gate-late-dialog-add", `clicked=${clickedDialogAdd}`);
      if (clickedDialogAdd) {
        await page.waitForTimeout(2_000);
      } else {
        await page.keyboard.press("Escape").catch(() => undefined);
        await page.waitForTimeout(500);
        await addCurrentScriptToChart(page, options.scriptName, { forceInsert: true });
        await page.waitForTimeout(1_500);
      }
      // Re-open Pine editor (addCurrentScriptToChart may have closed it)
      await ensurePineEditor(page).catch(() => undefined);
      await page.waitForTimeout(500);
      // Retry the full publish flow after resolving the gate
      const retryResult = await publishPrivateScript(page, options);
      return retryResult;
    }

    if (await handlePublishNoChangeDialog(page, 750)) {
      noChangeDetected = true;
      await ensurePineEditor(page).catch(() => undefined);
      return {
        noChangeDetected,
        publishConfirmed: false,
        publishSurfaceClosedAfterConfirm: false,
        versionContextTexts: [],
        bodyText: await page.locator("body").innerText().catch(() => ""),
      };
    }
    throw new Error("Could not confirm TradingView publish flow after the publish surface opened");
  }

  const evidence = await capturePublishConfirmationEvidence(page, options.scriptName, 12_000);
  return {
    noChangeDetected,
    publishConfirmed: true,
    publishSurfaceClosedAfterConfirm: evidence.publishSurfaceClosed,
    versionContextTexts: evidence.versionContextTexts,
    bodyText: evidence.bodyText || openSurfaceBodyText,
  };
}

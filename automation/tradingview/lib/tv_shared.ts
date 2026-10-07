import { randomUUID } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { NobleCryptoPlugin, ScureBase32Plugin, generateSync } from "otplib";
import {
  chromium,
  type Browser,
  type BrowserContext,
  type LaunchOptions,
  type Locator,
  type Page,
} from "playwright";

import { tvSelectors, type PineDraftKind } from "../selectors.js";
import { saveChartLayout } from "./tv_layout_save.js";
import { normalizedPineSha256 } from "./tv_consumer_rollout_evidence.js";
import {
  chartIntervalDisplayLabel,
  clipboardReadbackProvesWrite,
  type ChartStateSnapshot,
} from "./tv_validation_model.js";
import {
  inspectTradingViewStorageState,
  resolveTradingViewAuthResolution,
  type DataWindowItem,
  type TradingViewAuthResolution,
  type TradingViewStorageStateInspection,
} from "./tv_validation_model.js";
import { TradingViewRuntimeErrorMonitor } from "./tv_runtime_errors.js";

export type TradingViewSession = {
  browser: Browser;
  context: BrowserContext;
  page: Page;
  authResolution: TradingViewAuthResolution;
  runtimeErrors: TradingViewRuntimeErrorMonitor;
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

export type TradingViewStorageCaptureWaitAction =
  | "wait"
  | "navigate_to_login"
  | "navigate_to_chart"
  | "complete";

/** TradingView serves every interactive login surface under /accounts/. */
function isTradingViewAuthSurface(url: string): boolean {
  return /\/accounts\//i.test(url);
}

export function resolveTradingViewStorageCaptureWaitAction(input: {
  url: string;
  signInSignals: boolean;
  authenticated: boolean;
  storageLooksAuthenticated: boolean;
  persistentProfile: boolean;
  /**
   * Server-confirmed anonymous session (not merely "no positive auth evidence
   * yet"). Optional so existing callers keep their previous behaviour.
   */
  explicitlyAnonymous?: boolean;
  /**
   * RAW DOM evidence that a login form is on screen. Deliberately separate from
   * `signInSignals`, which the capture script ORs with "session is anonymous" —
   * that conflated flag is true for every anonymous page and would suppress the
   * login navigation entirely.
   */
  loginFormVisible?: boolean;
}): TradingViewStorageCaptureWaitAction {
  const authenticatedSession =
    !input.signInSignals
    && input.authenticated
    && (input.storageLooksAuthenticated || input.persistentProfile);
  if (authenticatedSession) {
    return input.url.includes("/chart") ? "complete" : "navigate_to_chart";
  }

  // A persistent profile whose session expired (or was never minted) lands on
  // the chart URL, where TradingView shows no login form. Polling it until the
  // timeout looks identical to "operator is still typing", so send the operator
  // to the login page once. Only on a SERVER-CONFIRMED anonymous session:
  // storage heuristics accept a guest `sessionid`/`device_t` as authenticated,
  // so they cannot gate this. The raw login-form check and the /accounts/ check
  // keep the navigation from fighting a form that is already on screen.
  if (
    input.explicitlyAnonymous === true
    && !input.loginFormVisible
    && !isTradingViewAuthSurface(input.url)
  ) {
    return "navigate_to_login";
  }

  return "wait";
}

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

export type VisibleDialogSnapshot = {
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
  // Override for the tracked-step timeout. The refresh path passes the same
  // 90s floor as its outer wrapper: a healthy insertion was observed at 44s,
  // and the default 45s inner timer closed the session right after
  // (documented in refreshChartScriptInstance; live run 29929470730).
  stepTimeoutMs?: number;
};

// Pure helper for the producer chart-instance refresh: the applied Suite
// instance lives in EVERY layout that carries consumers, so the refresh must
// cover the primary layout plus every distinct per-target chartUrl. The
// 2026-07-22 live run refreshed only primaryChartUrl (desktop) while the
// operator watched the Mobile layout — the visible instance stayed frozen.
export function resolveProducerRefreshChartUrls(config: {
  primaryChartUrl: string;
  verifyTargets: Array<{ chartUrl?: string }>;
}): string[] {
  const urls = [config.primaryChartUrl];
  for (const target of config.verifyTargets) {
    if (target.chartUrl && !urls.includes(target.chartUrl)) urls.push(target.chartUrl);
  }
  return urls;
}

/** The consumer instances a save-then-rebind rollout must RE-APPLY.
 *
 * Saving a consumer's source does not touch the instance already applied to a
 * layout: TradingView keeps it on the version it was added with, which is the
 * whole reason the producer gets re-applied after a save. The consumer never
 * was, so one whose own source GAINED an input kept a stale instance — its new
 * rows do not exist in the settings dialog and the rebind dies with "Source
 * combobox not found" (runs 30694013096, 30696257671, 30698519321, all on
 * CTX SessionMssBull after #4263 appended two channels).
 *
 * Only consumers whose source this run actually saved are returned: an
 * untouched instance cannot have gained an input, and re-applying it would
 * drop healthy bindings for nothing. The producer is excluded — it has its own
 * pass, and refreshing it here would strip the bindings a second time.
 */
export function resolveConsumerRefreshTargets(config: {
  producerName: string;
  primaryChartUrl: string;
  saveTargets: ReadonlyArray<{ scriptName: string }>;
  verifyTargets: ReadonlyArray<{ scriptName: string; chartUrl?: string }>;
}): Array<{ scriptName: string; chartUrl: string }> {
  const saved = new Set(config.saveTargets.map((target) => target.scriptName));
  const out: Array<{ scriptName: string; chartUrl: string }> = [];
  const seen = new Set<string>();

  for (const target of config.verifyTargets) {
    if (target.scriptName === config.producerName) continue;
    if (!saved.has(target.scriptName)) continue;
    const chartUrl = target.chartUrl ?? config.primaryChartUrl;
    const key = `${target.scriptName}\u0000${chartUrl}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ scriptName: target.scriptName, chartUrl });
  }
  return out;
}

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

/** Viewport shared by every TradingView session (persistent-profile and storage-state). */
export const TRADINGVIEW_SESSION_VIEWPORT = { width: 1600, height: 1200 } as const;

/**
 * Viewport of a session: TRADINGVIEW_SESSION_VIEWPORT unless TV_SESSION_VIEWPORT="<w>x<h>"
 * is set. Opt-in for local read flows on multi-chart layouts: vWgAWyfC's left chart is
 * 293 of 1292 px wide at the default (2026-10-06), too narrow for its legend to stay
 * clickable. CI keeps the default (Xvfb screen size, create_tradingview_storage_state.ts).
 */
export function resolveSessionViewport(env: NodeJS.ProcessEnv = process.env): { width: number; height: number } {
  const raw = env.TV_SESSION_VIEWPORT?.trim();
  if (!raw) return { ...TRADINGVIEW_SESSION_VIEWPORT };
  const m = raw.match(/^(\d{3,5})x(\d{3,5})$/);
  if (!m) throw new Error(`TV_SESSION_VIEWPORT must look like 2400x1200, got: ${raw}`);
  return { width: Number(m[1]), height: Number(m[2]) };
}

export function resolveTradingViewLaunchOptions(env: NodeJS.ProcessEnv = process.env): LaunchOptions {
  const launchOptions: LaunchOptions = {
    headless: resolveTradingViewHeadlessDefault(env),
  };
  const executablePath = (env.TV_CHROMIUM_EXECUTABLE_PATH || "").trim();
  const channel = (env.TV_BROWSER_CHANNEL || "").trim();

  if (executablePath && channel) {
    throw new Error(
      "TV_CHROMIUM_EXECUTABLE_PATH and TV_BROWSER_CHANNEL are mutually exclusive — unset one of them "
      + "(see docs/tradingview-storage-state-capture-runbook.md, section \"Browser selection\").",
    );
  }

  if (executablePath) {
    launchOptions.executablePath = executablePath;
  } else if (channel) {
    // Playwright types `channel` as plain string and validates the value at launch
    // time; launchWithTradingViewFallback ties launch errors back to TV_BROWSER_CHANNEL
    // so a bogus value is attributable to the env var that supplied it.
    launchOptions.channel = channel;
  }

  return launchOptions;
}

/** Names the env var (or default) that selected the browser, for attributable errors. */
export function describeTradingViewLaunchTarget(launchOptions: LaunchOptions): string {
  // Name the selector value AND both possible sources: the helper only sees the
  // final options, so it cannot tell an env var from a caller override — naming a
  // single env var would mislead when the value actually came from an override.
  if (launchOptions.executablePath) {
    return `executablePath "${launchOptions.executablePath}" (TV_CHROMIUM_EXECUTABLE_PATH or a caller override)`;
  }
  if (launchOptions.channel) {
    return `channel "${launchOptions.channel}" (TV_BROWSER_CHANNEL or a caller override)`;
  }
  return "Playwright bundled chromium";
}

const MISSING_BROWSER_ERROR_MARKERS = [
  // Playwright registry: browser not downloaded (covers the docker-image variant too).
  // Deliberately NOT "npx playwright install": that is a substring of Playwright's
  // missing-OS-deps remedy "npx playwright install-deps" — a different failure
  // (browser IS installed) with a different fix, which must propagate untouched.
  "Executable doesn't exist",
  // Second independent marker so a reword of the phrase above still classifies. This
  // download remedy is emitted only for a missing browser; the missing-OS-deps error
  // says "install them", never "download new browsers", so it stays unmatched.
  "download new browsers",
] as const;

export function isMissingBrowserExecutableError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error);
  return MISSING_BROWSER_ERROR_MARKERS.some((marker) => message.includes(marker));
}

/**
 * Launch bound for the last-ditch system-Chrome fallback. Playwright's default is
 * 180s, which it spends waiting on a Chrome that already started but never answers
 * the CDP handshake (an arm64 Chrome 150 against the pinned Playwright 1.55 does
 * exactly this). Unbounded, every browser-backed test in `npm run tv:test` burned
 * that full timeout — 25 uniform ~210s failures whose messages said "Timeout
 * 180000ms exceeded" and never once named the actually-missing pinned browser.
 * A launch that has not connected in 30s is not going to; failing fast surfaces
 * the real remedy instead of a 90-minute suite of misleading timeouts.
 */
export const CHROME_CHANNEL_FALLBACK_TIMEOUT_MS = 30_000;

export type TradingViewLaunchFallbackOptions = {
  /**
   * Whether a missing bundled chromium may fall back to the system Chrome channel.
   * MUST be false for launches that own a persistent browser profile: opening the
   * long-lived TradingView auth profile with a different browser build cross-
   * contaminates its version (Chrome mints/migrates what bundled Chromium later
   * reopens), silently invalidating the stored login.
   */
  fallbackToChromeChannel: boolean;
  log?: (message: string) => void;
};

/**
 * Launch a browser (or persistent context) with fail-loud semantics:
 * - env-selected browsers (TV_CHROMIUM_EXECUTABLE_PATH / TV_BROWSER_CHANNEL) never
 *   fall back; their errors are wrapped to name the env var that chose the target;
 * - only a missing bundled chromium triggers the chrome-channel fallback (any other
 *   error — timeout, profile lock, sandbox — propagates untouched so the root cause
 *   is never masked), and the fallback is logged;
 * - every wrapped error chains the original via `cause`.
 */
export async function launchWithTradingViewFallback<T>(
  launch: (options: LaunchOptions) => Promise<T>,
  launchOptions: LaunchOptions,
  { fallbackToChromeChannel, log = (message) => console.warn(message) }: TradingViewLaunchFallbackOptions,
): Promise<T> {
  // Enforce the at-most-one invariant on the FINAL options: caller overrides can
  // recombine what resolveTradingViewLaunchOptions' env-level check cannot see
  // (Playwright would silently prefer executablePath and the error attribution
  // below would name an env var that never supplied the value).
  if (launchOptions.executablePath && launchOptions.channel) {
    throw new Error(
      "Browser launch options carry BOTH executablePath and channel — they are mutually exclusive "
      + "(from TV_CHROMIUM_EXECUTABLE_PATH / TV_BROWSER_CHANNEL or caller overrides); unset one.",
    );
  }
  try {
    return await launch(launchOptions);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (launchOptions.executablePath || launchOptions.channel) {
      throw new Error(
        `Browser launch failed for ${describeTradingViewLaunchTarget(launchOptions)}: ${message}`,
        { cause: error },
      );
    }
    if (!isMissingBrowserExecutableError(error)) {
      throw error;
    }
    if (!fallbackToChromeChannel) {
      throw new Error(
        "Playwright bundled chromium is not installed and this launch owns a persistent browser profile, "
        + "so it will not silently fall back to system Chrome (a different browser build would corrupt the profile). "
        + "Run `npx playwright install chromium` to open the EXISTING profile. To use system Chrome instead, delete "
        + "the profile dir and re-create it from scratch with TV_BROWSER_CHANNEL=chrome — reopening a chromium-minted "
        + `profile under Chrome corrupts it, so it is never a drop-in. Original error: ${message.split("\n")[0]}`,
        { cause: error },
      );
    }
    log(
      `[tv-launch] Playwright bundled chromium unavailable (${message.split("\n")[0]}); `
      + "falling back to channel \"chrome\". Run `npx playwright install chromium` to use the pinned browser.",
    );
    try {
      // Bounded: an explicit caller timeout still wins, otherwise the fallback gets
      // CHROME_CHANNEL_FALLBACK_TIMEOUT_MS instead of Playwright's 180s default.
      return await launch({
        ...launchOptions,
        channel: "chrome",
        timeout: launchOptions.timeout ?? CHROME_CHANNEL_FALLBACK_TIMEOUT_MS,
      });
    } catch (fallbackError) {
      const fallbackMessage = fallbackError instanceof Error ? fallbackError.message : String(fallbackError);
      // Preserve the fallback failure's FULL detail via the log channel — the thrown
      // error keeps cause = original (the actionable root cause), so without this
      // log the reason system Chrome also failed would be truncated to one line.
      log(`[tv-launch] chrome-channel fallback also failed:\n${fallbackMessage}`);
      throw new Error(
        "Bundled chromium is missing AND the chrome-channel fallback failed. Run `npx playwright install chromium`. "
        + `Original: ${message.split("\n")[0]} | Fallback: ${fallbackMessage.split("\n")[0]}`,
        { cause: error },
      );
    }
  }
}

/**
 * Merge caller overrides onto the env-resolved defaults with correct browser-
 * selector precedence: an override naming EITHER selector (executablePath / channel)
 * replaces BOTH env-derived selectors, so an explicit call-site choice wins instead
 * of recombining with an env selector into the mutually-exclusive both-set state
 * (which would otherwise hard-error at launch even though the caller was explicit).
 */
export function mergeTradingViewLaunchOverrides(base: LaunchOptions, overrides: LaunchOptions): LaunchOptions {
  if (overrides.executablePath == null && overrides.channel == null) {
    return { ...base, ...overrides };
  }
  const merged: LaunchOptions = { ...base, ...overrides };
  // Exactly one selector survives — whichever the override named (leaving both set
  // when the override itself names both, so the at-most-one guard still fires).
  merged.executablePath = overrides.executablePath;
  merged.channel = overrides.channel;
  return merged;
}

/** Standard TradingView chromium launch honouring TV_CHROMIUM_EXECUTABLE_PATH / TV_BROWSER_CHANNEL. */
export async function launchTradingViewChromium(
  overrides: LaunchOptions = {},
  env: NodeJS.ProcessEnv = process.env,
): Promise<Browser> {
  return launchWithTradingViewFallback(
    (options) => chromium.launch(options),
    mergeTradingViewLaunchOverrides(resolveTradingViewLaunchOptions(env), overrides),
    { fallbackToChromeChannel: true },
  );
}

/**
 * Persistent-profile launch: NEVER falls back to another browser build — a
 * different build opening the long-lived TradingView auth profile corrupts its
 * version (see TradingViewLaunchFallbackOptions). Using this helper instead of
 * spelling the boolean makes the wrong pairing unwritable at call sites.
 */
export async function launchTradingViewPersistentContext(
  userDataDir: string,
  launchOptions: LaunchOptions,
  viewport: { width: number; height: number },
): Promise<BrowserContext> {
  return launchWithTradingViewFallback(
    (options) => chromium.launchPersistentContext(userDataDir, { ...options, viewport }),
    launchOptions,
    { fallbackToChromeChannel: false },
  );
}

export function utcNow(): string {
  return new Date().toISOString();
}

export function readJson<T>(filePath: string): T {
  return JSON.parse(fs.readFileSync(filePath, "utf-8")) as T;
}

/**
 * Write JSON via a same-directory temp file + rename, never in place.
 *
 * A plain writeFileSync truncates first and fills afterwards: a crash (or the
 * 30-minute job timeout) between the two leaves a half-written file behind.
 * For the throwaway reports that is cosmetic — for the COMMITTED hand-lib
 * release manifest it is not: `recordHandLibRelease` read-merges the file on
 * every publish, so a torn write turns the next verified publish into a
 * JSON.parse failure and reports it failed (2026-08-15 review, Minor #7).
 * rename() within one directory is atomic on POSIX; readers see the old
 * bytes or the new bytes, never a mix. Same shape as
 * `writePrivateJsonAtomic` below, without the owner-only permission bits —
 * these files are committed artifacts, not credentials.
 */
export function writeJson(filePath: string, payload: unknown): void {
  const parent = path.dirname(filePath);
  fs.mkdirSync(parent, { recursive: true });
  const temporaryPath = path.join(parent, `.${path.basename(filePath)}.${randomUUID()}.tmp`);
  try {
    fs.writeFileSync(temporaryPath, JSON.stringify(payload, null, 2) + "\n", {
      encoding: "utf-8",
      flag: "wx",
    });
    fs.renameSync(temporaryPath, filePath);
  } finally {
    fs.rmSync(temporaryPath, { force: true });
  }
}

/**
 * Atomically replace a credential-bearing JSON file with owner-only
 * permissions. The temporary file lives beside the destination so rename()
 * cannot cross filesystems.
 */
export function writePrivateJsonAtomic(filePath: string, payload: unknown): void {
  const parent = path.dirname(filePath);
  fs.mkdirSync(parent, { recursive: true });
  const temporaryPath = path.join(parent, `.${path.basename(filePath)}.${randomUUID()}.tmp`);
  try {
    fs.writeFileSync(
      temporaryPath,
      JSON.stringify(payload, null, 2) + "\n",
      { encoding: "utf-8", flag: "wx", mode: 0o600 },
    );
    fs.chmodSync(temporaryPath, 0o600);
    fs.renameSync(temporaryPath, filePath);
    fs.chmodSync(filePath, 0o600);
  } finally {
    fs.rmSync(temporaryPath, { force: true });
  }
}

export type ExclusiveFileLock = {
  owner: string;
  path: string;
  release: () => void;
};

/**
 * Acquire a fail-closed, owner-labelled lock for a local TradingView capture.
 *
 * The lock is deliberately not auto-stolen: after a crash, an operator must
 * first establish that no capture still owns the account session and then
 * remove the stale lock. A random token prevents an old process from deleting
 * a newer lock if somebody manually removes/replaces the file.
 */
export function acquireExclusiveFileLock(
  lockPath: string,
  owner: string,
): ExclusiveFileLock {
  const resolvedPath = path.resolve(lockPath);
  const parent = path.dirname(resolvedPath);
  fs.mkdirSync(parent, { recursive: true });
  const token = randomUUID();
  const payload = {
    owner,
    pid: process.pid,
    acquiredAt: new Date().toISOString(),
    token,
  };

  try {
    fs.writeFileSync(
      resolvedPath,
      JSON.stringify(payload, null, 2) + "\n",
      { encoding: "utf-8", flag: "wx", mode: 0o600 },
    );
    fs.chmodSync(resolvedPath, 0o600);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EEXIST") {
      throw error;
    }
    let currentOwner = "unknown";
    try {
      const current = JSON.parse(fs.readFileSync(resolvedPath, "utf-8")) as { owner?: unknown };
      if (typeof current.owner === "string" && current.owner.trim()) {
        currentOwner = current.owner.trim();
      }
    } catch {
      // The existence of an unreadable lock is still a lock; fail closed.
    }
    throw new Error(
      `TradingView capture lock is already held by ${currentOwner}: ${resolvedPath}. `
      + "If the previous capture crashed, verify that no capture process is running before removing the stale lock.",
    );
  }

  let released = false;
  return {
    owner,
    path: resolvedPath,
    release: () => {
      if (released) {
        return;
      }
      released = true;
      try {
        const current = JSON.parse(fs.readFileSync(resolvedPath, "utf-8")) as { token?: unknown };
        if (current.token === token) {
          fs.rmSync(resolvedPath);
        }
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
          console.warn(
            `[tv-auth] Could not release capture lock ${resolvedPath}: `
            + `${error instanceof Error ? error.message : String(error)}`,
          );
        }
      }
    },
  };
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

// TradingView's sign-in page renders social buttons + an "Email" chooser and
// creates the identifier input only once that chooser is clicked. Probed live
// 2026-07-28: 0 matching inputs on load, buttons ["Show more options", "Email"],
// input visible immediately after the click.
export const TV_LOGIN_IDENTIFIER_SELECTOR =
  'input[name="id_username"], input[name="username"], input[type="email"], '
  + 'input[placeholder*="email" i], input[placeholder*="username" i]';

const TV_LOGIN_EMAIL_CHOOSER_SELECTOR =
  'button:has-text("Email"), span[role="button"]:has-text("Email"), '
  + 'div[role="button"]:has-text("Email")';

/**
 * Make the e-mail/username field available for an automated login.
 *
 * Returns true when the identifier input is visible afterwards. Callers must
 * NOT wait on the input first: until 2026-07-28 the headless-login fallback did
 * exactly that, burned its 10 s timeout on an element TradingView had not
 * created yet, and fell through to the interactive branch — which on CI can
 * only time out. Reveal first, then fill.
 */
export async function revealEmailLoginField(
  page: Page,
  revealTimeoutMs = 5_000,
): Promise<boolean> {
  const identifier = page.locator(TV_LOGIN_IDENTIFIER_SELECTOR).first();
  if (await identifier.isVisible().catch(() => false)) {
    return true;
  }

  const chooser = page.locator(TV_LOGIN_EMAIL_CHOOSER_SELECTOR).first();
  if (await chooser.isVisible().catch(() => false)) {
    await chooser.click({ timeout: revealTimeoutMs }).catch(() => undefined);
    try {
      await identifier.waitFor({ state: "visible", timeout: revealTimeoutMs });
      return true;
    } catch {
      // fall through to the "more options" retry below
    }
  }

  // Some layouts hide the e-mail chooser behind "Show more options".
  const moreOptions = page
    .locator('button:has-text("Show more options"), button:has-text("More options")')
    .first();
  if (await moreOptions.isVisible().catch(() => false)) {
    await moreOptions.click({ timeout: revealTimeoutMs }).catch(() => undefined);
    if (await chooser.isVisible().catch(() => false)) {
      await chooser.click({ timeout: revealTimeoutMs }).catch(() => undefined);
    }
  }

  return await identifier.isVisible().catch(() => false);
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

// ── TradingView 2FA (one-time code) entry ──────────────────────────────────
//
// The headless fallback reached the 2FA step for the first time on 2026-07-28
// (run 30341257192, after #4140 unblocked the login form) and then looped:
// "TOTP code generated — filling 2FA field automatically." 32 times in 180 s
// with no submit and no error. `fill(token)` wrote the whole 6-digit code into
// the FIRST matching input; a per-digit OTP layout caps each box at one char,
// so the read-back never reached 6 and the caller's `hasLikelyCode` guard
// skipped every submit candidate — filling forever, submitting never.

/** Inputs that plausibly hold a one-time code, most specific first. */
export const TV_OTP_FIELD_SELECTOR =
  'input[autocomplete="one-time-code"], input[inputmode="numeric"], '
  + 'input[name*="code" i], input[placeholder*="code" i], input[type="tel"]';

export type OtpEntryPlan = {
  /** Digits go into separate single-character boxes. */
  perBox: boolean;
  /** The layout can hold the whole code at all. */
  usable: boolean;
  reason: string;
};

/**
 * Decide how a code of `codeLength` digits has to be entered.
 *
 * Pure so the decision is pinned by a browserless test — the DOM interaction
 * around it is thin on purpose.
 */
export function planOtpEntry(
  fields: { maxLength: number }[],
  codeLength: number,
): OtpEntryPlan {
  if (fields.length === 0) {
    return { perBox: false, usable: false, reason: "no_code_field" };
  }

  // maxLength is -1 / 524288 when unset, so only a genuinely small cap counts.
  const singleCharBoxes = fields.filter(
    (field) => field.maxLength === 1,
  ).length;
  if (singleCharBoxes >= codeLength) {
    return { perBox: true, usable: true, reason: "per_box_inputs" };
  }
  if (singleCharBoxes > 0) {
    return {
      perBox: true,
      usable: false,
      reason: `per_box_inputs_short:${singleCharBoxes}/${codeLength}`,
    };
  }

  const first = fields[0];
  const capacity = first.maxLength > 0 ? first.maxLength : Number.MAX_SAFE_INTEGER;
  if (capacity < codeLength) {
    return {
      perBox: false,
      usable: false,
      reason: `single_field_too_small:${capacity}/${codeLength}`,
    };
  }
  return { perBox: false, usable: true, reason: "single_field" };
}

/** A code counts as entered only when every digit landed somewhere. */
export function isOtpEntryComplete(
  observed: string,
  expected: string,
): boolean {
  return observed.replace(/\s+/g, "") === expected;
}

export type TotpTelemetryResolution = {
  entered: boolean;
  submitted: boolean;
  inferredFromAuthenticatedSession: boolean;
};

export const TOTP_AUTH_INFERENCE_MAX_LAG_MS = 15_000;

/**
 * Reconcile TOTP telemetry when the provider auto-submits and clears its code
 * field before Playwright can read it back.
 *
 * Dispatch alone is not proof of success. Only authentication observed shortly
 * after that dispatch can promote an unobservable entry to entered+submitted;
 * the time bound prevents a later manual login from claiming an older attempt.
 */
export function resolveTotpTelemetry(input: {
  inputDispatchedAtMs?: number;
  entryObserved: boolean;
  submitDispatched: boolean;
  authenticated: boolean;
  authenticatedAtMs?: number;
  maxInferenceLagMs?: number;
}): TotpTelemetryResolution {
  const maxInferenceLagMs =
    input.maxInferenceLagMs ?? TOTP_AUTH_INFERENCE_MAX_LAG_MS;
  const inferenceLagMs =
    input.inputDispatchedAtMs !== undefined
    && input.authenticatedAtMs !== undefined
      ? input.authenticatedAtMs - input.inputDispatchedAtMs
      : undefined;
  const authenticatedAfterDispatch =
    input.authenticated
    && inferenceLagMs !== undefined
    && inferenceLagMs >= 0
    && inferenceLagMs <= maxInferenceLagMs;
  return {
    entered: input.entryObserved || authenticatedAfterDispatch,
    submitted: input.submitDispatched || authenticatedAfterDispatch,
    inferredFromAuthenticatedSession:
      authenticatedAfterDispatch && (!input.entryObserved || !input.submitDispatched),
  };
}

/** Return the TOTP time-step number for deterministic retry de-duplication. */
export function totpTimeStep(nowMs: number, periodSeconds = 30): number {
  if (!Number.isFinite(nowMs) || !Number.isFinite(periodSeconds) || periodSeconds <= 0) {
    throw new Error("TOTP time-step inputs must be finite and periodSeconds must be positive");
  }
  return Math.floor(nowMs / (periodSeconds * 1_000));
}

/** Generate the current 6-digit TOTP for a Base32 secret.
 *
 * Lives here rather than at the call site so it can be pinned against the
 * RFC 6238 vectors. It was inline in `scripts/create_tradingview_storage_state.ts`
 * as `authenticator.generate(secret)` until 2026-08-05, when the otplib 12 -> 13
 * bump (#4445, an npm-all group update) removed the `authenticator` export
 * outright. The next scheduled `tradingview-storage-refresh` run died on the
 * import before a browser ever started, and its failure issue asked for a manual
 * cookie refresh -- a fix for a problem that did not exist.
 *
 * Two things about v13 that a naive migration gets wrong, both pinned by
 * `tv_totp_token.test.ts`:
 *   - the plugins are classes, so they must be instantiated, not called;
 *   - `epoch` is SECONDS here and was MILLISECONDS in v12. Passing ms yields
 *     confident, well-formed, wrong codes -- which against a live 2FA prompt
 *     looks exactly like a bad secret.
 */
export function generateTotpToken(
  secret: string,
  options: { epochSeconds?: number; digits?: number } = {},
): string {
  const { epochSeconds, digits = 6 } = options;
  return generateSync({
    strategy: "totp",
    secret,
    base32: new ScureBase32Plugin(),
    crypto: new NobleCryptoPlugin(),
    digits,
    ...(epochSeconds === undefined ? {} : { epoch: epochSeconds }),
  });
}

/** A TOTP may be entered/submitted at most once in a given time-step. */
export function shouldAttemptTotp(
  lastAttemptedStep: number | undefined,
  nowMs: number,
  periodSeconds = 30,
): { attempt: boolean; step: number } {
  const step = totpTimeStep(nowMs, periodSeconds);
  return { attempt: lastAttemptedStep !== step, step };
}

/** Raw shape collected from the DOM for one potentially-actionable node. */
export type ActionableNode = {
  tag: string;
  type?: string;
  role?: string;
  className?: string;
  text?: string;
  visible: boolean;
};

/**
 * Compact, log-safe inventory of what could submit a form.
 *
 * Run 30343856471 reported `buttons on page: []` on TradingView's 2FA step:
 * neither `button` nor `[role="button"]` existed, so the submit-candidate list
 * could not match by construction. Naming the actual control needs a wider net
 * than "button", and a bounded one — this runs inside a 180 s poll loop.
 */
export function summariseActionableNodes(
  nodes: ActionableNode[],
  limit = 15,
): string[] {
  return nodes
    .filter((node) => node.visible)
    .map((node) => {
      const parts = [node.tag.toLowerCase()];
      if (node.type) parts.push(`type=${node.type}`);
      if (node.role) parts.push(`role=${node.role}`);
      const cls = (node.className || "").trim().split(/\s+/).filter(Boolean).slice(0, 2).join(".");
      if (cls) parts.push(`.${cls}`);
      const text = (node.text || "").replace(/\s+/g, " ").trim().slice(0, 30);
      if (text) parts.push(`"${text}"`);
      return parts.join(" ");
    })
    .slice(0, limit);
}

/** Visible lines that read like a rejection, so a failing run says WHY. */
export function extractErrorLines(bodyText: string, limit = 5): string[] {
  return bodyText
    .split("\n")
    .map((line) => line.trim())
    .filter(
      (line) =>
        line.length > 0
        && line.length <= 200
        && /invalid|incorrect|wrong|expired|failed|error|try again|too many|locked|blocked/i.test(line),
    )
    .slice(0, limit);
}

export function resolveTradingViewPageAuthState(evidence: TradingViewPageAuthEvidence): TradingViewPageAuthState {
  const htmlClass = normalizeUiText(evidence.htmlClass).toLowerCase();
  const bodyText = normalizeUiText(evidence.bodyText).toLowerCase();
  const hasAnonymousClass = /(?:^|\s)is-not-authenticated(?:\s|$)/.test(htmlClass);
  const hasAuthenticatedClass = /(?:^|\s)is-authenticated(?:\s|$)/.test(htmlClass);
  const hasSignInSignals = /sign in|log in|email|password|continue with google/i.test(bodyText);
  // The body-text sign-in heuristic is fuzzy — words like "email" appear
  // throughout an authenticated UI (e.g. "Email notifications") — so it must
  // NOT override the two *explicit* authentication signals: a confirmed HTTP
  // 2xx account probe, or an `is-authenticated` HTML class. Either would
  // otherwise misclassify a logged-in session as anonymous and trigger
  // spurious re-login/recovery. The authoritative probe-anonymous term (a live
  // 401/403 from /user/profile/me) is intentionally NOT gated on the HTML
  // class: a live "not authenticated" API response outranks a possibly-stale
  // `is-authenticated` class, so an expired session is still caught.
  //
  // Symmetrically, a confirmed live 2xx account probe is authoritative and
  // short-circuits EVERY anonymity heuristic — including a possibly-stale
  // `is-not-authenticated` HTML class. Gating the whole term on
  // `!accountProbeAuthenticated` makes the live probe the strongest,
  // most-current signal in both directions; without it a transient/stale
  // anonymous class would misclassify a logged-in session and trigger spurious
  // re-login/recovery loops.
  const explicitlyAnonymous = !evidence.accountProbeAuthenticated
    && (hasAnonymousClass
      || (hasSignInSignals && !hasAuthenticatedClass)
      || evidence.accountProbeAnonymous);

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
  // Fail-soft like the probe evaluate below: a crashed page / destroyed
  // execution context must yield a controlled "no evidence" state instead
  // of throwing out of the auth probe and aborting recovery loops. But the
  // failure must NOT be swallowed silently: empty evidence resolves to
  // `no_positive_auth_evidence`, indistinguishable from a real logout, so a
  // distinct trace event is emitted to let operators (and recovery loops) tell
  // a crashed context — "reload the page" — apart from "re-login".
  const pageEvidence = await page.evaluate(() => ({
    url: location.href,
    htmlClass: String(document.documentElement?.className || ""),
    bodyText: String(document.body?.innerText || "").replace(/\s+/g, " ").trim().slice(0, 2_000),
  })).catch((error: unknown) => {
    tracePageEvent(
      page,
      "auth-state-probe-eval-failed",
      error instanceof Error ? error.message : String(error),
    );
    return { url: "", htmlClass: "", bodyText: "" };
  });

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
  }, probeEndpoints).catch((error: unknown) => {
    // Same rationale as the evidence probe above: a rejected account probe
    // must be visible, not silently degraded to an empty status list that
    // looks identical to a page that genuinely returned no probe results.
    tracePageEvent(
      page,
      "auth-state-probe-fetch-failed",
      error instanceof Error ? error.message : String(error),
    );
    return [];
  });

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

export function stepTimeoutMs(): number {
  return numEnv("TV_STEP_TIMEOUT_MS", 45_000);
}

export function resolveOpenScriptTiming(env: NodeJS.ProcessEnv = process.env): {
  stepTimeoutMs: number;
  modelSettleTimeoutMs: number;
} {
  const parseMs = (name: string, fallback: number): number => {
    const raw = env[name];
    if (!raw) return fallback;
    const parsed = Number(raw);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
  };
  const baseStepTimeoutMs = parseMs("TV_STEP_TIMEOUT_MS", 45_000);

  return {
    // Opening a 200+ KiB Pine consumer can require multiple selector attempts
    // plus a delayed Monaco model swap. The generic 45s step timeout caused the
    // first attempt to keep running while the batch started a second attempt.
    stepTimeoutMs: parseMs(
      "TV_OPEN_SCRIPT_TIMEOUT_MS",
      Math.max(baseStepTimeoutMs, 180_000),
    ),
    modelSettleTimeoutMs: parseMs("TV_OPEN_SCRIPT_MODEL_SETTLE_TIMEOUT_MS", 30_000),
  };
}

export function isTrackedStepTimeoutError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error);
  return /^Step timed out after \d+ms: /.test(message);
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

export function tracePageEvent(page: Page, type: string, detail?: string): void {
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

  for (const match of normalizedDialogText.matchAll(/\b(?:BUS|CTX)\s+[A-Za-z][A-Za-z0-9/]*\b/g)) {
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

  // 2026-08-01: drift used to require `legacyLabels.length >= 2`, i.e. it was
  // only recognised when the instance still SHOWED labels that no longer exist.
  // That sees renames and replacements and is structurally blind to a purely
  // ADDITIVE contract change, where the stale instance shows a strict subset
  // and no legacy label at all. #4263 added CTX SessionMssBull/Bear to the
  // Context BUS ("additive within schema 8001"); the saved overlay was updated
  // and verified, yet the applied instance kept its old 60 inputs. The
  // diagnosis called that `likelyPartialSurface` — "we probably just did not
  // see everything" — so the mutating preflight never refreshed the instance
  // and the R4 rebind failed with "Source combobox not found for
  // CTX SessionMssBull" on runs 30694013096 and 30696257671.
  //
  // The benign reading is not available here: `collectVisibleInputLabels`
  // enumerates through `snapshotDialogAcrossScroll`, which walks the dialog's
  // whole scroll plan. A label missing from an across-scroll enumeration is
  // missing from the instance, not merely off-screen.
  //
  // What DOES stay a surface problem is seeing none of the expected labels:
  // that is the wrong dialog or an unrendered one, and re-applying the script
  // on that evidence would drop bindings for nothing. So the split is now
  // "some seen, some missing" = stale instance, "none seen" = surface.
  // legacyLabels stays reported: it still names WHY an instance is stale.
  const likelyDrift = missingCount > 0 && overlapCount > 0;

  return {
    expectedCount,
    observedCount,
    overlapCount,
    missingCount,
    legacyLabels,
    likelyDrift,
    likelyPartialSurface: missingCount > 0 && overlapCount === 0,
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
    case "smc long-dip suite":
      return ["SMC Core", "SMC Core Engine"];
    case "smc hold manager r2.4 validation":
      // 2026-08-16: the operator renamed the saved document to its
      // declaration title. Any caller still holding the pre-rename name
      // (an unmerged branch, a stale checkout) resolves to the new one.
      return ["SMC Hold Manager"];
    case "smc core":
      return ["SMC Core Engine"];
    case "smc core engine":
      return ["SMC Core"];
    case "smc long-dip dashboard":
      return ["SMC Long-Dip Dashboard v7", "SMC Decision Board", "SMC Dashboard"];
    case "smc long-dip dashboard v7":
      return ["SMC Decision Board", "SMC Dashboard"];
    case "smc decision board":
      // 2026-08-31: the plain declaration title was missing here while the
      // counter-direction ("smc long-dip dashboard", above) already listed
      // "SMC Decision Board" — an asymmetric table. It matters because the
      // chart legend carries the indicator() title: SMC_Long_Dip_Dashboard.pine
      // declares "SMC Long-Dip Dashboard", so the legend row reads that, while
      // the rollout config verifies the product name "SMC Decision Board"
      // (docs/SMC_PRODUCT_IDENTITY.md: the Pro chart companion). Measured
      // against the real legend text: neither "SMC Long-Dip Dashboard v7" nor
      // "SMC Dashboard" matches it on exact|loose — and only exact|loose reach
      // the legend probes. The v7 suffix is NOT normalised away.
      return ["SMC Long-Dip Dashboard", "SMC Long-Dip Dashboard v7", "SMC Dashboard"];
    case "smc long-dip strategy":
      return ["SMC Long-Dip Strategy v7", "SMC Execution", "SMC Long Strategy"];
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

export function resolveOpenScriptSelectionAttempts(scriptName: string): Array<{
  searchName: string;
  exactTitleOnly: boolean;
}> {
  const searchNames = resolveOpenScriptSearchNames(scriptName);
  return searchNames.flatMap((searchName, index) =>
    index === 0
      ? [
        { searchName, exactTitleOnly: false },
        { searchName, exactTitleOnly: true },
      ]
      : [{ searchName, exactTitleOnly: true }]
  );
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

export function hasDirectUpdatePublishSurface(scriptName: string, bodyText: string): boolean {
  const normalizedScriptName = normalizeUiText(scriptName);
  if (!normalizedScriptName) {
    return false;
  }

  const directUpdateTitle = new RegExp(
    `^update\\s+['\u2018\u2019\u201C\u201D"]?${escapeRegex(normalizedScriptName)}['\u2018\u2019\u201C\u201D"]?\\s+(?:library|script)(?:\\s|$)`,
    "i",
  );
  return bodyText
    .split(/\r?\n/)
    .map((line) => normalizeUiText(line))
    .some((line) => directUpdateTitle.test(line));
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

/**
 * Strict identity primitive: normalized, case-insensitive EQUALITY (not
 * substring containment, despite the historical "Contains" name). It is the
 * deliberately-strict base other matchers build on — callers that want
 * truncation/version-suffix tolerance use the looser helpers instead.
 */
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
  const launchOptions = resolveTradingViewLaunchOptions(process.env);

  let browser: Browser;
  let context: BrowserContext;

  if (authResolution.authMode === "persistent_profile") {
    if (!authResolution.authSourcePath) {
      throw new Error("TradingView auth resolution selected persistent_profile without a path");
    }

    fs.mkdirSync(authResolution.authSourcePath, { recursive: true });
    context = await launchTradingViewPersistentContext(
      authResolution.authSourcePath,
      launchOptions,
      TRADINGVIEW_SESSION_VIEWPORT,
    );
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

    browser = await launchTradingViewChromium(); // re-resolves env: pure, and the mutual-exclusion throw already fired at the top-of-function resolve
    context = await browser.newContext({
      storageState: storageStatePath,
      viewport: resolveSessionViewport(),
    });
  } else {
    throw new Error(
      "No reusable TradingView auth source configured. Provide a valid TV_STORAGE_STATE or TV_PERSISTENT_PROFILE_DIR before running TradingView automation.",
    );
  }

  const chartOrigin = new URL(process.env.TV_CHART_URL || "https://www.tradingview.com/chart/").origin;
  await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin: chartOrigin }).catch(() => undefined);

  const page = context.pages()[0] ?? await context.newPage();
  const runtimeErrors = new TradingViewRuntimeErrorMonitor();
  runtimeErrors.attach(page);
  page.setDefaultTimeout(numEnv("TV_TIMEOUT_MS", 25_000));
  attachPageLifecycleTracking(page, context, browser);

  return { browser, context, page, authResolution, runtimeErrors };
}

export async function closeTradingViewSession(session: TradingViewSession): Promise<void> {
  await session.context.close().catch(() => undefined);
  await session.browser.close().catch(() => undefined);
}

/**
 * Navigate to a chart.
 *
 * Traced deliberately (2026-08-22). Three of the call sites in
 * `tv_batch_consumer_rollout.ts` swallow the rejection with
 * `.catch(() => undefined)` because a failed recovery navigation must not kill
 * the run — but until now that combination left NOTHING behind: the function
 * emitted no event, so a navigation that never happened was invisible in both
 * the log and the artifact, and only surfaced as an unrelated-looking failure
 * further down. Measured on runs 758 and 771: zero occurrences of this
 * function in either log, which made the absence unusable as evidence.
 */
export async function gotoChart(page: Page, chartUrl?: string): Promise<void> {
  const target = chartUrl || process.env.TV_CHART_URL || "https://www.tradingview.com/chart/";
  tracePageEvent(page, "goto-chart-start", target);
  try {
    await page.goto(target, { waitUntil: "domcontentloaded" });
  } catch (error) {
    tracePageEvent(
      page,
      "goto-chart-error",
      `${target}:${String((error as Error)?.message ?? error)}`,
    );
    throw error;
  }
  await page.waitForTimeout(3_000);
  tracePageEvent(page, "goto-chart-ok", target);
}

export const DRILL_SETTLE_TIMEOUT_MS = Number(process.env.TV_DRILL_SETTLE_TIMEOUT_MS ?? 30_000);

/**
 * Load a chart and wait until TradingView has actually surfaced `scriptName`.
 *
 * `gotoChart` resolves on `domcontentloaded` plus a FIXED 3s wait, which is
 * sometimes before the legend has been rebuilt. Every read afterwards then dies
 * on `Existing chart instance not found` against a chart that is perfectly
 * healthy: CI run 30684930443 failed that way 8s in, and the identical retry
 * (30685141166) was green. Re-rolling the dice costs a whole browser run, so
 * wait for the condition instead of paying for another one.
 *
 * The wait is deliberately the SAME predicate that throws inside
 * `verifyConsumerBindings`, not a stricter proxy for it: waiting on a different
 * signal would only move the guess. If it never becomes true the error says how
 * long it waited, so a genuinely missing indicator still reads as missing
 * rather than as a slow one.
 *
 * Introduced for the repair drill (#4295) and shared from here because a second
 * drill needs the identical wait. A drill that asserts a script is ABSENT needs
 * it even more: on an unsettled chart absence is indistinguishable from a
 * legend that has not been drawn, so it must first wait for something that is
 * expected to be present — the producer — and only then read the absence.
 */
export async function gotoChartAndAwaitScript(
  page: Page,
  chartUrl: string,
  scriptName: string,
): Promise<void> {
  await gotoChart(page, chartUrl);
  const deadline = Date.now() + DRILL_SETTLE_TIMEOUT_MS;
  for (;;) {
    if (await isScriptVisibleOnChartSurface(page, scriptName).catch(() => false)) return;
    if (Date.now() >= deadline) {
      throw new Error(
        `Chart did not surface ${scriptName} within ${DRILL_SETTLE_TIMEOUT_MS}ms of loading ${chartUrl}`,
      );
    }
    await page.waitForTimeout(500);
  }
}

/**
 * Close a Pine editor DOCKED into the account's UI state. Its title-bar Close button sits
 * outside the scope closePineEditorIfVisible searches (measured 2026-10-05). Docked, it
 * squeezes the chart until legend rows have no height: the CI save flow then could not
 * open any consumer's settings (tv-save run 37510785146, 2026-10-06). Returns whether it
 * closed one. Not for flows that need the editor afterwards.
 */
export async function closeDockedPineEditor(page: Page): Promise<boolean> {
  const editor = page.locator("#pine-editor-dialog").first();
  if (!(await editor.isVisible().catch(() => false))) return false;
  const close = await pineEditorTitleBarClose(page, editor);
  await (close ?? page.locator('button[aria-label="Close"][title="Close"]').first()).click().catch(() => undefined);
  await page.waitForTimeout(1_500);
  return true;
}

/**
 * The docked editor's own Close button sits in the title bar ABOVE the editor element,
 * outside the dialog scope. Only a Close button horizontally inside the editor's span
 * from 80 px above to 60 px below its top counts -- never some other dialog's Close.
 * Measured 2026-10-05/06: this button closes the docked editor (readouts, migration).
 */
export async function pineEditorTitleBarClose(page: Page, editor: Locator): Promise<Locator | null> {
  const box = await editor.boundingBox().catch(() => null);
  if (!box) return null;
  const candidates = page.locator('button[aria-label="Close"][title="Close"]');
  const n = await candidates.count().catch(() => 0);
  for (let i = 0; i < n; i += 1) {
    const b = await candidates.nth(i).boundingBox().catch(() => null);
    if (b && b.x >= box.x - 8 && b.x + b.width <= box.x + box.width + 8 && b.y <= box.y + 60 && b.y >= box.y - 80) {
      return candidates.nth(i);
    }
  }
  return null;
}

/**
 * gotoChartAndAwaitScript for READ flows on the operator layout: a Pine editor docked
 * into the account's UI state squeezes the chart pane until its legend has no height,
 * so the script never "surfaces" (2026-10-06: migration and both readouts failed this
 * way after a publish left the editor docked). Closes the docked editor while waiting.
 * Not for publish flows, which need the editor.
 */
export async function gotoChartClosingDockedEditor(page: Page, chartUrl: string, scriptName: string): Promise<void> {
  await gotoChart(page, chartUrl);
  const deadline = Date.now() + DRILL_SETTLE_TIMEOUT_MS;
  for (;;) {
    await closeDockedPineEditor(page);
    if (await isScriptVisibleOnChartSurface(page, scriptName).catch(() => false)) return;
    if (Date.now() >= deadline) {
      throw new Error(`Chart did not surface ${scriptName} within ${DRILL_SETTLE_TIMEOUT_MS}ms of loading ${chartUrl} (docked editor closed)`);
    }
    await page.waitForTimeout(500);
  }
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

async function waitForFirstVisibleLocator(
  candidates: Locator[],
  timeoutMs: number,
  accept: (candidate: Locator) => Promise<boolean> = async () => true,
): Promise<Locator | null> {
  const deadline = Date.now() + timeoutMs;
  do {
    for (const locator of candidates) {
      const total = await locator.count().catch(() => 0);
      for (let index = 0; index < total; index += 1) {
        const candidate = locator.nth(index);
        if (
          (await candidate.isVisible({ timeout: 100 }).catch(() => false))
          && (await accept(candidate).catch(() => false))
        ) {
          return candidate;
        }
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  } while (Date.now() < deadline);

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
  let legendEvidenceSkipped = 0;

  for (const candidate of tvSelectors.openScriptIdentity(page, scriptName)) {
    const total = await candidate.count().catch(() => 0);
    for (let index = 0; index < total; index += 1) {
      const element = candidate.nth(index);
      try {
        if (!(await element.isVisible({ timeout: 750 }))) {
          continue;
        }
      } catch {
        continue;
      }
      // The identity families scan the whole page, and with the script ON THE
      // CHART two chart-side surfaces carry its name in exactly the
      // [class*="title"] shapes they accept: the legend row and the Object
      // Tree entry in the right widgetbar. Both leaked as open-script identity
      // evidence while the editor sat on an untouched "Untitled script" draft
      // (measured live 2026-07-31 during the CE10156 diagnosis; ancestor
      // chains: legend titles under .legend-* < .chart-gui-wrapper <
      // .chart-container, tree entries under [data-name="tree"] inside the
      // widgetbar). Chart-side texts are never editor evidence. Two layers:
      // the measured, unhashed chart-surface containers first, then the same
      // legend-action-button proximity probe countChartScriptInstances uses,
      // in case TradingView renames the wrapper classes.
      const insideLegendRow = await element.evaluate((node) => {
        if (node.closest('.chart-container, .chart-gui-wrapper, [data-name="tree"]')) {
          return true;
        }
        let current: Element | null = node;
        for (let depth = 0; depth < 4 && current; depth += 1) {
          const text = (current as HTMLElement).innerText ?? "";
          if (text.length > 300) {
            break;
          }
          if (current.querySelector('button[data-qa-id="legend-settings-action"], button[data-qa-id="legend-more-action"]')) {
            return true;
          }
          current = current.parentElement;
        }
        return false;
      }).catch(() => false);
      if (insideLegendRow) {
        legendEvidenceSkipped += 1;
        continue;
      }
      texts.push(...normalizeVisibleEvidenceValues(await collectVisibleLocatorMetadata(element, 750)));
    }
  }

  if (legendEvidenceSkipped > 0) {
    tracePageEvent(page, "open-script-identity-legend-evidence-skipped", `${scriptName}:${legendEvidenceSkipped}`);
  }

  return uniqueNormalizedTexts(texts);
}

/** Parse a pine-facade listing ``version`` value ("152.0", 152, "3") into
 * a positive integer, or ``null`` when it is not one. Exported for tests. */
export function parseFacadeSavedVersion(value: unknown): number | null {
  const parsed = Number.parseInt(String(value ?? "").trim(), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

/**
 * Authoritative published-version lookup via TradingView's pine-facade API
 * (the same backend the Pine editor uses). Incident 2026-07-13: the UI-text
 * evidence chain settled on the generator manifest's HARDCODED version (1),
 * so every consumer repin rewrote imports to the 2026-03 first publish —
 * CE10272 on every modern mp.* symbol. CORRECTION (same day, operator compile
 * proof "does not have a version '164'"): the ``filter=saved`` listing counts
 * EDITOR SAVE REVISIONS (USER;… ids), not the published library version the
 * ``import user/lib/N`` path resolves — only the ``filter=published`` listing
 * (PUB;… ids) carries the importable version (152 vs 164 at incident time).
 * Returns null (never throws) when the request fails or the script is absent,
 * so callers can fall back to the UI evidence.
 */
export async function fetchPublishedLibraryVersionViaFacade(page: Page, scriptName: string): Promise<number | null> {
  try {
    const response = await page.request.get("https://pine-facade.tradingview.com/pine-facade/list/?filter=published");
    if (!response.ok()) {
      tracePageEvent(page, "facade-version-http", `${scriptName}:${response.status()}`);
      return null;
    }
    const scripts = (await response.json()) as Array<{ scriptName?: string; version?: unknown }>;
    const hit = Array.isArray(scripts)
      ? scripts.find((script) => (script.scriptName || "") === scriptName)
      : undefined;
    const version = parseFacadeSavedVersion(hit?.version);
    tracePageEvent(page, "facade-version-resolved", `${scriptName}:${version ?? "absent"}`);
    return version;
  } catch (error: unknown) {
    tracePageEvent(page, "facade-version-error", `${scriptName}:${String(error).slice(0, 120)}`);
    return null;
  }
}

/**
 * Extract the title from a Pine declaration statement
 * (`indicator("…")` / `strategy("…")` / `library("…")`, optionally via the
 * named `title=` argument). Returns null when the source carries no such
 * declaration. Pure and exported for hermetic tests: this is the identity
 * leg of the persisted-source readback (run 33031264859, 2026-08-27 — the
 * editor-buffer readback verified this run's own staged content while the
 * saved-script store held ANOTHER consumer's source in the slot).
 */
export function extractPineDeclarationTitle(source: string): string | null {
  const match = /\b(?:indicator|strategy|library)\s*\(\s*(?:title\s*=\s*)?(["'])([^"'\r\n]*)\1/.exec(source);
  return match ? match[2] ?? null : null;
}

export type SavedScriptFacadeSource = {
  scriptIdPart: string;
  version: number;
  source: string;
};

/**
 * Authoritative PERSISTED saved-script source via TradingView's pine-facade
 * API (`filter=saved` listing + per-script get). This deliberately bypasses
 * the Pine editor: the editor serves per-script working buffers that survive
 * even a hard page reload, so any chooser+Monaco readback can report the
 * session's own writes instead of the stored document (proven by run
 * 33031264859: verify pass after the 11:08:02Z reload hashed the repo source
 * for "SMC Long-Dip Mobile" while the persisted slot — operator evidence
 * 2026-08-28, fresh add from the Indicators dialog — held the
 * "SMC Long-Dip Strategy" source at this run's own pin /364).
 *
 * Returns null (never throws) when the listing/get fails, the script is
 * absent, the saved name is ambiguous, or the response shape is not the
 * expected one — every reason is traced so a run that silently loses the
 * store-authoritative leg is visible in its job log.
 */
export async function fetchSavedScriptSourceViaFacade(
  page: Page,
  scriptName: string,
): Promise<SavedScriptFacadeSource | null> {
  try {
    const listResponse = await page.request.get("https://pine-facade.tradingview.com/pine-facade/list/?filter=saved");
    if (!listResponse.ok()) {
      tracePageEvent(page, "facade-saved-source-http", `${scriptName}:list:${listResponse.status()}`);
      return null;
    }
    const scripts = (await listResponse.json()) as Array<{
      scriptName?: string;
      scriptIdPart?: unknown;
      version?: unknown;
    }>;
    const hits = Array.isArray(scripts)
      ? scripts.filter((script) => (script.scriptName || "") === scriptName)
      : [];
    if (hits.length === 0) {
      tracePageEvent(page, "facade-saved-source-absent", scriptName);
      return null;
    }
    if (hits.length > 1) {
      // Two saved documents with the same name: the readback cannot know
      // which one the rollout wrote. Refusing here keeps the caller on the
      // (traced) editor fallback instead of verifying an arbitrary slot.
      tracePageEvent(page, "facade-saved-source-ambiguous", `${scriptName}:${hits.length}`);
      return null;
    }
    const scriptIdPart = typeof hits[0].scriptIdPart === "string" ? hits[0].scriptIdPart : "";
    const version = parseFacadeSavedVersion(hits[0].version);
    if (!scriptIdPart || version === null) {
      tracePageEvent(
        page,
        "facade-saved-source-shape",
        `${scriptName}:idPart=${scriptIdPart ? "present" : "missing"}:version=${String(hits[0].version ?? "missing")}`,
      );
      return null;
    }
    const getResponse = await page.request.get(
      `https://pine-facade.tradingview.com/pine-facade/get/${encodeURIComponent(scriptIdPart)}/${version}`,
    );
    if (!getResponse.ok()) {
      tracePageEvent(page, "facade-saved-source-http", `${scriptName}:get:${getResponse.status()}`);
      return null;
    }
    const payload = (await getResponse.json()) as { source?: unknown } | null;
    const source = typeof payload?.source === "string" ? payload.source : null;
    if (source === null || !source.trim()) {
      tracePageEvent(page, "facade-saved-source-shape", `${scriptName}:get-payload-has-no-source-string`);
      return null;
    }
    tracePageEvent(
      page,
      "facade-saved-source-resolved",
      `${scriptName}:v${version}:${Buffer.byteLength(source, "utf-8")}`,
    );
    return { scriptIdPart, version, source };
  } catch (error: unknown) {
    tracePageEvent(page, "facade-saved-source-error", `${scriptName}:${String(error).slice(0, 120)}`);
    return null;
  }
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

function normalizePublishFieldValue(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

export async function fillFirstAndVerify(
  value: string,
  candidates: Locator[],
  timeoutMs = 2_500,
): Promise<boolean> {
  const expected = normalizePublishFieldValue(value);

  for (const locator of candidates) {
    const candidate = await firstVisibleLocator(locator, timeoutMs);
    if (!candidate) {
      continue;
    }

    const filled = await candidate.fill(value).then(() => true).catch(() => false);
    if (!filled) {
      continue;
    }

    const actual = await candidate.evaluate((node) => {
      if (node instanceof HTMLInputElement || node instanceof HTMLTextAreaElement) {
        return node.value;
      }
      return (node as HTMLElement).innerText || node.textContent || "";
    }).catch(() => "");
    if (normalizePublishFieldValue(actual) === expected) {
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

    // JS pointer-events bypass: walk the elements stacked at the candidate's
    // centre, temporarily disable their pointer-events, dispatch the click,
    // then restore. This is the ONLY strategy that defeats TradingView's
    // persistent price-axis / legend value overlays (e.g. valueValue-* inside
    // js-rootresizer) — plain hover/force/offset clicks all re-hit the same
    // stacked interceptor. Kept as a named helper so it can run BOTH as an
    // early fast-path on a pointer-interception error and as the ladder's
    // penultimate fallback.
    const tryPointerEventsBypass = async (reason: string): Promise<boolean> => {
      const bypassBox = await candidate.boundingBox().catch(() => null);
      if (!bypassBox) {
        tracePageEvent(page, `${tracePrefix}-pointer-bypass-skip`, `candidate:${index}:no-box:${reason}`);
        return false;
      }
      try {
        const pointerBypassed = await candidate.evaluate((node) => {
          const element = node as HTMLElement;
          const rect = element.getBoundingClientRect();
          const x = rect.left + Math.max(2, Math.min(rect.width / 2, rect.width - 2));
          const y = rect.top + Math.max(2, Math.min(rect.height / 2, rect.height - 2));
          const patched: Array<{ element: HTMLElement; value: string }> = [];

          // Restore in finally: if the dispatched click throws synchronously
          // (e.g. a page-patched click()), the stacked overlays must not be
          // left with pointer-events:none for the rest of the session.
          try {
            let hit = document.elementFromPoint(x, y) as HTMLElement | null;
            while (hit && hit !== element && !element.contains(hit) && patched.length < 6) {
              patched.push({ element: hit, value: hit.style.pointerEvents });
              hit.style.pointerEvents = "none";
              hit = document.elementFromPoint(x, y) as HTMLElement | null;
            }

            // DOM dispatch does not depend on elementFromPoint once the exact
            // candidate has been resolved. TradingView can stack more than six
            // canvas/SVG layers, so do not suppress the fallback merely because
            // the diagnostic walk did not expose the target within its cap.
            const targetReady = true;
            {
              // TradingView's current React controls arm on pointer/mouse down
              // and ignore a synthetic click-only shortcut. Reproduce the
              // complete primary-button sequence after removing interceptors.
              for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
                const EventCtor = type.startsWith("pointer") ? PointerEvent : MouseEvent;
                element.dispatchEvent(
                  new EventCtor(type, {
                    bubbles: true,
                    cancelable: true,
                    composed: true,
                    button: 0,
                    buttons: type.endsWith("down") ? 1 : 0,
                    clientX: x,
                    clientY: y,
                    view: window,
                  }),
                );
              }
            }

            return targetReady;
          } finally {
            for (const entry of patched.reverse()) {
              entry.element.style.pointerEvents = entry.value;
            }
          }
        });
        if (pointerBypassed) {
          tracePageEvent(page, `${tracePrefix}-pointer-bypass-ok`, `candidate:${index}:${reason}`);
          if (await settleClickEffect(`candidate:${index}:pointer-bypass`)) {
            return true;
          }
        }
        tracePageEvent(page, `${tracePrefix}-pointer-bypass-miss`, `candidate:${index}:${reason}`);
      } catch (error: unknown) {
        const message = error instanceof Error ? error.message : String(error);
        tracePageEvent(page, `${tracePrefix}-pointer-bypass-error`, `candidate:${index}:${message}`);
      }
      return false;
    };

    try {
      await candidate.scrollIntoViewIfNeeded().catch(() => undefined);
      await candidate.click({ timeout: timeoutMs + 1_000 });
      if (await settleClickEffect(`candidate:${index}:click`)) {
        return true;
      }
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      tracePageEvent(page, `${tracePrefix}-click-error`, `candidate:${index}:${message}`);
      // Fast-path: a pointer-events interception (persistent chart overlay)
      // cannot be cleared by hover/force/offset — they re-hit the same stacked
      // element. Jump straight to the JS bypass and skip ~13s of doomed retries
      // that would otherwise eat the step timeout before the bypass runs.
      if (message.includes("intercepts pointer events") && (await tryPointerEventsBypass("early"))) {
        return true;
      }
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

    // Ladder fallback: same JS bypass, reached when the earlier fast-path did
    // not fire (e.g. offset/force failed for a non-interception reason).
    if (await tryPointerEventsBypass("ladder")) {
      return true;
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

          // Restore in finally: if the dispatched click throws synchronously
          // (e.g. a page-patched click()), the stacked overlays must not be
          // left with pointer-events:none for the rest of the session.
          try {
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

            return targetReady;
          } finally {
            for (const entry of patched.reverse()) {
              entry.element.style.pointerEvents = entry.value;
            }
          }
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
        const meta = await ancestor.evaluate((node) => {
          if (!(node instanceof Element)) {
            return { tagName: "", text: "" };
          }
          const element = node as HTMLElement;
          const tagName = element.tagName.toLowerCase();
          if (tagName === "body" || tagName === "html") {
            return { tagName, text: "" };
          }
          return {
            tagName,
            text: (element.innerText || element.textContent || ""),
          };
        }, undefined, { timeout: 250 }).catch(() => ({ tagName: "", text: "" }));
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

        // Restore in finally: if the dispatched click throws synchronously
        // (e.g. a page-patched click()), the stacked overlays must not be
        // left with pointer-events:none for the rest of the session.
        try {
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

          return targetReady;
        } finally {
          for (const entry of patched.reverse()) {
            entry.element.style.pointerEvents = entry.value;
          }
        }
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

// What marks a TradingView promotion, as opposed to a tool dialog. Kept to
// phrases a settings / indicator / alert dialog does not carry.
const PROMOTION_OVERLAY_TEXT = /offer ends in|explore offers?|\b\d{1,3}\s?% off\b/i;

/**
 * Close a TradingView promotion overlay through its own close button.
 *
 * Measured 2026-10-01 (repair-only run 36859274386, layout vWgAWyfC): a
 * full-size "Autumn sale — Up to 80% off — Offer ends in …" modal sat on the
 * chart and intercepted every click on five of seven settings dialogs
 * ("<div class=modalContent-…> from <div data-id=…> subtree intercepts pointer
 * events"); the run repaired 0 of 108 bindings. dismissOverlapManagerOverlay
 * does not help there: it runs once after navigation, the promotion appears
 * later, and its last resort would also neutralise an open settings dialog.
 *
 * Deliberately narrow: only an overlay that reads like an offer is touched,
 * only its close control is clicked (never the offer button), and the result
 * says whether the overlay is actually gone. Returns false both when there was
 * no promotion and when one would not close — the caller's next click then
 * fails with the screenshot, which is the honest outcome.
 */
export async function dismissPromotionOverlay(page: Page): Promise<boolean> {
  if (page.isClosed()) return false;
  const promotion = page
    .locator('#overlap-manager-root [data-id], [role="dialog"]')
    .filter({ hasText: PROMOTION_OVERLAY_TEXT });
  if ((await promotion.count().catch(() => 0)) === 0) return false;

  const overlay = promotion.first();
  const headline = ((await overlay.innerText().catch(() => "")) ?? "").replace(/\s+/g, " ").trim().slice(0, 120);
  tracePageEvent(page, "promotion-overlay-found", headline);

  const closeCandidates = [
    overlay.getByRole("button", { name: /^close$/i }),
    overlay.locator('button[aria-label*="close" i], [role="button"][aria-label*="close" i]'),
    overlay.locator('[data-name="close"], button[class*="close" i]'),
  ];
  for (const candidate of closeCandidates) {
    const control = candidate.first();
    if (!(await control.isVisible().catch(() => false))) continue;
    await control.click({ timeout: 3_000 }).catch(() => undefined);
    break;
  }

  const deadline = Date.now() + 3_000;
  while (Date.now() < deadline) {
    if ((await promotion.count().catch(() => 0)) === 0) {
      tracePageEvent(page, "promotion-overlay-dismissed", headline);
      return true;
    }
    await page.waitForTimeout(150).catch(() => undefined);
  }
  tracePageEvent(page, "promotion-overlay-stuck", headline);
  return false;
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
    const bodyText = normalizeUiText((await page.locator("body").innerText().catch((error: unknown) => {
      // Same fail-open hazard as getVisibleCompileErrorMarker: a crashed
      // context makes the body unreadable -> "" -> null ("no details"), which
      // is silently downgraded to a generic "Could not open publish flow"
      // error, losing the compile-error attribution. Trace the crash.
      tracePageEvent(
        page,
        "compile-error-details-body-read-failed",
        error instanceof Error ? error.message : String(error),
      );
      return "";
    })) || "");
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
  await dismissSymbolSearchDialog(page).catch(() => undefined);

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
  // 2026-08-17: TradingView replaced this confirmation. The old dialog read
  // "Cancel publication?" and confirmed with "Yes"; the new one reads
  // "Delete this publication? … you will lose everything and will need to
  // start from scratch" with buttons Cancel / Delete — it discards the
  // UNSAVED publication draft, which is exactly what the no-change dismissal
  // wants. Seven publish runs hung on the unanswered modal (surface-close
  // clicks timing out behind it, identity evidence collapsing on the covered
  // page) while the refresh treadmill re-published 255 -> 262 unverified.
  // Both variants stay handled; the matched text decides which affirmative
  // button this is allowed to press, strictly inside the matched dialog.
  const cancelDialog = await findVisibleDialogByText(page, /cancel publication/i, timeoutMs);
  const dialog = cancelDialog
    ?? await findVisibleDialogByText(page, /delete this publication/i, timeoutMs);
  if (!dialog) {
    return false;
  }
  const isLegacyCancel = cancelDialog !== null;
  const dialogPattern = isLegacyCancel ? /cancel publication/i : /delete this publication/i;
  const variant = isLegacyCancel ? "cancel" : "delete";

  tracePageEvent(page, "publish-no-change", `${variant}-confirm-visible`);
  const affirmatives = isLegacyCancel
    ? [
        dialog.getByRole("button", { name: /^yes$/i }),
        dialog.getByText(/^yes$/i),
        dialog.locator('button:has-text("Yes")'),
      ]
    : [
        dialog.getByRole("button", { name: /^delete$/i }),
        dialog.locator('button:has-text("Delete")'),
      ];
  const confirmed = await clickVisibleWithFallback(
    page,
    affirmatives,
    `publish-no-change-${variant}-confirm`,
    1_500,
    500,
  ).catch(() => false);

  if (!confirmed) {
    await page.keyboard.press("Enter").catch(() => undefined);
  }

  const dialogClosed = await waitForDialogByTextToClose(page, dialogPattern, 1_500);
  tracePageEvent(page, "publish-no-change", dialogClosed ? `${variant}-confirm-dismissed` : `${variant}-confirm-still-visible`);
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

    // Answer the confirmation the close click just spawned BEFORE pressing
    // Escape: Escape cancels the confirm modal and hands the stuck publish
    // surface straight back (the 2026-08-17 loop shape — three attempts,
    // every close click timing out behind the unanswered modal).
    await dismissPublishCancelConfirmation(page, 500).catch(() => false);
    if (!(await hasPublishSurface(page, 150))) {
      tracePageEvent(page, "publish-no-change", `surface-dismissed:confirm:${attempt}`);
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
    publishSurfaceClosed = !(await hasPublishSurface(page, 150));

    if (
      publishSurfaceClosed
      || (scriptName && detectPublishedVersionFromContextTexts(versionContextTexts, scriptName) !== null)
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

async function visiblePublishValidationMessage(page: Page, timeoutMs = 250): Promise<string | null> {
  for (const locator of tvSelectors.publishValidationError(page)) {
    const candidate = await firstVisibleLocatorFast(locator, timeoutMs);
    if (!candidate) {
      continue;
    }
    const text = await candidate.innerText().catch(() => "");
    if (text.trim()) {
      return text.replace(/\s+/g, " ").trim();
    }
  }
  return null;
}

async function visiblePublishSurfaceFingerprint(page: Page): Promise<string> {
  const snippets = await collectVisibleOverlayTextSnippets(page, 250).catch(() => []);
  return snippets.map((value) => value.replace(/\s+/g, " ").trim()).filter(Boolean).join("\n");
}

export function publishStepMadeProgress(options: {
  beforeStep: string;
  afterStep: string;
  continueStillVisible: boolean;
}): boolean {
  return !options.continueStillVisible
    || !options.beforeStep
    || options.afterStep !== options.beforeStep;
}

export function publishConfirmationIsAuthoritative(options: {
  publishSurfaceClosed: boolean;
  versionContextTexts: string[];
  scriptName?: string;
}): boolean {
  const publishedVersionDetected = options.scriptName
    ? detectPublishedVersionFromContextTexts(options.versionContextTexts, options.scriptName)
    : null;
  return options.publishSurfaceClosed || publishedVersionDetected !== null;
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

  // Restore in finally: an unguarded await inside the loop (e.g.
  // waitForTimeout on a closing page) must not leave the dialog scrolled
  // away from its original position.
  try {
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
  } finally {
    await scrollDialogTo(dialog, plan.restoreTop);
  }

  return {
    title: [...titles][0] ?? "",
    text: [...texts].join(" "),
    labelTexts: [...labelTexts],
  };
}

async function verifyOpenedSettingsDialogIdentity(page: Page, scriptName: string, tracePrefix: string): Promise<boolean> {
  tracePageEvent(page, `${tracePrefix}-identity-start`, scriptName);
  // Nachlese statt Sofort-Urteil (Lauf 32886027492: target-visible im
  // Deklarationsmoment) — siehe settleDialogPick. Ein Treffer erst in der
  // Nachlese traegt eine eigene Spur: sie ist die inhaltliche Versionsprobe
  // dieses Fixes am echten Lauf.
  const readPick = async () =>
    pickDialogForScript(await collectVisibleDialogSnapshots(page).catch(() => []), scriptName);
  const traceSettled = (picked: DialogPick, reads: number) => {
    if (reads > 1 && picked.verdict === "match") {
      tracePageEvent(page, `${tracePrefix}-identity-title-settled`, `${picked.dialog!.title}:reads=${reads}`);
    }
  };
  if (await hasScriptSettingsInputsSurface(page)) {
    const settled = await settleDialogPick(readPick, SETTINGS_IDENTITY_RE_READ_WAITS_MS, async (ms) => {
      await page.waitForTimeout(ms);
    });
    const picked = settled.pick;
    traceSettled(picked, settled.reads);
    if (picked.verdict === "untitled") {
      // Review-Fund 27.8.: ein untitled aus der NACHLESE traegt eine bis zu
      // 1,2 s alte Surface-Messung — der (fremde) Dialog kann waehrend der
      // Wartezeit geschlossen worden sein (Ghost-Versuche rufen closeModal).
      // Erst frisch bestaetigen. Ohne Surface ist das KEIN Erfolg und KEIN
      // Identitaets-Mismatch (kein Zaehler-Tick): die Leiter oeffnet erneut.
      if (settled.reads === 1 || await hasScriptSettingsInputsSurface(page)) {
        tracePageEvent(page, `${tracePrefix}-identity-implicit-surface`, scriptName);
        return true;
      }
      tracePageEvent(page, `${tracePrefix}-identity-surface-gone-after-settle`, scriptName);
      return false;
    }
    if (picked.verdict === "match") {
      tracePageEvent(page, `${tracePrefix}-identity-title-match`, picked.dialog!.title);
      return true;
    }
    tracePageEvent(
      page,
      `${tracePrefix}-identity-mismatch`,
      `${scriptName} != ${picked.dialog!.title} (${picked.visibleCount} titled dialog(s) visible)`,
    );
    recordSettingsIdentityMismatch(settingsIdentityMismatchCountsForPage(page), scriptName);
    await closeModal(page).catch(() => undefined);
    return false;
  }

  const settled = await settleDialogPick(readPick, SETTINGS_IDENTITY_RE_READ_WAITS_MS, async (ms) => {
    await page.waitForTimeout(ms);
  });
  const picked = settled.pick;
  traceSettled(picked, settled.reads);
  if (picked.verdict === "untitled") {
    tracePageEvent(page, `${tracePrefix}-identity-missing-title`, scriptName);
    throw new Error(`Opened settings dialog without an identifiable script title for: ${scriptName}`);
  }
  if (picked.verdict === "match") {
    return true;
  }
  tracePageEvent(
    page,
    `${tracePrefix}-identity-mismatch`,
    `${scriptName} != ${picked.dialog!.title} (${picked.visibleCount} titled dialog(s) visible)`,
  );
  recordSettingsIdentityMismatch(settingsIdentityMismatchCountsForPage(page), scriptName);
  throw new Error(
    `Opened settings dialog for wrong script: expected ${scriptName}, got ${picked.dialog!.title}`
    + ` (${picked.visibleCount} titled dialog(s) visible)`,
  );
}

export type DialogPick = {
  verdict: "match" | "mismatch" | "untitled";
  /** Bei "match" der passende, bei "mismatch" der erste betitelte (fuer die Spur). */
  dialog: { title: string } | null;
  /** Wie viele betitelte Dialoge gleichzeitig sichtbar waren — das ist der Befund. */
  visibleCount: number;
};

/**
 * Welcher der sichtbaren Dialoge gehoert zum Ziel?
 *
 * Bis 2026-08-23 nahm die Identitaetspruefung `dialogs.find(titled)` — den
 * ERSTEN mit Titel, nicht den passenden. Sind mehrere Dialoge gleichzeitig
 * offen, ist das eine Lotterie: der richtige kann offen sein und trotzdem
 * abgelehnt werden.
 *
 * Gemessen an Lauf 32556181388: Ziel `SMC Long-Dip Alerts` sah in EINEM Lauf
 * drei verschiedene fremde Dialoge (`SMC Breakout Overlay` 4x, `SMC Setup
 * Check` 2x, Producer `SMC Long-Dip Suite` 2x). Bei einem einzigen
 * haengengebliebenen Dialog waere der Fremde immer derselbe — drei
 * verschiedene sind nur mit mehreren gleichzeitig sichtbaren erklaerbar.
 * `closeModal` meldete dabei 31/31 Erfolg, schliesst aber je nur einen.
 *
 * "untitled" bleibt vom Mismatch getrennt: eine sichtbare Einstellungsflaeche
 * ohne lesbaren Titel ist NICHT das falsche Skript, und dieser Unterschied
 * trug bereits den implicit-surface-Pfad.
 */
export function pickDialogForScript(
  dialogs: ReadonlyArray<{ title: string }>,
  scriptName: string,
): DialogPick {
  const titled = dialogs.filter((dialog) => normalizeUiText(dialog.title).length > 0);
  if (titled.length === 0) {
    return { verdict: "untitled", dialog: null, visibleCount: 0 };
  }
  const matching = titled.find((dialog) => settingsDialogTitleMatchesScriptName(scriptName, dialog.title));
  if (matching) {
    return { verdict: "match", dialog: matching, visibleCount: titled.length };
  }
  return { verdict: "mismatch", dialog: titled[0], visibleCount: titled.length };
}

/**
 * Nachlese-Staffel, bevor ein Mismatch deklariert wird. Kurz und endlich:
 * die Summe lebt im 60-s-Budget des umgebenden Steps, und im Erfolgsfall
 * (erste Lesung trifft) wird gar nicht gewartet.
 */
export const SETTINGS_IDENTITY_RE_READ_WAITS_MS: readonly number[] = [400, 800];

/**
 * Ein Mismatch gilt erst, wenn er eine kurze Nachlese ueberlebt.
 *
 * Messgrund (Ledger klasse-h, Lauf 32886027492, 2026-08-26): im Moment der
 * Fehlschlag-Deklaration stand der RICHTIGE Dialog offen
 * (`dialogAtFailureVerdict = target-visible`, Titel korrekt, genau einer
 * sichtbar) — die einmalige Sofort-Lesung hatte Sekunden vorher den Titel des
 * VORHERIGEN Ziels gesehen (2026-08-24: "der gelesene Dialog ist immer der
 * des vorherigen Ziels"). Das passt zu einem wiederverwendeten
 * Settings-Modal, dessen Titel dem Inhalt nachzieht: der Klick oeffnet den
 * richtigen Dialog, die Pruefung liest zu frueh, deklariert Mismatch — und
 * closeModal schliesst den gerade korrekt geoeffneten Dialog. Genau daraus
 * wurde die symmetrische Nachbar-Kaskade.
 *
 * Nur "mismatch" wird nachgelesen: "match" ist fertig, und "untitled" hat
 * eigene Zweige (implicit-surface bzw. missing-title), die eine Wartezeit nur
 * verlangsamen wuerde, ohne etwas zu entscheiden.
 */
export async function settleDialogPick(
  readPick: () => Promise<DialogPick>,
  waitsMs: readonly number[],
  sleep: (ms: number) => Promise<void>,
): Promise<{ pick: DialogPick; reads: number }> {
  let pick = await readPick();
  let reads = 1;
  for (const waitMs of waitsMs) {
    if (pick.verdict !== "mismatch") {
      break;
    }
    await sleep(waitMs);
    pick = await readPick();
    reads += 1;
  }
  return { pick, reads };
}

export type DialogAtFailureVerdict = "target-visible" | "foreign-visible" | "untitled-visible" | "no-dialog";

/**
 * Ledger klasse-h, Kandidat (A): klassifiziert, was `pickDialogForScript`
 * ueber die zum Messzeitpunkt sichtbaren Dialoge sagt, in die vier Zustaende,
 * die die Beweisdatei unterscheidbar halten sollen. Reine Funktion, ohne
 * Browser testbar -- derselbe Zuschnitt wie `pickDialogForScript` selbst, das
 * sie wiederverwendet statt eine zweite Fassung der Auswahl danebenzustellen.
 *
 * "no-dialog" ist ein eigener Zustand VOR `pickDialogForScript`, weil dessen
 * "untitled"-Verdikt sowohl "kein Dialog da" als auch "ein Dialog ohne
 * lesbaren Titel" abdeckt -- hier muessen beide auseinanderbleiben.
 */
export function classifyDialogAtFailure(
  dialogs: ReadonlyArray<{ title: string }>,
  scriptName: string,
): { verdict: DialogAtFailureVerdict; title: string | null; visibleCount: number } {
  if (dialogs.length === 0) {
    return { verdict: "no-dialog", title: null, visibleCount: 0 };
  }
  const picked = pickDialogForScript(dialogs, scriptName);
  if (picked.verdict === "match") {
    return { verdict: "target-visible", title: picked.dialog?.title ?? null, visibleCount: picked.visibleCount };
  }
  if (picked.verdict === "mismatch") {
    return { verdict: "foreign-visible", title: picked.dialog?.title ?? null, visibleCount: picked.visibleCount };
  }
  // "untitled": dialogs.length > 0 here (checked above), so this is genuinely
  // a visible dialog without a readable title -- not the zero-dialogs case.
  return { verdict: "untitled-visible", title: null, visibleCount: picked.visibleCount };
}

/**
 * Ledger klasse-h, Eskalation (Lauf 32803019213, save-Job 2026-08-25
 * 11:52:50Z): der Doppelklick-Pfad trifft nicht zufaellig daneben, sondern
 * STABIL den Legenden-NACHBARN (Alerts->Setup Check 2x, Alerts->Breakout
 * Overlay 1x, symmetrisch Setup Check->Alerts 1x, alle in einem Lauf). Der
 * Waechter (verifyOpenedSettingsDialogIdentity) lehnt das korrekt ab, aber
 * ein dritter/vierter Doppelklick auf dieselbe Zielzeile aendert nichts --
 * die Leiter wiederholte bis dahin denselben Ansatz, bis das 60s-Schrittbudget
 * (`Step timed out`) ausging. Ab dem ZWEITEN Mismatch fuer dasselbe Ziel lohnt
 * ein weiterer Doppelklick nicht mehr.
 *
 * Reine Zaehl-/Entscheidungslogik auf einer einfachen Map, ohne Browser
 * beweisbar (derselbe Zuschnitt wie pickDialogForScript). Der Page-gebundene
 * Teil -- welche Zaehlung zu welcher Page/welchem Skript gehoert -- ist unten
 * in settingsIdentityMismatchCountsForPage vom Browser abgetrennt, damit
 * diese Funktionen selbst keinen Browser brauchen.
 */
export type SettingsIdentityMismatchCounts = Map<string, number>;

export function recordSettingsIdentityMismatch(
  counts: SettingsIdentityMismatchCounts,
  scriptName: string,
): number {
  const next = (counts.get(scriptName) ?? 0) + 1;
  counts.set(scriptName, next);
  return next;
}

export function settingsIdentityMismatchCount(
  counts: SettingsIdentityMismatchCounts,
  scriptName: string,
): number {
  return counts.get(scriptName) ?? 0;
}

export function resetSettingsIdentityMismatchCount(
  counts: SettingsIdentityMismatchCounts,
  scriptName: string,
): void {
  counts.delete(scriptName);
}

/**
 * Gemessene Schwelle (Lauf 32803019213): der ERSTE Mismatch bleibt beim
 * bestehenden Doppelklick-Pfad -- die Leiter bleibt fuer die erfolgreichen
 * 80 % der Ziele (2,9-6,2s) unangetastet. Erst der ZWEITE Mismatch fuer
 * dasselbe Ziel eskaliert auf den zeilengebundenen Knopf-Pfad
 * (openSettingsForScriptViaLegendButton).
 */
export const SETTINGS_IDENTITY_MISMATCH_ESCALATION_THRESHOLD = 2;

export function shouldEscalateSettingsOpenPath(mismatchCount: number): boolean {
  return mismatchCount >= SETTINGS_IDENTITY_MISMATCH_ESCALATION_THRESHOLD;
}

// Browser-gebunden: eine Zaehlung je Page+Skript (WeakMap, damit sie mit der
// Page verschwindet), so dass parallele Ziele auf verschiedenen Pages sich
// nicht gegenseitig eskalieren.
const settingsIdentityMismatchCountsByPage = new WeakMap<Page, SettingsIdentityMismatchCounts>();

function settingsIdentityMismatchCountsForPage(page: Page): SettingsIdentityMismatchCounts {
  let counts = settingsIdentityMismatchCountsByPage.get(page);
  if (!counts) {
    counts = new Map();
    settingsIdentityMismatchCountsByPage.set(page, counts);
  }
  return counts;
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
  // Incident 2026-07-13 (post-release validation, "SMC Decision Board"): a
  // script WITHOUT input() parameters renders a Style+Visibility-only settings
  // dialog — the old filters demanded the literal word "inputs", so the
  // successfully opened dialog was never recognised, tryOpenScriptSettingsBy-
  // DoubleClick declared failure and closeModal() CLOSED the dialog it had
  // just opened, and the strategy ladder click-stormed into the (re)opened
  // modal until the 60s step timeout — deterministically per run.
  // New rule (kept in lockstep with isIndicatorSettingsDialogSnapshot): one
  // word from {inputs, visibility} AND one from {style, properties} — a
  // genuine two-tab settings structure. Style-only dialogs match
  // (visibility+style); the publish dialog (visibility only) and one-word
  // impostors do not.
  return [
    page.locator('#overlap-manager-root [role="dialog"]').filter({ hasText: /\b(inputs|visibility)\b/i }).filter({ hasText: /\b(style|properties)\b/i }),
    page.locator('#overlap-manager-root [data-name*="dialog" i], #overlap-manager-root [class*="dialog" i], #overlap-manager-root [class*="modal" i], #overlap-manager-root [class*="popover" i], #overlap-manager-root [data-name*="popover" i]').filter({ hasText: /\b(inputs|visibility)\b/i }).filter({ hasText: /\b(style|properties)\b/i }),
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

export function isIndicatorSettingsDialogSnapshot(dialog: VisibleDialogSnapshot | null | undefined): boolean {
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

  // Incident 2026-07-13: scripts without input() parameters render a
  // Style+Visibility-only settings dialog. The old ``hasInputsTab && (...)``
  // rule refused to recognise it, so the open-settings ladder closed its own
  // successfully opened dialog and click-stormed until the step timeout.
  // Accept a genuine two-tab structure instead: one tab word from
  // {inputs, visibility} AND one from {style, properties} — kept in lockstep
  // with indicatorSettingsDialogLocators above.
  return (hasInputsTab || hasVisibilityTab) && hasIndicatorTab;
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
    // Tolerate a leading/trailing icon, emoji or whitespace on an otherwise
    // "Settings"/"Settings..." button (e.g. "⚙ Settings"): strip the non-letter
    // decoration around the word instead of anchoring on the raw innerText,
    // which missed icon-prefixed buttons. Still anchored around the word so
    // multi-word labels like "Chart settings" / "Reset settings" don't match.
    // Stricter than a bare [^a-z0-9]* run — \p{L} boundaries reject digit- and
    // punctuation-decorated impostors while the explicit ellipsis group keeps
    // "Settings…".
    const settingsActionPattern = /^[^\p{L}]*settings(?:\.\.\.|…)?[^\p{L}.…]*$/iu;
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

// The chart legend lives under the chart surface; the Pine editor, dialogs,
// menus and the Object Tree do not. Legend titles sit under .legend-* <
// .chart-gui-wrapper < .chart-container (measured 2026-07-31 during the CE10156
// diagnosis).
export const CHART_LEGEND_CONTAINER_SELECTOR = ".chart-container, .chart-gui-wrapper";

// Surfaces that also carry the script name but are NOT the chart legend. The
// pine-editor host is the important one: the editor shows the script's title
// whenever it is open, and counting that as on-chart would make presence
// trivially true. LEGEND_TEXT_EXCLUDED_SURFACES (defined further down) covers
// dialogs, menus, the tree and the pine-dialog; the id-based editor selectors
// catch the docked editor's title button. Composed at call time, not module
// load, because LEGEND_TEXT_EXCLUDED_SURFACES initializes after this point.
function chartLegendExcludedSelector(): string {
  return `${LEGEND_TEXT_EXCLUDED_SURFACES}, #pine-editor-dialog, [id*="pine-editor" i]`;
}

/**
 * Pure verdict for {@link hasVisibleChartLegendText}: a name match counts as an
 * on-chart legend row only when it sits inside the chart container AND outside
 * every excluded surface. Kept separate from the DOM probe so the decision is
 * unit-testable without a browser.
 */
export function chartLegendTextVerdict(flags: { inContainer: boolean; inExcluded: boolean }): boolean {
  return flags.inContainer && !flags.inExcluded;
}

/**
 * Button-free presence check: is {@link scriptName} visible as legend text on
 * the chart? This is the source-level fix for the transient-button blindness
 * that {@link findLegendRowWrappers} inherits — removal, the refresh residual
 * check and verify visibility all funnel through hasLegendMatch, so keying
 * presence on the text here fixes all three at once. It does NOT return a
 * clickable handle (removal still needs the wrapper for that); it only answers
 * "is it there".
 */
async function hasVisibleChartLegendText(page: Page, scriptName: string): Promise<boolean> {
  // Alias-aware, like findLegendRowWrappers. Both are halves of ONE signal
  // (hasLegendMatch) and this half exists for when the button half is blind —
  // until 2026-08-31 it was the narrower of the two. Rationale and the measured
  // incident: tv_legend_text_visibility.test.ts.
  const patterns = resolveOpenScriptSearchNames(scriptName)
    .flatMap((name) => {
      const [exactPattern, loosePattern] = buildScriptNamePatterns(name);
      return [exactPattern, loosePattern];
    });
  for (const pattern of patterns) {
    const matches = page.getByText(pattern);
    const total = await matches.count().catch(() => 0);
    for (let index = 0; index < Math.min(total, 24); index += 1) {
      const target = matches.nth(index);
      if (!(await target.isVisible({ timeout: 250 }).catch(() => false))) {
        continue;
      }
      const flags = await target
        .evaluate(
          (node, selectors) => ({
            inContainer: Boolean((node as Element).closest(selectors.container)),
            inExcluded: Boolean((node as Element).closest(selectors.excluded)),
          }),
          { container: CHART_LEGEND_CONTAINER_SELECTOR, excluded: chartLegendExcludedSelector() },
        )
        .catch(() => ({ inContainer: false, inExcluded: true }));
      if (chartLegendTextVerdict(flags)) {
        tracePageEvent(page, "chart-legend-text-present", `${scriptName}:${index}`);
        return true;
      }
    }
  }
  return false;
}

export async function collectVisibleChartScriptState(
  page: Page,
  scriptName: string,
  options: VisibleChartScriptStateProbeOptions = {},
): Promise<VisibleChartScriptState> {
  const [, scriptNamePattern, fuzzyPattern] = buildScriptNamePatterns(scriptName);
  const strategyPattern = /strategy report/i;
  const locatorTimeoutMs = options.locatorTimeoutMs ?? 500;

  const legendWrappers = await findLegendRowWrappers(page, scriptName, options).catch(() => []);
  // The wrapper probe starts at the legend-settings-action button, which
  // TradingView only renders on hover / right after an interaction. A script
  // that IS on the chart but whose row is idle reads as absent (run
  // 30718040533: a freshly added overlay verified as "not found"). Fall back
  // to the visible legend TEXT, which does not depend on the transient button.
  const hasLegendMatch = legendWrappers.length > 0
    || await hasVisibleChartLegendText(page, scriptName).catch(() => false);
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
  // The legend row is the only signal tied to THIS script. `hasStrategyReportMatch`
  // merely asks whether "Strategy report" is visible anywhere on the page, and
  // `hasScriptNameMatch` matches the name anywhere — including the Pine editor's
  // own title. Combining them reported a library as already-on-chart whenever any
  // strategy happened to be loaded, and flipped to a false negative as soon as the
  // Pine editor replaced the Strategy Tester in the bottom panel. Both flags stay in
  // the state because the traces they feed are useful evidence; neither decides.
  return state.hasLegendMatch;
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
        // A pane/container ancestor also contains the text of every study below it.
        // Treat only the tight legend row, which owns exactly one settings action,
        // as a script instance. Otherwise one installed study is counted once for
        // every sibling study in the pane and the duplicate-layout guard fails shut.
        const settingsActionCount = await ancestor
          .locator('button[data-qa-id="legend-settings-action"]')
          .count()
          .catch(() => 0);
        if (settingsActionCount !== 1) continue;

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

// The script name also shows up in dialogs, menus, the Object Tree and the
// Pine dialog (measured 2026-07-31 during the CE10156 diagnosis). Text-first
// legend discovery must never resolve one of those as a legend row.
export const LEGEND_TEXT_EXCLUDED_SURFACES =
  '[role="dialog"], [data-name*="dialog" i], [class*="modal" i], [role="menu"], [data-name*="menu" i], [data-name="tree"], [data-name="pine-dialog"]';

export type LegendRowScanCounts = {
  /**
   * ROHTREFFER der Textsuche ueber alle Kandidatennamen. Die Schleife
   * verarbeitet je Name hoechstens 24 — uebersteigt matches die Summe der
   * uebrigen Zaehler, BENENNT das den Deckel, statt ihn zu verschweigen
   * (Review-Fund 27.8.: vorher stand hier der gedeckelte Wert, und
   * `matches=24` sah aus wie eine vollstaendige Messung).
   */
  matches: number;
  invisible: number;
  excluded: number;
  noWrapper: number;
  badText: number;
  actionCount: number;
  dup: number;
};

/**
 * Benennt die stillen Skip-Gruende eines leeren Zeilen-Scans.
 *
 * Messgrund (Ledger klasse-h, Lauf 32886027492, 2026-08-26): die Eskalation
 * meldete `escalation-rows SMC Long-Dip Alerts:0` — null Zeilen, waehrend
 * dieselbe Textsuche zwei Minuten vorher die Zeile fand. Die Spur nannte nur
 * das Endergebnis; WELCHER der sechs Filter jeden Treffer verwarf, war aus
 * dem Log nicht rekonstruierbar. Ein schweigender Zweig sieht aus wie ein
 * gesunder.
 */
export function formatLegendRowScanDetail(scan: LegendRowScanCounts): string {
  return `matches=${scan.matches}:invisible=${scan.invisible}:excluded=${scan.excluded}`
    + `:no-wrapper=${scan.noWrapper}:text=${scan.badText}:actions=${scan.actionCount}:dup=${scan.dup}`;
}

/**
 * Ist diese Knopf-Menge die einer EINZELNEN Legendenzeile?
 *
 * Messgrund (Lauf 32957051467, 2026-08-27 01:44/01:45Z — erste Auswertung
 * der #5098-Skip-Zaehler): beide Alerts-Scans starben mit `actions=1` — der
 * einzige sichtbare, nicht ausgeschlossene Kandidat fiel an der alten
 * Summenregel `count !== 1` ueber BEIDE Knopfarten, weil die Hover-Leiste
 * der Zeile Settings- UND More-Knopf traegt (Summe 2). Der Filter, der
 * Pane-Container aussieben soll, frass die Zielzeile — ausgerechnet auf dem
 * Eskalationspfad, der den Settings-Knopf klicken will.
 *
 * Der tragfaehige Container-Diskriminator ist die Zahl der SETTINGS-Knoepfe:
 * eine enge Zeile traegt genau einen (egal ob daneben ein More-Knopf steht),
 * ein Container mit N Zeilen traegt N. Zeilen ganz ohne Settings-Knopf
 * bleiben wie bisher ueber genau einen More-Knopf zugelassen.
 */
export function isSingleLegendRowActionSet(settingsCount: number, moreCount: number): boolean {
  if (settingsCount === 1) {
    return true;
  }
  return settingsCount === 0 && moreCount === 1;
}

/**
 * Text-first legend row discovery, for rows the button-first probes miss.
 *
 * Run 30702240413, same session, same DOM: {@link findLegendRowWrappers}
 * reported 0 rows for the pre-#4263 overlay instance while the text-first
 * settings opener found the row, hovered it and opened it — 60 rows, twice,
 * in two runs. TradingView renders the legend action buttons on hover, so a
 * probe that STARTS at the buttons never sees a row nobody is pointing at.
 * This starts at the visible legend text, hovers it (which is what makes the
 * action buttons the wrapper resolution needs exist), and only then resolves
 * the tight legend row exactly like the settings opener does.
 */
export async function findLegendRowWrappersByVisibleText(page: Page, scriptName: string): Promise<Locator[]> {
  const candidateNames = resolveOpenScriptSearchNames(scriptName);
  const patternsList = candidateNames.map((name) => buildScriptNamePatterns(name));
  const wrappers: Locator[] = [];
  const seenKeys = new Set<string>();
  const scan: LegendRowScanCounts = { matches: 0, invisible: 0, excluded: 0, noWrapper: 0, badText: 0, actionCount: 0, dup: 0 };

  for (const [index] of candidateNames.entries()) {
    const [, loosePattern] = patternsList[index];
    const matches = page.getByText(loosePattern);
    const total = await matches.count().catch(() => 0);
    scan.matches += total;  // Rohtreffer; die Schleife selbst deckelt bei 24
    for (let item = 0; item < Math.min(total, 24); item += 1) {
      const target = matches.nth(item);
      if (!(await target.isVisible({ timeout: 250 }).catch(() => false))) {
        scan.invisible += 1;
        continue;
      }
      const excluded = await target
        .evaluate((node, selector) => Boolean(node.closest(selector)), LEGEND_TEXT_EXCLUDED_SURFACES)
        .catch(() => true);
      if (excluded) {
        scan.excluded += 1;
        continue;
      }
      await target.scrollIntoViewIfNeeded().catch(() => undefined);
      await target.hover({ timeout: 750 }).catch(() => undefined);
      const wrapper = target
        .locator('xpath=ancestor::*[.//button[@data-qa-id="legend-settings-action"] or .//button[@data-qa-id="legend-more-action"]][1]')
        .first();
      if (!(await wrapper.isVisible({ timeout: 400 }).catch(() => false))) {
        scan.noWrapper += 1;
        continue;
      }
      const wrapperText = normalizeUiText((await wrapper.innerText({ timeout: 300 }).catch(() => "")) || "");
      if (!wrapperText || wrapperText.length > 300) {
        scan.badText += 1;
        continue;
      }
      // Tight row only — a pane container carries the text of every study
      // below it. Diskriminator ist die Zahl der SETTINGS-Knoepfe (siehe
      // isSingleLegendRowActionSet): die alte Summenregel ueber beide
      // Knopfarten frass eine echte Zeile mit Settings+More (Summe 2) —
      // Lauf 32957051467, actions=1 in beiden Alerts-Scans.
      const settingsActionCount = await wrapper
        .locator('button[data-qa-id="legend-settings-action"]')
        .count()
        .catch(() => 0);
      const moreActionCount = await wrapper
        .locator('button[data-qa-id="legend-more-action"]')
        .count()
        .catch(() => 0);
      if (!isSingleLegendRowActionSet(settingsActionCount, moreActionCount)) {
        scan.actionCount += 1;
        continue;
      }
      const box = await wrapper.boundingBox().catch(() => null);
      const key = box ? `${Math.round(box.x)}:${Math.round(box.y)}:${Math.round(box.width)}` : `${index}:${item}`;
      if (seenKeys.has(key)) {
        scan.dup += 1;
        continue;
      }
      seenKeys.add(key);
      wrappers.push(wrapper);
      tracePageEvent(page, "legend-text-wrapper-found", `${scriptName}:${item}:${wrapperText.slice(0, 80)}`);
    }
  }
  if (wrappers.length === 0) {
    // Lauf 32886027492 (escalation-rows :0): das Leer-Ergebnis MUSS seinen
    // Grund nennen — nur dann entscheidet der naechste natuerliche Fehlschlag,
    // welcher Filter greift. Auf dem Erfolgspfad keine zusaetzliche Spur.
    tracePageEvent(page, "legend-text-wrapper-scan-empty", `${scriptName}:${formatLegendRowScanDetail(scan)}`);
  }
  return wrappers.slice(0, 6);
}

/**
 * Count how many DISTINCT legend rows on the chart match {@link scriptName}.
 *
 * {@link findLegendRowWrappers} dedupes matched wrappers by their rendered text
 * (`${depth}:${text}`), so two copies of the SAME script — which share identical
 * legend text — collapse to a single wrapper. Using its `.length` as an instance
 * count therefore reports 2 identical scripts as 1, defeating the very
 * duplicate-detection the onboarding/verify ambiguity guards rely on. This
 * counts each matching legend settings button once instead, so accidental
 * duplicates report their true multiplicity.
 */
export async function countChartScriptInstances(
  page: Page,
  scriptName: string,
  options: VisibleChartScriptStateProbeOptions = {},
): Promise<number> {
  const candidateNames = resolveOpenScriptSearchNames(scriptName);
  const patternsList = candidateNames.map((name) => buildScriptNamePatterns(name));
  const buttonLimit = options.legendButtonLimit ?? 40;
  const visibleTimeoutMs = options.legendVisibleTimeoutMs ?? 250;
  const ancestorTextTimeoutMs = options.legendAncestorTextTimeoutMs ?? 300;

  const buttons = page.locator('button[data-qa-id="legend-settings-action"]');
  const buttonCount = await buttons.count().catch(() => 0);
  let instances = 0;

  for (let i = 0; i < Math.min(buttonCount, buttonLimit); i += 1) {
    const btn = buttons.nth(i);
    const visible = await btn.isVisible({ timeout: visibleTimeoutMs }).catch(() => false);
    if (!visible) continue;

    let matched = false;
    for (const depth of [1, 2, 3, 4, 5]) {
      const xpath = new Array(depth).fill("..").join("/");
      const ancestor = btn.locator(`xpath=${xpath}`);
      const text = normalizeUiText((await ancestor.innerText({ timeout: ancestorTextTimeoutMs }).catch(() => "")) || "");
      if (!text || text.length > 300) continue;

      for (const [index, candidate] of candidateNames.entries()) {
        const [, loosePattern, fuzzyPattern] = patternsList[index];
        if (loosePattern.test(text) || fuzzyPattern.test(text) || isLegendTruncatedMatch(text, candidate)) {
          const settingsActionCount = await ancestor
            .locator('button[data-qa-id="legend-settings-action"]')
            .count()
            .catch(() => 0);
          matched = settingsActionCount === 1;
          break;
        }
      }
      if (matched) break;
    }
    if (matched) instances += 1;
  }

  return instances;
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

// Measured 2026-07-31 at the identity-evidence probe: Object Tree entries
// live under [data-name="tree"] inside the right widgetbar.
export const OBJECT_TREE_PANEL_SELECTOR = '[data-name="tree"]';

// Candidates for the right-sidebar toggle that opens the Object Tree panel.
// Unlike the panel anchor above these are NOT live-measured yet — the first
// tree-removal run proves them. Kept as a family so one rename does not kill
// the path.
function objectTreeToggleLocators(page: Page): Locator[] {
  return [
    page.locator('button[data-name="object_tree"], [data-name="object-tree"], [data-name="objecttree"]'),
    page.getByRole("button", { name: /object tree/i }),
    page.locator('button[aria-label*="object tree" i], [data-tooltip*="object tree" i]'),
  ];
}

async function ensureObjectTreeVisible(page: Page): Promise<boolean> {
  const panel = page.locator(OBJECT_TREE_PANEL_SELECTOR).first();
  if (await panel.isVisible({ timeout: 300 }).catch(() => false)) {
    return true;
  }
  const opened = await clickVisibleWithFallback(
    page,
    objectTreeToggleLocators(page),
    "object-tree-open",
    1_500,
    300,
  ).catch(() => false);
  if (!opened) {
    return false;
  }
  await page.waitForTimeout(400);
  return await panel.isVisible({ timeout: 1_000 }).catch(() => false);
}

function objectTreeRowsForScript(page: Page, scriptName: string): Locator {
  const [, loosePattern] = buildScriptNamePatterns(scriptName);
  return page.locator(OBJECT_TREE_PANEL_SELECTOR).first().getByText(loosePattern);
}

/**
 * Operator-suggested removal path (2026-08-02): right sidebar -> Object Tree
 * -> right-click the entry -> Remove.
 *
 * Every other removal path anchors on the chart LEGEND row, which must first
 * be found by the button-first probe — and TradingView renders those buttons
 * on hover only, so the pre-#4263 overlay row was undiscoverable (0 wrappers
 * in 192ms across four detection variants) while plainly visible to a human,
 * who removed it by hand exactly this way. The Object Tree is a complete
 * inventory panel with stable rows, and the context menu needs no
 * hover-rendered buttons. The menu machinery (right-click, the Remove and
 * confirm locator families) already existed; only the tree as an anchor
 * surface was missing.
 *
 * Success is judged by the tree's OWN row count, never by
 * countChartScriptInstances — that probe is blind for exactly the rows this
 * path exists to remove, and consulting it would report every successful
 * tree removal as a failure.
 */
export async function removeChartScriptInstancesViaObjectTree(
  page: Page,
  scriptName: string,
  maxRemovals = 4,
): Promise<number> {
  if (!(await ensureObjectTreeVisible(page))) {
    tracePageEvent(page, "object-tree-unavailable", scriptName);
    return 0;
  }

  let removedCount = 0;
  for (let attempt = 0; attempt < maxRemovals; attempt += 1) {
    const rows = objectTreeRowsForScript(page, scriptName);
    const before = await rows.count().catch(() => 0);
    if (before === 0) {
      break;
    }
    const row = rows.first();
    if (!(await row.isVisible({ timeout: 400 }).catch(() => false))) {
      break;
    }
    await row.scrollIntoViewIfNeeded().catch(() => undefined);
    await row.click({ timeout: 800 }).catch(() => undefined); // highlight, as the operator does
    await row.click({ button: "right", timeout: 1_000, force: true }).catch(() => undefined);

    const clickedRemove = await clickVisibleWithFallback(
      page,
      scriptRemovalActionLocators(page),
      "object-tree-remove",
      1_200,
      300,
    ).catch(() => false);
    if (!clickedRemove) {
      tracePageEvent(page, "object-tree-remove-miss", `${scriptName}:${attempt}`);
      await closeModal(page).catch(() => undefined);
      break;
    }
    await clickVisibleWithFallback(
      page,
      scriptRemovalConfirmActionLocators(page),
      "object-tree-remove-confirm",
      1_000,
      300,
    ).catch(() => false);
    await page.waitForTimeout(400);

    const after = await objectTreeRowsForScript(page, scriptName).count().catch(() => before);
    if (after >= before) {
      tracePageEvent(page, "object-tree-remove-no-change", `${scriptName}:${attempt}:${before}->${after}`);
      break;
    }
    removedCount += before - after;
    tracePageEvent(page, "object-tree-remove-ok", `${scriptName}:${before}->${after}`);
  }
  return removedCount;
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

// Counts INSTANCES via countChartScriptInstances, not findLegendRowWrappers(...).length:
// the latter dedupes rows by legend text, so two identical copies collapse to 1 and a
// 2->1 removal is never observed as a decrease (the loop would burn the full timeout and
// mis-count removals). previousCount at the call site must be an instance count too.
export async function waitForChartScriptInstanceCountChange(
  page: Page,
  scriptName: string,
  previousCount: number,
  timeoutMs = 2_500,
): Promise<number> {
  const startedAt = Date.now();

  while (Date.now() - startedAt < timeoutMs) {
    const nextCount = await countChartScriptInstances(page, scriptName).catch(() => previousCount);
    if (nextCount < previousCount) {
      return nextCount;
    }
    await page.waitForTimeout(125);
  }

  return countChartScriptInstances(page, scriptName).catch(() => previousCount);
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

      let wrappers = await findLegendRowWrappers(page, scriptName).catch(() => []);
      if (wrappers.length === 0) {
        // Run 30702240413: the pre-#4263 overlay row was invisible to the
        // button-first probe above while the text-first settings opener found
        // and opened it. Without this fallback the stale instance survives
        // removal and the force-insert stacks a fresh copy next to it — which
        // is what five R4 readback runs then rebound into.
        wrappers = await findLegendRowWrappersByVisibleText(page, scriptName).catch(() => []);
        if (wrappers.length > 0) {
          tracePageEvent(page, "script-remove-text-fallback-found", `${scriptName}:${wrappers.length}`);
        }
      }
      if (wrappers.length === 0) {
        // Last resort, suggested by the operator after removing by hand what
        // four legend-probe variants could not find: the Object Tree lists
        // every applied object as a stable row and its context menu needs no
        // hover-rendered buttons. Zero tree removals means there is genuinely
        // nothing left to remove (or no tree) — then, as before, we stop.
        const treeRemoved = await removeChartScriptInstancesViaObjectTree(page, scriptName).catch(() => 0);
        if (treeRemoved > 0) {
          removedCount += treeRemoved;
          tracePageEvent(page, "script-remove-object-tree-fallback-ok", `${scriptName}:${treeRemoved}`);
          continue; // re-probe: further copies may now be discoverable
        }
        break;
      }

      const targetWrapper = wrappers[0] ?? wrappers[wrappers.length - 1];
      // Instance count, NOT wrappers.length: findLegendRowWrappers dedupes identical
      // rows, so N identical copies report as 1 and the removal accounting/detection
      // below (which compares against this) would never see a decrease.
      const previousCount = await countChartScriptInstances(page, scriptName).catch(() => wrappers.length);
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

        const remainingCount = await waitForChartScriptInstanceCountChange(page, scriptName, previousCount);
        if (remainingCount < previousCount) {
          removedCount += previousCount - remainingCount;
          tracePageEvent(page, "script-remove-ok", `${scriptName}:${previousCount}->${remainingCount}:direct`);
          await page.waitForTimeout(250);
          continue;
        }

        // `=> true`, not `=> false` (2026-08-15 sweep): a CRASHED visibility
        // probe (dead context, closed page) is not a cleared instance. With
        // `false` the failure counted as a removal AND emitted the success
        // trace `script-remove-ok:…:cleared:direct` -- a stale instance left
        // behind is the known measurement poison (UNIVERSE UNINIT, rebind
        // into the wrong dialog). The keyboard twin above already maps the
        // same failure to `true`, and refreshChartScriptInstance deliberately
        // probes residuals WITHOUT a catch for the same reason.
        const stillVisibleAfterDirectDelete = await isScriptStrictlyVisibleOnChartSurface(page, scriptName).catch(() => true);
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
        const remainingCount = await waitForChartScriptInstanceCountChange(page, scriptName, previousCount);
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

      const remainingCount = await waitForChartScriptInstanceCountChange(page, scriptName, previousCount);
      if (remainingCount < previousCount) {
        removedCount += previousCount - remainingCount;
        tracePageEvent(page, "script-remove-ok", `${scriptName}:${previousCount}->${remainingCount}`);
        await page.waitForTimeout(250);
        continue;
      }

      // Same decision as the direct-delete probe above: a crashed probe must
      // not read as "cleared".
      const stillVisible = await isScriptStrictlyVisibleOnChartSurface(page, scriptName).catch(() => true);
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
    // Remember the chart this refresh started on: ensurePineEditor's recovery
    // clicks can navigate the tab off the chart onto /pine-screener/ (CI run
    // 29946386778; two headed repros 2026-07-24). Off-chart, every editor and
    // script-open candidate misses until the outer 90s timer fires, so a URL
    // check + goto back converts that strand into a same-step retry.
    const originChartUrl = page.url();
    // Use the exact legend-instance probe for refresh safety. The broader chart
    // visibility probe also accepts "Strategy Report" plus a script-name text
    // match; after a successful removal TradingView can briefly retain those
    // texts outside the legend and make a cleared 1 -> 0 instance look stale.
    const initialCount = await countChartScriptInstances(page, scriptName).catch(() => 0);
    let removedCount = await removeVisibleChartScriptInstances(page, scriptName).catch(() => 0);
    const remainingCount = await countChartScriptInstances(page, scriptName).catch(() => initialCount);
    tracePageEvent(page, "script-refresh-instance-counts", `${scriptName}:${initialCount}->${remainingCount}`);

    if (initialCount > 0 && remainingCount > 0) {
      throw new Error(`Could not clear stale chart instance before refresh for ${scriptName}`);
    }

    // The counting probes above are button-first and were blind to exactly the
    // row this matters for (run 30702240413: overlay 0->0 while the row was
    // openable by text). Re-probe by TEXT and fail closed: inserting next to a
    // stale instance is how five runs rebound 60 sources into the wrong
    // dialog. No .catch on the probe — if it breaks, failing this step is
    // more honest than reading the breakage as "no residuals".
    let residualRows = await findLegendRowWrappersByVisibleText(page, scriptName);
    for (let extra = 0; residualRows.length > 0 && extra < 2; extra += 1) {
      tracePageEvent(page, "script-refresh-residual-text-rows", `${scriptName}:${residualRows.length}`);
      removedCount += await removeVisibleChartScriptInstances(page, scriptName).catch(() => 0);
      residualRows = await findLegendRowWrappersByVisibleText(page, scriptName);
    }
    if (residualRows.length > 0) {
      throw new Error(
        `Stale ${scriptName} instance still on the chart after removal (${residualRows.length} text-visible row(s))`,
      );
    }

    await ensurePineEditor(page).catch(() => undefined);
    if (originChartUrl.includes("/chart/") && !page.url().includes("/chart/")) {
      tracePageEvent(page, "script-refresh-strand-recovered", `${page.url()} -> ${originChartUrl}`);
      await gotoChart(page, originChartUrl);
      await ensurePineEditor(page).catch(() => undefined);
    }
    await openExistingScript(page, scriptName).catch(() => undefined);
    await addCurrentScriptToChart(page, scriptName, { forceInsert: true, stepTimeoutMs: Math.max(stepTimeoutMs(), 90_000) });
    await page.waitForTimeout(1_250);
    return removedCount;
  // This is a composite operation: removal, editor recovery, script lookup and
  // chart insertion each have their own tracked work. A normal CI run observed
  // the insertion effect at 44s, then the default 45s outer timer closed the
  // otherwise healthy session. Keep operator overrides, but provide enough
  // floor for the whole refresh transaction.
  }, Math.max(stepTimeoutMs(), 90_000));
}

export type AppliedInstanceSource = {
  pane: number;
  entityId: string | null;
  sha256: string | null;
  length: number;
  error: string;
};

/**
 * Which applied instances of `expectedSha256` are stale (or unreadable).
 *
 * 2026-10-05: a green producer refresh (save v435 + remove/re-add, 131 bindings
 * repaired) left BOTH Suite instances on vWgAWyfC — one per chart pane — on old
 * source (220 105 / 220 030 chars, neither carrying the new code). The refresh
 * counted one instance per layout and never looked at what the panes actually
 * run. Pure, so the verdict is provable without a browser.
 */
export function staleAppliedInstances(instances: AppliedInstanceSource[], expectedSha256: string): AppliedInstanceSource[] {
  return instances.filter((instance) => instance.sha256 !== expectedSha256);
}

/**
 * Read the source each chart pane's applied instance of `scriptName` carries.
 *
 * The legend's "Source code" action opens the source OF THAT INSTANCE (measured
 * 2026-10-05: it showed the old code while the saved slot held v435), so this is
 * the ground truth for "what does the chart compute". A docked Pine editor is
 * closed first and after each read; its title-bar Close button sits outside the
 * scope closePineEditorIfVisible searches.
 */
export async function readAppliedInstanceSources(page: Page, scriptName: string): Promise<AppliedInstanceSource[]> {
  const closeEditor = async () => {
    if (await page.locator("#pine-editor-dialog").first().isVisible().catch(() => false)) {
      await page.locator('button[aria-label="Close"][title="Close"]').first().click().catch(() => undefined);
      await page.waitForTimeout(1_500);
    }
  };
  await closeEditor();
  const panes = page.locator('[data-qa-id="chart-container"]');
  const paneCount = await panes.count();
  const out: AppliedInstanceSource[] = [];
  for (let pane = 0; pane < paneCount; pane += 1) {
    const rows = panes.nth(pane).locator('[data-qa-id="legend-source-item"]').filter({ hasText: scriptName });
    const rowCount = await rows.count();
    for (let r = 0; r < rowCount; r += 1) {
      const row = rows.nth(r);
      const entityId = await row.getAttribute("data-entity-id").catch(() => null);
      try {
        await row.locator('[data-qa-id*="legend-source-title"]').first().hover({ force: true });
        await page.waitForTimeout(400);
        await row.locator('[data-qa-id="legend-pine-action"]').click({ force: true });
        const source = await readEditorContent(page, { expectedDeclarationTitle: scriptName });
        out.push({ pane, entityId, sha256: normalizedPineSha256(source), length: source.length, error: "" });
      } catch (error) {
        out.push({ pane, entityId, sha256: null, length: 0, error: String((error as Error)?.message ?? error).slice(0, 300) });
      }
      tracePageEvent(page, "applied-instance-source", `${scriptName}:pane=${pane}:${entityId}:${out.at(-1)?.sha256?.slice(0, 12) ?? "unreadable"}`);
      await closeEditor();
    }
  }
  return out;
}

/**
 * Where to double-click inside a legend row, guaranteed to land INSIDE it.
 *
 * Pure so it can be proven without a browser; the DOM hit-test that follows it
 * is Playwright-against-TradingView and is only proven by the next CI run.
 *
 * The offsets aim a little inside the row rather than at its centre, because a
 * legend row's centre can sit under the hover toolbar TradingView renders over
 * it. They used to be applied UNCLAMPED:
 *
 *     x + max(16, min(56, width * 0.25))
 *     y + max(6, min(height / 2, max(height - 6, 6)))
 *
 * For a row of height <= 5 or width <= 16 — a clipped or partially scrolled row
 * reports exactly that — the result lies OUTSIDE the element: 16px to the right
 * of a 10px-wide row, or 6px below a 4px-tall one. `page.mouse.dblclick` takes
 * raw viewport coordinates and has no actionability check, so it then opens
 * whatever IS painted there: the NEIGHBOURING legend row.
 *
 * Measured on 2026-08-22 (runs 758 and 771): every attempt to open
 * `SMC Long-Dip Alerts` opened the dialog of `SMC Setup Check` or
 * `SMC Breakout Overlay` — its two neighbours in the rollout order — and
 * targeting Setup Check opened Long-Dip Alerts. The identity guard rejected
 * each wrong dialog correctly, so nothing wrong was written, but the step burnt
 * its full 60s budget twice per run and the layout repair stopped there.
 */
export type LegendRowGeometry = {
  text: string;
  box: { x: number; y: number; width: number; height: number };
};

/** TradingView's legend row. Same selector the shared test fixture models. */
const LEGEND_SOURCE_ITEM_SELECTOR = '[data-name="legend-source-item"]';

/** Script name to a safe file-name fragment: "SMC Long-Dip Alerts" -> "smc-long-dip-alerts". */
export function slugifyForPath(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60) || "unnamed";
}

export type LegendFailureEvidence = {
  scriptName: string;
  capturedAt: string;
  /**
   * Welcher Weg die Zeilen geliefert hat. Ohne dieses Feld ist eine leere
   * `neighbourhood` nicht von "falsch gesucht" zu unterscheiden — genau die
   * Verwechslung, die Lauf 32556181388 erzeugt hat.
   */
  rowSource: "legend-source-item" | "visible-text";
  /** The target row and its vertical neighbours, or [] when it was not found. */
  neighbourhood: LegendRowGeometry[];
  /** Where a double-click would have gone, and what actually sits there. */
  aim: { point: { x: number; y: number }; topElement: string } | null;
  screenshotPath: string;
  /**
   * Ledger klasse-h, Kandidat (A): war GENAU in dem Moment, in dem dieser
   * Fehlschlag deklariert wird, ein Dialog sichtbar -- und trug er den Titel
   * des Zielskripts? Dieselbe Pruefung (collectVisibleDialogSnapshots +
   * pickDialogForScript), die die Leiter vorher hat scheitern lassen, nur
   * nachtraeglich an derselben Stelle, statt an einer zweiten.
   *
   * "target-visible" bewiese (A): der Dialog war schon da, nur die Erkennung
   * war schon fertig. "no-dialog" oder "foreign-visible" widerlegen (A) an
   * dieser Stelle: der Zieldialog stand zu diesem Zeitpunkt schlicht nicht
   * auf dem Schirm. Vier explizite Werte statt eines Booleans, weil "kein
   * Dialog", "Dialog ohne lesbaren Titel" und "Messung fehlgeschlagen" sonst
   * ununterscheidbar waeren -- genau die Verwechslung, an der
   * `neighbourhood: []` schon einmal gescheitert ist.
   */
  dialogAtFailureVerdict: DialogAtFailureVerdict | "probe-failed";
  /** Titel des zum Messzeitpunkt gefundenen Dialogs, falls einer da war; sonst null. */
  dialogAtFailureTitle: string | null;
  /** Wie viele BETITELTE Dialoge gleichzeitig sichtbar waren (wie DialogPick.visibleCount). */
  dialogAtFailureVisibleCount: number;
  /** Nur bei "probe-failed" belegt: warum die Messung selbst scheiterte. */
  dialogAtFailureReason: string;
};

/**
 * Whether a legend row belongs to `scriptName`.
 *
 * TradingView appends a version chip ("SMC Setup Check · 8.0"), so the row text
 * is longer than the name — but a bare `startsWith` would be useless here:
 * "SMC Long-Dip" prefixes four real script names, and Dashboard / Strategy /
 * Alerts / Mobile would all match each other. The name must be followed by a
 * separator, or be the whole text.
 */
function legendRowBelongsToScript(text: string, scriptName: string): boolean {
  const rowText = normalizeUiText(text);
  const name = normalizeUiText(scriptName);
  if (!rowText || !name) return false;
  if (rowText === name) return true;
  if (!rowText.startsWith(name)) return false;
  // Only the version chip may follow. A SPACE is not a valid separator: script
  // names contain spaces, so "SMC Long-Dip" would swallow "SMC Long-Dip
  // Dashboard" and the neighbourhood would describe the wrong row.
  return /^\s*·/.test(rowText.slice(name.length));
}

/**
 * The target legend row plus the rows directly above and below it.
 *
 * Written down as failure evidence because a mis-aimed double-click hits a
 * NEIGHBOUR: on 2026-08-22 every attempt to open `SMC Long-Dip Alerts` opened
 * `SMC Setup Check` or `SMC Breakout Overlay`, and nothing recorded where those
 * rows actually were — so the geometry had to be inferred instead of read.
 *
 * Neighbourhood is vertical position, not DOM order. An absent target yields
 * nothing rather than a guess: evidence that quietly describes the wrong row is
 * worse than evidence that says it could not find the row.
 */
export function selectLegendNeighbourhood(
  rows: readonly LegendRowGeometry[],
  scriptName: string,
): LegendRowGeometry[] {
  const ordered = [...rows].sort((a, b) => a.box.y - b.box.y);
  const index = ordered.findIndex((entry) => legendRowBelongsToScript(entry.text, scriptName));
  if (index === -1) return [];
  return ordered.slice(Math.max(0, index - 1), index + 2);
}

/**
 * Everything a 3am reader needs about a target that never opened: a full-page
 * screenshot, the geometry of its legend row and its neighbours, and what
 * actually sits at the point a double-click would have gone to.
 *
 * Written only when a target has failed for good — one file pair per failed
 * script, nothing on a green run. The 2026-08-22 diagnosis needed exactly this
 * and had to infer it instead: the run left a bindings snapshot and trace lines,
 * but no record of where any row was.
 *
 * Best-effort by construction. This runs on a page that has ALREADY failed, so
 * every probe here can fail too; a partial evidence file beats throwing a second
 * error over the first one and losing both.
 */
export async function captureLegendFailureEvidence(
  page: Page,
  scriptName: string,
  runId: string,
): Promise<LegendFailureEvidence> {
  const evidence: LegendFailureEvidence = {
    scriptName,
    capturedAt: utcNow(),
    rowSource: "legend-source-item",
    neighbourhood: [],
    aim: null,
    screenshotPath: "",
    dialogAtFailureVerdict: "probe-failed",
    dialogAtFailureTitle: null,
    dialogAtFailureVisibleCount: 0,
    dialogAtFailureReason: "",
  };

  // Klasse-H-Messprobe (Kandidat A), zuerst und lesend: BEVOR irgendetwas
  // anderes hier den Zustand der Seite noch anfasst, festhalten, welcher
  // Dialog (falls einer) genau jetzt sichtbar ist. Wiederverwendet dieselben
  // Bausteine wie die Erkennungsstufe selbst (collectVisibleDialogSnapshots,
  // pickDialogForScript ueber classifyDialogAtFailure) statt einer zweiten
  // Fassung derselben Pruefung.
  try {
    const dialogsAtFailure = await collectVisibleDialogSnapshots(page);
    const classified = classifyDialogAtFailure(dialogsAtFailure, scriptName);
    evidence.dialogAtFailureVerdict = classified.verdict;
    evidence.dialogAtFailureTitle = classified.title;
    evidence.dialogAtFailureVisibleCount = classified.visibleCount;
  } catch (error) {
    evidence.dialogAtFailureVerdict = "probe-failed";
    evidence.dialogAtFailureReason = `probe-failed: ${String((error as Error)?.message ?? error)}`;
  }

  evidence.screenshotPath = await takeScreenshot(page, runId, `settings-failure-${slugifyForPath(scriptName)}`)
    .catch(() => "");

  // Zwei Wege, weil der erste nachweislich leer ausgehen kann.
  //
  // `[data-name="legend-source-item"]` stammt aus einer Test-Fixture dieses
  // Repos, nicht aus gemessenem TradingView-DOM. Lauf 32556181388 (2026-08-22)
  // hat das live gezeigt: die Beweisdatei entstand, aber `aim` blieb null und
  // die Warnung trug kein `click point hit` — die Zielzeile war in der
  // Nachbarschaft nicht enthalten. Der Produktionscode dieses Repos sucht
  // Legendenzeilen deshalb seit dem 2026-07-Vorfall ueber TEXT statt ueber
  // Attribute (findLegendRowWrappersByVisibleText): ein Attribut-Selektor auf
  // der Legende ist hier bekannt fragil.
  //
  // Der Attribut-Weg bleibt zuerst, weil er die ganze Legende liefert und damit
  // echte Nachbarn kennt; der Text-Weg liefert nur die Zielzeile, aber lieber
  // eine Zeile mit Geometrie als eine leere Datei, die wie "nichts gefunden"
  // aussieht und in Wahrheit "falsch gesucht" heisst.
  const rows = await page
    .evaluate((rowSelector) => {
      const items = Array.from(document.querySelectorAll(rowSelector));
      return items.map((item) => {
        const rect = item.getBoundingClientRect();
        return {
          text: ((item as HTMLElement).innerText ?? item.textContent ?? "").trim().slice(0, 120),
          box: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
        };
      });
    }, LEGEND_SOURCE_ITEM_SELECTOR)
    .catch(() => [] as LegendRowGeometry[]);
  evidence.rowSource = rows.length > 0 ? "legend-source-item" : "visible-text";

  if (rows.length === 0) {
    const wrappers = await findLegendRowWrappersByVisibleText(page, scriptName).catch(() => []);
    for (const wrapper of wrappers) {
      const box = await wrapper.boundingBox().catch(() => null);
      if (!box) continue;
      const text = await wrapper.innerText().catch(() => "");
      rows.push({ text: (text || scriptName).trim().slice(0, 120), box });
    }
  }

  evidence.neighbourhood = selectLegendNeighbourhood(rows, scriptName);

  const targetRow = evidence.neighbourhood.find((entry) => legendRowBelongsToScript(entry.text, scriptName));
  if (targetRow && !legendBoxIsTooSmallToClick(targetRow.box)) {
    const point = resolveLegendDoubleClickPoint(targetRow.box);
    const topElement = await page
      .evaluate((at) => {
        const top = document.elementFromPoint(at.x, at.y);
        if (!top) return "none";
        const label = ((top as HTMLElement).innerText ?? top.textContent ?? "").trim();
        return label.slice(0, 120) || top.nodeName;
      }, point)
      .catch(() => "unknown");
    evidence.aim = { point, topElement };
  }

  return evidence;
}

/**
 * Write the evidence next to its screenshot and return the path.
 *
 * Same directory as `takeScreenshot`, so one upload step collects both and the
 * `.json` sits beside the `.png` it explains.
 */
export function writeLegendFailureEvidence(evidence: LegendFailureEvidence): string {
  const dir = process.env.TV_SCREENSHOT_DIR || "automation/tradingview/reports/screenshots";
  fs.mkdirSync(dir, { recursive: true });
  const base = evidence.screenshotPath
    ? path.basename(evidence.screenshotPath).replace(/\.png$/, "")
    : `settings-failure-${slugifyForPath(evidence.scriptName)}`;
  const filePath = path.join(dir, `${base}.json`);
  fs.writeFileSync(filePath, `${JSON.stringify(evidence, null, 2)}\n`, "utf-8");
  return filePath;
}

export function resolveLegendDoubleClickPoint(
  box: { x: number; y: number; width: number; height: number },
): { x: number; y: number } {
  // A degenerate box has no interior to aim at; the caller must not click it.
  const insetX = Math.max(16, Math.min(56, box.width * 0.25));
  const insetY = Math.max(6, Math.min(box.height / 2, Math.max(box.height - 6, 6)));
  // Clamp strictly inside: an offset equal to the extent is already the first
  // pixel of whatever is drawn next to this row.
  const safeX = Math.min(insetX, Math.max(box.width / 2, box.width - 1));
  const safeY = Math.min(insetY, Math.max(box.height / 2, box.height - 1));
  return { x: box.x + safeX, y: box.y + safeY };
}

/** A box too small to aim into at all — clicking it can only hit a neighbour. */
export function legendBoxIsTooSmallToClick(
  box: { width: number; height: number },
): boolean {
  return box.width < 2 || box.height < 2;
}

/**
 * Ledger klasse-h, offene Messfrage (Lauf 32803019213): das BEWIESENE
 * Phaenomen ist ein stabiler Treffer auf den Legenden-NACHBARN, nicht ein
 * zufaelliger Fehlklick -- ob ein mehrzeiliger Wrapper die Klickgeometrie
 * verschiebt oder TradingView die Zeile intern falsch zuordnet, ist noch
 * NICHT geklaert. Beim naechsten natuerlichen Fehlschlag entscheidet die
 * Boxhoehe in dieser Spur: ~20px = Einzelzeile (TV-Fehlzuordnung), ~40px+ =
 * mehrzeiliger Wrapper (der Klick landet geometrisch auf dem Nachbarn).
 *
 * Reine Formatierung, ohne Browser beweisbar -- box und point kommen
 * unveraendert aus tryOpenScriptSettingsByDoubleClick herein. Kein
 * Verhaltenseingriff, nur ein zusaetzliches Detail an einer bestehenden
 * Trace-Zeile (dblclick-start).
 */
export function formatLegendDblclickBoxDetail(
  box: { x: number; y: number; width: number; height: number },
  point: { x: number; y: number },
): string {
  const offsetX = Math.round(point.x - box.x);
  const offsetY = Math.round(point.y - box.y);
  return `${Math.round(box.width)}x${Math.round(box.height)}@${offsetX},${offsetY}`;
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

  if (legendBoxIsTooSmallToClick(box)) {
    // Clicking a degenerate box cannot hit it; the DOM gesture below still can.
    tracePageEvent(
      page,
      `${traceStartEvent}-box-degenerate`,
      `${traceDetail}:${Math.round(box.width)}x${Math.round(box.height)}`,
    );
    const domOnly = await dispatchDomMouseGesture(target, "dblclick").catch(() => false);
    if (domOnly) {
      tracePageEvent(page, `${traceStartEvent}-dom`, traceDetail);
      await page.waitForTimeout(350);
      if (await settleSettingsOpen()) {
        tracePageEvent(page, `${traceOkEvent}-dom`, traceDetail);
        return true;
      }
    }
    return false;
  }

  const { x: doubleClickX, y: doubleClickY } = resolveLegendDoubleClickPoint(box);

  // Does that point actually belong to this row? `page.mouse.dblclick` has no
  // actionability check, so without this a covered, clipped or just-relaid-out
  // row silently sends the double-click to whatever is painted on top — which
  // is how targeting one script opened its neighbour's settings for a whole
  // day. A foreign hit is now NAMED instead of surfacing as a 60s timeout.
  const hitOwner = await target
    .evaluate((element, point) => {
      const top = document.elementFromPoint(point.x, point.y);
      if (!top) return "none";
      if (element === top || element.contains(top) || top.contains(element)) return "self";
      const label = (top as HTMLElement).innerText ?? top.textContent ?? "";
      return `foreign:${label.trim().slice(0, 60) || top.nodeName}`;
    }, { x: doubleClickX, y: doubleClickY })
    .catch(() => "unknown");
  if (hitOwner !== "self") {
    tracePageEvent(page, `${traceStartEvent}-hit-target-miss`, `${traceDetail}:${hitOwner}`);
    // Re-measure once after scrolling it in: a row that merely drifted is
    // cheap to recover, and the DOM gesture below covers what scrolling cannot.
    await target.scrollIntoViewIfNeeded().catch(() => undefined);
    const rebox = await target.boundingBox().catch(() => null);
    if (rebox && !legendBoxIsTooSmallToClick(rebox)) {
      const retry = resolveLegendDoubleClickPoint(rebox);
      // Review I4: this retry is exactly the case a mislaid wrapper is most
      // likely to explain (hit-target-miss already fired) — it must carry
      // the same box/offset detail as the normal click, not go blind.
      tracePageEvent(
        page,
        `${traceStartEvent}-hit-target-remeasured`,
        `${traceDetail}:${formatLegendDblclickBoxDetail(rebox, retry)}`,
      );
      await page.mouse.dblclick(retry.x, retry.y).catch(() => undefined);
      await page.waitForTimeout(350);
      if (await settleSettingsOpen()) {
        return true;
      }
    }
  }
  tracePageEvent(page, traceStartEvent, `${traceDetail}:${formatLegendDblclickBoxDetail(box, { x: doubleClickX, y: doubleClickY })}`);
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

async function dismissSymbolSearchDialog(page: Page, timeoutMs = 750): Promise<boolean> {
  const dialog = page
    .locator(
      '#overlap-manager-root [role="dialog"], #overlap-manager-root [class*="dialog" i], #overlap-manager-root [data-name*="dialog" i]',
    )
    .filter({ hasText: /add symbol/i })
    .last();

  if (!(await dialog.isVisible({ timeout: 200 }).catch(() => false))) {
    return false;
  }

  tracePageEvent(page, "dismiss-symbol-search", "found");
  const closeButton = dialog
    .locator('[data-name="close"], button[aria-label*="close" i], [class*="close" i]')
    .first();
  if (await closeButton.isVisible({ timeout: 200 }).catch(() => false)) {
    await closeButton.click({ timeout: timeoutMs }).catch(() => undefined);
  }

  if (await dialog.isVisible({ timeout: 200 }).catch(() => false)) {
    await page.keyboard.press("Escape").catch(() => undefined);
    await page.waitForTimeout(200).catch(() => undefined);
  }

  const dismissed = !(await dialog.isVisible({ timeout: 200 }).catch(() => false));
  tracePageEvent(page, "dismiss-symbol-search", dismissed ? "dismissed" : "still-visible");
  return dismissed;
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

/**
 * Best-effort: dismiss the Pine editor so it stops covering chart surfaces.
 *
 * Returns whether the editor is gone — `true` also when none was open.
 *
 * 2026-08-01, CORRECTION. This comment used to state that "TradingView serves
 * no close affordance for this panel at all". That is FALSE. The operator's
 * screenshot of the docked panel shows minimise / expand / X in the panel
 * chrome, and reports the X present on every chart and every layout. The
 * earlier claim generalised a single probe of one layout (vWgAWyfC, 2026-07-22)
 * into a statement about the product, and because it was written as settled
 * nobody looked again for ten days.
 *
 * What the traces actually said was never evidence for that claim either:
 * `pine-editor-close-candidate-miss-summary count:2` counts candidate LOCATORS
 * that yielded nothing visible, not elements found. Both families below match
 * on an English accessible name or `aria-label="Close"`; the real controls are
 * icon-only, so the helper has been searching for a button that was never the
 * one on screen.
 *
 * The fix is deliberately NOT a positional guess. The same panel chrome carries
 * Publish and Add-to-chart, and a mis-aimed click there is a live action on the
 * operator's account. The failed-close path therefore ENUMERATES the controls
 * into the trace instead of aiming at them. Callers still treat a `false` as
 * normal and stay correct with the editor open.
 *
 * MEASURED 2026-08-01, read-only run 30716530874. The inventory found eight
 * button-like elements inside the dialog subtree and NO close control among
 * them: the script-title dropdown, Add-to-chart, one untitled 34x34 button,
 * Publish, More, and three status-bar items. In the session the storage state
 * renders, the panel is right-docked WITHOUT the window chrome the operator's
 * own browser shows (back-arrow / "Pine Editor" / minimise / expand / X). Both
 * statements are true at once: the operator's X exists, and this session has
 * nothing to click. Scope honestly stated: the enumeration covered
 * `button, [role="button"], [data-name]` under the dialog root only — chrome
 * living outside that subtree, or rendered as plain icon divs, would not
 * appear. So this helper stays advisory-false by measurement, not by claim.
 */
export async function closePineEditorIfVisible(page: Page): Promise<boolean> {
  const dialog = await firstVisibleLocator(
    page.locator('#pine-editor-dialog, [data-name="pine-dialog"], [id*="pine-editor" i]'),
    500,
  );
  if (!dialog) {
    return true;
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

  const dialogStillVisible = await dialog.isVisible({ timeout: 500 }).catch(() => false);
  if (!dialogStillVisible) {
    tracePageEvent(page, "pine-editor-close-ok");
    return true;
  }

  // 2026-10-07: the dialog-scoped candidates above never reach the docked editor's own Close:
  // it sits in the title bar above the dialog. Pinned by measurement, not aimed: exact
  // aria-label AND title "Close", inside the editor's span (pineEditorTitleBarClose).
  // It runs BEFORE the read-only inventory below, which stays click-free. Every producer
  // refresh since 2026-10-06 timed out behind this ("pine-editor-docked-not-closeable",
  // then the add-to-chart legend check saw a squeezed legend; tv-save run 37549435565).
  const titleBarClose = await pineEditorTitleBarClose(page, dialog);
  if (titleBarClose) {
    await titleBarClose.click().catch(() => undefined);
    await page.waitForTimeout(1_000);
    if (!(await dialog.isVisible({ timeout: 500 }).catch(() => false))) {
      tracePageEvent(page, "pine-editor-close-ok-titlebar");
      return true;
    }
  }

  // The selectors above missed. Rather than assert again that nothing exists,
  // read the panel's controls out and put them in the trace. Attributes only --
  // no click, no keyboard, nothing that could reach Publish or Add-to-chart.
  // The next change pins the real control against THIS output instead of
  // against a guess about how TradingView labels its buttons.
  const controls = await dialog
    .evaluate((root: Element) =>
      Array.from(root.querySelectorAll('button, [role="button"], [data-name]'))
        .slice(0, 40)
        .map((element, index) => {
          const box = element.getBoundingClientRect();
          return {
            i: index,
            tag: element.tagName.toLowerCase(),
            dataName: element.getAttribute("data-name"),
            ariaLabel: element.getAttribute("aria-label"),
            title: element.getAttribute("title"),
            text: (element.textContent ?? "").trim().slice(0, 24),
            cls: (element.getAttribute("class") ?? "").slice(0, 60),
            x: Math.round(box.x),
            y: Math.round(box.y),
            w: Math.round(box.width),
            h: Math.round(box.height),
          };
        }),
    )
    .catch(() => null);
  tracePageEvent(
    page,
    "pine-editor-close-control-inventory",
    controls ? JSON.stringify(controls) : "unreadable",
  );

  // Still unresolved and NOT to be assumed either way: whether the docked state
  // lives in the saved layout (server-side, so a CI run could close it for the
  // operator) or in the browser profile the storage state was captured from (in
  // which case closing it here changes nothing on the operator's screen). The
  // earlier comment asserted the former without measuring it.
  //
  // Evidence so far, 2026-08-01, listed without concluding: the operator closed
  // the panel in their browser (~19:0xZ) and CI runs at 18:50Z and 19:5xZ both
  // still saw it open — and both editors showed the SAME script (SMC HTF
  // Confluence). Consistent with: which script is open is server-side, whether
  // the panel shows (and its dock mode) is client-side per browser profile.
  // Also consistent with the operator simply not having saved. Not settled.
  tracePageEvent(page, "pine-editor-docked-not-closeable");
  return false;
}

/**
 * Persist the current chart layout to the server so binding/source mutations
 * survive the session. The settings "submit" click only updates the in-memory
 * indicator instance — without this save, a fresh session (and the operator's
 * reloaded chart) reverts to the last SAVED layout, so a force-rebind that
 * reads back "bound" in its own session silently does not stick (2026-07-25:
 * consumers stayed on "Close" on the live chart while every rebind run
 * reported mismatches:0).
 *
 * The mechanics live in tv_layout_save.ts, shared with the onboarding package:
 * the save counts when TradingView answered `POST /api/v1/charts/save/`, not
 * when a header control changed its label. A button that reports nothing to
 * save is believed (measured, see that file), so this is a no-op on a layout
 * TradingView's autosave already persisted.
 */
export async function saveChangedChartLayout(page: Page): Promise<void> {
  await runTrackedStep(page, "saveChangedChartLayout", async () => {
    await dismissPromotionOverlay(page);
    const outcome = await saveChartLayout(page);
    tracePageEvent(page, "chart-layout-saved", `${outcome.trigger} control=${outcome.control} http=${outcome.status}`);
  });
}

export async function openExistingScript(
  page: Page,
  scriptName: string,
  options: {
    forceSelection?: boolean;
    requireVisibleDeclarationIdentity?: boolean;
    allowDeclarationDriftRepair?: boolean;
  } = {},
): Promise<boolean> {
  const timing = resolveOpenScriptTiming();
  return runTrackedStep(page, `openExistingScript:${scriptName}`, async () => {
    const identityNames = openScriptIdentityNames(scriptName);
    const selectionAttempts = resolveOpenScriptSelectionAttempts(scriptName);
    // The title is not sufficient proof that the corresponding Monaco model is
    // active. TradingView can retain a previous script buffer while repainting
    // the requested title after a publish/save transition. Worse, the identity
    // families scan the whole page, so with the script ON THE CHART the legend
    // row satisfies them while the editor sits on an untouched "Untitled
    // script" draft — observed live 2026-07-31 during the CE10156 diagnosis,
    // where this fast path returned true without touching the editor. The
    // Monaco-model declaration can only come from the editor buffer, so the
    // fast path requires it unconditionally; when it cannot be proven the
    // function just proceeds to the picker, which is what it would do anyway.
    const uiAlreadyOpen = options.forceSelection
      ? false
      : await waitForAnyOpenScriptIdentity(page, identityNames, 750).catch(() => false);
    const alreadyOpen = uiAlreadyOpen
      && await waitForVisiblePineDeclarationIdentity(page, identityNames, 1_500).catch(() => false);
    if (alreadyOpen) {
      tracePageEvent(page, "open-script-identity-current", scriptName);
      return true;
    }

    for (let attempt = 0; attempt < selectionAttempts.length; attempt += 1) {
      const selectionAttempt = selectionAttempts[attempt] ?? {
        searchName: scriptName,
        exactTitleOnly: true,
      };
      const { searchName, exactTitleOnly: exactTitleRetry } = selectionAttempt;
      // A saved TradingView document can have the correct private-script
      // title while its current Pine source declares another consumer. That
      // is precisely the state this rollout must repair. Capture the visible
      // source before opening the picker so repair authority can require an
      // actual, stable Monaco-buffer transition in addition to the canonical
      // document title and the closed picker. A repainted title alone remains
      // insufficient.
      const repairBaseline = options.allowDeclarationDriftRepair && searchName === scriptName
        ? await readVisiblePineEditorSource(page)
        : null;
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

      const rowCandidates = exactTitleRetry
        ? tvSelectors.openScriptExactTitle(page, searchName)
        : tvSelectors.openScriptRow(page, searchName);
      const clickedScript = await clickVisibleWithFallback(
        page,
        rowCandidates,
        exactTitleRetry ? "open-script-exact-title" : "open-script-row",
        3_000,
        1_000,
      );
      await page.waitForTimeout(750);

      let dialogStillVisible = await hasVisibleOpenScriptSurface(page, 750);

      if (dialogStillVisible && clickedScript) {
        await doubleClickVisible(
          page,
          rowCandidates,
          exactTitleRetry ? "open-script-exact-title-confirm" : "open-script-row-confirm",
          2_000,
          1_000,
        );
        dialogStillVisible = await hasVisibleOpenScriptSurface(page, 750);
      }

      if ((!clickedScript || dialogStillVisible)) {
        await page.keyboard.press("ArrowDown").catch(() => undefined);
        await page.keyboard.press("Enter").catch(() => undefined);
        await page.waitForTimeout(1_000);
      }

      const identityVerified = await waitForAnyOpenScriptIdentity(page, identityNames);
      const canonicalIdentityVerified = options.allowDeclarationDriftRepair && searchName === scriptName
        ? await waitForAnyOpenScriptIdentity(page, [scriptName], 1_500)
        : false;
      const declarationVerified = identityVerified
        && options.requireVisibleDeclarationIdentity
        && await waitForVisiblePineDeclarationIdentity(
          page,
          identityNames,
          options.allowDeclarationDriftRepair ? 1_500 : timing.modelSettleTimeoutMs,
        ).catch(() => false);
      const sourceTransitionVerified = identityVerified
        && canonicalIdentityVerified
        && options.allowDeclarationDriftRepair
        && repairBaseline !== null
        && await waitForStableVisiblePineSourceTransition(
          page,
          repairBaseline,
          timing.modelSettleTimeoutMs,
        ).catch(() => false);
      const modelIdentityVerified = !options.requireVisibleDeclarationIdentity
        || declarationVerified
        || sourceTransitionVerified;
      if (identityVerified && modelIdentityVerified) {
        if (sourceTransitionVerified && !declarationVerified) {
          tracePageEvent(
            page,
            "open-script-declaration-drift-repair",
            `${scriptName}:search=${searchName}`,
          );
        }
        if (searchName !== scriptName) {
          tracePageEvent(page, "open-script-legacy-alias", `${scriptName}<=${searchName}`);
        }
        return true;
      }

      if (identityVerified && !modelIdentityVerified) {
        tracePageEvent(
          page,
          "open-script-visible-declaration-retry",
          `${scriptName}:attempt=${attempt + 1}:search=${searchName}`,
        );
      }
      tracePageEvent(page, "open-script-identity-retry", `${scriptName}:attempt=${attempt + 1}:search=${searchName}`);
      await page.keyboard.press("Escape").catch(() => undefined);
      await ensurePineEditor(page).catch(() => undefined);
      await page.waitForTimeout(500);
    }

    return false;
  }, timing.stepTimeoutMs);
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

export async function setEditorContent(
  page: Page,
  code: string,
  options: { editorAlreadyOpen?: boolean } = {},
): Promise<void> {
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
      if (!options.editorAlreadyOpen) await ensurePineEditor(page);
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

      // Re-seed the clipboard with a marker BEFORE copying the editor back.
      // Without it the readback below compares `code` against the very value
      // this function put on the clipboard 20 lines ago: a copy that never
      // lands (focus lost, Monaco not focused, an overlay in front) leaves the
      // original write in place and the comparison succeeds while the editor is
      // untouched. The read path in this module has guarded against exactly
      // this since it was written — "so a copy that never lands cannot
      // masquerade as source".
      const clipboardMarker = `tv-editor-write-probe-${Date.now()}-${code.length}`;
      const seeded = await page
        .evaluate(async (marker) => {
          try {
            await navigator.clipboard.writeText(marker);
            return true;
          } catch {
            return false;
          }
        }, clipboardMarker)
        .catch(() => false);
      tracePageEvent(page, "editor-trace", `clipboard:seed:${seeded}`);
      if (!seeded) {
        // Cannot tell a stale readback from a real one — fail closed and let
        // the next strategy try.
        return false;
      }

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

      const matches = clipboardReadbackProvesWrite({
        expected: code,
        seededMarker: clipboardMarker,
        readback: copiedBack,
        normalize: normalizeClipboardText,
      });
      tracePageEvent(
        page,
        "editor-trace",
        `clipboard:readback:${copiedBack.length}:${copiedBack === clipboardMarker ? "marker" : "content"}:${matches}`,
      );
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

/**
 * Anchored Pine declaration matcher for a saved script title. Matches the
 * script's own `indicator("<title>"` / `strategy('<title>'` declaration only —
 * NOT incidental mentions of the title (e.g. a consumer's
 * `input.source(..., "SMC Long-Dip Suite: BUS Armed")` binding labels), so it
 * uniquely identifies the Monaco model that holds the requested script buffer.
 */
export function pineDeclarationTitlePattern(title: string): RegExp {
  const escaped = title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`\\b(?:indicator|strategy|library)\\s*\\(\\s*(["'])${escaped}\\1`);
}

/**
 * Build the in-page Monaco model picker as a PLAIN-JS source string.
 *
 * Why a string and not a function: tsx/esbuild compiles this file with
 * keep-names, wrapping named inner arrows in a `__name(...)` helper that only
 * exists in the compiled module scope. Playwright serializes a function-form
 * `page.evaluate` callback via toString, so inside the page every such closure
 * throws `ReferenceError: __name is not defined` — which is why the monaco
 * path of readEditorContent (and of the legacy models[0] reader) NEVER ran in
 * CI and every read silently fell through to the untargeted clipboard grab
 * (run 29888669703; reproduced locally with the raw error). A source string is
 * never transformed, so what we author is exactly what the page executes.
 *
 * Selection rules (unchanged from #3858): prefer visible/focused editor
 * instances, resolve by the anchored Pine declaration title when provided,
 * else accept only an unambiguous single buffer; never an arbitrary model.
 */
export function buildPineEditorModelPickerSource(
  patternSource: string,
  requireVisibleEditor = false,
): string {
  return `(() => {
  var patternSource = ${JSON.stringify(patternSource)};
  var requireVisibleEditor = ${JSON.stringify(requireVisibleEditor)};
  function findMonaco(value, seen) {
    if (!value || (typeof value !== "object" && typeof value !== "function") || seen.has(value)) return null;
    seen.add(value);
    try {
      if (value.editor && typeof value.editor.getModels === "function") return value;
    } catch (error) {
      return null;
    }
    var nested;
    try {
      nested = Object.values(value);
    } catch (error) {
      return null; // throwing getters (webpack TDZ namespaces) — skip object
    }
    for (var i = 0; i < nested.length; i += 1) {
      var found = findMonaco(nested[i], seen);
      if (found) return found;
    }
    return null;
  }
  function findMonacoViaWebpack() {
    var chunk = window.webpackChunktradingview;
    if (!chunk || typeof chunk.push !== "function") return null;
    var moduleCache = {};
    try {
      chunk.push([["tv-monaco-read-" + Date.now()], {}, function (requireFn) { moduleCache = (requireFn && requireFn.c) || {}; }]);
      if (typeof chunk.pop === "function") chunk.pop();
    } catch (error) {
      return null;
    }
    var seen = new Set();
    var records = Object.values(moduleCache);
    for (var i = 0; i < records.length; i += 1) {
      var record = records[i];
      try {
        var found = findMonaco(record && record.exports, seen);
        if (found) return found;
      } catch (error) {
        // tolerate modules whose exports enumeration throws
      }
    }
    return null;
  }
  function safeValue(model) {
    try {
      var value = model && model.getValue();
      return typeof value === "string" ? value : null;
    } catch (error) {
      return null;
    }
  }
  function distinct(values) {
    return Array.from(new Set(values));
  }

  var direct = null;
  try {
    if (window.monaco && window.monaco.editor && typeof window.monaco.editor.getModels === "function") direct = window.monaco;
  } catch (error) {
    direct = null;
  }
  var monaco = direct || findMonacoViaWebpack();
  if (!monaco) return { value: null, reason: "monaco-not-found" };

  // Visible/focused editor instances beat the bare model list: they are the
  // buffers actually rendered to the operator.
  var editorValues = [];
  try {
    var editors = (monaco.editor && typeof monaco.editor.getEditors === "function") ? monaco.editor.getEditors() : [];
    for (var i = 0; i < editors.length; i += 1) {
      var editor = editors[i];
      var dom = editor && typeof editor.getDomNode === "function" ? editor.getDomNode() : null;
      if (!dom || !dom.isConnected) continue;
      var rect = dom.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) continue;
      var editorValue = safeValue(editor && typeof editor.getModel === "function" ? editor.getModel() : null);
      if (editorValue === null || !editorValue.trim()) continue;
      var focused = false;
      try { focused = typeof editor.hasTextFocus === "function" && editor.hasTextFocus() === true; } catch (error) { focused = false; }
      editorValues.push({ value: editorValue, focused: focused });
    }
  } catch (error) {
    // getEditors is unavailable on older Monaco builds; model fallback below.
  }

  var modelValues = [];
  try {
    var models = monaco.editor.getModels();
    for (var j = 0; j < models.length; j += 1) {
      var modelValue = safeValue(models[j]);
      if (modelValue !== null && modelValue.trim() !== "") modelValues.push(modelValue);
    }
  } catch (error) {
    return { value: null, reason: "get-models-threw:" + String(error).slice(0, 120) };
  }

  if (patternSource) {
    var pattern = new RegExp(patternSource);
    var matchingEditorValues = distinct(editorValues.filter(function (entry) { return pattern.test(entry.value); }).map(function (entry) { return entry.value; }));
    if (matchingEditorValues.length === 1) return { value: matchingEditorValues[0], reason: "editor-declaration-match" };
    if (requireVisibleEditor) return { value: null, reason: "visible-editor-declaration-unresolved:editors=" + matchingEditorValues.length + ":visibleEditors=" + editorValues.length + ":totalModels=" + modelValues.length };
    var matchingModelValues = distinct(modelValues.filter(function (value) { return pattern.test(value); }));
    if (matchingModelValues.length === 1) return { value: matchingModelValues[0], reason: "model-declaration-match" };
    return { value: null, reason: "declaration-title-unresolved:editors=" + matchingEditorValues.length + ":models=" + matchingModelValues.length + ":totalModels=" + modelValues.length };
  }

  var focusedValues = editorValues.filter(function (entry) { return entry.focused; });
  if (focusedValues.length === 1) return { value: focusedValues[0].value, reason: "focused-editor" };
  var distinctEditorValues = distinct(editorValues.map(function (entry) { return entry.value; }));
  if (distinctEditorValues.length === 1) return { value: distinctEditorValues[0], reason: "single-visible-editor" };
  var distinctModelValues = distinct(modelValues);
  if (distinctModelValues.length === 1) return { value: distinctModelValues[0], reason: "single-model" };
  return { value: null, reason: "ambiguous-models:editors=" + distinctEditorValues.length + ":models=" + distinctModelValues.length };
})()`;
}

export async function waitForVisiblePineDeclarationIdentity(
  page: Page,
  scriptNames: string[],
  timeoutMs = 4_000,
): Promise<boolean> {
  const pickerSources = uniqueNormalizedTexts(scriptNames).map((name) =>
    buildPineEditorModelPickerSource(pineDeclarationTitlePattern(name).source, true)
  );
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    for (const pickerSource of pickerSources) {
      const picked = await page.evaluate(pickerSource).catch(() => null) as {
        value?: unknown;
        reason?: unknown;
      } | null;
      if (typeof picked?.value === "string" && picked.value.trim()) {
        tracePageEvent(page, "visible-pine-declaration-identity", String(picked.reason ?? "resolved"));
        return true;
      }
    }
    await page.waitForTimeout(250);
  }

  return false;
}

async function readVisiblePineEditorSource(page: Page): Promise<string | null> {
  const picked = await page.evaluate(
    buildPineEditorModelPickerSource("", true),
  ).catch(() => null) as { value?: unknown } | null;
  return typeof picked?.value === "string" && picked.value.trim()
    ? picked.value
    : null;
}

export function visiblePineSourceTransitionVerified(
  baseline: string | null,
  candidate: string | null,
): boolean {
  return typeof baseline === "string"
    && Boolean(baseline.trim())
    && typeof candidate === "string"
    && Boolean(candidate.trim())
    && candidate !== baseline;
}

async function waitForStableVisiblePineSourceTransition(
  page: Page,
  baseline: string,
  timeoutMs: number,
): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  let previousChangedSource: string | null = null;

  while (Date.now() < deadline) {
    const candidate = await readVisiblePineEditorSource(page);
    if (visiblePineSourceTransitionVerified(baseline, candidate)) {
      if (candidate === previousChangedSource) {
        tracePageEvent(page, "visible-pine-source-transition", "stable");
        return true;
      }
      previousChangedSource = candidate;
    } else {
      previousChangedSource = null;
    }
    await page.waitForTimeout(250);
  }

  return false;
}

/**
 * Read the complete source currently loaded in TradingView's Pine editor.
 *
 * Model targeting contract (2026-07-22, #3846 follow-up): `getModels()[0]` is
 * NOT the open script — after a save/producer-refresh transition the page holds
 * several Monaco models (console/snippet buffers of a few hundred bytes), and
 * TradingView can keep a previous buffer while already repainting the requested
 * title (see openExistingScript). Reading an arbitrary model made every source
 * verification compare garbage (735–1177-byte reads with duplicated hashes
 * across different scripts, run 29863161441). We therefore poll until a model
 * is unambiguously the requested script — matched via its anchored Pine
 * declaration title when provided, else a focused/visible editor or a single
 * surviving model — and require the value to be stable across two reads before
 * trusting it. The picker runs as a source string, see
 * buildPineEditorModelPickerSource for why function-form evaluate is unusable
 * here.
 */
export async function readEditorContent(
  page: Page,
  options: {
    editorAlreadyOpen?: boolean;
    expectedDeclarationTitle?: string;
    requireVisibleEditor?: boolean;
  } = {},
): Promise<string> {
  return runTrackedStep(page, "readEditorContent", async () => {
    await dismissCookieBanner(page);
    if (!options.editorAlreadyOpen) await ensurePineEditor(page);

    const declarationPatternSource = options.expectedDeclarationTitle
      ? pineDeclarationTitlePattern(options.expectedDeclarationTitle).source
      : "";
    const pickerSource = buildPineEditorModelPickerSource(
      declarationPatternSource,
      options.requireVisibleEditor === true,
    );

    const readOnce = (): Promise<{ value: string | null; reason: string }> =>
      page
        .evaluate(pickerSource)
        .then((raw) => {
          const picked = raw as { value?: unknown; reason?: unknown } | null;
          const value = typeof picked?.value === "string" ? picked.value : null;
          const reason = typeof picked?.reason === "string" ? picked.reason : "malformed-picker-result";
          return { value, reason };
        })
        .catch((error) => ({ value: null, reason: `evaluate-rejected:${String(error).slice(0, 160)}` }));

    // Poll for the buffer swap (openExistingScript verifies the TITLE only; the
    // model content can lag), then require two identical consecutive reads so a
    // mid-swap snapshot is never reported as the saved source.
    const pollDeadline = Date.now() + numEnv("TV_READ_EDITOR_POLL_MS", 20_000);
    let lastReason = "not-attempted";
    let previousValue: string | null = null;
    while (Date.now() < pollDeadline) {
      const attempt = await readOnce();
      lastReason = attempt.reason;
      if (attempt.value !== null) {
        if (previousValue !== null && attempt.value === previousValue) {
          tracePageEvent(page, "read-editor-content", `resolved:${attempt.reason}:${attempt.value.length}`);
          return attempt.value;
        }
        previousValue = attempt.value;
      } else {
        previousValue = null;
      }
      await page.waitForTimeout(500);
    }
    tracePageEvent(page, "read-editor-content", `monaco-unresolved:${lastReason}`);

    const declarationPattern = options.expectedDeclarationTitle
      ? pineDeclarationTitlePattern(options.expectedDeclarationTitle)
      : null;
    const readClipboard = (): Promise<string> =>
      page.evaluate("navigator.clipboard.readText().catch(() => \"\")").then((raw) => (typeof raw === "string" ? raw : "")).catch(() => "");
    const mod = process.platform === "darwin" ? "Meta" : "Control";
    const clipboardMarker = `__tv_editor_source_probe_${Date.now()}__`;
    for (const host of tvSelectors.editorHosts(page)) {
      const count = await host.count().catch(() => 0);
      for (let index = 0; index < count; index += 1) {
        const candidate = host.nth(index);
        if (!(await candidate.isVisible({ timeout: 250 }).catch(() => false))) continue;
        // Clicking a Monaco *container* does not reliably focus its hidden
        // input. In that state Ctrl+A/C copies a visible viewport fragment or
        // a stale page selection, so a healthy saved source reads back
        // truncated (735-1,177 bytes for ~200KB scripts) or even identical
        // across different scripts. Focus the actual textarea/contenteditable
        // Monaco uses instead.
        const tagName = await candidate.evaluate((node) => node.tagName.toLowerCase()).catch(() => "");
        let input = candidate;
        if (tagName !== "textarea" && !(await candidate.getAttribute("contenteditable").catch(() => null))) {
          const descendant = candidate.locator('textarea, [contenteditable="true"]').first();
          if (!(await descendant.isVisible({ timeout: 250 }).catch(() => false))) continue;
          input = descendant;
        }
        const focused = await input.focus().then(() => true).catch(() => false);
        if (!focused) continue;
        await input.click({ force: true }).catch(() => undefined);
        // Pre-seed a marker so a copy that never lands cannot masquerade as
        // source: the clipboard otherwise keeps stale content, which the
        // copy-until-stable check below reads as "stable" (it never changes)
        // and — with no expected declaration title to reject it — would
        // return as the saved source. Fail closed instead.
        const seededClipboard = await page.evaluate(async (marker) => {
          try {
            await navigator.clipboard.writeText(marker);
            return true;
          } catch {
            return false;
          }
        }, clipboardMarker).catch(() => false);
        if (!seededClipboard) continue;
        // Copy-until-stable: for a ~200KB document the editor may still be
        // streaming the buffer in, and a single quick select-all/copy captured
        // only the loaded head (552-byte suite grab, run 29888669703). Accept a
        // grab only when two consecutive copies return the identical text.
        let previousCopy = "";
        for (let attempt = 0; attempt < 5; attempt += 1) {
          await page.keyboard.press(`${mod}+A`).catch(() => undefined);
          await page.keyboard.press(`${mod}+C`).catch(() => undefined);
          await page.waitForTimeout(400);
          const copied = await readClipboard();
          tracePageEvent(
            page,
            "editor-source-readback",
            `candidate:${index}:attempt:${attempt}:bytes:${Buffer.byteLength(copied, "utf-8")}`,
          );
          // The copy never landed — the marker is still all the clipboard
          // holds. Retry; never let it stabilise into an accepted read.
          if (copied === clipboardMarker) continue;
          if (copied.trim() && copied === previousCopy) {
            // The clipboard grab is as untargeted as the old models[0] read;
            // with a known declaration title only accept this script's buffer.
            if (!declarationPattern || declarationPattern.test(copied)) return copied;
            break; // stable but wrong buffer — try the next host, not more copies
          }
          previousCopy = copied;
        }
      }
    }

    throw new Error(
      `Could not read complete Pine editor source via Monaco or clipboard (last monaco state: ${lastReason})`,
    );
  }, Math.max(stepTimeoutMs(), 45_000));
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

// Returned when the page body cannot be read at all (crashed/destroyed
// context). Lets callers distinguish "readable, no compile-error marker
// present" (-> null) from "could not check" (-> this sentinel). A caller that
// gates on a clean compile MUST treat unreadable as a probe failure, never as
// a clean result — otherwise a crashed page reads as a successful compile.
const COMPILE_PROBE_UNREADABLE = Symbol("compile-probe-unreadable");

const PINE_COMPILE_ERROR_MARKERS = [
  "syntax error",
  "compilation error",
  "script could not be translated",
  "error at ",
  "error on bar",
  "undeclared identifier",
  "mismatched input",
] as const;

export function detectPineCompileErrorMarker(text: string): string | null {
  const normalized = normalizeUiText(text || "").toLowerCase();
  return PINE_COMPILE_ERROR_MARKERS.find((marker) => normalized.includes(marker)) ?? null;
}

async function getVisibleCompileErrorMarker(
  page: Page,
): Promise<string | typeof COMPILE_PROBE_UNREADABLE | null> {
  let bodyUnreadable = false;
  const rawBody = await page.locator("body").innerText().catch((error: unknown) => {
    // A crashed/destroyed context makes the body unreadable. Trace it, and
    // signal the crash via the sentinel below so it is never conflated with a
    // genuinely clean compile.
    tracePageEvent(
      page,
      "compile-error-marker-body-read-failed",
      error instanceof Error ? error.message : String(error),
    );
    bodyUnreadable = true;
    return "";
  });
  if (bodyUnreadable) {
    return COMPILE_PROBE_UNREADABLE;
  }

  return detectPineCompileErrorMarker(rawBody || "");
}

/**
 * Waits (up to ~7s) for the post-save "Save script" dialog to close and throws
 * if a real compile-error *marker string* becomes visible while the compile
 * settles.
 *
 * NOT a hard compile gate. This is a settling **poller**: an unreadable body
 * (crashed/destroyed context) is deliberately non-blocking — it can be a
 * transient mid-poll blip — so this function returns normally if the body stays
 * unreadable through the timeout. Callers that need an actual compile
 * *decision* MUST call {@link assertNoVisibleCompileError} immediately after;
 * that is the authoritative gate and it fails closed on an unreadable body.
 * Every current caller (`tv_publish_*`, `tv_preflight`) already pairs the two.
 */
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
      // Only a real marker string is a compile error. UNREADABLE (a crashed
      // read) stays non-blocking here — keep polling — per the round-6 decision
      // that a transient read failure must not spuriously fail a save.
      if (typeof compileErrorMarker === "string") {
        throw new Error(`Visible compile error detected after save for ${scriptName}: ${compileErrorMarker}`);
      }

      await page.waitForTimeout(pollMs);
    }

    const finalCompileErrorMarker = await getVisibleCompileErrorMarker(page);
    if (typeof finalCompileErrorMarker === "string") {
      throw new Error(`Visible compile error detected after save for ${scriptName}: ${finalCompileErrorMarker}`);
    }
  });
}

export async function assertNoVisibleCompileError(page: Page): Promise<void> {
  const hit = await getVisibleCompileErrorMarker(page);
  if (typeof hit === "string") {
    throw new Error(`Visible compile error detected: ${hit}`);
  }
  // This is a HARD compile gate: every caller (tv_publish_*, tv_preflight
  // mutating path) treats a non-throw as "compile clean" and proceeds to
  // publish. An unreadable body (crashed/destroyed context) is NOT a clean
  // compile — it is an unknown compile state — so it must fail CLOSED here and
  // abort the publish, rather than being silently read as success.
  // (waitForPostSaveCompileSettlement, which polls, keeps the UNREADABLE case
  // non-blocking on purpose; this assertion is always run right after it as the
  // authoritative final gate.)
  if (hit === COMPILE_PROBE_UNREADABLE) {
    throw new Error("Visible compile error check failed: page body is unreadable (crashed/destroyed context)");
  }
}

/**
 * Return a compile/runtime error attached to the exact chart legend row for
 * {@link scriptName}. TradingView can expose a clean editor body immediately
 * after Save, then reveal a Pine compiler error only after Add to chart. The
 * generic body-text gate above cannot see an icon whose diagnostic lives in a
 * title/aria-label attribute (the CE10271 incident on 2026-07-16).
 */
/**
 * Signals that the chart error channel could not LOOK, as opposed to having
 * looked and found nothing. Mirrors {@link COMPILE_PROBE_UNREADABLE} on the
 * body-text side, for the same reason: an unobservable probe must never be
 * conflated with a genuinely clean compile.
 */
export const CHART_ERROR_PROBE_UNREADABLE = Symbol("chart-error-probe-unreadable");

/**
 * Look for a Pine error on the script's legend row, and say whether the look
 * succeeded.
 *
 * This channel exists for errors that live ONLY in the legend badge's
 * `title`/`aria-label` (the CE10271 class); the body-text channel cannot see
 * them. The button-first finder can return `[]` while TradingView keeps legend
 * actions hidden until hover, so the hard gate follows it with the bounded
 * text-first hover probe already used by removal/refresh. Both finders require
 * one tight legend row with exactly one known action; if neither can observe
 * that row, the result remains explicitly unreadable rather than "clean".
 *
 * One bounded re-look of both strategies remains before giving up: a gate that
 * flakes red gets switched off by the humans it protects, and the legend row
 * is genuinely still painting right after an insert.
 */
export async function probeVisibleChartScriptError(
  page: Page,
  scriptName: string,
): Promise<string | typeof CHART_ERROR_PROBE_UNREADABLE | null> {
  const discoverReadableWrappers = async (): Promise<Locator[]> => {
    const buttonFirst = await findLegendRowWrappers(page, scriptName);
    if (buttonFirst.length > 0) return buttonFirst;

    const textFirst = await findLegendRowWrappersByVisibleText(page, scriptName).catch(() => []);
    if (textFirst.length > 0) {
      tracePageEvent(page, "chart-error-probe", `text-fallback:${scriptName}:${textFirst.length}`);
    }
    return textFirst;
  };

  let wrappers = await discoverReadableWrappers();
  if (wrappers.length === 0) {
    await page.waitForTimeout(750).catch(() => undefined);
    wrappers = await discoverReadableWrappers();
  }
  if (wrappers.length === 0) {
    tracePageEvent(page, "chart-error-probe", `unreadable:${scriptName}`);
    return CHART_ERROR_PROBE_UNREADABLE;
  }
  for (const wrapper of wrappers) {
    const candidates = wrapper.locator("[title], [aria-label]");
    const count = await candidates.count();
    for (let index = 0; index < Math.min(count, 30); index += 1) {
      const candidate = candidates.nth(index);
      if (!(await candidate.isVisible({ timeout: 250 }).catch(() => false))) continue;
      for (const attribute of ["title", "aria-label"] as const) {
        const value = normalizeUiText((await candidate.getAttribute(attribute).catch(() => null)) || "");
        if (detectPineCompileErrorMarker(value)) return value;
      }
    }

    const rowText = normalizeUiText((await wrapper.innerText({ timeout: 300 }).catch(() => "")) || "");
    if (detectPineCompileErrorMarker(rowText)) return rowText;
  }
  return null;
}

/**
 * Back-compatible view of {@link probeVisibleChartScriptError} for callers that
 * only want the error text. "Could not look" maps to `null` here, so this must
 * NOT be used by anything that gates on a clean compile — use the probe.
 */
export async function getVisibleChartScriptError(page: Page, scriptName: string): Promise<string | null> {
  const probed = await probeVisibleChartScriptError(page, scriptName);
  return probed === CHART_ERROR_PROBE_UNREADABLE ? null : probed;
}

/**
 * Hard pre-publish gate. Deliberately built on {@link probeVisibleChartScriptError},
 * not {@link getVisibleChartScriptError}: that view maps "could not look" to
 * `null`, so gating on it would let a publish certify a compile it never
 * observed. Its own docstring says not to use it for gating.
 */
export async function assertNoVisibleChartScriptError(page: Page, scriptName: string): Promise<void> {
  const probed = await probeVisibleChartScriptError(page, scriptName);
  if (probed === CHART_ERROR_PROBE_UNREADABLE) {
    throw new Error(
      `Chart legend unreadable for ${scriptName}: refusing to report a clean compile from a surface that could not be read.`,
    );
  }
  if (probed) {
    throw new Error(`Visible chart error detected for ${scriptName}: ${probed}`);
  }
}

/**
 * Materialize an indicator that is absent from the chart, then require a
 * readable, error-free legend row before its publish flow can continue.
 *
 * The Open-Prep publisher updates a saved script that is not necessarily
 * attached to the active layout.  A chart-error assertion before this step is
 * therefore impossible to satisfy: the publish helper has not yet had a chance
 * to add the script.  Keep the materialization inside the publish helper so the
 * caller records an attempted publish and so every exit remains fail-closed.
 */
export async function ensureCleanChartScriptForPublish(page: Page, scriptName: string): Promise<void> {
  const initialProbe = await probeVisibleChartScriptError(page, scriptName);
  if (initialProbe === CHART_ERROR_PROBE_UNREADABLE) {
    tracePageEvent(page, "publish-chart-prepare", `materialize:${scriptName}`);
    await addCurrentScriptToChart(page, scriptName);
  }

  await assertNoVisibleChartScriptError(page, scriptName);
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

async function settleChartSurfaceAfterInsert(
  page: Page,
  scriptName: string,
  phase: string,
  allowTextMatchOnly = true,
  requireLegendMatch = false,
): Promise<boolean> {
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
    // A forced insert must prove that the newly added chart instance has its
    // own legend row.  The looser strategy-report + text heuristic can match
    // the open editor title alongside an unrelated existing strategy report.
    if (state && (requireLegendMatch ? state.hasLegendMatch : isScriptVisibleOnChart(state))) {
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

      if (await settleChartSurfaceAfterInsert(page, scriptName, "click", !options.forceInsert, options.forceInsert)) {
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
      if (await settleChartSurfaceAfterInsert(page, scriptName, "hotkey", !options.forceInsert, options.forceInsert)) {
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
  }, options.stepTimeoutMs ?? stepTimeoutMs());
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

/**
 * Ledger klasse-h, Fix (Lauf 32803019213, save-Job 2026-08-25 11:52:50Z):
 * called instead of another `openSettingsForScriptOnce` double-click round
 * once `shouldEscalateSettingsOpenPath` says the target has already
 * mismatched onto its legend neighbour twice — a third double-click on the
 * same spot proved to reproduce the same neighbour hit, not a fresh miss, and
 * only burns the 60s step budget the whole call runs under.
 *
 * Goes straight for the row-bound settings control
 * (`button[data-qa-id="legend-settings-action"]`, selectors.ts
 * `legendSettingsButtons`). Review I2 (Fix-Runde 1): this is NOT the only
 * place that clicks it — openSettingsFromVisibleLegendText/-LegendContainer
 * (twice)/-ScriptText each carry their own direct-settings-button fallback
 * (tv_shared.ts:6645/6693/6779/6896). The true, narrower claim: every
 * MEASURED klasse-h failure had its double-click OPEN a (wrong) dialog and
 * return via identity mismatch before the ladder ever reached one of those
 * fallbacks — they exist for "nothing opened at all", never fire for
 * "opened the wrong thing", so a mismatched target never reached them either.
 * `findLegendRowWrappersByVisibleText` re-resolves the target row by its text
 * (not by re-using whatever row the mismatched attempt aimed at), and the
 * extra `wrapper.hover()` before each button click mirrors
 * `openLegendRemovalMenu`'s pattern: these action buttons render only on
 * hover.
 *
 * Review C1 (CRITICAL, Fix-Runde 1): the "More" fallback originally used
 * `legendMenuButtons`, whose candidate list ends in bare `button` /
 * `[role="button"]` catch-alls (selectors.ts:652-653) — inside the SAME hover
 * strip as the row's Remove control, which this ledger's own evidence twice
 * caught the plain double-click landing on (`foreign:Remove`,
 * hit-target-miss). Clicked via `clickLegendControlWithFallback`'s
 * force+offset-position fallback ladder, that could have removed the
 * indicator from the live (or, worse, the readonly-verify) chart without
 * ever opening a dialog the identity guard could reject. Replaced with the
 * narrow `legendMoreActionLocators` (tv_shared.ts:5571 — the exact list
 * `openLegendRemovalMenu` already trusts to mean "this row's More trigger,
 * nothing else") and a plain actionable `clickFirst` click — no
 * `force: true`. If the opened menu has no "Settings" entry, the menu is
 * closed (Escape) right here in this branch instead of being left open for
 * the caller's catch (mirrors the closeModal-before-throw shape at the end of
 * `openSettingsForScriptOnce`).
 *
 * Review I6: the threshold is REACHABLE within one call (a legend-text
 * mismatch followed by a legend-container mismatch, each through
 * `verifyOpenedSettingsDialogIdentity`), but no real run has exercised this
 * escalation path yet — Lauf 32803019213 measured mismatches per RUN, not
 * per openSettingsForScript call. Effectiveness is UNPROVEN until a real run
 * shows `script-settings-open-button-escalation-armed` followed by success.
 *
 * Same arbiter as every other path: `verifyOpenedSettingsDialogIdentity`
 * decides match/mismatch here exactly as it does for the double-click ladder.
 * Browser-bound end to end (Locator/hover/click) — the decision to call this
 * function at all lives in the pure `shouldEscalateSettingsOpenPath`.
 */
async function openSettingsForScriptViaLegendButton(page: Page, scriptName: string): Promise<boolean> {
  tracePageEvent(page, "script-settings-open-button-escalation-start", scriptName);
  await dismissSignInModal(page);
  await closePineEditorIfVisible(page);

  const wrappers = await findLegendRowWrappersByVisibleText(page, scriptName).catch(() => []);
  tracePageEvent(page, "script-settings-open-button-escalation-rows", `${scriptName}:${wrappers.length}`);

  for (const [index, wrapper] of wrappers.entries()) {
    await wrapper.scrollIntoViewIfNeeded().catch(() => undefined);
    // Legend action buttons render only on hover — same pattern
    // openLegendRemovalMenu already uses for the remove path.
    await wrapper.hover({ timeout: 1_000 }).catch(() => undefined);

    // Settings-specific candidates only (review C1): every locator in
    // legendSettingsButtons targets a settings control, never Remove.
    const clickedDirectSettings = await clickLegendControlWithFallback(
      page,
      tvSelectors.legendSettingsButtons(wrapper),
      "script-settings-open-button-escalation-settings",
      600,
      200,
      async () => hasSettingsSurfaceDomHint(page),
    );
    if (clickedDirectSettings) {
      tracePageEvent(page, "script-settings-open-button-escalation-settings-clicked", `${scriptName}:${index}`);
      if (await waitForScriptSettingsInputsSurface(page, 750)) {
        return verifyOpenedSettingsDialogIdentity(page, scriptName, "script-settings-open-button-escalation-surface");
      }
      if (await resolveOpenedSettingsSurfaceToIndicatorDialog(page, "script-settings-open-button-escalation-settings", 750)) {
        return verifyOpenedSettingsDialogIdentity(page, scriptName, "script-settings-open-button-escalation-dialog");
      }
    }

    await wrapper.hover({ timeout: 1_000 }).catch(() => undefined);
    // Review C1: legendMoreActionLocators, NOT legendMenuButtons — the narrow
    // "More" trigger list openLegendRemovalMenu already relies on, never a
    // bare button/[role="button"] catch-all that could also resolve to
    // Remove in the same hover strip. clickFirst does a plain actionable
    // click (Playwright's own actionability wait), no force:true.
    const clickedMenu = await clickFirst(legendMoreActionLocators(wrapper), 600);
    if (clickedMenu) {
      tracePageEvent(page, "script-settings-open-button-escalation-menu-clicked", `${scriptName}:${index}`);
      const clickedMenuSettings = await clickFirst(tvSelectors.settingsAction(page), 1_500);
      if (clickedMenuSettings) {
        if (await waitForScriptSettingsInputsSurface(page, 1_500)) {
          tracePageEvent(page, "script-settings-open-button-escalation-menu-action-clicked", `${scriptName}:${index}`);
          return verifyOpenedSettingsDialogIdentity(page, scriptName, "script-settings-open-button-escalation-menu-dialog");
        }
        if (await resolveOpenedSettingsSurfaceToIndicatorDialog(page, "script-settings-open-button-escalation-menu", 750)) {
          tracePageEvent(page, "script-settings-open-button-escalation-menu-action-clicked", `${scriptName}:${index}`);
          return verifyOpenedSettingsDialogIdentity(page, scriptName, "script-settings-open-button-escalation-menu-dialog");
        }
      }
      // Review C1/M7: close the menu HERE, in this branch, instead of
      // leaving it open for the caller's catch to clean up later — mirrors
      // the closeModal-before-throw shape at the end of
      // openSettingsForScriptOnce (tv_shared.ts, just above this function).
      tracePageEvent(page, "script-settings-open-button-escalation-menu-no-settings", `${scriptName}:${index}`);
      await page.keyboard.press("Escape").catch(() => undefined);
    }
  }

  tracePageEvent(page, "script-settings-open-button-escalation-miss", scriptName);
  return false;
}

export async function openSettingsForScript(
  page: Page,
  scriptName: string,
  options: { allowChartRefresh?: boolean } = {},
): Promise<boolean> {
  const allowChartRefresh = options.allowChartRefresh === true;
  // A promotion overlay can appear at any point in the session and then sits
  // above or below the dialog this function opens (both seen in run
  // 36859274386). Closing it here covers every caller that is about to work
  // inside a settings dialog.
  await dismissPromotionOverlay(page);
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

  // Ledger klasse-h: the mismatch count is scoped to this call ("je
  // openSettingsForScript-Aufruf") — a stale count from an earlier call for
  // the same script on the same page must not trigger an escalation before
  // this call has mismatched even once.
  resetSettingsIdentityMismatchCount(settingsIdentityMismatchCountsForPage(page), scriptName);

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
        // Ledger klasse-h escalation: the double-click ladder proved to hit
        // the same legend neighbour again on repeat, not a fresh miss — past
        // the measured threshold, skip straight to the row-bound button path.
        const mismatchCount = settingsIdentityMismatchCount(settingsIdentityMismatchCountsForPage(page), scriptName);
        const escalate = shouldEscalateSettingsOpenPath(mismatchCount);
        if (escalate) {
          tracePageEvent(page, "script-settings-open-button-escalation-armed", `${scriptName}:mismatches=${mismatchCount}`);
        }
        // Review I5: the button path replacing the whole attempt ate the
        // target's second rescue attempt outright when the row search itself
        // came up empty (findLegendRowWrappersByVisibleText requires exactly
        // one action button in the wrapper). Falling through to the plain
        // ladder keeps that rescue attempt instead of trading it away.
        const opened = escalate
          ? (await openSettingsForScriptViaLegendButton(page, scriptName)) || (await openSettingsForScriptOnce(page, scriptName))
          : await openSettingsForScriptOnce(page, scriptName);
        if (opened === true) {
          return true;
        }
        // Diese Meldung hiess bis 2026-08-22 "Settings opened for the wrong
        // TradingView script: <ziel>" — und log, denn `openSettingsForScriptOnce`
        // liefert bei JEDEM Misserfolg `false`, auch wenn ueberhaupt kein Dialog
        // aufging. Der genannte Name war das ZIEL, nicht ein fremder Dialog. Wer
        // sie las, suchte eine Namensverwechslung, die es nicht gab: die Diagnose
        // zu Klasse H lief deshalb zuerst in die falsche Richtung, und der
        // eigentliche Befund (kein Dialog, Legende nicht getroffen) stand nur in
        // den Trace-Events daneben.
        //
        // Ein echter Identitaets-Mismatch wirft weiter in
        // verifyOpenedSettingsDialogIdentity und nennt dort BEIDE Namen.
        throw new Error(
          `Settings dialog never opened for: ${scriptName} (no dialog surfaced; see the ` +
            `script-settings-* trace events of this attempt for which lookup failed)`,
        );
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
  // getVisibleCompileErrorMarker is fail-soft (never throws), so the .catch is
  // only a defensive backstop. The real crash signal is the UNREADABLE
  // sentinel: map it to a probe-failure value so a crashed body read fails the
  // smoke gate CLOSED instead of masquerading as a clean compile (`null`).
  const compileMarker = await getVisibleCompileErrorMarker(page).catch(() => "runtime_smoke_probe_failed" as const);
  const bodyCompileError = compileMarker === COMPILE_PROBE_UNREADABLE ? "runtime_smoke_probe_failed" : compileMarker;
  // The chart channel now reports whether it could look at all. An unreadable
  // look fails the gate CLOSED, exactly as the body channel already did — the
  // two are not redundant: the body text cannot see an error that lives only in
  // the legend badge's title attribute, which is the whole reason this second
  // channel exists.
  //
  // This also closes the combination that made the gate certifiable-by-accident:
  // `scriptVisible` below falls back to matching the script NAME anywhere on the
  // page (its own comment two definitions up says that flag must not decide), so
  // a script that never loaded could read as visible while the error channel
  // reported clean. With no legend row there is now no clean verdict to have.
  const chartProbe = bodyCompileError
    ? null
    : await probeVisibleChartScriptError(page, scriptName).catch(() => "runtime_smoke_probe_failed" as const);
  const chartCompileError = chartProbe === CHART_ERROR_PROBE_UNREADABLE
    ? "runtime_smoke_probe_failed"
    : chartProbe;
  const compileError = bodyCompileError || chartCompileError;

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

// Selector set behind tvSelectors.pinePublishButtons' `pineDialog` — kept here
// so the absence diagnostic reports exactly what that locator resolves over.
const PINE_DIALOG_SELECTOR = '[data-name="pine-dialog"], #pine-editor-dialog, [id*="pine-editor" i]';

// 2026-07-31 (smc-library-refresh publish outage, issue #4238): a candidate miss
// logs only a COUNT, never the DOM it looked at — which is why two days of
// failures could not name their own cause. Run 30644048525 carried the #4251
// fix, matched the relabelled control by title, opened the publish surface and
// satisfied the "script is not on the chart" gate; 29s later the SAME candidate
// list reported no-visible-candidate for all 11 entries while the editor header
// still showed `smc_micro_profiles_generated`.
//
// The cause turned out to be the title strip fixed in #4261: the control carries
// apply-common-tooltip, which removes its title attribute on click, so a
// title-only match works exactly once per session. Reaching that answer needed a
// DOM dump — the trace alone could not tell it apart from a `.last()` retarget
// of PINE_DIALOG_SELECTOR, from TradingView removing the control, or from an
// undismissed gate dialog. All three were plausible from the trace, and all
// three were wrong.
//
// So this dumps, at the moment of the miss: every node the pineDialog set
// resolves to (marking the .last() one), every share control in the document
// with its attributes and computed visibility, and the text of any open overlay.
// A stripped attribute, a retarget, a removal and a covering modal each leave a
// different fingerprint here. Without it the next such regression costs another
// ~2h CI cycle per guess.
async function tracePublishSurfaceAbsence(page: Page, phase: string): Promise<void> {
  const dialogs = await page
    .locator(PINE_DIALOG_SELECTOR)
    .evaluateAll((nodes) => nodes.map((node, index) => {
      const element = node as HTMLElement;
      const rect = element.getBoundingClientRect();
      const style = window.getComputedStyle(element);
      return {
        index,
        isLast: index === nodes.length - 1,
        tag: element.tagName,
        id: element.id || "",
        dataName: element.getAttribute("data-name") || "",
        className: String(element.className || "").slice(0, 80),
        display: style.display,
        visibility: style.visibility,
        rect: { x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height) },
        buttons: element.querySelectorAll('button, [role="button"]').length,
        hasShareControl: Boolean(element.querySelector('[title*="hare your script"], [class*="publishButton" i]')),
      };
    }))
    .catch(() => []);
  tracePageEvent(page, "publish-absence-pine-dialogs", `${phase}:${JSON.stringify(dialogs).slice(0, 1_800)}`);

  const shareControls = await page
    .locator('[title*="hare your script"], [class*="publishButton" i]')
    .evaluateAll((nodes, dialogSelector) => nodes.map((node, index) => {
      const element = node as HTMLElement;
      const rect = element.getBoundingClientRect();
      const style = window.getComputedStyle(element);
      const owner = element.closest(dialogSelector) as HTMLElement | null;
      return {
        index,
        tag: element.tagName,
        title: element.getAttribute("title") || "",
        className: String(element.className || "").slice(0, 80),
        display: style.display,
        visibility: style.visibility,
        opacity: style.opacity,
        // A detached/collapsed control has no offsetParent — this separates
        // "removed by TradingView" from "present but hidden".
        hasOffsetParent: Boolean(element.offsetParent),
        rect: { x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height) },
        // Which pine-dialog node owns it, so a .last() retarget is visible as
        // "control lives in dialog 0 while .last() points at dialog 1".
        ownerId: owner ? (owner.id || owner.getAttribute("data-name") || String(owner.className || "").slice(0, 40)) : "none",
      };
    }), PINE_DIALOG_SELECTOR)
    .catch(() => []);
  tracePageEvent(page, "publish-absence-share-controls", `${phase}:${JSON.stringify(shareControls).slice(0, 1_800)}`);

  const overlaySnippets = await collectVisibleOverlayTextSnippets(page, 250).catch(() => []);
  tracePageEvent(page, "publish-absence-overlays", `${phase}:${JSON.stringify(overlaySnippets).slice(0, 1_200)}`);
}

/**
 * Elements the "Choose script" control could plausibly be, read out by
 * attribute. No click, no keyboard, nothing that could reach Continue.
 *
 * Deliberately scoped to the whole overlay root rather than to
 * `publishSurface`. If the surface is what mis-resolved, an inventory taken
 * inside it would report the same emptiness that caused the failure and would
 * read as proof the control is absent.
 */
const PUBLISH_CHOOSER_INVENTORY_SELECTOR = [
  "select",
  "input",
  "[role]",
  "button",
  "[data-name]",
  '[class*="select" i]',
  '[class*="dropdown" i]',
  '[class*="combobox" i]',
  '[class*="chooser" i]',
].join(", ");

export type PublishChooserInventoryEntry = {
  i: number;
  inDialog: boolean;
  tag: string;
  role: string;
  ariaLabel: string;
  ariaExpanded: string;
  placeholder: string;
  dataName: string;
  title: string;
  name: string;
  text: string;
  cls: string;
  disabled: boolean;
  display: string;
  visibility: string;
  x: number;
  y: number;
  w: number;
  h: number;
};

export async function collectPublishChooserInventory(page: Page): Promise<PublishChooserInventoryEntry[]> {
  // Run 31850269023 (2026-08-14 23:24Z) proved the first cut of this
  // inventory blind in practice: FOUR toast stacks ("orders", "alerts",
  // "alertsFireControl", ...) sit at the front of #overlap-manager-root, and
  // their expand/close buttons plus counter spans exhausted both the
  // 60-element cap and the 6000-char trace budget before a single dialog
  // control appeared. Two corrections, both measured against that run:
  //
  // - dialog-shaped containers are walked FIRST, the remaining overlay root
  //   second, so the publish dialog can never again lose the budget race to
  //   notification noise;
  // - toast subtrees ([data-name^="toast-"]) and content-free nodes (no
  //   text, no role, no label of any kind) are excluded entirely.
  //
  // Still deliberately NOT scoped to publishSurface(): if the surface
  // fingerprint itself mis-resolves, the second phase keeps reporting what
  // else the overlay holds.
  return page
    .locator("#overlap-manager-root")
    .first()
    .evaluate((root: Element, selector: string) => {
      const seen = new Set<Element>();
      const dialogish = Array.from(
        root.querySelectorAll('[role="dialog"], [aria-modal="true"], [data-name*="dialog" i]'),
      );
      const ordered: Array<{ element: Element; inDialog: boolean }> = [];
      for (const container of dialogish) {
        for (const node of Array.from(container.querySelectorAll(selector))) {
          if (!seen.has(node)) {
            seen.add(node);
            ordered.push({ element: node, inDialog: true });
          }
        }
      }
      for (const node of Array.from(root.querySelectorAll(selector))) {
        if (!seen.has(node)) {
          seen.add(node);
          ordered.push({ element: node, inDialog: false });
        }
      }
      return ordered
        .filter(({ element }) => !element.closest('[data-name^="toast-"], [class*="toast" i]'))
        .map(({ element, inDialog }) => ({ element: element as HTMLElement, inDialog }))
        .filter(({ element }) =>
          Boolean(
            (element.textContent ?? "").trim()
            || element.getAttribute("role")
            || element.getAttribute("aria-label")
            || element.getAttribute("placeholder")
            || element.getAttribute("data-name")
            || element.getAttribute("title")
            || element.tagName.toLowerCase() === "select"
            || element.tagName.toLowerCase() === "input",
          ))
        .slice(0, 60)
        .map(({ element, inDialog }, index) => {
          const box = element.getBoundingClientRect();
          const style = window.getComputedStyle(element);
          return {
            i: index,
            inDialog,
            tag: element.tagName.toLowerCase(),
            role: element.getAttribute("role") || "",
            ariaLabel: element.getAttribute("aria-label") || "",
            ariaExpanded: element.getAttribute("aria-expanded") || "",
            placeholder: element.getAttribute("placeholder") || "",
            dataName: element.getAttribute("data-name") || "",
            title: element.getAttribute("title") || "",
            name: element.getAttribute("name") || "",
            text: (element.textContent ?? "").trim().slice(0, 48),
            cls: (element.getAttribute("class") ?? "").slice(0, 60),
            disabled: element.hasAttribute("disabled"),
            display: style.display,
            visibility: style.visibility,
            x: Math.round(box.x),
            y: Math.round(box.y),
            w: Math.round(box.width),
            h: Math.round(box.height),
          };
        });
    }, PUBLISH_CHOOSER_INVENTORY_SELECTOR)
    .catch((error) => {
      // A crashed DOM readout must not read as "TradingView renders no
      // matching controls" -- that corrupts exactly the inventory this
      // function exists to collect (#4706/#4723 were built on it after five
      // blind selector guesses). The empty result stays (the caller's
      // absence semantics are unchanged) but the failure leaves a trace, so
      // the next triage reads "probe failed", not "DOM is empty".
      tracePageEvent(page, "publish-chooser-inventory-probe-failed", String(error).slice(0, 300));
      return [] as PublishChooserInventoryEntry[];
    });
}

/**
 * Five selector changes between 2026-08-09 and 2026-08-10 (#4585, #4587,
 * #4591, #4597, #4606) all aimed at this control and none moved the failure:
 * eight of the ten runs since carry the byte-identical error
 * "Could not select existing TradingView script: Open-Prep Daily Panel", and
 * the only evidence each one left was a screenshot. A sixth guess is not what
 * is missing -- the DOM is. This reads it out so the next change can be pinned
 * against what TradingView renders instead of against an assumption about it.
 */
async function tracePublishChooserAbsence(
  page: Page,
  stage: string,
): Promise<{ stage: string; surfaceCount: number; controls: PublishChooserInventoryEntry[] }> {
  const surfaceCount = await tvSelectors.publishSurfaceProbe(page).count().catch(() => -1);
  const controls = await collectPublishChooserInventory(page);
  const evidence = { stage, surfaceCount, controls };
  tracePageEvent(page, "publish-existing-script-absence", JSON.stringify(evidence).slice(0, 6_000));
  return evidence;
}

/**
 * Darf der Neu-Publish-Rueckfall feuern?
 *
 * Nur bei POSITIV belegtem Nicht-Treffer, nie bei ausbleibender Evidenz --
 * dieser Zweig publiziert auf ein echtes Konto, und ein Rueckfall auf eine
 * leere Antwort erzeugt Duplikate. Zwei Belege muessen beide vorliegen:
 *
 *  1. der getippte Name steht wirklich im Chooser-Feld (die Keystrokes kamen
 *     an -- sonst waere die leere Liste eine Aussage ueber die Eingabe);
 *  2. die Optionsliste hat MINDESTENS EINEN Eintrag aufgeloest (die Liste
 *     existiert und filtert -- sonst waere sie nie geoeffnet, und "kein
 *     Treffer" waere ununterscheidbar von "nie gefragt").
 *
 * Gemessen 2026-08-20 (Lauf 32313143879): Feld trug "Open-Prep Daily Panel",
 * Liste fuehrte einen Eintrag ("EMA Suite - Trend & Breakout Monitor (v6)").
 * Beide Belege lagen also vor.
 */
export async function gatherPublishNewFallbackEvidence(
  page: Page,
  scriptName: string,
): Promise<{ eligible: boolean; typedValue: string | null; optionCount: number }> {
  const chooser = await waitForFirstVisibleLocator(
    tvSelectors.publishExistingScriptChooser(page),
    1_500,
    async (candidate) => (await candidate.evaluate((element) => element.tagName.toLowerCase())) === "input",
  );
  const typedValue = chooser ? await chooser.inputValue().catch(() => null) : null;

  let optionCount = 0;
  for (const locator of tvSelectors.publishAnyScriptOption(page)) {
    optionCount = Math.max(optionCount, await locator.count().catch(() => 0));
  }

  return {
    eligible: publishNewFallbackEligible(typedValue, optionCount, scriptName),
    typedValue,
    optionCount,
  };
}

/**
 * Die Entscheidung, getrennt vom DOM-Sammeln -- damit die sicherheitskritische
 * Haelfte ohne Playwright-Page pruefbar ist. Ein Quelltext-Test kann "trifft
 * die Entscheidung" nicht von "erwaehnt sie" unterscheiden; diese Funktion
 * laesst sich direkt ausfuehren.
 *
 * `true` NUR bei zwei positiven Belegen. Jede Abwesenheit -- kein Feld, leeres
 * Feld, anderer Text, keine Optionen -- ist ein Sondenfehler und KEIN
 * Nicht-Treffer.
 */
export function publishNewFallbackEligible(
  typedValue: string | null,
  optionCount: number,
  scriptName: string,
): boolean {
  if (typeof typedValue !== "string") return false;
  if (typedValue.trim() !== scriptName.trim()) return false;
  if (!Number.isFinite(optionCount) || optionCount <= 0) return false;
  return true;
}

export async function selectExistingPublishScript(page: Page, scriptName: string): Promise<boolean> {
  const nativeChooser = await waitForFirstVisibleLocator(
    tvSelectors.publishExistingScriptChooser(page),
    3_000,
    async (candidate) => (await candidate.evaluate((element) => element.tagName.toLowerCase())) === "select",
  );
  if (nativeChooser) {
    const nativeSnapshot = () => nativeChooser
      .evaluate((element) => {
        const select = element as HTMLSelectElement;
        return {
          tag: select.tagName,
          role: select.getAttribute("role") || "",
          ariaLabel: select.getAttribute("aria-label") || "",
          name: select.getAttribute("name") || "",
          className: String(select.className || "").slice(0, 120),
          options: Array.from(select.options)
            .map((option) => (option.textContent || "").trim())
            .filter(Boolean)
            .slice(0, 20),
        };
      })
      .catch(() => null);
    tracePageEvent(
      page,
      "publish-existing-script-native-candidate",
      JSON.stringify(await nativeSnapshot()),
    );

    const nativeDeadline = Date.now() + 3_000;
    do {
      const selectedValues = await nativeChooser
        .selectOption({ label: scriptName }, { timeout: 250 })
        .catch(() => [] as string[]);
      if (selectedValues.length > 0) {
        tracePageEvent(
          page,
          "publish-existing-script-native-selected",
          `${scriptName}:${JSON.stringify(await nativeSnapshot())}`,
        );
        return true;
      }
      await page.waitForTimeout(100);
    } while (Date.now() < nativeDeadline);

    tracePageEvent(
      page,
      "publish-existing-script-native-fallback",
      `${scriptName}:${JSON.stringify(await nativeSnapshot())}`,
    );
  }

  const chooserControl = await waitForFirstVisibleLocator(
    tvSelectors.publishExistingScriptChooser(page),
    3_000,
    async (candidate) => (await candidate.evaluate((element) => element.tagName.toLowerCase())) !== "select",
  );
  if (!chooserControl) {
    // The observed stage. Runs 31805361109 and the seven before it spent
    // 3s here and 3s in the native branch above, then returned false without
    // recording anything about what WAS on the page.
    await tracePublishChooserAbsence(page, "chooser-control-absent");
    return false;
  }
  const openedChooser = await clickVisibleWithFallback(
    page,
    [chooserControl],
    "publish-existing-script-chooser",
    3_000,
    350,
  );
  if (!openedChooser) {
    await tracePublishChooserAbsence(page, "chooser-control-not-clickable");
    return false;
  }

  let scriptOption = await waitForFirstVisibleLocator(
    tvSelectors.publishExistingScriptOption(page, scriptName),
    3_000,
  );
  if (!scriptOption) {
    // 2026-08-18, Lauf 32141943180 (#4772): die Input-Form des Choosers ist
    // ein Type-ahead — ein Klick allein öffnet keine Optionsliste. Stufe 1
    // (fill + Optionssuche) kam aus dessen Absenz-Trace; Stufe 2 (echte
    // Keystrokes) aus dem Folge-Lauf 32197059724: fill=true, Liste trotzdem
    // leer — die Combobox filtert erst auf Tastatur-Events. Jede Stufe ist
    // durch genau einen Lauf-Trace gedeckt; weitere erst mit neuer Evidenz.
    const isTextInput = await chooserControl
      .evaluate((element) => element.tagName.toLowerCase() === "input")
      .catch(() => false);
    if (isTextInput) {
      const filled = await chooserControl
        .fill(scriptName, { timeout: 1_000 })
        .then(() => true)
        .catch(() => false);
      // Wert-Readback: value=="" trotz filled=true heißt "React hat den
      // programmatischen Wert verworfen" (nächster Schritt pressSequentially),
      // value==Name heißt "Wert steht, nur die Optionsliste fehlt" (Debounce/
      // Keystrokes oder Skript nicht gelistet). Ohne Readback sind diese
      // Mechanismen im Trace des Live-Laufs ununterscheidbar.
      const typedValue = await chooserControl.inputValue().catch(() => null);
      tracePageEvent(
        page,
        "publish-existing-script-typeahead",
        `${scriptName}:filled=${filled}:value=${JSON.stringify(typedValue)}`,
      );
      if (!filled) {
        // Eigene Stage: fehlgeschlagenes fill() (readonly, Re-Render-Detach)
        // verlangt einen anderen nächsten Schritt als eine ausbleibende
        // Optionsliste — der Stage-String allein muss den Schritt benennen.
        await tracePublishChooserAbsence(page, "typeahead-fill-failed");
        return false;
      }
      scriptOption = await waitForFirstVisibleLocator(
        tvSelectors.publishExistingScriptOption(page, scriptName),
        3_000,
      );
      if (!scriptOption) {
        // Stufe 2 (Lauf 32197059724): Feld leeren, Namen als echte
        // Keystrokes tippen — fill() dispatcht nur ein input-Event, die
        // gemessene Combobox reagiert darauf nicht. Readback wieder dabei,
        // damit der Live-Trace "Keys kamen an, Liste blieb leer" (Skript
        // nicht gelistet?) von "Keys verworfen" unterscheiden kann.
        const typed = await chooserControl
          .fill("", { timeout: 1_000 })
          .then(() => chooserControl.pressSequentially(scriptName, { delay: 60, timeout: 5_000 }))
          .then(() => true)
          .catch(() => false);
        const keyedValue = await chooserControl.inputValue().catch(() => null);
        tracePageEvent(
          page,
          "publish-existing-script-typeahead-keys",
          `${scriptName}:typed=${typed}:value=${JSON.stringify(keyedValue)}`,
        );
        if (typed) {
          scriptOption = await waitForFirstVisibleLocator(
            tvSelectors.publishExistingScriptOption(page, scriptName),
            3_000,
          );
        }
      }
    }
  }
  if (!scriptOption) {
    await tracePublishChooserAbsence(page, "script-option-absent");
    return false;
  }

  return clickVisibleWithFallback(
    page,
    [scriptOption],
    "publish-existing-script-option",
    3_000,
    350,
  );
}

export async function publishPrivateScript(
  page: Page,
  options: {
    scriptName?: string;
    title?: string;
    description?: string;
    requireCleanChartBeforePublish?: boolean;
    publishMode?: "auto" | "update_existing";
  } = {},
): Promise<{
  noChangeDetected: boolean;
  publishConfirmed: boolean;
  publishSurfaceClosedAfterConfirm: boolean;
  versionContextTexts: string[];
  bodyText: string;
}> {
  await dismissSignInModal(page).catch(() => undefined);
  await dismissSymbolSearchDialog(page).catch(() => undefined);
  if (options.requireCleanChartBeforePublish) {
    if (!options.scriptName) {
      throw new Error("requireCleanChartBeforePublish requires scriptName");
    }
    await ensureCleanChartScriptForPublish(page, options.scriptName);
  }
  await ensurePineEditor(page).catch(() => undefined);
  let noChangeDetected = false;

  let clickedPublish = await openPublishSurface(page, 4_000);
  if (!clickedPublish) {
    const compileErrorDetails = await getVisibleCompileErrorDetails(page, 500).catch(() => null);
    if (compileErrorDetails) {
      throw new Error(`Could not open publish flow because TradingView reported a compile error: ${compileErrorDetails}`);
    }
    await tracePublishSurfaceAbsence(page, "open").catch(() => undefined);
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
      await tracePublishSurfaceAbsence(page, `reopen:dialog-add-clicked=${clickedDialogAdd}`).catch(() => undefined);
      throw new Error("Could not reopen publish flow after adding script to chart");
    }
  }

  await page.waitForTimeout(750);
  const openSurfaceBodyText = await page.locator("body").innerText().catch(() => "");

  let publishedViaNewFallback = false;

  if (options.publishMode === "update_existing") {
    if (!options.scriptName) {
      throw new Error("Update existing script publish mode requires scriptName");
    }

    // Run 31381577126 opened TradingView directly on
    // "Update '<name>' library" with the side-by-side diff and Continue
    // button. That is already the exact update surface: it intentionally has
    // neither the generic mode selector nor a Choose script control.
    const directUpdateSurface = hasDirectUpdatePublishSurface(options.scriptName, openSurfaceBodyText);
    if (directUpdateSurface) {
      tracePageEvent(page, "publish-update-existing-direct-surface", options.scriptName);
    } else {
      const selectedUpdateMode = await clickVisibleWithFallback(
        page,
        tvSelectors.publishUpdateExistingMode(page),
        "publish-update-existing-mode",
        2_000,
        350,
      );
      if (!selectedUpdateMode) {
        throw new Error("Could not select Update existing script in TradingView publish flow");
      }

      const selectedExistingScript = await selectExistingPublishScript(page, options.scriptName);
      if (!selectedExistingScript) {
        // 2026-08-20: der Chooser IST nicht das Problem. Screenshot + Inventar
        // aus Lauf 32313143879 (nach #4871) zeigen: Dialog offen, Modus
        // "Update existing script" gewaehlt, `input[placeholder="Choose script"]`
        // sichtbar, der getippte Name steht drin -- und die Liste darunter
        // fuehrt EIN anderes Skript. "Open-Prep Daily Panel" ist schlicht nicht
        // publiziert. Gespeichert (Pine-Editor) != publiziert (Publish-Liste),
        // und `openedExistingScript:true` beschreibt nur das Erste. Damit kann
        // "Update existing" es NIE finden: der Workflow hat seit Einfuehrung des
        // Pfads nie erfolgreich publiziert, also fehlt der Eintrag, also
        // scheitert der naechste Lauf genauso. Fuenf Selektor-Aenderungen
        // konnten daran nichts bewegen.
        //
        // Der Rueckfall auf "Publish new script" bricht diesen Kreis -- EINMAL,
        // danach traegt der Update-Pfad von selbst.
        //
        // ER FEUERT NUR BEI POSITIV BELEGTEM NICHT-TREFFER. Das ist die ganze
        // Sicherheit dieser Stelle: dieser Zweig PUBLIZIERT auf ein echtes
        // TradingView-Konto, und ein Rueckfall auf eine ausbleibende Antwort
        // erzeugt Duplikate. Verlangt werden deshalb zwei positive Belege --
        // der getippte Name steht im Feld UND die Optionsliste hat mindestens
        // einen Eintrag aufgeloest. Fehlt einer davon, ist es ein Sondenfehler
        // und kein Nicht-Treffer, und der alte Wurf bleibt.
        const fallbackEvidence = await gatherPublishNewFallbackEvidence(page, options.scriptName);
        if (fallbackEvidence.eligible) {
          tracePageEvent(
            page,
            "publish-new-fallback",
            `${options.scriptName}:typed=${JSON.stringify(fallbackEvidence.typedValue)}`
              + `:options=${fallbackEvidence.optionCount}`,
          );
          const selectedNewMode = await clickVisibleWithFallback(
            page,
            tvSelectors.publishNewScriptMode(page),
            "publish-new-script-mode",
            2_000,
            350,
          );
          if (!selectedNewMode) {
            throw new Error(
              `Could not select Publish new script after "${options.scriptName}" was found unpublished`
                + `; chooser listed ${fallbackEvidence.optionCount} other script(s)`,
            );
          }
          publishedViaNewFallback = true;
        } else {
        // The trace already carries the inventory, but the trace lives only in
        // the run log. The error travels into the publish report, which is the
        // uploaded artifact -- so put the DOM facts where the evidence is kept.
          const evidence = await tracePublishChooserAbsence(page, "publish-throw");
          throw new Error(
            `Could not select existing TradingView script: ${options.scriptName}`
            + `; publish surface nodes: ${evidence.surfaceCount}`
            + `; chooser typed=${JSON.stringify(fallbackEvidence.typedValue)}`
            + `; chooser options=${fallbackEvidence.optionCount}`
            + `; overlay controls: ${JSON.stringify(evidence.controls).slice(0, 4_000)}`,
          );
        }
      }
    }
  }

  // Der Rueckfall publiziert NEU, auch wenn publishMode nominell
  // "update_existing" ist -- ohne Titel endet das in "Script title is
  // required", also im falschen Gruen vom 2026-08-08.
  if (options.title && (options.publishMode !== "update_existing" || publishedViaNewFallback)) {
    const titleFilled = await fillFirstAndVerify(options.title, tvSelectors.publishTitleInput(page), 1_000);
    if (!titleFilled) {
      throw new Error("Could not fill and verify the TradingView publish title");
    }
  }

  if (options.description) {
    const descriptionFilled = await fillFirstAndVerify(
      options.description,
      tvSelectors.publishDescriptionInput(page),
      1_000,
    );
    if (!descriptionFilled) {
      throw new Error("Could not fill and verify the TradingView publish description");
    }
  }

  for (let stepIndex = 0; stepIndex < 8; stepIndex += 1) {
    const beforeStep = await visiblePublishSurfaceFingerprint(page);
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
      const publishSurfaceClosed = !(await hasPublishSurface(page, 250));
      if (!publishSurfaceClosed) {
        throw new Error("TradingView no-change dialog closed without dismissing the publish surface");
      }
      await ensurePineEditor(page).catch(() => undefined);
      return {
        noChangeDetected,
        publishConfirmed: false,
        publishSurfaceClosedAfterConfirm: true,
        versionContextTexts: [],
        bodyText: await page.locator("body").innerText().catch(() => ""),
      };
    }

    const validationMessage = await visiblePublishValidationMessage(page, 500);
    if (validationMessage) {
      throw new Error(`TradingView publish validation blocked Continue: ${validationMessage}`);
    }

    const afterStep = await visiblePublishSurfaceFingerprint(page);
    const continueStillVisible = await hasVisibleLocatorFast(tvSelectors.publishContinue(page), 250);
    if (!publishStepMadeProgress({ beforeStep, afterStep, continueStillVisible })) {
      throw new Error("TradingView publish Continue had no observable effect");
    }
  }

  const validationMessage = await visiblePublishValidationMessage(page, 500);
  if (validationMessage) {
    throw new Error(`TradingView publish validation blocked confirmation: ${validationMessage}`);
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
      const publishSurfaceClosed = !(await hasPublishSurface(page, 250));
      if (!publishSurfaceClosed) {
        throw new Error("TradingView no-change dialog closed without dismissing the publish surface");
      }
      await ensurePineEditor(page).catch(() => undefined);
      return {
        noChangeDetected,
        publishConfirmed: false,
        publishSurfaceClosedAfterConfirm: true,
        versionContextTexts: [],
        bodyText: await page.locator("body").innerText().catch(() => ""),
      };
    }
    throw new Error("Could not confirm TradingView publish flow after the publish surface opened");
  }

  const evidence = await capturePublishConfirmationEvidence(page, options.scriptName, 12_000);
  const publishConfirmed = publishConfirmationIsAuthoritative({
    publishSurfaceClosed: evidence.publishSurfaceClosed,
    versionContextTexts: evidence.versionContextTexts,
    scriptName: options.scriptName,
  });
  if (!publishConfirmed) {
    const postConfirmValidation = await visiblePublishValidationMessage(page, 500);
    const suffix = postConfirmValidation ? `: ${postConfirmValidation}` : "";
    throw new Error(`TradingView publish confirmation produced no authoritative evidence${suffix}`);
  }
  return {
    noChangeDetected,
    publishConfirmed,
    publishSurfaceClosedAfterConfirm: evidence.publishSurfaceClosed,
    versionContextTexts: evidence.versionContextTexts,
    bodyText: evidence.bodyText || openSurfaceBodyText,
  };
}

// ── Bar Replay driver + on-chart table reader ───────────────────────────────
// Added 2026-07-31. Before this, the repository had no Bar Replay automation:
// the R2.4 evidence was produced by driving TradingView by hand, which left
// nothing reusable and cost a full reconstruction cycle later. The decision
// layer (case plans, expectation matching, table parsing) lives in
// tv_validation_model.ts and is unit-tested; this file owns only the DOM.

/** Open the Object-tree/Data-window panel if it is not already visible. */
export async function openDataWindow(page: Page): Promise<boolean> {
  return runTrackedStep(page, "openDataWindow", async () => {
    const already = await page.locator("[data-test-id-value-title]").first().isVisible().catch(() => false);
    if (already) return true;
    const clicked = await page.evaluate(`(() => {
      const nodes = document.querySelectorAll('button,[role="button"]');
      for (const n of nodes) {
        const label = (n.getAttribute('aria-label') || n.getAttribute('data-tooltip') || n.getAttribute('title') || '');
        if (/data window|object tree/i.test(label)) { n.click(); return label; }
      }
      return null;
    })()`).catch(() => null);
    tracePageEvent(page, "data-window-toggle", String(clicked));
    await page.waitForTimeout(4_000);
    return page.locator("[data-test-id-value-title]").first().isVisible().catch(() => false);
  });
}

/**
 * Read every Data Window row as a label/value pair.
 *
 * Pine tables are canvas-rendered and therefore unreadable; the Data Window is
 * the readable channel. `data-test-id-value-title` is TradingView's own test
 * hook, so this does not depend on hashed class names.
 */
export async function readDataWindowValues(page: Page): Promise<DataWindowItem[]> {
  return runTrackedStep(page, "readDataWindowValues", async () => {
    await openDataWindow(page);
    const items = await page.evaluate(`(() => {
      const out = [];
      const rows = document.querySelectorAll('[data-test-id-value-title]');
      for (const row of rows) {
        const title = row.getAttribute('data-test-id-value-title') || '';
        let value = '';
        const cells = row.querySelectorAll('div');
        for (const c of cells) {
          if (String(c.className).indexOf('valueValue') === 0 || String(c.className).indexOf('valueValue') > -1) {
            value = (c.innerText || '').trim();
          }
        }
        if (title) out.push({ title: title, value: value });
      }
      return out;
    })()`) as DataWindowItem[];
    tracePageEvent(page, "data-window-items", String(items.length));
    return items;
  });
}

async function clickFirstVisible(page: Page, selectors: string[], label: string): Promise<boolean> {
  for (const selector of selectors) {
    const candidate = page.locator(selector).first();
    if (await candidate.isVisible().catch(() => false)) {
      await candidate.click().catch(() => undefined);
      tracePageEvent(page, `${label}-clicked`, selector);
      return true;
    }
  }
  tracePageEvent(page, `${label}-miss`, selectors.join("|"));
  return false;
}

const REPLAY_TOGGLE_SELECTORS = [
  '[data-name="replay"]',
  'button[aria-label*="Replay" i]',
  'button[data-tooltip*="Replay" i]',
  '#header-toolbar-replay',
];

const REPLAY_TOOLBAR = '[data-name="replay-bottom-toolbar"]';

/**
 * Wait for the Bar Replay toolbar itself — the surface every replay control
 * lives on.
 *
 * {@link isBarReplayActive} accepts a body-text fallback, and that is not good
 * enough to drive from: measured 2026-07-31, enterBarReplay returned true
 * 2.5s after the toggle click while the toolbar had not rendered, so the
 * checkpoint jump found no "Select date" control and every DST case failed
 * with "checkpoint did not apply". Anything that intends to CLICK a replay
 * control must wait for the control's own surface.
 */
export async function waitForBarReplayToolbar(page: Page, timeoutMs = 20_000): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await page.locator(REPLAY_TOOLBAR).first().isVisible({ timeout: 500 }).catch(() => false)) {
      return true;
    }
    await page.waitForTimeout(250);
  }
  tracePageEvent(page, "bar-replay-toolbar-timeout", String(timeoutMs));
  return false;
}

/** Enter Bar Replay. Idempotent: a chart already in replay mode is left alone. */
export async function enterBarReplay(page: Page): Promise<boolean> {
  return runTrackedStep(page, "enterBarReplay", async () => {
    if (await page.locator(REPLAY_TOOLBAR).first().isVisible({ timeout: 500 }).catch(() => false)) {
      tracePageEvent(page, "bar-replay-already-active");
      return true;
    }
    if (!(await clickFirstVisible(page, REPLAY_TOGGLE_SELECTORS, "bar-replay-toggle"))) return false;
    // Settle on the toolbar, not on the loose activity probe: returning true
    // before the controls exist strands every caller that wants to use them.
    const ready = await waitForBarReplayToolbar(page);
    tracePageEvent(page, "bar-replay-entered", `toolbar=${ready}`);
    return ready;
  }, Math.max(stepTimeoutMs(), 60_000));
}

/** Leave Bar Replay so the chart is handed back in its ordinary state. */
export async function exitBarReplay(page: Page): Promise<boolean> {
  return runTrackedStep(page, "exitBarReplay", async () => {
    if (!(await isBarReplayActive(page))) return true;
    await clickFirstVisible(page, REPLAY_TOGGLE_SELECTORS, "bar-replay-exit");
    await page.waitForTimeout(2_000);
    return !(await isBarReplayActive(page));
  });
}

export async function isBarReplayActive(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    // Measured 2026-07-31 on the private validation layout: entering Bar
    // Replay adds [data-name="replay-bottom-toolbar"] (text "Select date 1x
    // <tf>"), and neither replay-play-pause nor replay-step-forward exists
    // under those names. The structural marker is therefore the authority.
    // The body-text fallback stays for older/other TradingView surfaces, but
    // it is a substring grep over the first 400 characters and would answer
    // "yes" to any chrome that merely says "Replay" — so it must never be the
    // reason a caller believes replay is active when the toolbar is absent.
    const toolbar = document.querySelector(
      '[data-name="replay-bottom-toolbar"], [data-name="replay-play-pause"], [data-name="replay-step-forward"]',
    );
    if (toolbar) return true;
    const text = document.body?.innerText ?? "";
    return /replay/i.test(text.slice(0, 400));
  }).catch(() => false);
}

const CHART_TIMEZONE_CONTROL = '[aria-label="Timezone"]';

/**
 * Put the chart on a named timezone (measured menu entries: a bare "UTC",
 * "Exchange", then "(UTC±N) City" rows).
 *
 * The R5 DST cases pin their checkpoints as UTC instants, while the Bar Replay
 * date/time dialog reads in CHART-LOCAL time. Typing a UTC instant into a
 * UTC+2 chart silently lands on the wrong bar — exactly the confusion these
 * cases exist to detect — so the driver puts the chart on UTC first and the
 * two clocks coincide.
 */
export async function setChartTimezone(page: Page, label: string): Promise<boolean> {
  return runTrackedStep(page, `setChartTimezone:${label}`, async () => {
    const control = page.locator(CHART_TIMEZONE_CONTROL).first();
    if (!(await control.count())) {
      tracePageEvent(page, "chart-timezone-control-missing", label);
      return false;
    }
    const before = ((await control.innerText().catch(() => "")) ?? "").trim();
    await control.click({ timeout: 5_000, force: true }).catch(() => undefined);
    await page.waitForTimeout(2_000);

    const picked = await page.evaluate((wanted) => {
      for (const el of Array.from(document.querySelectorAll("div,span,button,[role='menuitem']"))) {
        const node = el as HTMLElement;
        const rect = node.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) continue;
        const own = Array.from(node.childNodes)
          .filter((child) => child.nodeType === Node.TEXT_NODE)
          .map((child) => child.textContent ?? "")
          .join("")
          .trim();
        if (own === wanted) {
          node.click();
          return true;
        }
      }
      return false;
    }, label).catch(() => false);

    await page.waitForTimeout(2_500);
    const after = ((await control.innerText().catch(() => "")) ?? "").trim();
    tracePageEvent(page, "chart-timezone", `${label}:picked=${picked}:${before}->${after}`);
    return picked && after.includes(label);
  });
}

export type ReplayCheckpoint = { dateIso: string; timeHhMm: string };

/**
 * Drive Bar Replay to a checkpoint. `dateIso` is YYYY-MM-DD and `timeHhMm` is
 * HH:mm, both read in the chart's current timezone — call
 * {@link setChartTimezone} with "UTC" first when the checkpoint is a UTC
 * instant.
 *
 * Measured dialog (2026-07-31): the replay toolbar carries a "Select date"
 * control which opens [data-name="select-date-dialog"] holding an input with
 * placeholder YYYY-MM-DD and a second input holding HH:mm.
 */
export async function jumpToReplayCheckpoint(page: Page, checkpoint: ReplayCheckpoint): Promise<boolean> {
  return runTrackedStep(page, `jumpToReplayCheckpoint:${checkpoint.dateIso}T${checkpoint.timeHhMm}`, async () => {
    if (!(await waitForBarReplayToolbar(page))) {
      tracePageEvent(page, "replay-checkpoint-not-in-replay", checkpoint.dateIso);
      return false;
    }

    const toolbar = page.locator(REPLAY_TOOLBAR);
    // After a checkpoint has been chosen once, the control shows that date
    // instead of the "Select date" placeholder, so accept either.
    //
    // Poll rather than probe once: the toolbar element becomes visible before
    // its contents render. Measured 2026-07-31 — with a single count() check
    // straight after enterBarReplay every case failed with
    // "no-select-date", while the same query 4s later returned 1.
    const selectDate = toolbar.getByText(/select date|^\d{4}-\d{2}-\d{2}/i).first();
    const controlDeadline = Date.now() + 20_000;
    let controlReady = false;
    while (Date.now() < controlDeadline) {
      if (await selectDate.isVisible({ timeout: 500 }).catch(() => false)) {
        controlReady = true;
        break;
      }
      await page.waitForTimeout(250);
    }
    if (!controlReady) {
      tracePageEvent(page, "replay-checkpoint-no-select-date", checkpoint.dateIso);
      return false;
    }
    await selectDate.click({ timeout: 5_000 }).catch(() => undefined);
    await page.waitForTimeout(2_000);

    const dialog = page.locator('[data-name="select-date-dialog"]');
    if (!(await dialog.first().isVisible({ timeout: 5_000 }).catch(() => false))) {
      tracePageEvent(page, "replay-checkpoint-no-dialog", checkpoint.dateIso);
      return false;
    }

    const dateInput = dialog.locator('input[placeholder="YYYY-MM-DD"]').first();
    const timeInput = dialog.locator("input").nth(1);
    if (!(await dateInput.count()) || !(await timeInput.count())) {
      tracePageEvent(page, "replay-checkpoint-no-inputs", checkpoint.dateIso);
      return false;
    }

    await dateInput.fill(checkpoint.dateIso).catch(() => undefined);
    await timeInput.fill(checkpoint.timeHhMm).catch(() => undefined);
    await page.waitForTimeout(500);

    // Read the fields back before committing: a rejected date silently keeps
    // the previous value, and a checkpoint that never applied must not be
    // reported as reached.
    const echoedDate = (await dateInput.inputValue().catch(() => "")) ?? "";
    const echoedTime = (await timeInput.inputValue().catch(() => "")) ?? "";
    if (echoedDate !== checkpoint.dateIso || echoedTime !== checkpoint.timeHhMm) {
      tracePageEvent(
        page,
        "replay-checkpoint-input-rejected",
        `${checkpoint.dateIso}T${checkpoint.timeHhMm}!=${echoedDate}T${echoedTime}`,
      );
      await page.keyboard.press("Escape").catch(() => undefined);
      return false;
    }

    // Enter does NOT submit this dialog — measured 2026-07-31, the fields
    // accepted the checkpoint and the dialog stayed open, so every case
    // reported "did not apply". The dialog's own footer buttons are "Cancel"
    // and "Select"; the latter is the commit.
    const confirm = dialog.getByRole("button", { name: /^select$/i }).first();
    if (!(await confirm.isVisible({ timeout: 5_000 }).catch(() => false))) {
      tracePageEvent(page, "replay-checkpoint-no-confirm", checkpoint.dateIso);
      await page.keyboard.press("Escape").catch(() => undefined);
      return false;
    }
    await confirm.click({ timeout: 5_000 }).catch(() => undefined);

    const closeDeadline = Date.now() + 20_000;
    let dialogGone = false;
    while (Date.now() < closeDeadline) {
      if (!(await dialog.first().isVisible({ timeout: 500 }).catch(() => false))) {
        dialogGone = true;
        break;
      }
      await page.waitForTimeout(250);
    }
    // Give the chart time to reload history at the checkpoint before any
    // caller reads diagnostics off it.
    if (dialogGone) await page.waitForTimeout(6_000);
    tracePageEvent(page, "replay-checkpoint-applied", `${checkpoint.dateIso}T${checkpoint.timeHhMm}:closed=${dialogGone}`);
    return dialogGone;
  }, Math.max(stepTimeoutMs(), 90_000));
}

/**
 * Read the chart timeframe the Bar Replay toolbar is stepping in ("5m", "1h").
 * Returns the raw label; callers convert with `timeframeLabelToMinutes`.
 */
export async function readReplayTimeframeLabel(page: Page, timeoutMs = 20_000): Promise<string | null> {
  if (!(await waitForBarReplayToolbar(page, timeoutMs))) return null;
  const toolbar = page.locator(REPLAY_TOOLBAR).first();
  // Poll for CONTENT, not just for the element. The toolbar becomes visible
  // before it renders its children — the same race that made the first
  // checkpoint attempts fail, observed a third time here as an empty label.
  const deadline = Date.now() + timeoutMs;
  let text = "";
  while (Date.now() < deadline) {
    text = ((await toolbar.innerText().catch(() => "")) ?? "").trim();
    if (text) break;
    await page.waitForTimeout(250);
  }
  // Measured layout: "Select date\n1x\n5m" — speed then timeframe.
  const match = /(\d+\s*[smhdwSMHDW])\s*$/.exec(text);
  const label = match ? match[1].replace(/\s+/g, "") : null;
  tracePageEvent(page, "replay-timeframe-label", `${JSON.stringify(text)}->${label ?? "none"}`);
  return label;
}

/**
 * Set the chart's data session mode.
 *
 * Measured 2026-07-31: chart settings (`[data-name="header-toolbar-properties"]`)
 * -> Symbol tab -> "DATA MODIFICATION" -> a "Session" dropdown whose options are
 * exactly "Regular", "Extended" and "24 hours". This is what an extended-hours
 * case needs; without it the requested instant simply has no bar and Bar Replay
 * clamps to the last regular-session bar.
 *
 * Applies with the dialog's "Ok" button and reports whether the control ended
 * up on the requested value, so a caller can fail closed instead of driving a
 * chart that never changed mode.
 */
export async function setChartSessionMode(page: Page, mode: "Regular" | "Extended" | "24 hours"): Promise<boolean> {
  return runTrackedStep(page, `setChartSessionMode:${mode}`, async () => {
    const opened = await page.locator('[data-name="header-toolbar-properties"]').first()
      .click({ timeout: 5_000 }).then(() => true).catch(() => false);
    if (!opened) {
      tracePageEvent(page, "chart-session-no-settings", mode);
      return false;
    }
    await page.waitForTimeout(2_000);
    await page.getByText(/^Symbol$/).first().click({ timeout: 5_000 }).catch(() => undefined);
    await page.waitForTimeout(1_500);

    const current = await page.evaluate(() => {
      for (const el of Array.from(document.querySelectorAll("span,div"))) {
        const node = el as HTMLElement;
        const own = Array.from(node.childNodes)
          .filter((child) => child.nodeType === Node.TEXT_NODE)
          .map((child) => child.textContent ?? "")
          .join("")
          .trim();
        if (own === "Regular" || own === "Extended" || own === "24 hours") {
          const rect = node.getBoundingClientRect();
          if (rect.width > 0 && rect.height > 0) return own;
        }
      }
      return null;
    }).catch(() => null);

    if (current === mode) {
      tracePageEvent(page, "chart-session-already", mode);
      await page.getByText(/^Cancel$/).first().click({ timeout: 3_000 }).catch(() => undefined);
      return true;
    }
    if (current === null) {
      tracePageEvent(page, "chart-session-no-control", mode);
      await page.keyboard.press("Escape").catch(() => undefined);
      return false;
    }

    await page.getByText(new RegExp(`^${current}$`)).first().click({ timeout: 5_000 }).catch(() => undefined);
    await page.waitForTimeout(1_500);
    // The closed control still shows the old value, so the OPTION is the second
    // match; pick the lowest one on screen, which is the list entry.
    const picked = await page.evaluate((wanted) => {
      const hits: HTMLElement[] = [];
      for (const el of Array.from(document.querySelectorAll("span,div,[role='option']"))) {
        const node = el as HTMLElement;
        const own = Array.from(node.childNodes)
          .filter((child) => child.nodeType === Node.TEXT_NODE)
          .map((child) => child.textContent ?? "")
          .join("")
          .trim();
        if (own !== wanted) continue;
        const rect = node.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0) hits.push(node);
      }
      if (!hits.length) return false;
      hits.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);
      hits[0].click();
      return true;
    }, mode).catch(() => false);
    await page.waitForTimeout(1_500);

    await page.getByText(/^Ok$/).first().click({ timeout: 5_000 }).catch(() => undefined);
    await page.waitForTimeout(6_000);
    tracePageEvent(page, "chart-session-mode", `${current}->${mode}:picked=${picked}`);
    return picked;
  }, Math.max(stepTimeoutMs(), 60_000));
}

/**
 * Step Bar Replay forward by one chart bar.
 *
 * The control must NOT be addressed by `[title="Forward"]`. TradingView's
 * `apply-common-tooltip` machinery strips the `title` attribute while its own
 * tooltip is up and does not restore it while the pointer remains on the
 * button — so a title-based locator finds it exactly ONCE and never again.
 * Measured 2026-07-31 by diffing the toolbar around a click: the element stays
 * at the same position with the same classes, only `title="Forward"` becomes
 * `title=""`. That single-use behaviour is what made every multi-step run
 * report "the frame never advanced", on 5m and 15m alike.
 *
 * The stable identity is structural: inside the replay toolbar the interactive
 * `controls__button` elements are, in order, Play, Forward, Replay speed,
 * Update interval, Jump to real-time chart. Forward is index 1.
 */
export async function stepReplayForward(page: Page, bars = 1, settleMs = 2_500): Promise<number> {
  return runTrackedStep(page, `stepReplayForward:${bars}`, async () => {
    if (!(await waitForBarReplayToolbar(page))) return 0;

    const controls = page.locator(`${REPLAY_TOOLBAR} [class*="controls__button"]`);
    const deadline = Date.now() + 25_000;
    let ready = false;
    while (Date.now() < deadline) {
      if ((await controls.count().catch(() => 0)) >= 2) {
        ready = true;
        break;
      }
      await page.waitForTimeout(250);
    }
    if (!ready) {
      tracePageEvent(page, "replay-forward-missing", String(bars));
      return 0;
    }
    const forward = controls.nth(1);

    // Guard the ordinal against a toolbar reshuffle: on the first pass the
    // title is still present, so it can be confirmed once. A later pass sees
    // an empty title by design and must not treat that as a mismatch.
    const firstTitle = await forward.getAttribute("title").catch(() => null);
    if (firstTitle !== null && firstTitle !== "" && !/forward/i.test(firstTitle)) {
      tracePageEvent(page, "replay-forward-ordinal-mismatch", firstTitle);
      return 0;
    }

    let stepped = 0;
    for (let index = 0; index < bars; index += 1) {
      const clicked = await forward.click({ timeout: 8_000 }).then(() => true).catch(() => false);
      if (!clicked) break;
      stepped += 1;
      await page.waitForTimeout(settleMs);
    }
    tracePageEvent(page, "replay-forward-stepped", `${stepped}/${bars}`);
    return stepped;
  }, Math.max(stepTimeoutMs(), 180_000));
}

/**
 * Put the chart on a timeframe ("5", "15", "60", "240").
 *
 * FAIL-CLOSED needs the chart moved ONTO the requested frames so the script's
 * strictly-higher rule can be observed rejecting equal and lower ones; that is
 * a chart-level change, not a replay one.
 *
 * Reports whether the interval control ended up showing the requested value,
 * so a caller can fail closed rather than measure the previous timeframe.
 */
export async function setChartInterval(page: Page, interval: string): Promise<boolean> {
  return runTrackedStep(page, `setChartInterval:${interval}`, async () => {
    const control = page.locator('[data-tooltip="Change interval"], [aria-label="Change interval"]').first();
    if (!(await control.isVisible({ timeout: 5_000 }).catch(() => false))) {
      tracePageEvent(page, "chart-interval-control-missing", interval);
      return false;
    }
    // The control shows "1h" for 60 and "4h" for 240, not the typed number.
    const expected = chartIntervalDisplayLabel(interval);
    if (expected === null) {
      tracePageEvent(page, "chart-interval-unmappable", interval);
      return false;
    }
    const before = ((await control.innerText().catch(() => "")) ?? "").trim();
    if (before === expected) {
      tracePageEvent(page, "chart-interval-already", interval);
      return true;
    }
    // The keyboard route is TradingView's own and avoids depending on the
    // menu's hashed rows: type the interval, then Enter.
    await page.locator("body").click({ position: { x: 400, y: 400 } }).catch(() => undefined);
    await page.waitForTimeout(300);
    for (const character of interval) {
      await page.keyboard.press(character).catch(() => undefined);
      await page.waitForTimeout(120);
    }
    await page.keyboard.press("Enter").catch(() => undefined);
    await page.waitForTimeout(6_000);
    const after = ((await control.innerText().catch(() => "")) ?? "").trim();
    tracePageEvent(page, "chart-interval", `${before}->${after} (wanted ${interval} shown as ${expected})`);
    return after === expected;
  }, Math.max(stepTimeoutMs(), 60_000));
}

/**
 * Read the chart state R5-REBUILD-ROLLBACK restores, from measured selectors.
 *
 * Measured 2026-07-31 on the R5 validation layout:
 *   symbol    `#header-toolbar-symbol-search`            -> "AAPL"
 *   interval  `[aria-label="Change interval"]`           -> "5" / "1h" / "4h"
 *   layout    `#header-toolbar-save-load`                -> "SMC HTF Context
 *                                                           R5 Validation\nSave"
 *   timezone  `[data-name="time-zone-menu"]`             -> "14:30:13 UTC"
 *   studies   `[class*="sourcesWrapper"] [class*="item"]`-> ["Vol", "SMC
 *                                                           Session Context",
 *                                                           "SMC HTF Confluence"]
 *
 * The interval control is the same one `setChartInterval` verifies against, so
 * it is already proven to report the display label rather than the typed value.
 *
 * Every field is nullable and nothing is defaulted: `compareChartState` treats
 * an unreadable field as a difference, so a broken reader fails the drill
 * instead of certifying a rollback nobody observed.
 */
export async function readChartStateSnapshot(page: Page): Promise<ChartStateSnapshot> {
  return runTrackedStep(page, "readChartStateSnapshot", async () => {
    const raw = await page.evaluate(`(() => {
      function text(sel) {
        var el = document.querySelector(sel);
        if (!el) return null;
        var t = (el.innerText || '').trim();
        return t.length > 0 ? t : null;
      }
      var studies = [];
      var rows = document.querySelectorAll('[class*="sourcesWrapper"] [class*="item"]');
      for (var i = 0; i < rows.length; i++) {
        var s = (rows[i].innerText || '').trim().replace(/\\s+/g, ' ');
        if (s && studies.indexOf(s) === -1) studies.push(s);
      }
      return {
        layoutRaw: text('#header-toolbar-save-load'),
        symbol: text('#header-toolbar-symbol-search'),
        interval: text('[aria-label="Change interval"]') || text('[data-tooltip="Change interval"]'),
        clock: text('[data-name="time-zone-menu"]'),
        studies: studies
      };
    })()`) as {
      layoutRaw: string | null;
      symbol: string | null;
      interval: string | null;
      clock: string | null;
      studies: string[];
    };

    // "SMC HTF Context R5 Validation\nSave" -> the layout name is the first line.
    const layoutName = raw.layoutRaw === null ? null : (raw.layoutRaw.split("\n")[0] ?? "").trim() || null;
    // "14:30:13 UTC" -> the zone is the trailing token; the time itself moves and
    // is deliberately not part of the state.
    const timezone = raw.clock === null ? null : (raw.clock.trim().split(/\s+/).pop() ?? null);

    const snapshot: ChartStateSnapshot = {
      layoutName,
      symbol: raw.symbol,
      interval: raw.interval,
      timezone,
      studies: raw.studies,
    };
    tracePageEvent(page, "chart-state", JSON.stringify(snapshot));
    return snapshot;
  });
}

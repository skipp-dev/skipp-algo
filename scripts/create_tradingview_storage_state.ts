#!/usr/bin/env -S node --enable-source-maps

import fs from "node:fs";
import path from "node:path";

import { authenticator } from "otplib";

import { inspectTradingViewStorageState } from "../automation/tradingview/lib/tv_validation_model.js";
import {
  collectTradingViewPageAuthState,
  launchTradingViewChromium,
  launchTradingViewPersistentContext,
  resolveTradingViewHeadlessDefault,
  resolveTradingViewLaunchOptions,
  isOtpEntryComplete,
  planOtpEntry,
  revealEmailLoginField,
  TV_LOGIN_IDENTIFIER_SELECTOR,
  TV_OTP_FIELD_SELECTOR,
} from "../automation/tradingview/lib/tv_shared.js";

/**
 * Viewport for the interactive storage-state capture session (differs from
 * TRADINGVIEW_SESSION_VIEWPORT). Kept in sync with the Xvfb virtual-screen size
 * in .github/workflows/tradingview-storage-refresh.yml ("1440x1100x24") — the CI
 * capture currently runs --headless (Xvfb inert), but a headed CI run would clip
 * if the two ever diverge.
 */
const STORAGE_STATE_CAPTURE_VIEWPORT = { width: 1440, height: 1100 } as const;

type CliArgs = {
  out: string;
  inputStorageState?: string;
  loginUrl: string;
  chartUrl: string;
  waitTimeoutMs: number;
  pollIntervalMs: number;
  persistentProfileDir?: string;
  username?: string;
  password?: string;
  totpSecret?: string;
  headless: boolean;
};

async function collectPageAuthDiagnostics(page: import("playwright").Page): Promise<{
  url: string;
  title: string;
  bodyPreview: string;
  signInSignals: boolean;
  authenticated: boolean;
  authReason: string;
  authProbeStatuses: number[];
}> {
  // Fail-soft like the auth-state probe below: a crashed page / destroyed
  // execution context must degrade to empty diagnostics, not throw past the
  // callers that rely on this function's best-effort contract.
  const domDiagnostics = await page.evaluate(() => {
    const bodyText = (document.body?.innerText || "").replace(/\s+/g, " ").trim();
    return {
      url: location.href,
      title: document.title,
      bodyPreview: bodyText.slice(0, 240),
      signInSignals: /sign in|log in|email|password|continue with google/i.test(bodyText),
    };
  }).catch((error) => {
    // Clone of the auth-state probe evaluate in tv_shared: a crashed execution
    // context returns the same empty diagnostics as a legitimately blank page.
    // Warn so the swallowed failure is visible to the operator running this
    // interactive script instead of looking like a genuinely signed-out page.
    console.warn(`[tv-auth] page auth diagnostics DOM probe crashed; using empty diagnostics: ${error instanceof Error ? error.message : String(error)}`);
    return { url: "", title: "", bodyPreview: "", signInSignals: false };
  });
  const pageAuthState = await collectTradingViewPageAuthState(page).catch(() => null);

  return {
    ...domDiagnostics,
    signInSignals: domDiagnostics.signInSignals || pageAuthState?.explicitlyAnonymous === true || pageAuthState?.authenticated === false,
    authenticated: pageAuthState?.authenticated === true,
    authReason: pageAuthState?.reason ?? "auth_state_probe_failed",
    authProbeStatuses: pageAuthState?.evidence.accountProbeStatuses ?? [],
  };
}

async function assistTwoFactorSubmission(
  page: import("playwright").Page,
  totpSecret?: string,
): Promise<void> {
  const bodyText = await page.locator("body").innerText().catch(() => "");
  if (!/two-factor authentication|verification code|backup code|code from your app/i.test(bodyText)) {
    return;
  }

  const codeFields = page.locator(TV_OTP_FIELD_SELECTOR);
  const fieldCount = await codeFields.count().catch(() => 0);
  const codeField = codeFields.first();

  const fieldVisible = fieldCount > 0 && (await codeField.isVisible().catch(() => false));

  const readEnteredCode = async (): Promise<string> => {
    if (!fieldVisible) {
      return "";
    }
    const values = await codeFields.evaluateAll(
      (nodes) => nodes.map((node) => (node as HTMLInputElement).value || ""),
    ).catch(() => [] as string[]);
    return values.join("").trim();
  };

  // If we have a TOTP secret, generate the current 6-digit code and enter it.
  if (totpSecret && fieldVisible) {
    try {
      const token = authenticator.generate(totpSecret);
      const shapes = await codeFields.evaluateAll(
        (nodes) => nodes.map((node) => ({ maxLength: (node as HTMLInputElement).maxLength })),
      ).catch(() => [] as { maxLength: number }[]);
      const plan = planOtpEntry(shapes, token.length);

      // Type instead of fill(): a per-digit layout auto-advances on keystrokes,
      // and framework-backed single fields ignore a value written straight to
      // the DOM. fill() wrote all six digits into box one — the bug this fixes.
      await codeField.click({ timeout: 2_000 }).catch(() => undefined);
      if (plan.perBox) {
        await page.keyboard.type(token, { delay: 60 });
      } else {
        await codeField.fill("").catch(() => undefined);
        await codeField.pressSequentially(token, { delay: 40 }).catch(() => undefined);
      }
      await page.waitForTimeout(500);

      const entered = await readEnteredCode();
      console.log(
        `TOTP code entered — fields=${fieldCount} plan=${plan.reason} `
        + `complete=${isOtpEntryComplete(entered, token)} digits=${entered.length}/${token.length}`,
      );
    } catch (err) {
      console.warn(`TOTP generation failed: ${err instanceof Error ? err.message : String(err)}. Proceeding without filling.`);
    }
  }

  const currentValue = await readEnteredCode();
  const hasLikelyCode = currentValue.length >= 6;
  if (fieldVisible && !hasLikelyCode) {
    console.warn(
      `2FA code incomplete (${currentValue.length}/6 digits across ${fieldCount} field(s)) — `
      + "not submitting; the next poll retries with a fresh code.",
    );
  }

  const submitCandidates = [
    page.getByRole("button", { name: /continue/i }),
    page.getByRole("button", { name: /verify/i }),
    page.getByRole("button", { name: /submit/i }),
    page.getByRole("button", { name: /sign in/i }),
    page.getByRole("button", { name: /next/i }),
    page.locator('button:has-text("Continue")'),
    page.locator('button:has-text("Verify")'),
    page.locator('button:has-text("Submit")'),
    page.locator('button:has-text("Next")'),
    page.locator('[role="button"]:has-text("Continue")'),
    page.locator('[role="button"]:has-text("Verify")'),
    page.locator('[role="button"]:has-text("Submit")'),
    page.locator('[role="button"]:has-text("Next")'),
    page.locator('button[type="submit"]'),
    page.locator('[type="submit"]'),
  ];

  for (const candidate of submitCandidates) {
    const count = await candidate.count().catch(() => 0);
    if (count === 0) {
      continue;
    }

    const button = candidate.first();
    const isVisible = await button.isVisible().catch(() => false);
    const isEnabled = await button.isEnabled().catch(() => false);
    if (!isVisible || !isEnabled) {
      continue;
    }

    if (!hasLikelyCode && fieldVisible) {
      continue;
    }

    const label = (await button.innerText().catch(() => "")).trim().split("\n")[0];
    console.log(`2FA submit clicked ("${label || "unlabelled"}").`);
    await button.click({ timeout: 2_000 }).catch(() => undefined);
    await page.waitForTimeout(750);
    return;
  }

  if (hasLikelyCode || !fieldVisible) {
    const labels = await page
      .locator("button, [role=\"button\"]")
      .evaluateAll((nodes) =>
        nodes
          .map((node) => (node.textContent || "").trim().split("\n")[0])
          .filter(Boolean)
          .slice(0, 12),
      )
      .catch(() => [] as string[]);
    console.warn(
      `2FA code is entered but no submit control matched — buttons on page: ${JSON.stringify(labels)}`,
    );
  }

  if (hasLikelyCode && fieldVisible) {
    await codeField.focus().catch(() => undefined);
    await codeField.press("Enter").catch(() => undefined);
    await page.keyboard.press("Enter").catch(() => undefined);
    await page.waitForTimeout(750);
  }
}


function parseArgs(): CliArgs {
  const args = process.argv.slice(2);

  function getFlag(name: string, fallback: string): string {
    const idx = args.indexOf(name);
    if (idx === -1 || !args[idx + 1]) {
      return fallback;
    }
    return args[idx + 1];
  }

  return {
    out: path.resolve(
      getFlag(
        "--out",
        process.env.TV_STORAGE_STATE || "automation/tradingview/auth/storage-state.json",
      ),
    ),
    inputStorageState: (getFlag(
      "--input-storage-state",
      process.env.TV_STORAGE_STATE_INPUT || "",
    ) || "").trim() || undefined,
    loginUrl: getFlag(
      "--login-url",
      process.env.TV_LOGIN_URL || "https://www.tradingview.com/accounts/signin/",
    ),
    chartUrl: getFlag(
      "--chart-url",
      process.env.TV_CHART_URL || "https://www.tradingview.com/chart/",
    ),
    waitTimeoutMs: Number.parseInt(
      getFlag("--wait-timeout-ms", process.env.TV_STORAGE_WAIT_TIMEOUT_MS || "900000"),
      10,
    ),
    pollIntervalMs: Number.parseInt(
      getFlag("--poll-interval-ms", process.env.TV_STORAGE_POLL_INTERVAL_MS || "3000"),
      10,
    ),
    persistentProfileDir: getFlag(
      "--persistent-profile-dir",
      process.env.TV_PERSISTENT_PROFILE_DIR || "",
    ).trim() || undefined,
    username: (getFlag("--username", process.env.TV_USERNAME || "") || "").trim() || undefined,
    password: (getFlag("--password", process.env.TV_PASSWORD || "") || "").trim() || undefined,
    totpSecret: (getFlag("--totp-secret", process.env.TV_TOTP_SECRET || "") || "").trim() || undefined,
    // Canonical TV_HEADLESS semantics ("1"/"true"/"yes"/"on" + CI fallback) — the
    // previous `=== "1"` parse silently diverged from every other TV entry point.
    headless: args.includes("--headless") || resolveTradingViewHeadlessDefault(process.env),
  };
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForUserOrAuthenticatedChart(
  page: import("playwright").Page,
  context: import("playwright").BrowserContext,
  cli: CliArgs,
): Promise<void> {
  console.log(
    `Waiting up to ${Math.round(cli.waitTimeoutMs / 1000)}s for an authenticated TradingView chart session...`,
  );

  const deadline = Date.now() + cli.waitTimeoutMs;
  while (Date.now() < deadline) {
    await page.waitForTimeout(1_000);
      await assistTwoFactorSubmission(page, cli.totpSecret).catch(() => undefined);
    const authDiagnostics = await collectPageAuthDiagnostics(page).catch(() => undefined);
    const storageState = await context.storageState({ indexedDB: true }).catch(() => undefined);
    const inspection = storageState ? inspectTradingViewStorageState(storageState) : undefined;

    if (
      authDiagnostics?.url.includes("/chart") &&
      !authDiagnostics.signInSignals &&
      authDiagnostics.authenticated &&
      (inspection?.looksAuthenticated || Boolean(cli.persistentProfileDir))
    ) {
      console.log("Authenticated TradingView chart session detected.");
      return;
    }

    await sleep(cli.pollIntervalMs);
  }

  throw new Error(
    `Timed out waiting for an authenticated TradingView chart session after ${Math.round(cli.waitTimeoutMs / 1000)}s. Log in fully, dismiss any sign-in overlay, open the chart, then rerun npm run tv:storage-state.`,
  );
}

async function attemptAutomatedLogin(
  page: import("playwright").Page,
  cli: CliArgs,
): Promise<void> {
  if (!cli.username || !cli.password) {
    return;
  }
  console.log("Attempting automated login with TV_USERNAME / TV_PASSWORD ...");
  try {
    // ── email / username field ───────────────────────────────────────
    // TradingView creates this input only after the "Email" chooser is clicked,
    // so reveal it FIRST. Waiting on it up front (as this did until 2026-07-28)
    // always burns the timeout and drops the run into the interactive branch.
    if (!(await revealEmailLoginField(page))) {
      console.warn(
        "Sign-in page exposed no e-mail/username field (chooser missing or "
        + "social-only login) — automated login cannot proceed.",
      );
      return;
    }
    const emailField = page.locator(TV_LOGIN_IDENTIFIER_SELECTOR).first();
    await emailField.waitFor({ state: "visible", timeout: 10_000 });
    await emailField.fill(cli.username);

    // Try clicking "Email" tab or "Sign in" — fall back to Enter
    const emailSubmit = page.locator(
      'button:has-text("Email"), button:has-text("Sign in"), ' +
      'button[type="submit"], button:has-text("Continue"), button:has-text("Next")',
    ).first();
    if (await emailSubmit.isVisible().catch(() => false)) {
      await emailSubmit.click({ timeout: 3_000 }).catch(() => undefined);
    } else {
      await emailField.press("Enter");
    }
    await page.waitForTimeout(2_000);

    // ── password field (same page or next page) ─────────────────────
    const passwordField = page.locator(
      'input[name="id_password"], input[name="password"], input[type="password"]',
    ).first();
    await passwordField.waitFor({ state: "visible", timeout: 10_000 });
    await passwordField.fill(cli.password);

    const signInBtn = page.locator(
      'button:has-text("Sign in"), button[type="submit"], button:has-text("Log in")',
    ).first();
    if (await signInBtn.isVisible().catch(() => false)) {
      await signInBtn.click({ timeout: 3_000 }).catch(() => undefined);
    } else {
      await passwordField.press("Enter");
    }
    await page.waitForTimeout(3_000);
    console.log("Automated login form submitted — waiting for authentication ...");
  } catch (err) {
    console.warn(
      `Automated login attempt failed (${err instanceof Error ? err.message : String(err)}). ` +
      "Falling back to manual login — complete the login in the browser window.",
    );
  }
}

async function main(): Promise<number> {
  const cli = parseArgs();

  fs.mkdirSync(path.dirname(cli.out), { recursive: true });
  const storageStatePath = cli.inputStorageState
    ? path.resolve(cli.inputStorageState)
    : undefined;
  const existingStorageStatePath =
    storageStatePath && fs.existsSync(storageStatePath) ? storageStatePath : undefined;

  if (storageStatePath && !existingStorageStatePath) {
    console.warn(`Input storage state not found, continuing without bootstrap: ${storageStatePath}`);
  }

  // Persistent-profile mode is exempt: it always launches HEADED (headless is
  // ignored there), so an interactive login without credentials works fine.
  if (cli.headless && !cli.persistentProfileDir && !existingStorageStatePath && (!cli.username || !cli.password)) {
    throw new Error(
      "Headless TradingView storage-state capture requires TV_STORAGE_STATE_INPUT or TV_USERNAME/TV_PASSWORD fallback credentials. "
      + "If you meant to log in interactively, note that headless defaults to true under CI (or TV_HEADLESS): "
      + "set TV_HEADLESS=0 to launch a headed browser for manual login.",
    );
  }

  let browser: import("playwright").Browser;
  let context: import("playwright").BrowserContext;
  let page: import("playwright").Page;

  if (cli.persistentProfileDir) {
    // Resolve (and validate) env-driven launch options BEFORE the mkdir side effect.
    // The interactive login profile always launches headed (pre-existing contract) —
    // say so instead of silently discarding an explicit headless request.
    const launchOptions = { ...resolveTradingViewLaunchOptions(process.env), headless: false, slowMo: 100 };
    if (cli.headless) {
      console.warn(
        "[tv-storage-state] --headless/TV_HEADLESS is ignored in persistent-profile mode: the interactive login profile always launches headed.",
      );
    }
    const profileDir = cli.persistentProfileDir;
    fs.mkdirSync(profileDir, { recursive: true });
    // Persistent helper: this script MINTS the shared auth profile — it must never
    // be created under a different browser build than the bundled chromium that
    // newTradingViewSession later opens it with.
    context = await launchTradingViewPersistentContext(profileDir, launchOptions, STORAGE_STATE_CAPTURE_VIEWPORT);
    const launchedBrowser = context.browser();
    if (!launchedBrowser) {
      throw new Error(`Could not resolve browser for persistent TradingView profile: ${cli.persistentProfileDir}`);
    }
    browser = launchedBrowser;
    page = context.pages()[0] ?? (await context.newPage());
  } else {
    browser = await launchTradingViewChromium({ headless: cli.headless, slowMo: cli.headless ? 0 : 100 });

    context = await browser.newContext({
      viewport: STORAGE_STATE_CAPTURE_VIEWPORT,
      ...(existingStorageStatePath ? { storageState: existingStorageStatePath } : {}),
    });

    page = await context.newPage();
  }

  console.log("");
  console.log("TradingView storage-state capture");
  console.log("--------------------------------");
  console.log(`Output file : ${cli.out}`);
  if (existingStorageStatePath) {
    console.log(`Input state : ${existingStorageStatePath}`);
  }
  console.log(`Login URL   : ${cli.loginUrl}`);
  console.log(`Chart URL   : ${cli.chartUrl}`);
  if (cli.persistentProfileDir) {
    console.log(`Profile dir : ${cli.persistentProfileDir}`);
  }
  console.log("");
  if (cli.username) {
    console.log("Credentials provided (TV_USERNAME / TV_PASSWORD) — automated login will be attempted.");
    console.log("If MFA/CAPTCHA appears, the existing 2FA auto-submit helper will try to continue.");
    console.log("If automation fails, fall back to completing the login in the browser window.");
  } else {
    console.log("A browser window will open.");
    console.log("1) Log in to TradingView manually.");
    console.log("2) If needed, solve MFA/CAPTCHA manually.");
    console.log("3) After login, open a TradingView chart page successfully.");
    console.log("4) Leave this process running while the script polls the current browser page.");
  }
  console.log("");

  await page.goto(cli.persistentProfileDir || existingStorageStatePath ? cli.chartUrl : cli.loginUrl, {
    waitUntil: "domcontentloaded",
  });

  const initialDiagnostics = await collectPageAuthDiagnostics(page).catch(() => undefined);
  const shouldTryLogin = Boolean(
    cli.username
    && cli.password
    && (!existingStorageStatePath || initialDiagnostics?.signInSignals || !page.url().includes("/chart")),
  );
  if (shouldTryLogin) {
    if (!page.url().includes("/accounts/signin")) {
      await page.goto(cli.loginUrl, { waitUntil: "domcontentloaded" });
    }
    await attemptAutomatedLogin(page, cli);
  }

  await waitForUserOrAuthenticatedChart(page, context, cli);

  const currentUrl = page.url();
  if (!currentUrl.includes("tradingview.com")) {
    console.warn(`Warning: current page URL is unexpected: ${currentUrl}`);
  }

  if (!currentUrl.includes("/chart")) {
    console.log("Navigating to chart URL once before saving storage state...");
    await page.goto(cli.chartUrl, { waitUntil: "domcontentloaded" });
  }

  await page.waitForTimeout(2_000);
  const authDiagnostics = await collectPageAuthDiagnostics(page);
  const storageState = await context.storageState({ indexedDB: true });
  const inspection = inspectTradingViewStorageState(storageState);

  if (!authDiagnostics.url.includes("/chart")) {
    throw new Error(
      `Chart page is not active after login. Current URL: ${authDiagnostics.url}. Open the TradingView chart successfully before pressing Enter.`,
    );
  }

  if (authDiagnostics.signInSignals || !authDiagnostics.authenticated || (!inspection.looksAuthenticated && !cli.persistentProfileDir)) {
    const cookiePreview = inspection.cookieNames.slice(0, 8).join(", ") || "none";
    const storagePreview = inspection.localStorageKeys.slice(0, 8).join(", ") || "none";
    const probePreview = authDiagnostics.authProbeStatuses.length > 0
      ? authDiagnostics.authProbeStatuses.join(",")
      : "no_probe";
    throw new Error(
      `Captured TradingView session still looks anonymous. Reason: ${authDiagnostics.authReason}. Auth probe statuses: ${probePreview}. URL: ${authDiagnostics.url}. Title: ${authDiagnostics.title}. Body preview: ${JSON.stringify(authDiagnostics.bodyPreview)}. Cookies: ${cookiePreview}. Local storage keys: ${storagePreview}. Log in fully, dismiss any sign-in overlay, open the chart, then rerun npm run tv:storage-state.`,
    );
  }

  // Normal authenticated session: always write meta.authValidatedAt so that
  // credential_health_check.py (which requires meta.authValidatedAt) does not
  // report "storage_state missing meta block".
  const storageStateToWrite: Record<string, unknown> = {
    ...(storageState as Record<string, unknown>),
    meta: {
      authValidatedAt: new Date().toISOString(),
      validationMode: "standard_session",
      chartUrl: authDiagnostics.url,
      authReason: authDiagnostics.authReason,
      authProbeStatuses: authDiagnostics.authProbeStatuses,
    },
  };

  fs.writeFileSync(cli.out, JSON.stringify(storageStateToWrite, null, 2) + "\n", "utf-8");

  console.log("");
  console.log(`Storage state saved to: ${cli.out}`);
  console.log("");

  await context.close();
  await browser.close();
  return 0;
}

main()
  .then((code) => process.exit(code))
  .catch((error: unknown) => {
    console.error(error instanceof Error ? error.stack || error.message : String(error));
    process.exit(1);
  });

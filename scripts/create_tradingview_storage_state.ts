#!/usr/bin/env -S node --enable-source-maps

import fs from "node:fs";
import path from "node:path";

import { chromium } from "playwright";
import { authenticator } from "otplib";

import { inspectTradingViewStorageState } from "../automation/tradingview/lib/tv_validation_model.js";

type CliArgs = {
  out: string;
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
}> {
  return page.evaluate(() => {
    const bodyText = (document.body?.innerText || "").replace(/\s+/g, " ").trim();
    return {
      url: location.href,
      title: document.title,
      bodyPreview: bodyText.slice(0, 240),
      signInSignals: /sign in|log in|email|password|continue with google/i.test(bodyText),
    };
  });
}

async function assistTwoFactorSubmission(
  page: import("playwright").Page,
  totpSecret?: string,
): Promise<void> {
  const bodyText = await page.locator("body").innerText().catch(() => "");
  if (!/two-factor authentication|verification code|backup code|code from your app/i.test(bodyText)) {
    return;
  }

  const codeField = page.locator(
    'input[autocomplete="one-time-code"], input[inputmode="numeric"], input[name*="code" i], input[placeholder*="code" i], input[type="tel"], input[type="text"]',
  ).first();

  const fieldVisible = (await codeField.count().catch(() => 0)) > 0 && (await codeField.isVisible().catch(() => false));

  // If we have a TOTP secret, generate the current 6-digit code and fill it.
  if (totpSecret && fieldVisible) {
    try {
      const token = authenticator.generate(totpSecret);
      console.log("TOTP code generated — filling 2FA field automatically.");
      await codeField.fill(token);
      await page.waitForTimeout(500);
    } catch (err) {
      console.warn(`TOTP generation failed: ${err instanceof Error ? err.message : String(err)}. Proceeding without filling.`);
    }
  }

  const currentValue = fieldVisible ? await codeField.inputValue().catch(() => "") : "";
  const hasLikelyCode = currentValue.trim().length >= 6;

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

    await button.click({ timeout: 2_000 }).catch(() => undefined);
    await page.waitForTimeout(750);
    return;
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
    headless: args.includes("--headless") || process.env.TV_HEADLESS === "1",
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
    const emailField = page.locator(
      'input[name="id_username"], input[name="username"], input[type="email"], ' +
      'input[placeholder*="email" i], input[placeholder*="username" i]',
    ).first();
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

  let browser: import("playwright").Browser;
  let context: import("playwright").BrowserContext;
  let page: import("playwright").Page;

  if (cli.persistentProfileDir) {
    fs.mkdirSync(cli.persistentProfileDir, { recursive: true });
    context = await chromium.launchPersistentContext(cli.persistentProfileDir, {
      headless: false,
      slowMo: 100,
      viewport: { width: 1440, height: 1100 },
    });
    const launchedBrowser = context.browser();
    if (!launchedBrowser) {
      throw new Error(`Could not resolve browser for persistent TradingView profile: ${cli.persistentProfileDir}`);
    }
    browser = launchedBrowser;
    page = context.pages()[0] ?? (await context.newPage());
  } else {
    browser = await chromium.launch({
      headless: cli.headless,
      slowMo: cli.headless ? 0 : 100,
    });

    context = await browser.newContext({
      viewport: { width: 1440, height: 1100 },
    });

    page = await context.newPage();
  }

  console.log("");
  console.log("TradingView storage-state capture");
  console.log("--------------------------------");
  console.log(`Output file : ${cli.out}`);
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

  await page.goto(cli.persistentProfileDir ? cli.chartUrl : cli.loginUrl, { waitUntil: "domcontentloaded" });

  await attemptAutomatedLogin(page, cli);

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

  if (authDiagnostics.signInSignals || (!inspection.looksAuthenticated && !cli.persistentProfileDir)) {
    const cookiePreview = inspection.cookieNames.slice(0, 8).join(", ") || "none";
    const storagePreview = inspection.localStorageKeys.slice(0, 8).join(", ") || "none";
    throw new Error(
      `Captured TradingView session still looks anonymous. URL: ${authDiagnostics.url}. Title: ${authDiagnostics.title}. Body preview: ${JSON.stringify(authDiagnostics.bodyPreview)}. Cookies: ${cookiePreview}. Local storage keys: ${storagePreview}. Log in fully, dismiss any sign-in overlay, open the chart, then rerun npm run tv:storage-state.`,
    );
  }

  let storageStateToWrite: Record<string, unknown>;

  if (!inspection.looksAuthenticated && cli.persistentProfileDir) {
    console.warn(
      `Warning: storageState heuristics still look anonymous, but the persistent Chromium profile at ${cli.persistentProfileDir} was kept because the chart page is active without visible sign-in prompts. Use TV_PERSISTENT_PROFILE_DIR=${cli.persistentProfileDir} for preflight and release runs.`,
    );

    storageStateToWrite = {
      ...(storageState as Record<string, unknown>),
      meta: {
        authValidatedByChartAccess: true,
        authValidatedAt: new Date().toISOString(),
        validationMode: "persistent_profile_chart_access",
        chartUrl: authDiagnostics.url,
      },
    };
  } else {
    // Normal authenticated session: always write meta.authValidatedAt so that
    // credential_health_check.py (which requires meta.authValidatedAt) does not
    // report "storage_state missing meta block".
    storageStateToWrite = {
      ...(storageState as Record<string, unknown>),
      meta: {
        authValidatedAt: new Date().toISOString(),
        validationMode: "standard_session",
        chartUrl: authDiagnostics.url,
      },
    };
  }

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
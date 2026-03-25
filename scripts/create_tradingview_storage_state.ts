#!/usr/bin/env -S node --enable-source-maps

import fs from "node:fs";
import path from "node:path";

import { chromium } from "playwright";

import { inspectTradingViewStorageState } from "../automation/tradingview/lib/tv_validation_model.js";

type CliArgs = {
  out: string;
  loginUrl: string;
  chartUrl: string;
  waitTimeoutMs: number;
  pollIntervalMs: number;
  persistentProfileDir?: string;
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

async function assistTwoFactorSubmission(page: import("playwright").Page): Promise<void> {
  const bodyText = await page.locator("body").innerText().catch(() => "");
  if (!/two-factor authentication|verification code|backup code|code from your app/i.test(bodyText)) {
    return;
  }

  const codeField = page.locator(
    'input[autocomplete="one-time-code"], input[inputmode="numeric"], input[name*="code" i], input[placeholder*="code" i], input[type="tel"], input[type="text"]',
  ).first();

  const fieldVisible = (await codeField.count().catch(() => 0)) > 0 && (await codeField.isVisible().catch(() => false));
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
    await assistTwoFactorSubmission(page).catch(() => undefined);
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
      headless: false,
      slowMo: 100,
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
  console.log("A browser window will open.");
  console.log("1) Log in to TradingView manually.");
  console.log("2) If needed, solve MFA/CAPTCHA manually.");
  console.log("3) After login, open a TradingView chart page successfully.");
  console.log("4) Leave this process running while the script polls the current browser page.");
  console.log("");

  await page.goto(cli.persistentProfileDir ? cli.chartUrl : cli.loginUrl, { waitUntil: "domcontentloaded" });

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

  let storageStateToWrite: Record<string, unknown> = storageState as Record<string, unknown>;

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
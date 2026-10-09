import assert from "node:assert/strict";
import test from "node:test";

import type { LaunchOptions } from "playwright";

import {
  describeTradingViewLaunchTarget,
  isMissingBrowserExecutableError,
  launchWithTradingViewFallback,
  mergeTradingViewLaunchOverrides,
  resolveTradingViewLaunchOptions,
} from "../lib/tv_shared.js";

const MISSING_BROWSER_ERROR = new Error(
  "browserType.launch: Executable doesn't exist at /nonexistent/chromium\n"
    + "Please run the following command to download new browsers:\n"
    + "npx playwright install",
);

// Marker-1-only fixture: no "npx playwright install" remedy line — pins that the
// "Executable doesn't exist" marker ALONE classifies (the docker-image variant
// of Playwright's error has no install command in its message).
const MISSING_BROWSER_ERROR_NO_REMEDY = new Error(
  "browserType.launch: Executable doesn't exist at /ms-playwright/chromium-1208/chrome-linux/chrome",
);

// Playwright's missing-OS-DEPS error: bundled chromium IS installed; the remedy
// line "sudo npx playwright install-deps" contains the substring
// "npx playwright install" — this MUST NOT classify as missing-browser
// (regression pin for the over-broad second marker removed 2026-07-10).
const HOST_DEPS_ERROR = new Error(
  "browserType.launch: Host system is missing dependencies to run browsers.\n"
    + "Please install them with the following command:\n"
    + "\n"
    + "    sudo npx playwright install-deps\n",
);

// Missing-browser error whose FIRST-line phrase is reworded ("Executable doesn't
// exist" absent) but keeps the "download new browsers" remedy — pins that the
// second marker classifies independently, so a single upstream reword can't
// silently disable the chrome fallback.
const MISSING_BROWSER_ERROR_REWORDED = new Error(
  "browserType.launch: Chromium browser is not installed.\n"
    + "Please run the following command to download new browsers:\n"
    + "npx playwright install",
);

test("resolveTradingViewLaunchOptions: no env vars -> bundled chromium, no channel/executablePath", () => {
  const options = resolveTradingViewLaunchOptions({});
  assert.equal(options.executablePath, undefined);
  assert.equal(options.channel, undefined);
  // Concrete value, not just `typeof boolean`: pins that headless is actually wired
  // from resolveTradingViewHeadlessDefault (a hardcoded true/false would slip a
  // `typeof === "boolean"` check).
  assert.equal(options.headless, false);
});

test("resolveTradingViewLaunchOptions: headless is wired from resolveTradingViewHeadlessDefault", () => {
  assert.equal(resolveTradingViewLaunchOptions({ TV_HEADLESS: "1" }).headless, true);
  assert.equal(resolveTradingViewLaunchOptions({ TV_HEADLESS: "0" }).headless, false);
  assert.equal(resolveTradingViewLaunchOptions({ CI: "true" }).headless, true);
});

test("resolveTradingViewLaunchOptions: TV_CHROMIUM_EXECUTABLE_PATH is trimmed and applied", () => {
  const options = resolveTradingViewLaunchOptions({ TV_CHROMIUM_EXECUTABLE_PATH: "  /opt/chromium/chrome  " });
  assert.equal(options.executablePath, "/opt/chromium/chrome");
  assert.equal(options.channel, undefined);
});

test("resolveTradingViewLaunchOptions: TV_BROWSER_CHANNEL is trimmed and applied", () => {
  const options = resolveTradingViewLaunchOptions({ TV_BROWSER_CHANNEL: " chrome " });
  assert.equal(options.channel, "chrome");
  assert.equal(options.executablePath, undefined);
});

test("resolveTradingViewLaunchOptions: whitespace-only env values count as unset", () => {
  const options = resolveTradingViewLaunchOptions({ TV_CHROMIUM_EXECUTABLE_PATH: "   ", TV_BROWSER_CHANNEL: "  " });
  assert.equal(options.executablePath, undefined);
  assert.equal(options.channel, undefined);
});

test("resolveTradingViewLaunchOptions: both env vars set -> throws with remedy hint", () => {
  assert.throws(
    () => resolveTradingViewLaunchOptions({ TV_CHROMIUM_EXECUTABLE_PATH: "/x", TV_BROWSER_CHANNEL: "chrome" }),
    (error: unknown) => {
      assert.ok(error instanceof Error);
      assert.match(error.message, /mutually exclusive/);
      assert.match(error.message, /unset one of them/);
      return true;
    },
  );
});

test("describeTradingViewLaunchTarget names the selector value and both possible sources", () => {
  const exe = describeTradingViewLaunchTarget({ executablePath: "/x" });
  assert.match(exe, /executablePath "\/x"/);
  assert.match(exe, /TV_CHROMIUM_EXECUTABLE_PATH/);
  assert.match(exe, /caller override/); // honest: value may have come from an override, not the env var
  const channel = describeTradingViewLaunchTarget({ channel: "msedge" });
  assert.match(channel, /channel "msedge"/);
  assert.match(channel, /TV_BROWSER_CHANNEL/);
  assert.equal(describeTradingViewLaunchTarget({}), "Playwright bundled chromium");
});

test("mergeTradingViewLaunchOverrides: an override selector replaces the env selector (no both-set)", () => {
  // env channel + override executablePath -> executablePath wins, env channel dropped
  const a = mergeTradingViewLaunchOverrides({ headless: true, channel: "chrome" }, { executablePath: "/opt/chrome" });
  assert.equal(a.executablePath, "/opt/chrome");
  assert.equal(a.channel, undefined);
  // env executablePath + override channel -> channel wins, env executablePath dropped
  const b = mergeTradingViewLaunchOverrides({ headless: true, executablePath: "/env/exe" }, { channel: "msedge" });
  assert.equal(b.channel, "msedge");
  assert.equal(b.executablePath, undefined);
  // non-selector override leaves the env selector intact and applies the override
  const c = mergeTradingViewLaunchOverrides({ headless: false, channel: "chrome" }, { headless: true });
  assert.equal(c.channel, "chrome");
  assert.equal(c.headless, true);
});

test("isMissingBrowserExecutableError: playwright install errors yes, other errors no", () => {
  assert.equal(isMissingBrowserExecutableError(MISSING_BROWSER_ERROR), true);
  assert.equal(isMissingBrowserExecutableError(MISSING_BROWSER_ERROR_NO_REMEDY), true);
  // Second marker classifies even when the "Executable doesn't exist" phrase is gone.
  assert.equal(isMissingBrowserExecutableError(MISSING_BROWSER_ERROR_REWORDED), true);
  assert.equal(isMissingBrowserExecutableError(new Error("Timeout 30000ms exceeded.")), false);
  assert.equal(isMissingBrowserExecutableError(new Error("ProcessSingleton: profile is in use")), false);
});

test("isMissingBrowserExecutableError: missing-OS-deps (install-deps) is NOT a missing browser", () => {
  // The remedy line contains "npx playwright install" as a substring — the old
  // second marker misclassified this; the browser is installed, OS libs are not.
  assert.equal(isMissingBrowserExecutableError(HOST_DEPS_ERROR), false);
});

test("launchWithTradingViewFallback: missing-OS-deps error propagates untouched (no chrome retry)", async () => {
  let calls = 0;
  await assert.rejects(
    launchWithTradingViewFallback(
      async () => {
        calls += 1;
        throw HOST_DEPS_ERROR;
      },
      { headless: true },
      { fallbackToChromeChannel: true, log: () => undefined },
    ),
    (error: unknown) => error === HOST_DEPS_ERROR, // same instance — root cause never masked
  );
  assert.equal(calls, 1);
});

test("launchWithTradingViewFallback: BOTH executablePath and channel in final options -> throws before launching", async () => {
  let calls = 0;
  await assert.rejects(
    launchWithTradingViewFallback(
      async () => {
        calls += 1;
        return "browser";
      },
      { headless: true, executablePath: "/opt/custom/chrome", channel: "msedge" },
      { fallbackToChromeChannel: true, log: () => undefined },
    ),
    (error: unknown) => {
      assert.ok(error instanceof Error);
      assert.match(error.message, /BOTH executablePath and channel/);
      return true;
    },
  );
  assert.equal(calls, 0); // guard fires before any launch attempt
});

test("launchWithTradingViewFallback: success path launches once with the given options", async () => {
  const calls: LaunchOptions[] = [];
  const result = await launchWithTradingViewFallback(
    async (options) => {
      calls.push(options);
      return "browser";
    },
    { headless: true },
    { fallbackToChromeChannel: true, log: () => undefined },
  );
  assert.equal(result, "browser");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].channel, undefined);
});

test("launchWithTradingViewFallback: missing bundled chromium -> logged chrome-channel fallback", async () => {
  const calls: LaunchOptions[] = [];
  const logs: string[] = [];
  const result = await launchWithTradingViewFallback(
    async (options) => {
      calls.push(options);
      if (calls.length === 1) {
        throw MISSING_BROWSER_ERROR;
      }
      return "chrome-browser";
    },
    { headless: true },
    { fallbackToChromeChannel: true, log: (message) => logs.push(message) },
  );
  assert.equal(result, "chrome-browser");
  assert.equal(calls.length, 2);
  assert.equal(calls[1].channel, "chrome");
  assert.equal(logs.length, 1);
  assert.match(logs[0], /falling back to channel "chrome"/);
  assert.match(logs[0], /npx playwright install chromium/);
});

test("launchWithTradingViewFallback: non-install failures propagate untouched (no masking retry)", async () => {
  const original = new Error("Timeout 30000ms exceeded.");
  let calls = 0;
  await assert.rejects(
    launchWithTradingViewFallback(
      async () => {
        calls += 1;
        throw original;
      },
      { headless: true },
      { fallbackToChromeChannel: true, log: () => undefined },
    ),
    (error: unknown) => error === original,
  );
  assert.equal(calls, 1); // no second launch attempt for a non-missing-browser error
});

test("launchWithTradingViewFallback: fallback disabled (persistent profile) -> remedy error, cause chained", async () => {
  let calls = 0;
  await assert.rejects(
    launchWithTradingViewFallback(
      async () => {
        calls += 1;
        throw MISSING_BROWSER_ERROR;
      },
      { headless: false },
      { fallbackToChromeChannel: false, log: () => undefined },
    ),
    (error: unknown) => {
      assert.ok(error instanceof Error);
      assert.match(error.message, /persistent browser profile/);
      assert.match(error.message, /npx playwright install chromium/);
      assert.match(error.message, /TV_BROWSER_CHANNEL=chrome/);
      // Safe framing: chrome is only offered as delete-and-re-create, never a
      // drop-in for the existing chromium-minted profile (which it would corrupt).
      assert.match(error.message, /delete[\s\S]*re-create|never a drop-in/);
      assert.equal(error.cause, MISSING_BROWSER_ERROR);
      return true;
    },
  );
  // The whole point of the persistent path: it must NEVER retry a different browser
  // build against the auth profile — assert no second (chrome) launch happened.
  assert.equal(calls, 1);
});

test("launchWithTradingViewFallback: env-selected browser never falls back; error names the env var", async () => {
  const original = new Error('browserType.launch: Unsupported chromium channel "Chrome"');
  let calls = 0;
  await assert.rejects(
    launchWithTradingViewFallback(
      async () => {
        calls += 1;
        throw original;
      },
      { headless: true, channel: "Chrome" },
      { fallbackToChromeChannel: true, log: () => undefined },
    ),
    (error: unknown) => {
      assert.ok(error instanceof Error);
      assert.match(error.message, /channel "Chrome"/);
      assert.match(error.message, /TV_BROWSER_CHANNEL/);
      assert.equal(error.cause, original);
      return true;
    },
  );
  assert.equal(calls, 1);
});

test("launchWithTradingViewFallback: env-selected executablePath that is MISSING fails loud (no chrome fallback)", async () => {
  // The dangerous case: an env-selected browser whose error IS a missing-executable
  // (classified true by isMissingBrowserExecutableError). The env-attribution branch
  // must fire BEFORE the missing-browser check, so it fails loud instead of silently
  // launching system Chrome and ignoring the user's explicit executablePath.
  const original = new Error("browserType.launch: Executable doesn't exist at /bad/path");
  let calls = 0;
  await assert.rejects(
    launchWithTradingViewFallback(
      async () => {
        calls += 1;
        throw original;
      },
      { headless: true, executablePath: "/bad/path" },
      { fallbackToChromeChannel: true, log: () => undefined },
    ),
    (error: unknown) => {
      assert.ok(error instanceof Error);
      assert.match(error.message, /TV_CHROMIUM_EXECUTABLE_PATH/);
      assert.equal(error.cause, original);
      return true;
    },
  );
  assert.equal(calls, 1); // no chrome retry despite the missing-executable classification
});

test("launchWithTradingViewFallback: both attempts fail -> error carries both messages, cause = original", async () => {
  const fallbackError = new Error(
    "browserType.launch: Chromium distribution 'chrome' is not found\nsecond-line detail: sandbox denied",
  );
  const logs: string[] = [];
  let calls = 0;
  await assert.rejects(
    launchWithTradingViewFallback(
      async () => {
        calls += 1;
        throw calls === 1 ? MISSING_BROWSER_ERROR : fallbackError;
      },
      { headless: true },
      { fallbackToChromeChannel: true, log: (message) => logs.push(message) },
    ),
    (error: unknown) => {
      assert.ok(error instanceof Error);
      assert.match(error.message, /Executable doesn't exist/);
      assert.match(error.message, /Chromium distribution 'chrome' is not found/);
      assert.match(error.message, /npx playwright install chromium/);
      // Truncation is the point: the thrown message keeps only first lines, so the
      // fallback's second line must NOT leak into it (it survives via the log channel).
      assert.doesNotMatch(error.message, /second-line detail: sandbox denied/);
      assert.equal(error.cause, MISSING_BROWSER_ERROR);
      return true;
    },
  );
  assert.equal(calls, 2);
  // The fallback failure's FULL detail (incl. lines >1) is preserved via the log
  // channel — the thrown message keeps only first lines, cause stays the original.
  assert.equal(logs.length, 2);
  assert.match(logs[1], /chrome-channel fallback also failed/);
  assert.match(logs[1], /second-line detail: sandbox denied/);
});

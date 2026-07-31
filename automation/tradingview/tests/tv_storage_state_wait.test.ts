import assert from "node:assert/strict";
import test from "node:test";

import { resolveTradingViewStorageCaptureWaitAction } from "../lib/tv_shared.js";

test("authenticated fresh login outside the chart transitions to the chart", () => {
  assert.equal(
    resolveTradingViewStorageCaptureWaitAction({
      url: "https://www.tradingview.com/accounts/signin/",
      signInSignals: false,
      authenticated: true,
      storageLooksAuthenticated: true,
      persistentProfile: false,
    }),
    "navigate_to_chart",
  );
});

test("authenticated chart session completes capture", () => {
  assert.equal(
    resolveTradingViewStorageCaptureWaitAction({
      url: "https://www.tradingview.com/chart/",
      signInSignals: false,
      authenticated: true,
      storageLooksAuthenticated: true,
      persistentProfile: false,
    }),
    "complete",
  );
});

test("pending authentication challenge must not navigate away", () => {
  assert.equal(
    resolveTradingViewStorageCaptureWaitAction({
      url: "https://www.tradingview.com/accounts/signin/",
      signInSignals: true,
      authenticated: true,
      storageLooksAuthenticated: true,
      persistentProfile: false,
    }),
    "wait",
  );
});

test("account probe without authenticated storage remains waiting", () => {
  assert.equal(
    resolveTradingViewStorageCaptureWaitAction({
      url: "https://www.tradingview.com/accounts/signin/",
      signInSignals: false,
      authenticated: true,
      storageLooksAuthenticated: false,
      persistentProfile: false,
    }),
    "wait",
  );
});

test("persistent profile can transition without portable storage evidence", () => {
  assert.equal(
    resolveTradingViewStorageCaptureWaitAction({
      url: "https://www.tradingview.com/",
      signInSignals: false,
      authenticated: true,
      storageLooksAuthenticated: false,
      persistentProfile: true,
    }),
    "navigate_to_chart",
  );
});

// 2026-07-31: an anonymous persistent profile used to sit on the chart URL for
// the whole 900s timeout. The capture prints "Log in to TradingView manually",
// so an explicitly anonymous session must be taken to the login page instead of
// polling a chart that offers no login form.
test("explicitly anonymous chart session navigates to the login page", () => {
  assert.equal(
    resolveTradingViewStorageCaptureWaitAction({
      url: "https://www.tradingview.com/chart/",
      // The capture script ORs signInSignals with "anonymous", so an anonymous
      // chart page arrives here as true even with no login form on screen.
      signInSignals: true,
      loginFormVisible: false,
      authenticated: false,
      explicitlyAnonymous: true,
      storageLooksAuthenticated: false,
      persistentProfile: true,
    }),
    "navigate_to_login",
  );
});

test("anonymous session already on the login surface does not re-navigate", () => {
  assert.equal(
    resolveTradingViewStorageCaptureWaitAction({
      url: "https://www.tradingview.com/accounts/signin/",
      signInSignals: true,
      loginFormVisible: true,
      authenticated: false,
      explicitlyAnonymous: true,
      storageLooksAuthenticated: false,
      persistentProfile: true,
    }),
    "wait",
  );
});

test("anonymous session showing a sign-in form anywhere keeps waiting", () => {
  assert.equal(
    resolveTradingViewStorageCaptureWaitAction({
      url: "https://www.tradingview.com/chart/",
      signInSignals: true,
      loginFormVisible: true,
      authenticated: false,
      explicitlyAnonymous: true,
      storageLooksAuthenticated: false,
      persistentProfile: true,
    }),
    "wait",
  );
});

test("indeterminate (not explicitly anonymous) session keeps waiting", () => {
  assert.equal(
    resolveTradingViewStorageCaptureWaitAction({
      url: "https://www.tradingview.com/chart/",
      signInSignals: false,
      loginFormVisible: false,
      authenticated: false,
      explicitlyAnonymous: false,
      storageLooksAuthenticated: false,
      persistentProfile: true,
    }),
    "wait",
  );
});

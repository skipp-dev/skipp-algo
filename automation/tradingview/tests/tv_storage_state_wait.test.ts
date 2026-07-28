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

import assert from "node:assert/strict";
import test from "node:test";

import { resolveTradingViewPageAuthState } from "../lib/tv_shared.js";

// A confirmed live 2xx account probe is the strongest, most-current
// authentication signal. It must short-circuit every anonymity heuristic —
// including a possibly-stale `is-not-authenticated` HTML class — otherwise a
// logged-in session is misclassified as anonymous and triggers spurious
// re-login/recovery loops.

const base = {
  url: "https://www.tradingview.com/chart/",
  bodyText: "AAPL chart",
  accountProbeStatuses: [] as number[],
  accountProbeAuthenticated: false,
  accountProbeAnonymous: false,
};

test("live 2xx probe outranks a stale is-not-authenticated HTML class", () => {
  const state = resolveTradingViewPageAuthState({
    ...base,
    htmlClass: "is-not-authenticated theme-light",
    accountProbeStatuses: [200],
    accountProbeAuthenticated: true,
  });
  assert.equal(state.authenticated, true);
  assert.equal(state.explicitlyAnonymous, false);
  assert.equal(state.reason, "account_probe_authenticated");
});

test("live 2xx probe outranks fuzzy sign-in body text", () => {
  const state = resolveTradingViewPageAuthState({
    ...base,
    htmlClass: "theme-light",
    bodyText: "Email notifications · sign in settings",
    accountProbeStatuses: [200],
    accountProbeAuthenticated: true,
  });
  assert.equal(state.authenticated, true);
  assert.equal(state.explicitlyAnonymous, false);
});

test("stale is-not-authenticated class WITHOUT a live probe stays anonymous", () => {
  const state = resolveTradingViewPageAuthState({
    ...base,
    htmlClass: "is-not-authenticated",
  });
  assert.equal(state.authenticated, false);
  assert.equal(state.explicitlyAnonymous, true);
  assert.equal(state.reason, "html_class_is_not_authenticated");
});

test("live 401/403 probe still outranks a stale is-authenticated class (unchanged)", () => {
  const state = resolveTradingViewPageAuthState({
    ...base,
    htmlClass: "is-authenticated",
    accountProbeStatuses: [401],
    accountProbeAnonymous: true,
  });
  assert.equal(state.authenticated, false);
  assert.equal(state.explicitlyAnonymous, true);
  assert.equal(state.reason, "account_probe_rejected:401");
});

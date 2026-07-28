import assert from "node:assert/strict";
import test from "node:test";

import {
  isOtpEntryComplete,
  planOtpEntry,
  shouldAttemptTotp,
  totpTimeStep,
} from "../lib/tv_shared.js";

// 2026-07-28: the headless fallback reached TradingView's 2FA step for the first
// time (run 30341257192, after #4140 unblocked the login form) and then looped —
// "TOTP code generated — filling 2FA field automatically." 32 times in 180 s,
// no submit, no error. `fill(token)` wrote all six digits into the FIRST
// matching input; a per-digit layout caps each box at one character, so the
// read-back never reached six and the caller's `hasLikelyCode` guard skipped
// every submit candidate. Filling forever, submitting never.
//
// These pins are browserless so they run in tv-onboarding-packages.yml, which
// installs no Playwright browser — see tv_signin_email_chooser.test.ts.

test("per-digit boxes are entered box by box", () => {
  const boxes = Array.from({ length: 6 }, () => ({ maxLength: 1 }));

  const plan = planOtpEntry(boxes, 6);

  assert.equal(plan.perBox, true);
  assert.equal(plan.usable, true);
});

test("a single unconstrained field takes the whole code", () => {
  const plan = planOtpEntry([{ maxLength: -1 }], 6);

  assert.equal(plan.perBox, false);
  assert.equal(plan.usable, true);
});

test("a single field with room for the code is usable", () => {
  const plan = planOtpEntry([{ maxLength: 6 }], 6);

  assert.equal(plan.perBox, false);
  assert.equal(plan.usable, true);
});

test("too few per-digit boxes is reported instead of half-filled", () => {
  const boxes = Array.from({ length: 4 }, () => ({ maxLength: 1 }));

  const plan = planOtpEntry(boxes, 6);

  assert.equal(plan.usable, false);
  assert.match(plan.reason, /per_box_inputs_short:4\/6/);
});

test("a single field too small for the code is reported, not truncated", () => {
  const plan = planOtpEntry([{ maxLength: 4 }], 6);

  assert.equal(plan.usable, false);
  assert.match(plan.reason, /single_field_too_small:4\/6/);
});

test("no field at all is unusable", () => {
  const plan = planOtpEntry([], 6);

  assert.equal(plan.usable, false);
  assert.equal(plan.reason, "no_code_field");
});

test("completeness compares the whole code, not just its length", () => {
  assert.equal(isOtpEntryComplete("123456", "123456"), true);
  assert.equal(isOtpEntryComplete("1 2 3 4 5 6", "123456"), true, "boxes join with stray whitespace");
  assert.equal(isOtpEntryComplete("1", "123456"), false, "the exact regression: one digit landed");
  assert.equal(isOtpEntryComplete("123457", "123456"), false, "same length, wrong code");
  assert.equal(isOtpEntryComplete("", "123456"), false);
});

test("the same TOTP time-step is attempted only once", () => {
  const nowMs = Date.UTC(2026, 6, 28, 16, 0, 5);
  const first = shouldAttemptTotp(undefined, nowMs);

  assert.equal(first.attempt, true);
  assert.equal(shouldAttemptTotp(first.step, nowMs + 20_000).attempt, false);
  assert.equal(shouldAttemptTotp(first.step, nowMs + 30_000).attempt, true);
});

test("TOTP time-step rejects invalid periods", () => {
  assert.throws(() => totpTimeStep(Date.now(), 0), /periodSeconds must be positive/);
});

import assert from "node:assert/strict";
import test from "node:test";

import { generateTotpToken } from "../lib/tv_shared.js";

// 2026-08-05: `tradingview-storage-refresh` failed at 04:04Z with
//   SyntaxError: The requested module 'otplib' does not provide an export
//   named 'authenticator'
// The cron's failure issue (#4459) lists six likely causes -- expired session,
// CAPTCHA, rotated TOTP secret, missing secrets -- and asks for a manual cookie
// capture. None of them applied. #4445 (an npm-all Dependabot group update)
// moved otplib from ^12.0.1 to ^13.4.1, a major bump that removed the
// `authenticator` export, and the very next scheduled run died on the import
// before a browser started. Every run before it was green.
//
// Nothing executed that import outside the cron, so the bump merged green and
// the breakage surfaced eight hours later as a request to rotate a credential
// that was never the problem. These pins are that missing execution.
//
// Browserless on purpose, so they run in tv-onboarding-packages.yml, which
// installs no Playwright browser -- see tv_otp_entry_plan.test.ts.

// RFC 6238 Appendix B, SHA-1 rows. The secret is the ASCII string
// "12345678901234567890" in Base32. Verified independently against a
// hand-rolled HMAC-SHA1 implementation before being pinned here, so a wrong
// library and a wrong expectation cannot agree with each other.
const RFC6238_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ";
const RFC6238_SHA1: ReadonlyArray<readonly [number, string]> = [
  [59, "94287082"],
  [1_111_111_109, "07081804"],
  [1_234_567_890, "89005924"],
  [2_000_000_000, "69279037"],
  [20_000_000_000, "65353130"],
];

test("the generated token matches the RFC 6238 vectors", () => {
  for (const [epochSeconds, expected] of RFC6238_SHA1) {
    assert.equal(
      generateTotpToken(RFC6238_SECRET, { epochSeconds, digits: 8 }),
      expected,
      `RFC 6238 vector at t=${epochSeconds}`,
    );
  }
});

test("epoch is seconds, not milliseconds", () => {
  // The trap in the otplib 12 -> 13 migration: v12's `epoch` was milliseconds
  // and v13's is seconds. Reading it the old way produces a confident,
  // well-formed, wrong six digits -- which against a live 2FA prompt is
  // indistinguishable from a bad secret, and burns login attempts to find out.
  const seconds = generateTotpToken(RFC6238_SECRET, { epochSeconds: 59, digits: 8 });
  const milliseconds = generateTotpToken(RFC6238_SECRET, { epochSeconds: 59_000, digits: 8 });
  assert.equal(seconds, "94287082");
  assert.notEqual(milliseconds, seconds);
});

test("TradingView's 2FA field gets six digits by default", () => {
  // planOtpEntry() distributes the token across per-digit boxes by length, so a
  // width change here silently mis-fills the form rather than failing loudly.
  const token = generateTotpToken(RFC6238_SECRET, { epochSeconds: 59 });
  assert.equal(token.length, 6);
  assert.match(token, /^[0-9]{6}$/);
  assert.equal(token, "287082", "the six-digit code is the RFC vector's tail");
});

test("the code changes across a 30-second step and holds within one", () => {
  // The retry de-duplication in shouldAttemptTotp() keys on the time-step, and
  // is only meaningful if the code is in fact constant inside a step.
  const early = generateTotpToken(RFC6238_SECRET, { epochSeconds: 1_234_567_890 });
  const sameStep = generateTotpToken(RFC6238_SECRET, { epochSeconds: 1_234_567_909 });
  const nextStep = generateTotpToken(RFC6238_SECRET, { epochSeconds: 1_234_567_920 });
  assert.equal(early, sameStep);
  assert.notEqual(early, nextStep);
});

test("a secret that is not Base32 fails loudly", () => {
  // Silent failure here would reach the login form as an empty or garbage code
  // and be reported as a rejected credential.
  assert.throws(() => generateTotpToken("not base32 !!!", { epochSeconds: 59 }));
});

test("omitting the epoch reads the current clock", () => {
  // The production call passes no epoch at all. If the default were anything
  // other than "now", every real login would submit a stale code while the
  // vector pins above stayed green.
  const now = Math.floor(Date.now() / 1000);
  assert.equal(
    generateTotpToken(RFC6238_SECRET),
    generateTotpToken(RFC6238_SECRET, { epochSeconds: now }),
  );
});

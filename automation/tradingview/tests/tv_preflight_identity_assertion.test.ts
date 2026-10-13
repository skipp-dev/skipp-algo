import test from "node:test";
import assert from "node:assert/strict";

import {
  isExactScriptNameMatch,
  uiTextContainsExactScriptName,
} from "../lib/tv_shared.js";

/**
 * Pin: 2026-04-22 substring-collision regression for the preflight identity guard.
 *
 * The third-party public TradingView script
 *   "SMC Execution Engine (Free) by @abdallacrypto v1.3"
 * substring-matched the preflight target name "SMC Execution" via the loose
 * scriptNameAppearsInUiText path inside verifyOpenedSettingsDialogIdentity.
 *
 * The strict guard isExactScriptNameMatch() that backs the
 * assertOpenedScriptIdentityOrThrow() defensive assertion in tv_preflight.ts
 * MUST refuse this collision (substring) and accept canonical exact matches
 * (with optional version suffix) and saved-name aliases.
 */

const THIRD_PARTY_TITLE = "SMC Execution Engine (Free) by @abdallacrypto v1.3";

test("isExactScriptNameMatch refuses third-party substring (the 2026-04-22 collision)", () => {
  // Pre-rename canonical name (still present in the legacy alias chain) must NOT
  // be treated as matching the third-party title.
  assert.equal(isExactScriptNameMatch(THIRD_PARTY_TITLE, "SMC Execution"), false);
  // Post-rename canonical name must obviously also reject it.
  assert.equal(isExactScriptNameMatch(THIRD_PARTY_TITLE, "SMC Long-Dip Strategy v7"), false);
  // Multiple candidates evaluated together must still reject.
  assert.equal(
    isExactScriptNameMatch(
      THIRD_PARTY_TITLE,
      "SMC Long-Dip Strategy v7",
      "SMC Long Strategy",
      "SMC Execution",
    ),
    false,
  );
});

test("isExactScriptNameMatch accepts the canonical post-rename title verbatim", () => {
  assert.equal(isExactScriptNameMatch("SMC Long-Dip Strategy v7", "SMC Long-Dip Strategy v7"), true);
  assert.equal(isExactScriptNameMatch("SMC Long-Dip Dashboard v7", "SMC Long-Dip Dashboard v7"), true);
});

test("isExactScriptNameMatch tolerates trailing version suffix", () => {
  // Matches scriptNamePatterns / canonicalSemanticVersionSuffixMatch tolerance:
  //   "v\d+(?:\.\d+){1,3}"  →  "v1.2", "v1.2.3"
  //   "version\s+\d+(?:\.\d+){1,3}"  →  "version 3.1"
  assert.equal(isExactScriptNameMatch("SMC Long-Dip Strategy v7 v1.2", "SMC Long-Dip Strategy v7"), true);
  assert.equal(isExactScriptNameMatch("SMC Long-Dip Strategy v7 version 3.1", "SMC Long-Dip Strategy v7"), true);
});

test("isExactScriptNameMatch is case-insensitive and whitespace-tolerant", () => {
  assert.equal(isExactScriptNameMatch("smc long-dip strategy v7", "SMC Long-Dip Strategy v7"), true);
  assert.equal(isExactScriptNameMatch("  SMC   Long-Dip   Strategy   v7  ", "SMC Long-Dip Strategy v7"), true);
});

test("isExactScriptNameMatch accepts saved-name alias when canonical does not match", () => {
  // Mid-rename TV state: chart still shows the legacy saved title.
  // Passing both names is the contract used by assertOpenedScriptIdentityOrThrow.
  assert.equal(
    isExactScriptNameMatch("SMC Long Strategy", "SMC Long-Dip Strategy v7", "SMC Long Strategy"),
    true,
  );
});

test("isExactScriptNameMatch returns false on empty actual title or empty candidates", () => {
  assert.equal(isExactScriptNameMatch("", "SMC Long-Dip Strategy v7"), false);
  assert.equal(isExactScriptNameMatch("   ", "SMC Long-Dip Strategy v7"), false);
  assert.equal(isExactScriptNameMatch("SMC Long-Dip Strategy v7", ""), false);
  assert.equal(isExactScriptNameMatch("SMC Long-Dip Strategy v7"), false);
});

test("isExactScriptNameMatch refuses additional substring-collision titles", () => {
  // Synthetic adversarial titles to lock down the strict semantics.
  const adversarial = [
    "SMC Long-Dip Strategy v7 Premium",       // trailing non-version suffix
    "Best SMC Long-Dip Strategy v7",          // leading word
    "SMC Long-Dip Strategy v7 (Free) by @x",  // trailing branding
  ];
  for (const title of adversarial) {
    assert.equal(
      isExactScriptNameMatch(title, "SMC Long-Dip Strategy v7"),
      false,
      `must refuse adversarial title "${title}"`,
    );
  }
});

test("uiTextContainsExactScriptName remains the strict primitive isExactScriptNameMatch builds on", () => {
  // Sanity guard: if the underlying primitive ever loosens, the strict guard breaks.
  assert.equal(uiTextContainsExactScriptName("SMC Long-Dip Strategy v7", "SMC Long-Dip Strategy v7"), true);
  assert.equal(uiTextContainsExactScriptName("SMC Execution", THIRD_PARTY_TITLE), false);
});

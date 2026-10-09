import test from "node:test";
import assert from "node:assert/strict";

import { tvSelectors } from "../selectors.js";

/**
 * Pin: 2026-04-22 substring-collision regression.
 *
 * The third-party public TradingView script
 *   "SMC Execution Engine (Free) by @abdallacrypto v1.3"
 * substring-matched the preflight target name "SMC Execution" via the loose
 * fallback in scriptRow(), causing the wrong script's input bindings to be
 * read. scriptRow({ strict: true }) MUST suppress every loose / fuzzy /
 * global-page-scope locator and only return USER-scoped exact-match locators.
 *
 * The fake DOM is structural: we record every locator/filter call so we can
 * assert the absence of loose patterns in strict mode and the presence of the
 * full chain in default mode.
 */

type Recording = {
  locatorCalls: string[];
  filterCalls: string[];
  textCalls: string[];
};

function makeFakePage(recording: Recording) {
  const recordFilter = (options: { hasText: RegExp }) => {
    recording.filterCalls.push(options.hasText.source);
    return { kind: "filter" };
  };
  const recordText = (pattern: RegExp) => {
    recording.textCalls.push(pattern.source);
    return { kind: "text" };
  };

  const filteredScope = {
    filter: recordFilter,
    getByText: recordText,
    locator: (_selector: string) => filteredScope,
  };

  const scope = {
    locator: (selector: string) => {
      recording.locatorCalls.push(selector);
      return filteredScope;
    },
    getByText: recordText,
    filter: recordFilter,
  };

  return {
    locator: (selector: string) => {
      recording.locatorCalls.push(selector);
      return scope;
    },
    getByText: recordText,
  };
}

test("scriptRow strict mode emits ONLY USER-scoped exact-match locators", () => {
  const recording: Recording = { locatorCalls: [], filterCalls: [], textCalls: [] };
  const fakePage = makeFakePage(recording);

  const locators = tvSelectors.scriptRow(fakePage as never, "SMC Long-Dip Strategy v7", { strict: true });

  // Exactly three strict locators: indicators-dialog, menu-inner, role=dialog.
  assert.equal(locators.length, 3);

  // Every filter must use the exact-match pattern (anchored ^...$ with optional version suffix).
  // This is what prevents the substring collision with third-party "SMC Execution Engine (Free)…".
  assert.equal(recording.filterCalls.length, 3);
  for (const pattern of recording.filterCalls) {
    assert.equal(
      pattern.startsWith("^SMC Long-Dip Strategy v7"),
      true,
      `strict-mode filter must be anchored exact-match, got: ${pattern}`,
    );
    assert.equal(pattern.endsWith("$"), true, `strict-mode filter must end with $, got: ${pattern}`);
  }

  // No loose-match patterns may be emitted in strict mode.
  for (const pattern of recording.filterCalls) {
    assert.equal(
      pattern.includes("SMC Long-Dip Strategy v7") && !pattern.startsWith("^"),
      false,
      `strict-mode must not emit loose (unanchored) patterns, got: ${pattern}`,
    );
  }
  assert.equal(recording.textCalls.length, 0, "strict-mode must not emit getByText fallbacks");

  // Every locator selector must scope to USER-saved private scripts.
  const userScopedSelectors = recording.locatorCalls.filter((sel) => sel.includes('[data-id^="USER;"]'));
  assert.equal(userScopedSelectors.length, 3, "strict-mode must only locate inside [data-id^=\"USER;\"]");
});

test("scriptRow default mode preserves the loose+fuzzy fallback chain", () => {
  const recording: Recording = { locatorCalls: [], filterCalls: [], textCalls: [] };
  const fakePage = makeFakePage(recording);

  const locators = tvSelectors.scriptRow(fakePage as never, "SMC Long-Dip Strategy v7");

  // Loose chain is much larger than 3 (back-compat with non-preflight callers).
  assert.equal(locators.length > 3, true, `default-mode must emit > 3 locators, got ${locators.length}`);
  assert.equal(
    recording.textCalls.length > 0,
    true,
    "default-mode must still emit getByText fallbacks",
  );

  // At least one filter must be a non-anchored loose pattern (used as fallback).
  const looseFilters = recording.filterCalls.filter((sel) => !sel.startsWith("^") && sel.includes("SMC Long-Dip Strategy v7"));
  assert.equal(looseFilters.length > 0, true, "default-mode must include loose filters");
});

test("scriptRow strict mode refuses third-party script substring match", () => {
  // The exact regex emitted by strict mode is anchored to ^...$ — so it cannot
  // match a third-party title that merely contains the script name as a substring.
  const recording: Recording = { locatorCalls: [], filterCalls: [], textCalls: [] };
  const fakePage = makeFakePage(recording);

  tvSelectors.scriptRow(fakePage as never, "SMC Execution", { strict: true });

  const thirdPartyTitle = "SMC Execution Engine (Free) by @abdallacrypto v1.3";
  for (const patternSource of recording.filterCalls) {
    const pattern = new RegExp(patternSource, "i");
    assert.equal(
      pattern.test(thirdPartyTitle),
      false,
      `strict-mode regex must not match third-party title "${thirdPartyTitle}" (regex: ${patternSource})`,
    );
  }
});

import assert from "node:assert/strict";
import test from "node:test";

import { describeScriptRowLocatorSpecs, tvSelectors } from "../selectors.js";

test("scriptRow locator specs are exact-first and dialog-scoped", () => {
  assert.deepEqual(describeScriptRowLocatorSpecs(), [
    { scope: "dialog", matchKind: "exact" },
    { scope: "menu_inner", matchKind: "exact" },
    { scope: "dialog", matchKind: "loose" },
    { scope: "menu_inner", matchKind: "loose" },
  ]);
});

test("scriptRow locator specs never fall back to global page scope", () => {
  assert.equal(describeScriptRowLocatorSpecs().some((spec) => spec.scope === "dialog" || spec.scope === "menu_inner"), true);
  assert.equal(describeScriptRowLocatorSpecs().some((spec) => !(spec.scope === "dialog" || spec.scope === "menu_inner")), false);
});

test("settingsForScript does not use raw CSS attribute interpolation for arbitrary script names", () => {
  const calls: string[] = [];
  const fakePage = {
    getByRole: (_role: string, options: { name: RegExp }) => {
      calls.push(`role:${options.name.source}`);
      return { kind: "role" };
    },
    getByTitle: (pattern: RegExp) => {
      calls.push(`title:${pattern.source}`);
      return { kind: "title" };
    },
    locator: (selector: string) => {
      calls.push(`locator:${selector}`);
      return { kind: "locator" };
    },
  };

  const locators = tvSelectors.settingsForScript(fakePage as never, 'SMC Core ["Engine"]');

  assert.equal(locators.length, 3);
  assert.equal(calls.some((call) => call.startsWith("locator:")), false);
});

test("publishedVersionContext requires immediate version evidence for the exact script name", () => {
  const calls: string[] = [];
  const fakeLocator = {
    filter: (options: { hasText: RegExp }) => {
      calls.push(`filter:${options.hasText.source}`);
      return { kind: "filter" };
    },
  };
  const fakePage = {
    locator: (_selector: string) => fakeLocator,
  };

  const locators = tvSelectors.publishedVersionContext(fakePage as never, "SMC Core");

  assert.equal(locators.length, 4);
  assert.equal(calls.every((call) => call.includes("SMC Core") && call.includes("version")), true);
});

test("openScript excludes the chart indicators entry point", () => {
  const calls: string[] = [];
  const fakePage = {
    getByRole: (_role: string, options: { name: RegExp }) => {
      calls.push(`role:${options.name.source}`);
      return { kind: "role" };
    },
    getByText: (pattern: RegExp) => {
      calls.push(`text:${pattern.source}`);
      return { kind: "text" };
    },
  };

  const locators = tvSelectors.openScript(fakePage as never);

  assert.equal(locators.length, 3);
  assert.equal(calls.some((call) => /indicators/i.test(call)), false);
});

test("openScriptIdentity probes exact and fuzzy title contexts", () => {
  const calls: string[] = [];
  const fakeScopedLocator = {
    filter: (options: { hasText: RegExp }) => {
      calls.push(`filter:${options.hasText.source}`);
      return { kind: "filter" };
    },
  };
  const fakePage = {
    getByRole: (_role: string, options: { name: RegExp }) => {
      calls.push(`role:${options.name.source}`);
      return { kind: "role" };
    },
    getByTitle: (pattern: RegExp) => {
      calls.push(`title:${pattern.source}`);
      return { kind: "title" };
    },
    locator: (selector: string) => {
      calls.push(`locator:${selector}`);
      return fakeScopedLocator;
    },
  };

  const locators = tvSelectors.openScriptIdentity(fakePage as never, "SMC Long-Dip Dashboard v7");

  assert.equal(locators.length, 12);
  assert.equal(calls.some((call) => call.includes("pine-dialog")), false);
  assert.equal(calls.some((call) => call.includes('[data-name*="editor" i]')), false);
  assert.equal(calls.some((call) => call.startsWith("title:") && call.includes("Dashboard")), true);
  assert.equal(calls.some((call) => call.startsWith("filter:") && call.includes("Dashboard")), true);
});

test("scriptLegendContainers only anchor exact script text descendants", () => {
  const calls: string[] = [];
  const fakePage = {
    getByText: (pattern: RegExp) => {
      calls.push(pattern.source);
      return {
        locator: (_selector: string) => ({ kind: "ancestor" }),
      };
    },
  };

  const locators = tvSelectors.scriptLegendContainers(fakePage as never, "SMC Core");

  assert.equal(locators.length, 4);
  assert.deepEqual(calls, [
    "^SMC Core(?:\\s+(?:v\\d+(?:\\.\\d+){1,3}|version\\s+\\d+(?:\\.\\d+){1,3}))?$",
    "^SMC Core(?:\\s+(?:v\\d+(?:\\.\\d+){1,3}|version\\s+\\d+(?:\\.\\d+){1,3}))?$",
    "^SMC Core(?:\\s+(?:v\\d+(?:\\.\\d+){1,3}|version\\s+\\d+(?:\\.\\d+){1,3}))?$",
    "^SMC Core(?:\\s+(?:v\\d+(?:\\.\\d+){1,3}|version\\s+\\d+(?:\\.\\d+){1,3}))?$",
  ]);
});

test("scriptRow exact locator tolerates semantic version suffixes", () => {
  const calls: string[] = [];
  const filteredScope = {
    filter: (options: { hasText: RegExp }) => {
      calls.push(options.hasText.source);
      return { kind: "filter" };
    },
  };
  const fakeScope = {
    getByText: (pattern: RegExp) => {
      calls.push(pattern.source);
      return { kind: "text" };
    },
    locator: (_selector: string) => filteredScope,
  };
  const fakePage = {
    locator: (_selector: string) => fakeScope,
  };

  tvSelectors.scriptRow(fakePage as never, "SkippALGO");

  assert.equal(calls.some((call) => call.includes("SkippALGO") && call.includes("version") && call.includes("v\\d+")), true);
});

test("openScriptRow is exact and dialog scoped without requiring USER data ids", () => {
  const locatorCalls: string[] = [];
  const filterCalls: string[] = [];
  const textCalls: string[] = [];

  const filteredScope = {
    filter: (options: { hasText: RegExp }) => {
      filterCalls.push(options.hasText.source);
      return { kind: "filter" };
    },
  };
  const scope = {
    locator: (selector: string) => {
      locatorCalls.push(selector);
      return filteredScope;
    },
    getByText: (pattern: RegExp) => {
      textCalls.push(pattern.source);
      return { kind: "text" };
    },
  };
  const fakePage = {
    locator: (selector: string) => {
      locatorCalls.push(selector);
      return scope;
    },
  };

  const locators = tvSelectors.openScriptRow(fakePage as never, "SMC Long-Dip Strategy v7");

  assert.equal(locators.length, 9);
  assert.equal(filterCalls.length, 6);
  assert.equal(textCalls.length, 3);
  assert.equal(locatorCalls.some((selector) => selector.includes('[data-id^="USER;"]')), true);
  assert.equal(locatorCalls.some((selector) => selector.includes('[role="option"]')), true);
  for (const pattern of [...filterCalls, ...textCalls]) {
    assert.equal(pattern.startsWith("^SMC Long-Dip Strategy v7"), true);
    assert.equal(pattern.endsWith("$"), true);
  }
});

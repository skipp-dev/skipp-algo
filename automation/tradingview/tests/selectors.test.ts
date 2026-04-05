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

  const locators = tvSelectors.publishedVersionContext(fakePage as never, "SMC Core Engine");

  assert.equal(locators.length, 4);
  assert.equal(calls.every((call) => call.includes("SMC Core Engine") && call.includes("version")), true);
});

test("openScriptIdentity probes exact and fuzzy title contexts", () => {
  const calls: string[] = [];
  const fakeScopedLocator = {
    getByText: (pattern: RegExp) => {
      calls.push(`text:${pattern.source}`);
      return { kind: "text" };
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

  const locators = tvSelectors.openScriptIdentity(fakePage as never, "SMC Dashboard");

  assert.equal(locators.length, 16);
  assert.equal(calls.some((call) => call.includes("pine-dialog")), true);
  assert.equal(calls.some((call) => call.startsWith("title:") && call.includes("Dash")), true);
  assert.equal(calls.some((call) => call.startsWith("text:") && call.includes("Dash")), true);
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

  const locators = tvSelectors.scriptLegendContainers(fakePage as never, "SMC Core Engine");

  assert.equal(locators.length, 4);
  assert.deepEqual(calls, ["^SMC Core Engine$", "^SMC Core Engine$", "^SMC Core Engine$", "^SMC Core Engine$"]);
});
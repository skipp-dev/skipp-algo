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
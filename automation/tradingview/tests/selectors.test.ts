import assert from "node:assert/strict";
import test from "node:test";

import { describeScriptRowLocatorSpecs } from "../selectors.js";

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
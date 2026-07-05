import assert from "node:assert/strict";
import test from "node:test";

import { PUBLISH_CONTINUE_LABEL } from "../selectors.js";

// The publish-flow "Continue" label may carry a stepper/decoration glyph
// ("Continue →" / "Continue ›"), but tolerated decoration must be an actual
// glyph or whitespace — never sentence punctuation. "Continue?" is a
// confirmation *question* (a distinct, possibly destructive dialog); the old
// `[^a-z0-9]*` matched its "?" and could mis-click it.

test("matches bare and glyph-decorated Continue labels", () => {
  const accepted = [
    "Continue",
    "continue",
    "CONTINUE",
    "Continue →",
    "Continue ›",
    "Continue »",
    "Continue ⟶",
    "Continue…",
    "  Continue  ",
    "⚙️ Continue",
  ];
  for (const label of accepted) {
    assert.equal(
      PUBLISH_CONTINUE_LABEL.test(label),
      true,
      `should match ${JSON.stringify(label)}`,
    );
  }
});

test("rejects sentence punctuation, questions, and other words", () => {
  const rejected = [
    "Continue?",
    "Continue!",
    "Continue.",
    "Continue:",
    "Continue editing",
    "Continue to checkout",
    "Discontinue",
    "Are you sure? Continue?",
    "",
  ];
  for (const label of rejected) {
    assert.equal(
      PUBLISH_CONTINUE_LABEL.test(label),
      false,
      `should reject ${JSON.stringify(label)}`,
    );
  }
});

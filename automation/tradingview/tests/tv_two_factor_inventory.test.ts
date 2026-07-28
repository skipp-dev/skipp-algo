import assert from "node:assert/strict";
import test from "node:test";

import {
  extractErrorLines,
  summariseActionableNodes,
} from "../lib/tv_shared.js";

// 2026-07-28, run 30343856471: the 2FA step reported `buttons on page: []` —
// neither `button` nor `[role="button"]` existed, so the submit-candidate loop
// could not match by construction. "What is absent" is not a diagnosis, so the
// inventory casts a wider net. These pins keep it readable and bounded: it runs
// inside a 180 s poll loop and its output is the only thing the next
// investigation has to go on.
//
// Browserless on purpose — see tv_signin_email_chooser.test.ts.

test("only visible nodes are reported", () => {
  const summary = summariseActionableNodes([
    { tag: "DIV", text: "Continue", visible: true },
    { tag: "BUTTON", text: "Hidden", visible: false },
  ]);

  assert.equal(summary.length, 1);
  assert.match(summary[0], /div/);
  assert.match(summary[0], /"Continue"/);
});

test("a node is described by tag, type, role, class and text", () => {
  const summary = summariseActionableNodes([
    {
      tag: "DIV",
      role: "presentation",
      className: "submitButton-x9 large-y2 extra-z3",
      text: "  Verify\n  now ",
      visible: true,
    },
  ]);

  assert.equal(summary.length, 1);
  const [entry] = summary;
  assert.match(entry, /^div/);
  assert.match(entry, /role=presentation/);
  assert.match(entry, /\.submitButton-x9\.large-y2/, "first two classes identify the control");
  assert.ok(!entry.includes("extra-z3"), "class list stays bounded");
  assert.match(entry, /"Verify now"/, "whitespace is normalised");
});

test("input controls keep their type", () => {
  const summary = summariseActionableNodes([
    { tag: "INPUT", type: "submit", visible: true },
  ]);

  assert.match(summary[0], /type=submit/);
});

test("the inventory is capped so a poll loop cannot flood the log", () => {
  const many = Array.from({ length: 40 }, (_unused, index) => ({
    tag: "DIV",
    text: `node-${index}`,
    visible: true,
  }));

  assert.equal(summariseActionableNodes(many).length, 15);
  assert.equal(summariseActionableNodes(many, 3).length, 3);
});

test("long text is truncated rather than dumped", () => {
  const summary = summariseActionableNodes([
    { tag: "DIV", text: "x".repeat(200), visible: true },
  ]);

  assert.ok(summary[0].length < 60, `entry stayed short: ${summary[0]}`);
});

test("rejection lines are extracted, ordinary copy is not", () => {
  const body = [
    "Two-factor authentication",
    "Enter the code from your app",
    "Invalid code. Try again.",
    "Need help?",
  ].join("\n");

  const errors = extractErrorLines(body);

  assert.deepEqual(errors, ["Invalid code. Try again."]);
});

test("error extraction is bounded and skips walls of text", () => {
  const body = [
    ...Array.from({ length: 10 }, (_unused, index) => `Invalid attempt ${index}`),
    `error ${"y".repeat(300)}`,
  ].join("\n");

  const errors = extractErrorLines(body);

  assert.equal(errors.length, 5);
  assert.ok(
    errors.every((line) => line.length <= 200),
    "a 300-char paragraph is not an error message",
  );
});

test("a clean page yields no error lines", () => {
  assert.deepEqual(extractErrorLines("Two-factor authentication\nEnter your code"), []);
});

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";

const SOURCE = fs.readFileSync(
  path.resolve(process.cwd(), "scripts/tv_batch_consumer_rollout.ts"),
  "utf-8",
);

test("the baseline comparison is wired to the shared pure function", () => {
  assert.match(SOURCE, /import \{[\s\S]*?compareAgainstBaseline[\s\S]*?\} from "\.\.\/automation\/tradingview\/lib\/tv_out_of_band_drift\.js"/);
});

test("the pre-mutation read happens only when the run mutates", () => {
  // A read-only run has nothing to prove: it cannot be the writer, and the
  // extra pass would double the cost of the cheapest run in the system.
  assert.match(SOURCE, /if \(executionPlan\.mode !== "verify-only"\) \{[\s\S]*?observeBindingsOnly\(/);
});

test("the pre-mutation read precedes the first write", () => {
  // Anchored on the CALL, not the name: the function definition sits above
  // main(), so indexOf("observeBindingsOnly(") would find the declaration and
  // every ordering assertion below would pass without measuring anything.
  const observe = SOURCE.indexOf("await observeBindingsOnly(");
  const firstSave = SOURCE.indexOf("if (executionPlan.saveSources) {");
  assert.ok(observe > 0, "observeBindingsOnly is never called");
  assert.ok(
    observe < firstSave,
    "the observation must run before the first save, or its finding is no longer attributable to a second writer",
  );
});

test("the observation leaves the save phase on the primary chart with an editor", () => {
  // observeBindingsOnly walks the OTHER layouts, so it ends off the primary
  // chart with the Pine editor closed. It must therefore sit ahead of the
  // gotoChart/ensurePineEditor pair, which then restores exactly the state
  // saveConsumerSource assumes. After that pair, the first save would open on
  // the wrong chart with no editor.
  const observe = SOURCE.indexOf("await observeBindingsOnly(");
  const restore = SOURCE.indexOf("await ensurePineEditor(session.page);");
  assert.ok(restore > 0, "the primary-chart editor restore is gone");
  assert.ok(observe < restore, "the pre-mutation observation must precede the editor restore");
});

test("a drifted or unknown verdict makes the run red", () => {
  assert.match(SOURCE, /report\.outOfBandDrift\.status === "clean"/);
});

test("the verdict is reported, not used to withhold the save", () => {
  // Operator decision 2026-08-01, repeated here: withholding freezes the
  // consumers on an old pinned library while the producer moves on.
  assert.doesNotMatch(SOURCE, /outOfBandDrift[\s\S]{0,200}?config\.saveTargets = \[\]/);
});

import assert from "node:assert/strict";
import test from "node:test";

import {
  evaluateReplayCase,
  parseDataWindowItems,
  resolveReplayCheckpointPlan,
} from "../lib/tv_validation_model.js";

// ── parseDataWindowItems ────────────────────────────────────────────────
// Verified 2026-07-31 against the live chart: Pine tables render on canvas, so
// the Data Window is the only DOM-readable value channel.

test("data window items fold into a label-keyed map", () => {
  assert.deepEqual(
    parseDataWindowItems([
      { title: "sourceCloseUtc", value: "1,785,441,600,000.00" },
      { title: "sessionCode", value: "3.00" },
    ]),
    { sourceCloseUtc: "1,785,441,600,000.00", sessionCode: "3.00" },
  );
});

test("the not-available glyph becomes null so it cannot satisfy an expectation", () => {
  assert.deepEqual(parseDataWindowItems([{ title: "available", value: "\u2205" }]), { available: null });
  assert.deepEqual(parseDataWindowItems([{ title: "available", value: "" }]), { available: null });
});

test("a later duplicate never overwrites an already resolved value", () => {
  assert.deepEqual(
    parseDataWindowItems([
      { title: "trend", value: "1.00" },
      { title: "trend", value: "\u2205" },
    ]),
    { trend: "1.00" },
  );
});

test("an unresolved duplicate is filled in by a later real value", () => {
  assert.deepEqual(
    parseDataWindowItems([
      { title: "trend", value: "" },
      { title: "trend", value: "1.00" },
    ]),
    { trend: "1.00" },
  );
});

test("untitled rows are dropped rather than keyed under an empty string", () => {
  assert.deepEqual(parseDataWindowItems([{ title: "  ", value: "5" }]), {});
});

// ── resolveReplayCheckpointPlan ──────────────────────────────────────────────

test("a replay case pins its checkpoint and chart timeframe", () => {
  assert.deepEqual(
    resolveReplayCheckpointPlan({
      caseId: "R5-REBUILD-DST-EU-GAP",
      mode: "replay",
      checkpointUtc: "2025-10-27T13:45:00Z",
      chartTimeframe: "5",
      expectedDiagnostics: ["sessionCode=3"],
    }),
    { runnable: true, caseId: "R5-REBUILD-DST-EU-GAP", checkpointUtc: "2025-10-27T13:45:00Z", chartTimeframe: "5" },
  );
});

test("a replay case without a checkpoint is not runnable by the driver", () => {
  const plan = resolveReplayCheckpointPlan({
    caseId: "R5-REBUILD-LIVE-NO-REPAINT",
    mode: "live_observation",
    chartTimeframe: "5",
    expectedDiagnostics: ["confirmedValuesStableInsideOpenSourceBar=1"],
  });
  assert.equal(plan.runnable, false);
  assert.match(plan.reason ?? "", /live_observation/);
});

test("a malformed checkpoint is rejected rather than silently replayed", () => {
  const plan = resolveReplayCheckpointPlan({
    caseId: "X",
    mode: "replay",
    checkpointUtc: "27.10.2025 13:45",
    expectedDiagnostics: [],
  });
  assert.equal(plan.runnable, false);
  assert.match(plan.reason ?? "", /checkpointUtc/);
});

// ── evaluateReplayCase ───────────────────────────────────────────────────────
// Expectations are written as "key=value" strings in the manifest.

test("all expectations satisfied yields a pass", () => {
  const r = evaluateReplayCase(["sessionCode=3", "sessionLabel=NY AM"], { sessionCode: "3", sessionLabel: "NY AM" });
  assert.equal(r.passed, true);
  assert.deepEqual(r.failures, []);
});

test("a mismatched expectation reports observed against expected", () => {
  const r = evaluateReplayCase(["sessionCode=3"], { sessionCode: "0" });
  assert.equal(r.passed, false);
  assert.deepEqual(r.failures, [{ key: "sessionCode", expected: "3", observed: "0" }]);
});

test("a missing diagnostic fails closed instead of counting as a pass", () => {
  const r = evaluateReplayCase(["sessionCode=3"], {});
  assert.equal(r.passed, false);
  assert.deepEqual(r.failures, [{ key: "sessionCode", expected: "3", observed: null }]);
});

test("an expectation list that is empty cannot certify a case", () => {
  const r = evaluateReplayCase([], { anything: "1" });
  assert.equal(r.passed, false);
  assert.match(r.failures[0]?.key ?? "", /no_expectations/);
});

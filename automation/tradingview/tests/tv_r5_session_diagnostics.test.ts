import assert from "node:assert/strict";
import test from "node:test";

import {
  SESSION_CODE_LABELS,
  checkpointAfterClose,
  epochMsToIsoUtc,
  evaluateReplayCase,
  mapSessionDiagnostics,
  parseDataWindowNumber,
  resolveReplayCheckpointPlan,
  timeframeLabelToMinutes,
} from "../lib/tv_validation_model.js";

// The R5 DST cases assert sessionCode / sessionLabel / sourceCloseUtc against
// values that only reach automation through the Data Window, which carries
// numbers formatted for a human. These pins cover the translation, and in
// particular that it fails CLOSED: a value that cannot be read produces no
// key at all, and evaluateReplayCase already treats a missing key as failure.

test("parseDataWindowNumber recovers TradingView's human formatting", () => {
  assert.equal(parseDataWindowNumber("1,785,440,700,000.00"), 1_785_440_700_000);
  assert.equal(parseDataWindowNumber("3.00"), 3);
  assert.equal(parseDataWindowNumber("-1.00"), -1);
  assert.equal(parseDataWindowNumber("0.0000"), 0);
});

test("parseDataWindowNumber refuses anything that is not a number", () => {
  for (const value of [null, undefined, "", "  ", "∅", "n/a", "NY AM", "1.2.3", "12px"]) {
    assert.equal(parseDataWindowNumber(value), null, `expected null for ${JSON.stringify(value)}`);
  }
});

test("epochMsToIsoUtc renders a UTC instant and refuses non-timestamps", () => {
  // 2025-10-27T13:45:00Z — the DST-EU-GAP checkpoint.
  assert.equal(epochMsToIsoUtc(1_761_572_700_000), "2025-10-27T13:45:00Z");
  // A price, not a timestamp: must not be dressed up as one.
  assert.equal(epochMsToIsoUtc(333.86), null);
  assert.equal(epochMsToIsoUtc(0), null);
  assert.equal(epochMsToIsoUtc(null), null);
  assert.equal(epochMsToIsoUtc(Number.NaN), null);
});

test("session labels mirror SMC_Session_Context.pine _session_label", () => {
  assert.deepEqual(SESSION_CODE_LABELS, {
    "0": "Outside",
    "1": "Asia",
    "2": "London",
    "3": "NY AM",
    "4": "NY PM",
  });
});

test("mapSessionDiagnostics translates a readable NY AM checkpoint", () => {
  const diagnostics = mapSessionDiagnostics({
    "Session Code": "3.00",
    "Session Source Close": "1,761,572,700,000.00",
    "Session VWAP": "251.30",
  });
  assert.deepEqual(diagnostics, {
    sessionCode: "3",
    sessionLabel: "NY AM",
    sourceCloseUtc: "2025-10-27T13:45:00Z",
    sourceConfirmed: "1",
  });
});

test("mapSessionDiagnostics omits keys it cannot read, and the case then fails", () => {
  // parseDataWindowItems maps TradingView's not-available glyph to null.
  const diagnostics = mapSessionDiagnostics({
    "Session Code": null,
    "Session Source Close": null,
  });
  assert.deepEqual(diagnostics, {});

  const result = evaluateReplayCase(
    ["sessionCode=3", "sessionLabel=NY AM", "sourceCloseUtc=2025-10-27T13:45:00Z"],
    diagnostics,
  );
  assert.equal(result.passed, false);
  assert.deepEqual(
    result.failures.map((failure) => failure.key),
    ["sessionCode", "sessionLabel", "sourceCloseUtc"],
  );
  assert.ok(result.failures.every((failure) => failure.observed === null));
});

test("mapSessionDiagnostics does not invent a label for an unknown code", () => {
  const diagnostics = mapSessionDiagnostics({ "Session Code": "9.00" });
  assert.equal(diagnostics.sessionCode, "9");
  assert.equal("sessionLabel" in diagnostics, false);
});

test("an Outside/extended checkpoint maps to code 0 with a confirmed source", () => {
  const diagnostics = mapSessionDiagnostics({
    "Session Code": "0.0000",
    "Session Source Close": "1,773,436,500,000.00",
  });
  assert.equal(diagnostics.sessionCode, "0");
  assert.equal(diagnostics.sessionLabel, "Outside");
  assert.equal(diagnostics.sourceConfirmed, "1");
  assert.equal(
    evaluateReplayCase(["sessionCode=0", "sessionLabel=Outside", "sourceConfirmed=1"], diagnostics).passed,
    true,
  );
});

// Bar Replay boundary semantics, measured on the private validation layout
// 2026-07-31: "Select date" positions AT the bar containing the chosen
// instant, while Session Context publishes the last CLOSED bar. Selecting
// 13:45 reported Source Close 13:40; selecting 13:50 reported 13:45 — the
// value the DST cases assert. The driver therefore drives one bar PAST the
// checkpoint, and these pin that arithmetic.

test("timeframeLabelToMinutes reads TradingView's replay toolbar labels", () => {
  assert.equal(timeframeLabelToMinutes("5m"), 5);
  assert.equal(timeframeLabelToMinutes("1h"), 60);
  assert.equal(timeframeLabelToMinutes("4h"), 240);
  assert.equal(timeframeLabelToMinutes("1D"), 1440);
  for (const bad of [null, undefined, "", "m", "0m", "-5m", "5x", "abc"]) {
    assert.equal(timeframeLabelToMinutes(bad), null, `expected null for ${JSON.stringify(bad)}`);
  }
});

test("checkpointAfterClose advances one bar and splits for the dialog", () => {
  assert.deepEqual(checkpointAfterClose("2025-10-27T13:45:00Z", 5), {
    dateIso: "2025-10-27",
    timeHhMm: "13:50",
  });
  assert.deepEqual(checkpointAfterClose("2025-11-03T14:45:00Z", 5), {
    dateIso: "2025-11-03",
    timeHhMm: "14:50",
  });
  // Crossing midnight must roll the date, not just the clock.
  assert.deepEqual(checkpointAfterClose("2026-03-09T23:55:00Z", 5), {
    dateIso: "2026-03-10",
    timeHhMm: "00:00",
  });
  // A whole-hour chart advances by an hour.
  assert.deepEqual(checkpointAfterClose("2025-10-27T13:00:00Z", 60), {
    dateIso: "2025-10-27",
    timeHhMm: "14:00",
  });
});

test("checkpointAfterClose refuses malformed input rather than guessing", () => {
  assert.equal(checkpointAfterClose("2025-10-27 13:45:00Z", 5), null);
  assert.equal(checkpointAfterClose("2025-10-27T13:45Z", 5), null);
  assert.equal(checkpointAfterClose("not-a-date", 5), null);
  assert.equal(checkpointAfterClose("2025-10-27T13:45:00Z", 0), null);
  assert.equal(checkpointAfterClose("2025-10-27T13:45:00Z", -5), null);
  assert.equal(checkpointAfterClose("2025-10-27T13:45:00Z", Number.NaN), null);
});

test("an extended-hours case is not runnable rather than silently failed", () => {
  const plan = resolveReplayCheckpointPlan({
    caseId: "R5-REBUILD-EXTENDED",
    mode: "replay",
    sessionMode: "extended",
    checkpointUtc: "2026-03-09T21:15:00Z",
    expectedDiagnostics: ["sessionCode=0"],
  });
  assert.equal(plan.runnable, false);
  assert.match(plan.reason ?? "", /extended-hours/i);
});

test("a regular-session replay case stays runnable", () => {
  const plan = resolveReplayCheckpointPlan({
    caseId: "R5-REBUILD-DST-EU-GAP",
    mode: "replay",
    checkpointUtc: "2025-10-27T13:45:00Z",
    expectedDiagnostics: ["sessionCode=3"],
  });
  assert.equal(plan.runnable, true);
  assert.equal(plan.checkpointUtc, "2025-10-27T13:45:00Z");
});

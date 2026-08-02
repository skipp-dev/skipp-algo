import assert from "node:assert/strict";
import { test } from "node:test";

import { compareAgainstBaseline } from "../lib/tv_out_of_band_drift.js";

const NAMES = ["SMC Decision Board", "SMC Event Overlay"];

function consumer(scriptName: string, actual: string | null) {
  return { scriptName, selections: [{ label: "Bus", actual }] };
}

test("identical readings are clean", () => {
  const observed = [consumer(NAMES[0], "study_1"), consumer(NAMES[1], "study_2")];
  const verdict = compareAgainstBaseline({
    observed,
    baseline: [consumer(NAMES[0], "study_1"), consumer(NAMES[1], "study_2")],
    expectedScriptNames: NAMES,
  });
  assert.equal(verdict.status, "clean");
  assert.deepEqual(verdict.changed, []);
});

test("a changed parent id is drift, and the target is named", () => {
  const verdict = compareAgainstBaseline({
    observed: [consumer(NAMES[0], "study_9"), consumer(NAMES[1], "study_2")],
    baseline: [consumer(NAMES[0], "study_1"), consumer(NAMES[1], "study_2")],
    expectedScriptNames: NAMES,
  });
  assert.equal(verdict.status, "drifted");
  assert.equal(verdict.changed.length, 1);
  assert.equal(verdict.changed[0].scriptName, NAMES[0]);
  assert.equal(verdict.changed[0].baseline, "study_1");
  assert.equal(verdict.changed[0].observed, "study_9");
});

test("a missing baseline is unknown, never clean", () => {
  const verdict = compareAgainstBaseline({
    observed: [consumer(NAMES[0], "study_1"), consumer(NAMES[1], "study_2")],
    baseline: null,
    expectedScriptNames: NAMES,
  });
  assert.equal(verdict.status, "unknown");
  assert.match(verdict.reason, /no published baseline/);
});

test("an INCOMPLETE baseline is unknown, not drift", () => {
  // The publish step runs under always(), so a run that died before verifying
  // publishes a partial observation. Comparing a full reading against that
  // would invent drift that never happened.
  const verdict = compareAgainstBaseline({
    observed: [consumer(NAMES[0], "study_1"), consumer(NAMES[1], "study_2")],
    baseline: [consumer(NAMES[0], "study_1")],
    expectedScriptNames: NAMES,
  });
  assert.equal(verdict.status, "unknown");
  assert.match(verdict.reason, /does not cover/);
});

test("an incomplete OBSERVATION is unknown too", () => {
  const verdict = compareAgainstBaseline({
    observed: [consumer(NAMES[0], "study_1")],
    baseline: [consumer(NAMES[0], "study_1"), consumer(NAMES[1], "study_2")],
    expectedScriptNames: NAMES,
  });
  assert.equal(verdict.status, "unknown");
  assert.match(verdict.reason, /this run did not read/);
});

test("a binding that disappeared counts as drift", () => {
  const verdict = compareAgainstBaseline({
    observed: [{ scriptName: NAMES[0], selections: [] }, consumer(NAMES[1], "study_2")],
    baseline: [consumer(NAMES[0], "study_1"), consumer(NAMES[1], "study_2")],
    expectedScriptNames: NAMES,
  });
  assert.equal(verdict.status, "drifted");
  assert.equal(verdict.changed[0].observed, null);
});

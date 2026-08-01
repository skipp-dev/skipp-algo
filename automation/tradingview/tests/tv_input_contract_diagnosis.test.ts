import assert from "node:assert/strict";
import { test } from "node:test";

import { diagnoseInputContract } from "../lib/tv_shared.js";

// The diagnosis decides whether a mutating preflight re-applies a script
// instance. Getting it wrong is silent in both directions: too narrow and a
// stale instance survives forever (the R4 case below), too wide and healthy
// instances lose their bindings for nothing.

const CTX = (n: number): string[] =>
  Array.from({ length: n }, (_, i) => `CTX Channel${i + 1}`);

test("an additive contract change is drift, not a partial surface", () => {
  // The case that stalled R4: #4263 appended two channels, the saved source was
  // updated and verified, and the applied instance kept the old 60 inputs. No
  // legacy label is involved — the old set is a strict SUBSET of the new one.
  const expected = [...CTX(60), "CTX SessionMssBull", "CTX SessionMssBear"];
  const observed = CTX(60);

  const d = diagnoseInputContract(expected, observed);

  assert.equal(d.missingCount, 2);
  assert.equal(d.overlapCount, 60);
  assert.equal(d.legacyLabels.length, 0, "no legacy label is present in this class of change");
  assert.equal(d.likelyDrift, true, "a stale instance must be recognised without legacy labels");
  assert.equal(d.likelyPartialSurface, false);
});

test("seeing none of the expected labels stays a surface problem", () => {
  // Wrong dialog, or nothing rendered. Re-applying the script on this evidence
  // would drop every binding and gain nothing.
  const d = diagnoseInputContract(CTX(62), ["Show structure", "Show sweeps"]);

  assert.equal(d.overlapCount, 0);
  assert.ok(d.missingCount > 0);
  assert.equal(d.likelyDrift, false);
  assert.equal(d.likelyPartialSurface, true);
});

test("a fully matching instance is neither drift nor partial", () => {
  const labels = CTX(62);
  const d = diagnoseInputContract(labels, labels);

  assert.equal(d.missingCount, 0);
  assert.equal(d.likelyDrift, false);
  assert.equal(d.likelyPartialSurface, false);
});

test("the legacy rename case keeps being drift and keeps naming its cause", () => {
  // The case the old heuristic was written for. It must not regress: the
  // instance shows v2 pack labels that the v3 contract no longer declares.
  const expected = ["BUS SchemaVersion", "BUS Ready", "BUS Bias"];
  const observed = ["BUS SchemaVersion", "BUS HardGatesPackA", "BUS QualityPackA"];

  const d = diagnoseInputContract(expected, observed);

  assert.equal(d.likelyDrift, true);
  // legacyLabels is no longer the trigger, but it must keep reporting WHY the
  // instance is stale — that is what makes a drift verdict actionable.
  assert.equal(d.legacyLabels.length, 2, "both v2 pack labels are still named");
});

test("extra observed labels alone do not make a healthy instance drift", () => {
  // A dialog carries the script's own display toggles next to the BUS inputs.
  // Those are not part of the expected contract and must not count as missing.
  const expected = CTX(3);
  const observed = [...CTX(3), "Show structure", "Show order-block zones"];

  const d = diagnoseInputContract(expected, observed);

  assert.equal(d.missingCount, 0);
  assert.equal(d.likelyDrift, false, "a superset instance is not stale");
  assert.equal(d.likelyPartialSurface, false);
});

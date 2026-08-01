import assert from "node:assert/strict";
import test from "node:test";

import { resolveHtfSuiteVerdict } from "../lib/tv_validation_model.js";

// Found by the vacuity sweep, in the runner that produced the R5 HTF
// certification evidence. The verdict was
//   failClosedPassed && cases.filter((c) => c.executed).every((c) => c.passed)
// so a run in which NO case executed filtered down to an empty list, `every`
// returned true vacuously, the process exited 0, and the artifact claimed a
// certification nothing had observed.

const CASES: Array<{ caseId: string; executed: boolean; passed?: boolean }> = [
  { caseId: "R5-REBUILD-HTF-15M", executed: true, passed: true },
  { caseId: "R5-REBUILD-HTF-1H", executed: true, passed: true },
  { caseId: "R5-REBUILD-HTF-4H", executed: true, passed: true },
];

test("no case executed is a failure, not a pass", () => {
  const verdict = resolveHtfSuiteVerdict(true, CASES.map((c) => ({ ...c, executed: false, passed: undefined })));
  assert.equal(verdict.ok, false);
  assert.equal(verdict.executed, 0);
  assert.deepEqual(verdict.notExecuted, [
    "R5-REBUILD-HTF-15M",
    "R5-REBUILD-HTF-1H",
    "R5-REBUILD-HTF-4H",
  ]);
});

test("an empty suite certifies nothing", () => {
  assert.equal(resolveHtfSuiteVerdict(true, []).ok, false);
});

test("a single unexecuted case blocks the suite", () => {
  const cases = [...CASES];
  cases[2] = { caseId: "R5-REBUILD-HTF-4H", executed: false };
  const verdict = resolveHtfSuiteVerdict(true, cases);
  assert.equal(verdict.ok, false);
  assert.deepEqual(verdict.notExecuted, ["R5-REBUILD-HTF-4H"]);
  assert.equal(verdict.executed, 2);
});

test("all executed and passing, with FAIL-CLOSED green, certifies", () => {
  const verdict = resolveHtfSuiteVerdict(true, CASES);
  assert.equal(verdict.ok, true);
  assert.equal(verdict.executed, 3);
  assert.deepEqual(verdict.notExecuted, []);
  assert.deepEqual(verdict.failed, []);
});

test("a failed FAIL-CLOSED blocks even a complete suite", () => {
  assert.equal(resolveHtfSuiteVerdict(false, CASES).ok, false);
});

test("an executed case without a verdict counts as failed, not as absent", () => {
  // `passed` stays undefined when the case threw after being marked executed.
  const cases = [...CASES];
  cases[0] = { caseId: "R5-REBUILD-HTF-15M", executed: true };
  const verdict = resolveHtfSuiteVerdict(true, cases);
  assert.equal(verdict.ok, false);
  assert.deepEqual(verdict.failed, ["R5-REBUILD-HTF-15M"]);
  assert.deepEqual(verdict.notExecuted, []);
});

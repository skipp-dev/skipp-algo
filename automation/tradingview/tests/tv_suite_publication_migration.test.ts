import assert from "node:assert/strict";
import test from "node:test";

import { diffInputs, legendScriptName, parseMigrationArgs, PRUNE_RIGHT_PANE } from "../../../scripts/tv_suite_publication_migration.js";

const inst = (name: string, values: Array<[string, string]>, hidden = false) => ({
  pane: 0, name, entityId: "x", hidden, inputsError: "",
  inputs: values.map(([label, value]) => ({ label, kind: "text", value })),
});

test("legend text resolves to the script name", () => {
  assert.equal(legendScriptName("SMC Long-Dip Suite · 242.0"), "SMC Long-Dip Suite");
  assert.equal(legendScriptName("SMC Decision Board"), "SMC Decision Board");
});

test("inputs are compared by position, so repeated labels cannot mis-pair", () => {
  // two "Length" inputs: a label map would pair them wrongly (2026-10-05 dry run)
  const before = [inst("S", [["Length", "14"], ["Length", "20"]])];
  assert.deepEqual(diffInputs(before, [inst("S", [["Length", "14"], ["Length", "20"]])]).diffs, []);
  assert.deepEqual(diffInputs(before, [inst("S", [["Length", "14"], ["Length", "5"]])]).diffs.map((d) => d.label), ["1:Length"]);
});

test("BUS inputs are bindings and are not compared as inputs", () => {
  const before = [inst("C", [["BUS Armed", "SMC Long-Dip Suite · 242.0: BUS Armed"]])];
  const after = [inst("C", [["BUS Armed", "SMC Long-Dip Suite · 435.0: BUS Armed"]])];
  assert.deepEqual(diffInputs(before, after).diffs, []);
});

test("a script that did not come back, or an unreadable input list, is a difference", () => {
  const d = diffInputs([inst("A", []), inst("B", [["x", "1"]])], [inst("B", [])]);
  assert.deepEqual(d.missing, ["A"]);
  assert.deepEqual(d.diffs.map((x) => x.label), ["(input count)"]);
});

test("arguments: phases, chart ids and the twh98JLB exclusion", () => {
  assert.equal(parseMigrationArgs(["--phase", "inventory", "--out", "o"]).charts.length, 3);
  assert.equal(parseMigrationArgs(["--phase", "migrate", "--out", "o", "--charts", "hKHTmKhu", "--dry-run"]).dryRun, true);
  assert.throws(() => parseMigrationArgs(["--phase", "migrate", "--out", "o", "--charts", "hKHTmKhu,vWgAWyfC"]), /exactly one/);
  assert.throws(() => parseMigrationArgs(["--phase", "migrate", "--out", "o", "--charts", "twh98JLB"]), /Hold Manager/);
  assert.throws(() => parseMigrationArgs(["--phase", "nope", "--out", "o"]), /unknown --phase/);
  assert.throws(() => parseMigrationArgs(["--phase", "inventory", "--out", "o", "--charts", "../x"]), /not a chart id/);
});

test("only vWgAWyfC loses its right pane", () => {
  assert.deepEqual([...PRUNE_RIGHT_PANE], ["vWgAWyfC"]);
});

test("an input the new Suite adds on purpose is accepted only when named; every other value is still compared", () => {
  const before = [inst("SMC Long-Dip Suite", [["HTF Bias Min Count", "2"], ["Fast length", "8"]])];
  const after = [inst("SMC Long-Dip Suite", [["HTF Bias Min Count", "2"], ["Ready: Min Soft Gates (of 12)", "12"], ["Fast length", "8"]])];
  assert.deepEqual(diffInputs(before, after).diffs.map((d) => d.label), ["(input count)"]);
  const ok = diffInputs(before, after, { "SMC Long-Dip Suite": ["Ready: Min Soft Gates (of 12)"] });
  assert.deepEqual(ok.diffs, []);
  assert.deepEqual(ok.acceptedNew, ["SMC Long-Dip Suite: Ready: Min Soft Gates (of 12)=12"]);
  const changed = [inst("SMC Long-Dip Suite", [["HTF Bias Min Count", "3"], ["Ready: Min Soft Gates (of 12)", "12"], ["Fast length", "8"]])];
  assert.deepEqual(diffInputs(before, changed, { "SMC Long-Dip Suite": ["Ready: Min Soft Gates (of 12)"] }).diffs.map((d) => d.label), ["0:HTF Bias Min Count"]);
  assert.deepEqual(parseMigrationArgs(["--phase", "migrate", "--out", "o", "--charts", "vWgAWyfC", "--accept-new-suite-input", "X"]).acceptNewSuiteInputs, ["X"]);
});

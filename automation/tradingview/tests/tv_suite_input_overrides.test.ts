import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

import {
  coerceInputValue,
  countSourceInputs,
  getAllFlagValues,
  parseSuiteInputOverride,
  resolveSuiteInputId,
  suiteInputIdsByLabel,
} from "../lib/tv_suite_input_overrides.js";
import { parseReadoutArgs } from "../../../scripts/tv_strategy_report_readout.js";
import { parseLogArgs } from "../../../scripts/tv_long_engine_log_readout.js";

test("an override is Label=value; the label keeps its spaces and arrows", () => {
  assert.deepEqual(parseSuiteInputOverride("Max Bars Armed -> Confirm=6"), { label: "Max Bars Armed -> Confirm", raw: "6" });
  assert.deepEqual(parseSuiteInputOverride("Structure Mode=Internal CHoCH or BOS"), { label: "Structure Mode", raw: "Internal CHoCH or BOS" });
  assert.throws(() => parseSuiteInputOverride("no equals sign"), /Label=value/);
});

test("a repeated flag yields every value; a trailing flag without value is refused", () => {
  assert.deepEqual(getAllFlagValues(["--suite-input", "A=1", "--out", "o", "--suite-input", "B=2"], "--suite-input"), ["A=1", "B=2"]);
  assert.throws(() => getAllFlagValues(["--suite-input"], "--suite-input"), /needs a value/);
});

test("inputs are numbered by input() call order; comments do not count; duplicates are refused", () => {
  const src = [
    "var int a = input.int(6, 'Alpha', minval = 1) // input.int(9, 'Ghost')",
    "// var bool g = input.bool(true, 'Commented')",
    "var bool b = input.bool(true, 'Beta')",
    "var int l1 = input.int(14, 'Length')",
    "var int l2 = input.int(20, 'Length')",
    "src = input.source(close, \"Source\")",
  ].join("\n");
  assert.equal(countSourceInputs(src), 5);
  assert.equal(resolveSuiteInputId(src, "Alpha"), "in_0");
  assert.equal(resolveSuiteInputId(src, "Beta"), "in_1");
  assert.equal(resolveSuiteInputId(src, "Source"), "in_4");
  assert.throws(() => resolveSuiteInputId(src, "Length"), /ambiguous/);
  assert.throws(() => resolveSuiteInputId(src, "Ghost"), /no Suite input/);
  assert.equal(suiteInputIdsByLabel(src).get("Length")?.length, 2);
});

test("the Suite's measured ids (2026-10-06, vWgAWyfC, v436) follow from the repository source", () => {
  const src = fs.readFileSync("SMC_Long_Dip_Suite.pine", "utf-8");
  assert.equal(resolveSuiteInputId(src, "Setup Expiry Bars"), "in_68");
  assert.equal(resolveSuiteInputId(src, "Max Bars Armed -> Confirm"), "in_72");
  assert.equal(resolveSuiteInputId(src, "Require Internal Break For Confirm"), "in_105");
  assert.equal(resolveSuiteInputId(src, "Require Main BOS For Ready"), "in_106");
  assert.equal(resolveSuiteInputId(src, "Live Confirm Uses High"), "in_107");
  assert.equal(resolveSuiteInputId(src, "Structure Mode"), "in_109");
});

test("values are coerced to the type currently on the chart", () => {
  assert.equal(coerceInputValue("false", true), false);
  assert.equal(coerceInputValue("6", 2), 6);
  assert.equal(coerceInputValue("Internal CHoCH or BOS", "Internal CHoCH only"), "Internal CHoCH or BOS");
  assert.throws(() => coerceInputValue("yes", true), /true\/false/);
  assert.throws(() => coerceInputValue("six", 2), /number/);
});

test("both readouts accept repeated --suite-input flags", () => {
  const r = parseReadoutArgs(["--out", "o", "--suite-input", "Require Internal Break For Confirm=false", "--suite-input", "Max Bars Armed -> Confirm=6"]);
  assert.deepEqual(r.suiteInputs.map((x) => x.label), ["Require Internal Break For Confirm", "Max Bars Armed -> Confirm"]);
  assert.deepEqual(parseLogArgs(["--out", "o"]).suiteInputs, []);
});

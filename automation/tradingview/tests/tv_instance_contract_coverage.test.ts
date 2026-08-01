import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import {
  assessInstanceContractCoverage,
  formatInstanceContractCoverage,
} from "../../../scripts/tv_verify_consumer_bindings.js";

const _dir = path.dirname(fileURLToPath(import.meta.url));
const VERIFY = path.join(_dir, "..", "..", "..", "scripts", "tv_verify_consumer_bindings.ts");

// Run 30702240413: the settings dialog carried 60 of the 62 contract inputs,
// ending on CTX SessionDirection — exactly the pre-#4263 build (87fd72c09 has
// 60 input.source, 9eb653c1b has 62). The instance being repaired was not the
// version the run had just saved and verified.
//
// The repair loop did not notice. It rebound 60 sources on that stale instance
// and only died on the 61st, so every failed run mutated a chart instance 60
// times for nothing. A contract that is knowably incomplete has to stop the
// mutation, not be discovered halfway through it.

const CONTRACT = ["CTX SchemaVersion", "CTX SessionDirection", "CTX SessionMssBull", "CTX SessionMssBear"];

const bound = (labels: readonly string[]) =>
  labels.map((label) => ({ label, actual: `SMC Context Bus: ${label}` }));

test("an instance carrying every contract input passes", () => {
  const coverage = assessInstanceContractCoverage(bound(CONTRACT));

  assert.equal(coverage.ok, true);
  assert.equal(coverage.present, 4);
  assert.deepEqual(coverage.missing, []);
});

test("a freshly added, still unbound instance passes — unbound is not absent", () => {
  // A new instance defaults every input.source to `close`. The rows exist, so
  // the contract is covered and the repair is exactly what should run.
  const coverage = assessInstanceContractCoverage(
    CONTRACT.map((label) => ({ label, actual: "close" })),
  );

  assert.equal(coverage.ok, true);
  assert.deepEqual(coverage.missing, []);
});

test("rows absent from the dialog are reported by name", () => {
  const coverage = assessInstanceContractCoverage([
    ...bound(["CTX SchemaVersion", "CTX SessionDirection"]),
    { label: "CTX SessionMssBull", actual: null },
    { label: "CTX SessionMssBear", actual: null },
  ]);

  assert.equal(coverage.ok, false);
  assert.equal(coverage.present, 2);
  assert.equal(coverage.total, 4);
  assert.deepEqual(coverage.missing, ["CTX SessionMssBull", "CTX SessionMssBear"]);
});

test("a dialog carrying none of the contract is a different failure than a partial one", () => {
  const none = assessInstanceContractCoverage(CONTRACT.map((label) => ({ label, actual: null })));
  const partial = assessInstanceContractCoverage([
    ...bound(["CTX SchemaVersion"]),
    { label: "CTX SessionDirection", actual: null },
    { label: "CTX SessionMssBull", actual: null },
    { label: "CTX SessionMssBear", actual: null },
  ]);

  assert.equal(none.ok, false);
  assert.equal(partial.ok, false);
  assert.match(formatInstanceContractCoverage("SMC Context Overlay", none), /none of the/);
  assert.doesNotMatch(formatInstanceContractCoverage("SMC Context Overlay", partial), /none of the/);
});

test("the message carries the counts and the missing names", () => {
  const message = formatInstanceContractCoverage(
    "SMC Context Overlay",
    assessInstanceContractCoverage([
      ...bound(["CTX SchemaVersion", "CTX SessionDirection"]),
      { label: "CTX SessionMssBull", actual: null },
      { label: "CTX SessionMssBear", actual: null },
    ]),
  );

  assert.match(message, /SMC Context Overlay/);
  assert.match(message, /2 of 4/);
  assert.match(message, /CTX SessionMssBull/);
  assert.match(message, /CTX SessionMssBear/);
});

test("an over-long missing list is truncated but says how many it dropped", () => {
  const many = Array.from({ length: 20 }, (_, i) => ({ label: `CTX Missing${i}`, actual: null }));
  const message = formatInstanceContractCoverage(
    "SMC Context Overlay",
    assessInstanceContractCoverage([...bound(["CTX SchemaVersion"]), ...many]),
  );

  assert.match(message, /\+\d+ more/);
});

test("the repair path refuses to mutate an instance with an incomplete contract", () => {
  // Pinned as wiring, not only as a helper: #4307 showed helper tests stay
  // green when the call site is deleted. The guard must sit BEFORE the repair
  // loop — after it, the 60 pointless rebinds have already happened.
  const source = fs.readFileSync(VERIFY, "utf-8");

  assert.match(
    source,
    /assessInstanceContractCoverage\(bindings\)/,
    "verifyConsumer must assess coverage from the bindings it just read",
  );
  assert.match(
    source,
    /assessInstanceContractCoverage\(bindings\)[\s\S]*?throw new Error\(\s*formatInstanceContractCoverage[\s\S]*?for \(const binding of bindingsToRepair\)/,
    "the throw must precede the repair loop",
  );
});

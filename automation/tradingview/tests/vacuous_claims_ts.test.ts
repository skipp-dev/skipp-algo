import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { scanDir, scanSource } from "../../../scripts/detect_vacuous_claims_ts.js";

const TEST_DIR = path.dirname(fileURLToPath(import.meta.url));

/**
 * Waived claims: key -> dated reason. Mirrors
 * [vacuous_claim_guard.exemptions] in pin_registry.toml, which TypeScript
 * cannot read. Same contract: a waiver is a decision, so it is dated and
 * says why, and a stale one is red.
 *
 * Empty by measurement, not by omission: the 2026-08-03 baseline was 7
 * claims over 55 files and every one of them was a real defect that a
 * length witness healed, so nothing needed declaring. A waiver belongs here
 * only when the emptiness is intended and something else does the proving —
 * never to silence a detector that is wrong. For that, add a fixture above
 * and sharpen scripts/detect_vacuous_claims_ts.ts.
 */
const TS_VACUITY_EXEMPTIONS: Record<string, string> = {};

const kinds = (source: string): Record<string, string> =>
  Object.fromEntries(scanSource(source, "example.test.ts").map((c) => [c.iterable, c.kind]));

test("a literal array loop is not a claim", () => {
  const source = `for (const flag of ["--a", "--b"]) { assert.ok(text.includes(flag)); }`;
  assert.deepEqual(kinds(source), {});
});

test("a filtered array loop is a claim", () => {
  const source = `
    const hits = lines.filter((line) => line.includes("export"));
    for (const hit of hits) { assert.ok(hit.startsWith("export")); }
  `;
  assert.deepEqual(kinds(source), { hits: "local filter call" });
});

test("a directory read is a claim", () => {
  const source = `
    for (const name of fs.readdirSync(dir)) { assert.ok(name.endsWith(".ts")); }
  `;
  assert.deepEqual(kinds(source), { "fs.readdirSync(dir)": "discovery call" });
});

test("assert.ok over .every of a filtered array is a claim", () => {
  const source = `
    const hits = lines.filter((line) => line.includes("export"));
    assert.ok(hits.every((hit) => hit.startsWith("export")));
  `;
  assert.deepEqual(kinds(source), { hits: "local filter call" });
});

test("a length witness clears its own iterable", () => {
  const source = `
    const hits = lines.filter((line) => line.includes("export"));
    assert.ok(hits.length > 0, "no export line — this pin would pass vacuously");
    for (const hit of hits) { assert.ok(hit.startsWith("export")); }
  `;
  assert.deepEqual(kinds(source), {});
});

test("a witness for one array does not clear another", () => {
  const source = `
    const exports = lines.filter((line) => line.startsWith("export"));
    const bools = lines.filter((line) => line.includes("bool"));
    assert.ok(bools.length > 0);
    for (const line of exports) { assert.ok(TYPE_PAT.test(line)); }
  `;
  assert.deepEqual(kinds(source), { exports: "local filter call" });
});

test("an empty recording array is a claim", () => {
  // The dominant idiom in this suite: a fake page pushes into `calls`. If
  // the code under test calls nothing, `calls` stays empty and the pin is
  // green having observed nothing.
  const source = `
    const calls: string[] = [];
    assert.equal(calls.every((call) => call.includes("version")), true);
  `;
  assert.deepEqual(kinds(source), { calls: "local empty array literal" });
});

test("assert.equal over .some compared to false is a claim", () => {
  const source = `
    const calls: string[] = [];
    assert.equal(calls.some((call) => call.startsWith("locator:")), false);
  `;
  assert.deepEqual(kinds(source), { calls: "local empty array literal" });
});

test("the loud polarities of .some and .every are not claims", () => {
  // `[].some(f)` is false and `[].every(f)` is true, so both of these fail
  // over an empty collection instead of passing silently.
  const source = `
    const calls: string[] = [];
    assert.equal(calls.some((call) => call.startsWith("locator:")), true);
    assert.equal(calls.every((call) => call.includes("version")), false);
    assert.ok(calls.some((call) => call.includes("version")));
  `;
  assert.deepEqual(kinds(source), {});
});

test("a spread of a discovery call is a claim, and its witness clears it", () => {
  const emptiable = `
    const matches = [...text.matchAll(/gotoChart/g)];
    for (const match of matches) { assert.ok(match.index >= 0); }
  `;
  assert.deepEqual(kinds(emptiable), { matches: "local discovery call" });

  const witnessed = `
    const matches = [...text.matchAll(/gotoChart/g)];
    assert.ok(matches.length > 0, "no gotoChart — this pin would pass vacuously");
    for (const match of matches) { assert.ok(match.index >= 0); }
  `;
  assert.deepEqual(kinds(witnessed), {});
});

test("a witness on one part of a concatenation clears the whole", () => {
  // `[...a, ...b]` is non-empty as soon as `a` is: concatenation only grows.
  const source = `
    const filterCalls: string[] = [];
    const textCalls: string[] = [];
    assert.equal(filterCalls.length, 6);
    for (const pattern of [...filterCalls, ...textCalls]) { assert.ok(pattern.endsWith("$")); }
  `;
  assert.deepEqual(kinds(source), {});
});

test("a witness on the base does not clear a filter over it", () => {
  const source = `
    assert.ok(lines.length > 0);
    for (const hit of lines.filter((line) => line.includes("export"))) {
      assert.ok(hit.startsWith("export"));
    }
  `;
  assert.deepEqual(kinds(source), {
    'lines.filter((line) => line.includes("export"))': "filter call",
  });
});

test("a length equality of zero is not a witness", () => {
  // assert.equal(xs.length, 0) proves the collection is EMPTY. Reading it as
  // a witness would let a proven-empty collection exonerate a loop over it.
  const source = `
    const hits = lines.filter((line) => line.includes("export"));
    assert.equal(hits.length, 0);
    for (const hit of hits) { assert.ok(hit.startsWith("export")); }
  `;
  assert.deepEqual(kinds(source), { hits: "local filter call" });
});

test("a witness in one test does not clear another test's collection", () => {
  const source = `
    test("proves it", () => {
      const hits = lines.filter((line) => line.includes("export"));
      assert.ok(hits.length > 0);
      for (const hit of hits) { assert.ok(hit.startsWith("export")); }
    });
    test("does not", () => {
      const hits = lines.filter((line) => line.includes("import"));
      for (const hit of hits) { assert.ok(hit.startsWith("import")); }
    });
  `;
  // Asserted by scope, not by `kinds`: both tests name the collection
  // `hits`, so keying on the iterable alone would collapse two claims into
  // one entry and hide a witness that stopped binding altogether.
  assert.deepEqual(
    scanSource(source, "example.test.ts").map((claim) => claim.scope),
    ["does not"],
  );
});

test("a throw after the loop is a witness", () => {
  const source = `
    for (const name of fs.readdirSync(dir)) {
      if (name === "target.ts") { assert.ok(name); return; }
    }
    throw new Error("target.ts is gone — the pin is stale");
  `;
  assert.deepEqual(kinds(source), {});
});

test("the analyzer observed the TypeScript test suite", () => {
  // Witness for the gate below: an empty scan would make it pass silently.
  const { files } = scanDir(TEST_DIR);
  assert.ok(
    files.length >= 20,
    `scanned only ${files.length} *.test.ts files — discovery broke and the gate below is vacuous`,
  );
});

test("no unexempted vacuous claims in the TypeScript tests", () => {
  const { claims } = scanDir(TEST_DIR);
  const undeclared = claims
    .filter((claim) => !(claim.key in TS_VACUITY_EXEMPTIONS))
    .map((claim) => `${claim.key} [${claim.kind}] ${claim.path}:${claim.line}`)
    .sort();
  assert.deepEqual(
    undeclared,
    [],
    `assertion(s) can pass without observing anything:\n${undeclared.join("\n")}`,
  );
});

test("every TypeScript exemption still matches a claim", () => {
  const { claims } = scanDir(TEST_DIR);
  const keys = new Set(claims.map((claim) => claim.key));
  const stale = Object.keys(TS_VACUITY_EXEMPTIONS).filter((key) => !keys.has(key)).sort();
  assert.deepEqual(stale, [], `stale exemption(s): ${stale.join(", ")}`);
});

test("every TypeScript exemption carries a dated reason", () => {
  const undated = Object.entries(TS_VACUITY_EXEMPTIONS)
    .filter(([, reason]) => !/^\d{4}-\d{2}-\d{2}: \S/.test(reason))
    .map(([key]) => key)
    .sort();
  assert.deepEqual(undated, [], `undated exemption(s): ${undated.join(", ")}`);
});

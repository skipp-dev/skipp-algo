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

test("a recording object's array property is a claim", () => {
  // The `recording` variant of the same idiom: one object holds several
  // recording arrays and the fake page pushes into its properties.
  const source = `
    const recording: Recording = { locatorCalls: [], filterCalls: [], textCalls: [] };
    for (const pattern of recording.filterCalls) { assert.ok(pattern.startsWith("^")); }
  `;
  assert.deepEqual(kinds(source), { "recording.filterCalls": "local empty array literal" });
});

test("a witness on a recording property clears that property only", () => {
  const source = `
    const recording: Recording = { locatorCalls: [], filterCalls: [], textCalls: [] };
    assert.equal(recording.filterCalls.length, 3);
    for (const pattern of recording.filterCalls) { assert.ok(pattern.startsWith("^")); }
    for (const selector of recording.locatorCalls) { assert.ok(selector.includes("USER;")); }
  `;
  assert.deepEqual(kinds(source), { "recording.locatorCalls": "local empty array literal" });
});

test("an unbound property access is not a claim", () => {
  // Bounded on purpose: only properties whose initialiser was seen to be
  // emptiable bind. Widening to every property access would report on
  // config literals the analyzer knows nothing about.
  const source = `
    for (const failure of result.failures) { assert.ok(failure.observed === null); }
    for (const item of CONFIG.targets) { assert.ok(item.name); }
  `;
  assert.deepEqual(kinds(source), {});
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

/**
 * Waived keys that no longer match any detected claim.
 *
 * Extracted so the registry tests below and the fixtures that observe them
 * run the *same* code. A fixture exercising a second copy of this logic
 * would prove nothing about what the registry test actually calls.
 */
const staleExemptions = (
  exemptions: Record<string, string>,
  claimKeys: readonly string[],
): string[] => {
  const keys = new Set(claimKeys);
  return Object.keys(exemptions)
    .filter((key) => !keys.has(key))
    .sort();
};

/** Waived keys whose reason is not a `YYYY-MM-DD: <something>` justification. */
const undatedExemptions = (exemptions: Record<string, string>): string[] =>
  Object.entries(exemptions)
    .filter(([, reason]) => !/^\d{4}-\d{2}-\d{2}: \S/.test(reason))
    .map(([key]) => key)
    .sort();

test("every TypeScript exemption still matches a claim", () => {
  const { claims } = scanDir(TEST_DIR);
  const stale = staleExemptions(TS_VACUITY_EXEMPTIONS, claims.map((claim) => claim.key));
  assert.deepEqual(stale, [], `stale exemption(s): ${stale.join(", ")}`);
});

test("the stale-exemption check names the waiver whose claim is gone", () => {
  // Witness for the registry test above. TS_VACUITY_EXEMPTIONS is empty, so
  // that test runs this predicate over no input at all and would stay green
  // if the predicate stopped working — the very shape this file forbids.
  assert.deepEqual(
    staleExemptions(
      { "a.test.ts::t::gone": "2026-08-03: x", "a.test.ts::t::live": "2026-08-03: x" },
      ["a.test.ts::t::live"],
    ),
    ["a.test.ts::t::gone"],
  );
});

test("every TypeScript exemption carries a dated reason", () => {
  const undated = undatedExemptions(TS_VACUITY_EXEMPTIONS);
  assert.deepEqual(undated, [], `undated exemption(s): ${undated.join(", ")}`);
});

test("the dated-reason check accepts a dated waiver and rejects a bare one", () => {
  // Witness for the registry test above, for the same reason.
  assert.deepEqual(undatedExemptions({ "a.test.ts::t::i": "2026-08-03: proven by test X" }), []);
  assert.deepEqual(undatedExemptions({ "a.test.ts::t::i": "because" }), ["a.test.ts::t::i"]);
});

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

// 2026-07-27 production evidence (run 30248563009) proved that
// `tolerateFailure: true` does not cover the outer runTrackedStep timeout:
// the timeout wins the Promise.race before addCurrentScriptToChart reaches its
// internal tolerance branch, so the publisher still exits with
// `publishAttempted: false`.
//
// The pre-publish insertion is unnecessary. publishPrivateScript owns the
// fail-closed "Script is not on the chart" gate and resolves it from the
// publish dialog. This contract therefore forbids the redundant chart probe
// between the compile gate and publish attempt.
//
// 2026-08-14 (handlib-publisher-dedup): the ten hand-authored libraries are
// being converted, one at a time, into thin descriptor wrappers over the
// shared `runHandLibPublish` body in
// automation/tradingview/lib/tv_publish_hand_lib.ts. Once converted, the
// compile-gate-before-publish sequencing this test protects no longer lives
// in the wrapper's own source. Folding the ten into a single
// "check the shared module" branch would have silently stopped covering the
// nine still-unconverted publishers. So each of the ten is checked against
// wherever it actually keeps the property: the original per-file check for a
// publisher that has not converted yet, or a delegation check for one that
// has, backed by one assertion that the shared module itself still carries
// the sequencing. "micro" and "overlay" are not part of this refactor (they
// stay self-contained, generated-library publishers) and keep their
// original, unmodified per-file check.

const _dir = path.dirname(fileURLToPath(import.meta.url));
const _scriptsDir = path.resolve(_dir, "..", "..", "..", "scripts");
const _sharedModulePath = path.resolve(_dir, "..", "lib", "tv_publish_hand_lib.ts");

// The ten hand-authored libraries this refactor is converting to descriptor
// wrappers over the shared publish body (see HAND_LIBS in
// scripts/tv_publish_hand_authored_libraries.ts).
const HAND_AUTHORED_LIBRARIES = [
  "bus",
  "context_engine",
  "context_resolvers",
  "core_types",
  "draw",
  "engine",
  "lifecycle",
  "observability",
  "profile_engine",
  "utils",
];

// "micro" publishes the generated micro-profiles library; "overlay" publishes
// a generated overlay library (see the 2026-07-31 note in
// hand_authored_publisher_facade_authority.test.ts). Neither is part of the
// handlib-publisher-dedup refactor, so both keep the original per-file check.
const GENERATED_LIBRARY_PUBLISHERS = ["micro", "overlay"];

/** The substantive property: the compile gate must run before publish, with no redundant chart probe between them. */
function assertDelegatesChartGateToPublish(name: string, source: string): void {
  const compileGate = source.indexOf("await assertNoVisibleCompileError(");
  const publishCall = source.indexOf("await publishPrivateScript(", compileGate);

  assert.ok(
    compileGate >= 0 && publishCall > compileGate,
    `${name}: must retain its compile gate before publishing`,
  );
  assert.doesNotMatch(
    source.slice(compileGate, publishCall),
    /addCurrentScriptToChart\(/,
    `${name}: must not run the redundant pre-publish chart probe; `
    + "publishPrivateScript owns the hard chart gate",
  );
}

for (const name of GENERATED_LIBRARY_PUBLISHERS) {
  test(`tv_publish_${name}_library delegates the chart gate to publishPrivateScript`, () => {
    const source = fs.readFileSync(
      path.join(_scriptsDir, `tv_publish_${name}_library.ts`),
      "utf-8",
    );
    assertDelegatesChartGateToPublish(name, source);
  });
}

test("the shared hand-lib publish body delegates the chart gate to publishPrivateScript", () => {
  const source = fs.readFileSync(_sharedModulePath, "utf-8");
  assertDelegatesChartGateToPublish("tv_publish_hand_lib (shared module)", source);
});

for (const name of HAND_AUTHORED_LIBRARIES) {
  test(`tv_publish_${name}_library reaches the chart-gate delegation to publishPrivateScript`, () => {
    const source = fs.readFileSync(
      path.join(_scriptsDir, `tv_publish_${name}_library.ts`),
      "utf-8",
    );
    if (/\brunHandLibPublish\(/.test(source)) {
      // Converted: the substantive property is checked once, above, against
      // the shared module. This publisher only needs to prove it actually
      // reaches that module.
      assert.ok(
        /from ["'][^"']*tv_publish_hand_lib\.js["']/.test(source),
        `${name}: calls runHandLibPublish but does not import it from the shared module`,
      );
    } else {
      // Not yet converted by this refactor: still owns the sequencing
      // inline, same contract as before the migration.
      assertDelegatesChartGateToPublish(name, source);
    }
  });
}

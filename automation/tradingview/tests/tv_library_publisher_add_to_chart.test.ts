import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { HAND_LIBS } from "../../../scripts/tv_publish_hand_authored_libraries.js";

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
//
// 2026-08-14 fix round 1 (review C1): the first cut of the delegation branch
// asserted only that the wrapper's source mentioned
// "tv_publish_hand_lib.js" somewhere — a raw text scan blind to comments,
// string literals, and type-only imports, and blind to a wrapper that
// genuinely calls runHandLibPublish but ALSO still carries its own
// addCurrentScriptToChart/publishPrivateScript inline path. See
// assertDelegatesToSharedChartGate below: it now requires a structural
// import binding, a literal call-and-return site, AND the absence of every
// inline publish primitive together — mirrors the fix in
// hand_authored_publisher_facade_authority.test.ts, which documents the four
// probes this closes in full.
//
// 2026-08-14 fix round 1 (review I3): HAND_AUTHORED_LIBRARIES below is
// DERIVED from HAND_LIBS (scripts/tv_publish_hand_authored_libraries.ts)
// instead of a hand-copied literal, so an eleventh hand-authored library
// cannot land unguarded here either.
//
// 2026-08-14 fix round 1 (review M4): the failure-message text for the two
// retained GENERATED_LIBRARY_PUBLISHERS ("micro", "overlay") — whose
// assertions the ruling required to survive this migration UNCHANGED — is
// restored to the original `tv_publish_<name>_library.ts ...` wording; it
// had drifted to a bare `${name}: ...` prefix when the check was extracted
// into a shared function.

const _dir = path.dirname(fileURLToPath(import.meta.url));
const _scriptsDir = path.resolve(_dir, "..", "..", "..", "scripts");
const _sharedModulePath = path.resolve(_dir, "..", "lib", "tv_publish_hand_lib.ts");

/** The short `tv_publish_<name>_library.ts` identifier for each of HAND_LIBS' hand-authored publishers. */
function handAuthoredPublisherNames(): string[] {
  const names: string[] = [];
  for (const lib of HAND_LIBS) {
    if (lib.publisher === null) {
      continue;
    }
    const match = /^scripts\/tv_publish_(.+)_library\.ts$/.exec(lib.publisher);
    if (!match) {
      throw new Error(`Unexpected hand-authored publisher path shape: ${lib.publisher}`);
    }
    names.push(match[1]);
  }
  return names;
}

// The hand-authored libraries this refactor is converting to descriptor
// wrappers over the shared publish body — derived from HAND_LIBS, not
// hand-copied (review I3).
const HAND_AUTHORED_LIBRARIES = handAuthoredPublisherNames();

// "micro" publishes the generated micro-profiles library; "overlay" publishes
// a generated overlay library (see the 2026-07-31 note in
// hand_authored_publisher_facade_authority.test.ts). Neither is part of the
// handlib-publisher-dedup refactor, so both keep the original per-file check,
// unchanged, including its original message text (review M4).
const GENERATED_LIBRARY_PUBLISHERS = ["micro", "overlay"];

/**
 * The substantive property: the compile gate must run before publish, with
 * no redundant chart probe between them. `subjectLabel` is the exact text an
 * operator reads in a failure message — kept a parameter (review M4) rather
 * than derived inside the function, so restoring "micro"/"overlay"'s
 * original `tv_publish_<name>_library.ts ...` wording does not require a
 * second, near-duplicate copy of this function for the shared-module case,
 * which uses a different label.
 */
function assertDelegatesChartGateToPublish(subjectLabel: string, source: string): void {
  const compileGate = source.indexOf("await assertNoVisibleCompileError(");
  const publishCall = source.indexOf("await publishPrivateScript(", compileGate);

  assert.ok(
    compileGate >= 0 && publishCall > compileGate,
    `${subjectLabel} must retain its compile gate before publishing`,
  );
  assert.doesNotMatch(
    source.slice(compileGate, publishCall),
    /addCurrentScriptToChart\(/,
    `${subjectLabel} must not run the redundant pre-publish `
    + "chart probe; publishPrivateScript owns the hard chart gate",
  );
}

/**
 * The delegation contract a converted wrapper must satisfy (review C1 fix).
 * Mirrors assertDelegatesToSharedFacadeAuthority in
 * hand_authored_publisher_facade_authority.test.ts, which documents the four
 * reviewer probes this closes: a structural import binding, an actual
 * call-and-return site, and the absence of every inline publish primitive —
 * all three required together, since a delegation check that only proves
 * "reaches the shared module" cannot tell "converted" from "converted AND
 * still fat".
 */
function assertDelegatesToSharedChartGate(name: string, source: string): void {
  assert.ok(
    /import\s*\{[^}]*\brunHandLibPublish\b[^}]*\}\s*\n?\s*from ["'][^"']*tv_publish_hand_lib\.js["']/.test(source),
    `${name}: must structurally import { runHandLibPublish } from the shared module`,
  );
  assert.ok(
    /return runHandLibPublish\(/.test(source),
    `${name}: must call and return runHandLibPublish(...) from its CLI entry point`,
  );
  for (const inlinePrimitive of ["newTradingViewSession(", "publishPrivateScript(", "addCurrentScriptToChart("]) {
    assert.equal(
      source.includes(inlinePrimitive),
      false,
      `${name}: a converted wrapper must not also carry inline publish logic (found ${inlinePrimitive})`,
    );
  }
}

for (const name of GENERATED_LIBRARY_PUBLISHERS) {
  test(`tv_publish_${name}_library delegates the chart gate to publishPrivateScript`, () => {
    const source = fs.readFileSync(
      path.join(_scriptsDir, `tv_publish_${name}_library.ts`),
      "utf-8",
    );
    assertDelegatesChartGateToPublish(`tv_publish_${name}_library.ts`, source);
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
      // Converted: see assertDelegatesToSharedChartGate's own doc comment
      // for what "reaches" now actually requires.
      assertDelegatesToSharedChartGate(name, source);
    } else {
      // Not yet converted by this refactor: still owns the sequencing
      // inline, same contract (and message wording) as before the migration.
      assertDelegatesChartGateToPublish(`tv_publish_${name}_library.ts`, source);
    }
  });
}

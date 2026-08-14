import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { HAND_LIBS } from "../../../scripts/tv_publish_hand_authored_libraries.js";

// #3603/#3606 follow-up: the pine-facade filter=published listing is the
// authoritative published-version source. #3603 wired it into the micro
// publisher; #3606 hit the gap manually — both hand-lib publishers exited rc=1
// `version_mode=not_verified` DESPITE a successful publish because the
// facade-authoritative verification existed ONLY in micro. This contract test
// pins the facade wiring into every hand-authored publisher so it cannot
// silently regress and reopen the "successful publish reads as a failure" gap.
//
// 2026-08-14 (handlib-publisher-dedup): the ten hand-authored libraries are
// being converted, one at a time, from a self-contained ~419-line file into a
// thin descriptor wrapper over the shared `runHandLibPublish` body in
// automation/tradingview/lib/tv_publish_hand_lib.ts. Once converted, the
// facade wiring this test protects no longer lives in the wrapper's own
// source — it lives in the shared module. Folding the ten into a single
// "check the shared module" branch would have silently stopped covering the
// nine still-unconverted publishers, which is exactly the kind of regression
// this file exists to catch. So each of the ten is now checked against
// whichever place it actually keeps the property: the original per-file
// check for a publisher that has not converted yet, or a delegation check
// for one that has — backed by one assertion that the shared module itself
// still carries the substantive property. "overlay" (a GENERATED library,
// see the 2026-07-31 note below) is not part of this refactor and keeps its
// original, unmodified per-file check.
//
// 2026-08-14 fix round 1 (review C1): the first cut of the delegation branch
// selected on `source.includes("runHandLibPublish(")` and, once selected,
// asserted only `/from [...]tv_publish_hand_lib\.js/.test(source)` — both raw
// text scans over the WHOLE file, blind to comments, string literals, and
// type-only imports. A sandboxed reviewer proved four ways through it without
// real delegation: the marker sitting in a `//` comment with a `return 0;`
// body; a type-only `import { type HandLibDescriptor }` plus a dead marker
// comment; both strings only inside a string literal; and the one that
// actually matters — a file that DOES call runHandLibPublish AND ALSO still
// carries its own addCurrentScriptToChart/publishPrivateScript inline path
// with zero facade wiring (a half-migrated wrapper). See
// assertDelegatesToSharedFacadeAuthority below for the fix: it requires a
// structural import binding, a literal call-and-return site, AND the absence
// of every inline publish primitive — a delegation check that does not also
// assert thin-ness cannot tell "converted" from "converted AND still fat".
//
// 2026-08-14 fix round 1 (review I2): the pre-verification throw statement's
// exact text is now a parameter of assertWiresFacadeAuthority instead of one
// regex accepting both the pre-refactor shape and the shared module's
// restated shape. "overlay" (still self-contained) keeps the ORIGINAL literal
// string; only the shared-module assertion uses the module's actual shape.
// Folding both into one alternation let a corrupted overlay accept the shape
// only the shared module is supposed to have — proven: rewriting overlay's
// throw to the `versionAcceptance.accepted` shape passed the widened check
// and failed the original, unwidened one it was supposed to still satisfy.
//
// 2026-08-14 fix round 1 (review I3): HAND_AUTHORED_LIBRARIES below is
// DERIVED from HAND_LIBS (scripts/tv_publish_hand_authored_libraries.ts) —
// it was a hand-copied literal in the first cut, which is what let it omit
// "bus" and "engine" unnoticed. HAND_LIBS is itself kept complete by
// tests/test_pine_handlib_publisher_inventory.py's
// test_every_smcpp_library_is_in_hand_libs, so an eleventh hand-authored
// library now shows up here automatically instead of landing unguarded.

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

// 2026-07-31: "overlay" was missing. It publishes a GENERATED library, so it
// fell outside both facade fixes (#3603 micro, #3606 hand-authored) and
// outside this guard — the one whose whole purpose is that the wiring "cannot
// silently regress". With no facade call its exactVersionVerified reduced to
// `details.version === details.version` (the --version default is 1 and the
// publishing workflow never passes the flag), so a "Nothing to update" dialog
// was enough for publishStatus "published". The list is about which
// publishers must be facade-authoritative, not about who hand-wrote the Pine.
// "overlay" is not part of the handlib-publisher-dedup refactor (it stays a
// self-contained file, same as "micro"), so it keeps the original per-file
// source check unchanged rather than moving into the shared-module branch.
const GENERATED_LIBRARY_PUBLISHERS = ["overlay"];

// The pre-refactor throw statement, byte-identical to what every
// self-contained publisher (converted or not) still carries. "overlay" and
// the not-yet-converted hand-authored publishers are checked against this
// exact string (review I2) — not a pattern that also accepts the shared
// module's restated shape.
const ORIGINAL_THROW_STATEMENT = "if (!exactScriptVerified || !exactVersionVerified) {";
// The shared module (automation/tradingview/lib/tv_publish_hand_lib.ts)
// restates the same gate using the named acceptance-rule result instead of
// the inline boolean. Only the shared-module assertion below uses this.
const SHARED_MODULE_THROW_STATEMENT = "if (!exactScriptVerified || !versionAcceptance.accepted) {";

/**
 * The substantive property: facade wiring, checked against arbitrary source
 * text. `throwStatement` is the exact pre-verification-throw text this
 * particular source is expected to carry — kept a parameter (review I2) so a
 * shape change in ONE population (the shared module) cannot silently loosen
 * the check for a population that is supposed to still carry the original,
 * unwidened literal.
 */
function assertWiresFacadeAuthority(name: string, source: string, throwStatement: string): void {
  // Imports the authoritative helper (never the deprecated saved-listing one).
  assert.ok(
    source.includes("fetchPublishedLibraryVersionViaFacade"),
    `${name}: must import fetchPublishedLibraryVersionViaFacade`,
  );
  assert.equal(
    source.includes("fetchSavedScriptVersionViaFacade"),
    false,
    `${name}: must not use the deprecated saved-listing helper`,
  );

  // Probes THIS script's published version and lets the facade override the
  // UI-text evidence before the exact-verification throw.
  assert.ok(
    source.includes("fetchPublishedLibraryVersionViaFacade(session.page, details.scriptName)"),
    `${name}: must probe details.scriptName`,
  );
  assert.ok(
    source.includes('versionVerificationMode = "facade_list"'),
    `${name}: facade hit must set versionVerificationMode = "facade_list"`,
  );

  // The override must sit BEFORE the exact-verification throw, or it cannot
  // rescue a successful-but-unverified publish.
  const facadeIdx = source.indexOf("const facadeVersion = await fetchPublishedLibraryVersionViaFacade");
  const throwIdx = source.indexOf(throwStatement);
  assert.ok(facadeIdx > 0, `${name}: facade override block missing`);
  assert.ok(throwIdx > 0, `${name}: verification throw missing`);
  assert.ok(facadeIdx < throwIdx, `${name}: facade override must precede the verification throw`);

  // "facade_list" must be a legal VersionVerificationMode value.
  assert.ok(
    /type VersionVerificationMode =[^;]*"facade_list"/.test(source),
    `${name}: VersionVerificationMode union must include "facade_list"`,
  );
}

/**
 * The delegation contract a converted wrapper must satisfy (review C1 fix).
 * All three conjuncts are required together:
 *   1. a STRUCTURAL import binding — `import { ... runHandLibPublish ... }
 *      from ".../tv_publish_hand_lib.js"` — not a bare mention anywhere in
 *      the file (a comment, a string literal, or a type-only import all fail
 *      this).
 *   2. an actual call-and-return site — `return runHandLibPublish(` — not
 *      just an import.
 *   3. the ABSENCE of every inline publish primitive
 *      (newTradingViewSession(, publishPrivateScript(,
 *      addCurrentScriptToChart() — this is what catches a half-migrated
 *      wrapper that genuinely calls runHandLibPublish but ALSO still carries
 *      its own inline publish path with zero facade wiring; a delegation
 *      check that only proves "reaches the shared module" cannot tell
 *      "converted" from "converted AND still fat".
 */
function assertDelegatesToSharedFacadeAuthority(name: string, source: string): void {
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
  test(`tv_publish_${name}_library wires facade-authoritative version verification`, () => {
    const source = fs.readFileSync(
      path.join(_scriptsDir, `tv_publish_${name}_library.ts`),
      "utf-8",
    );
    assertWiresFacadeAuthority(name, source, ORIGINAL_THROW_STATEMENT);
  });
}

test("the shared hand-lib publish body wires facade-authoritative version verification", () => {
  const source = fs.readFileSync(_sharedModulePath, "utf-8");
  assertWiresFacadeAuthority("tv_publish_hand_lib (shared module)", source, SHARED_MODULE_THROW_STATEMENT);
});

for (const name of HAND_AUTHORED_LIBRARIES) {
  test(`tv_publish_${name}_library reaches facade-authoritative version verification`, () => {
    const source = fs.readFileSync(
      path.join(_scriptsDir, `tv_publish_${name}_library.ts`),
      "utf-8",
    );
    if (/\brunHandLibPublish\(/.test(source)) {
      // Converted: see assertDelegatesToSharedFacadeAuthority's own doc
      // comment for what "reaches" now actually requires.
      assertDelegatesToSharedFacadeAuthority(name, source);
    } else {
      // Not yet converted by this refactor: still owns the logic inline,
      // same contract as before the migration.
      assertWiresFacadeAuthority(name, source, ORIGINAL_THROW_STATEMENT);
    }
  });
}

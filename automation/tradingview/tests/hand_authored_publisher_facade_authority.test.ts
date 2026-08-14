import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

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
// (does it reach `runHandLibPublish`, i.e. does the property reach it
// transitively) for one that has — backed by one assertion that the shared
// module itself still carries the substantive property. "overlay" (a
// GENERATED library, see the 2026-07-31 note below) is not part of this
// refactor and keeps its original, unmodified per-file check.
//
// Noticed and NOT fixed here (out of scope for the guard migration, filed in
// the task report instead): the original HAND_AUTHORED_PUBLISHERS list below
// omitted "bus" and "engine" — two of the ten hand-authored libraries per
// scripts/tv_publish_hand_authored_libraries.ts's HAND_LIBS table. The new
// HAND_AUTHORED_LIBRARIES list is sourced from that table and covers all ten,
// closing that pre-existing gap as a side effect of the migration.

const _dir = path.dirname(fileURLToPath(import.meta.url));
const _scriptsDir = path.resolve(_dir, "..", "..", "..", "scripts");
const _sharedModulePath = path.resolve(_dir, "..", "lib", "tv_publish_hand_lib.ts");

// The ten hand-authored libraries this refactor is converting to descriptor
// wrappers over the shared publish body (see HAND_LIBS in
// scripts/tv_publish_hand_authored_libraries.ts).
const HAND_AUTHORED_LIBRARIES = [
  "utils",
  "draw",
  "core_types",
  "lifecycle",
  "observability",
  "context_resolvers",
  "profile_engine",
  "context_engine",
  "bus",
  "engine",
];

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

/** The substantive property: facade wiring, checked against arbitrary source text. */
function assertWiresFacadeAuthority(name: string, source: string): void {
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
  // rescue a successful-but-unverified publish. The pre-refactor shape threw
  // on `!exactScriptVerified || !exactVersionVerified`; the shared module
  // (see tv_publish_hand_lib.ts) restates the same gate as
  // `!exactScriptVerified || !versionAcceptance.accepted`. Either counts.
  const facadeIdx = source.indexOf("const facadeVersion = await fetchPublishedLibraryVersionViaFacade");
  const throwIdx = source.search(/if \(!exactScriptVerified \|\| !(exactVersionVerified|versionAcceptance\.accepted)\) \{/);
  assert.ok(facadeIdx > 0, `${name}: facade override block missing`);
  assert.ok(throwIdx > 0, `${name}: verification throw missing`);
  assert.ok(facadeIdx < throwIdx, `${name}: facade override must precede the verification throw`);

  // "facade_list" must be a legal VersionVerificationMode value.
  assert.ok(
    /type VersionVerificationMode =[^;]*"facade_list"/.test(source),
    `${name}: VersionVerificationMode union must include "facade_list"`,
  );
}

for (const name of GENERATED_LIBRARY_PUBLISHERS) {
  test(`tv_publish_${name}_library wires facade-authoritative version verification`, () => {
    const source = fs.readFileSync(
      path.join(_scriptsDir, `tv_publish_${name}_library.ts`),
      "utf-8",
    );
    assertWiresFacadeAuthority(name, source);
  });
}

test("the shared hand-lib publish body wires facade-authoritative version verification", () => {
  const source = fs.readFileSync(_sharedModulePath, "utf-8");
  assertWiresFacadeAuthority("tv_publish_hand_lib (shared module)", source);
});

for (const name of HAND_AUTHORED_LIBRARIES) {
  test(`tv_publish_${name}_library reaches facade-authoritative version verification`, () => {
    const source = fs.readFileSync(
      path.join(_scriptsDir, `tv_publish_${name}_library.ts`),
      "utf-8",
    );
    if (/\brunHandLibPublish\(/.test(source)) {
      // Converted: the substantive property is checked once, above, against
      // the shared module. This publisher only needs to prove it actually
      // reaches that module rather than silently growing its own inline
      // publish path again.
      assert.ok(
        /from ["'][^"']*tv_publish_hand_lib\.js["']/.test(source),
        `${name}: calls runHandLibPublish but does not import it from the shared module`,
      );
    } else {
      // Not yet converted by this refactor: still owns the logic inline,
      // same contract as before the migration.
      assertWiresFacadeAuthority(name, source);
    }
  });
}

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

const _dir = path.dirname(fileURLToPath(import.meta.url));
const _scriptsDir = path.resolve(_dir, "..", "..", "..", "scripts");

const HAND_AUTHORED_PUBLISHERS = [
  "utils",
  "draw",
  "core_types",
  "lifecycle",
  "observability",
  "context_resolvers",
  "profile_engine",
  "context_engine",
];

for (const name of HAND_AUTHORED_PUBLISHERS) {
  test(`tv_publish_${name}_library wires facade-authoritative version verification`, () => {
    const source = fs.readFileSync(
      path.join(_scriptsDir, `tv_publish_${name}_library.ts`),
      "utf-8",
    );

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
    const throwIdx = source.indexOf("if (!exactScriptVerified || !exactVersionVerified) {");
    assert.ok(facadeIdx > 0, `${name}: facade override block missing`);
    assert.ok(throwIdx > 0, `${name}: verification throw missing`);
    assert.ok(facadeIdx < throwIdx, `${name}: facade override must precede the verification throw`);

    // "facade_list" must be a legal VersionVerificationMode value.
    assert.ok(
      /type VersionVerificationMode =[^;]*"facade_list"/.test(source),
      `${name}: VersionVerificationMode union must include "facade_list"`,
    );
  });
}

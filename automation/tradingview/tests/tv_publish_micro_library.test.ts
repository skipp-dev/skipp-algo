import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  resolvePreMutationOpenGate,
  resolveAuthoritativeReleaseTarget,
  resolvePublishPipelinePhase,
  readProductCutSummary,
  resolvePublishReportState,
  shouldPromoteNoChangeVersionEvidence,
  shouldPromotePublishConfirmationVersionEvidence,
  shouldReopenPublishedScriptAfterPublish,
  verifyPublishContract,
} from "../../../scripts/tv_publish_micro_library.js";

const _dir = path.dirname(fileURLToPath(import.meta.url));
const _publisherPath = path.resolve(_dir, "..", "..", "..", "scripts", "tv_publish_micro_library.ts");

test("facade-published version is the authoritative release target", () => {
  assert.deepEqual(resolveAuthoritativeReleaseTarget({
    libraryOwner: "owner_a",
    libraryName: "smc_micro_profiles_generated",
    libraryVersion: 1,
  }, 153), {
    expectedVersion: 153,
    expectedImportPath: "owner_a/smc_micro_profiles_generated/153",
  });
});

function buildGeneratedLibraryManifest(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    library_name: "smc_micro_profiles_generated",
    library_owner: "owner_a",
    library_version: 2,
    recommended_import_path: "owner_a/smc_micro_profiles_generated/2",
    core_import_snippet: "pine/generated/smc_micro_profiles_core_import_snippet.pine",
    pine_library: "pine/generated/smc_micro_profiles_generated.pine",
    input_path: "data/output/microstructure_features_2026-03-24.csv",
    universe_size: 240,
    event_risk_source: "smc_event_risk_builder",
    deprecated_field_policy: {
      mode: "compatibility_only",
      preferred_field_version: "v8.0a",
      extension_allowed: false,
      sunset_date: "2026-05-14",
      sunset_action: "remove_from_export",
      deprecated_groups: [],
    },
    productivity_gate: {
      publish_ready: true,
      blocking_reasons: [],
      fixture_input_detected: false,
      default_event_risk_detected: false,
      placeholder_symbols: [],
    },
    ...overrides,
  };
}

test("publish aborts before editor mutation when exact open gate fails", () => {
  assert.deepEqual(resolvePreMutationOpenGate({
    openExisting: true,
    openGateVerified: false,
    scriptName: "smc_micro_profiles_generated",
  }), {
    openGateAttempted: true,
    openGateVerified: false,
    allowEditorMutation: false,
    error: "Could not open existing TradingView script: smc_micro_profiles_generated. Aborted before first editor mutation at the exact-open gate. Rerun with --no-open-existing only if a fresh untitled draft is intended.",
  });
});

test("no-open-existing remains an explicit bypass of the pre-mutation open gate", () => {
  assert.deepEqual(resolvePreMutationOpenGate({
    openExisting: false,
    openGateVerified: false,
    scriptName: "smc_micro_profiles_generated",
  }), {
    openGateAttempted: false,
    openGateVerified: false,
    allowEditorMutation: true,
    error: null,
  });
});

test("existing library publishes update the current script instead of requiring a new title", () => {
  const source = fs.readFileSync(_publisherPath, "utf-8");
  const updateModePattern = /publishMode:\s*openedExistingScript\s*\?\s*"update_existing"\s*:\s*"auto"/g;

  assert.equal(
    source.match(updateModePattern)?.length,
    2,
    "the initial publish and its retry must both select update_existing after the exact-open gate",
  );
});

test("early open gate fail resolves to not_verified instead of manual publish required", () => {
  assert.deepEqual(resolvePublishReportState({
    openGateAttempted: true,
    publishAttempted: false,
    identityVerificationMode: "not_verified",
    versionVerificationMode: "not_verified",
    publishedVersion: null,
    expectedVersion: 7,
    repoCoreValidationOk: false,
  }), {
    ok: false,
    publishOk: false,
    publishStatus: "not_verified",
  });
});

test("publish report success requires exact identity and approved version verification", () => {
  assert.deepEqual(resolvePublishReportState({
    openGateAttempted: true,
    publishAttempted: true,
    identityVerificationMode: "script_context",
    versionVerificationMode: "version_context",
    publishedVersion: 7,
    expectedVersion: 7,
    repoCoreValidationOk: true,
  }), {
    ok: true,
    publishOk: true,
    publishStatus: "published",
  });

  assert.deepEqual(resolvePublishReportState({
    openGateAttempted: true,
    publishAttempted: true,
    identityVerificationMode: "script_context",
    versionVerificationMode: "idempotent_no_change",
    publishedVersion: 7,
    expectedVersion: 7,
    repoCoreValidationOk: true,
  }), {
    ok: true,
    publishOk: true,
    publishStatus: "published",
  });

  assert.deepEqual(resolvePublishReportState({
    openGateAttempted: true,
    publishAttempted: true,
    identityVerificationMode: "script_context",
    versionVerificationMode: "publish_confirmation",
    publishedVersion: 7,
    expectedVersion: 7,
    repoCoreValidationOk: true,
  }), {
    ok: true,
    publishOk: true,
    publishStatus: "published",
  });

  assert.deepEqual(resolvePublishReportState({
    openGateAttempted: true,
    publishAttempted: true,
    identityVerificationMode: "script_context",
    versionVerificationMode: "body_fallback",
    publishedVersion: 7,
    expectedVersion: 7,
    repoCoreValidationOk: true,
  }), {
    ok: false,
    publishOk: false,
    publishStatus: "not_verified",
  });
});

test("idempotent no-change skips reopen only when exact verification already exists", () => {
  assert.equal(shouldReopenPublishedScriptAfterPublish({
    publishNoChangeDetected: true,
    exactScriptVerified: true,
    exactVersionVerified: true,
  }), false);

  assert.equal(shouldReopenPublishedScriptAfterPublish({
    publishNoChangeDetected: true,
    exactScriptVerified: false,
    exactVersionVerified: true,
  }), true);

  assert.equal(shouldReopenPublishedScriptAfterPublish({
    publishNoChangeDetected: true,
    exactScriptVerified: true,
    exactVersionVerified: false,
  }), true);

  assert.equal(shouldReopenPublishedScriptAfterPublish({
    publishNoChangeDetected: false,
    exactScriptVerified: true,
    exactVersionVerified: true,
  }), true);
});

test("no-change version promotion accepts exact script identity without import-path body evidence", () => {
  assert.equal(shouldPromoteNoChangeVersionEvidence({
    publishNoChangeDetected: true,
    identityVerificationMode: "script_context",
    versionVerificationMode: "not_verified",
    bodyText: "publish dialog without import path",
    expectedImportPath: "owner_a/smc_micro_profiles_generated/2",
  }), true);
});

test("no-change version promotion still accepts import-path body evidence without exact identity", () => {
  assert.equal(shouldPromoteNoChangeVersionEvidence({
    publishNoChangeDetected: true,
    identityVerificationMode: "not_verified",
    versionVerificationMode: "not_verified",
    bodyText: "visible import owner_a/smc_micro_profiles_generated/2 as mp",
    expectedImportPath: "owner_a/smc_micro_profiles_generated/2",
  }), true);
});

test("no-change version promotion rejects empty expected import path evidence", () => {
  assert.equal(shouldPromoteNoChangeVersionEvidence({
    publishNoChangeDetected: true,
    identityVerificationMode: "not_verified",
    versionVerificationMode: "not_verified",
    bodyText: "visible import owner_a/smc_micro_profiles_generated/2 as mp",
    expectedImportPath: "",
  }), false);
});

test("no-change version promotion rejects import-path version substring evidence", () => {
  assert.equal(shouldPromoteNoChangeVersionEvidence({
    publishNoChangeDetected: true,
    identityVerificationMode: "not_verified",
    versionVerificationMode: "not_verified",
    bodyText: "visible import owner_a/smc_micro_profiles_generated/20 as mp",
    expectedImportPath: "owner_a/smc_micro_profiles_generated/2",
  }), false);
});

test("no-change version promotion rejects missing identity and missing import-path evidence", () => {
  assert.equal(shouldPromoteNoChangeVersionEvidence({
    publishNoChangeDetected: true,
    identityVerificationMode: "not_verified",
    versionVerificationMode: "not_verified",
    bodyText: "no exact publish evidence here",
    expectedImportPath: "owner_a/smc_micro_profiles_generated/2",
  }), false);
});

test("publish confirmation promotion requires closed surface, exact identity, and matching manifest version", () => {
  assert.equal(shouldPromotePublishConfirmationVersionEvidence({
    publishConfirmed: true,
    publishSurfaceClosedAfterConfirm: true,
    publishNoChangeDetected: false,
    identityVerificationMode: "script_context",
    versionVerificationMode: "not_verified",
    expectedImportPath: "owner_a/smc_micro_profiles_generated/2",
    expectedVersion: 2,
  }), true);

  assert.equal(shouldPromotePublishConfirmationVersionEvidence({
    publishConfirmed: true,
    publishSurfaceClosedAfterConfirm: false,
    publishNoChangeDetected: false,
    identityVerificationMode: "script_context",
    versionVerificationMode: "not_verified",
    expectedImportPath: "owner_a/smc_micro_profiles_generated/2",
    expectedVersion: 2,
  }), false);

  assert.equal(shouldPromotePublishConfirmationVersionEvidence({
    publishConfirmed: true,
    publishSurfaceClosedAfterConfirm: true,
    publishNoChangeDetected: false,
    identityVerificationMode: "not_verified",
    versionVerificationMode: "not_verified",
    expectedImportPath: "owner_a/smc_micro_profiles_generated/2",
    expectedVersion: 2,
  }), false);

  assert.equal(shouldPromotePublishConfirmationVersionEvidence({
    publishConfirmed: true,
    publishSurfaceClosedAfterConfirm: true,
    publishNoChangeDetected: true,
    identityVerificationMode: "script_context",
    versionVerificationMode: "not_verified",
    expectedImportPath: "owner_a/smc_micro_profiles_generated/2",
    expectedVersion: 2,
  }), false);

  assert.equal(shouldPromotePublishConfirmationVersionEvidence({
    publishConfirmed: true,
    publishSurfaceClosedAfterConfirm: true,
    publishNoChangeDetected: false,
    identityVerificationMode: "script_context",
    versionVerificationMode: "not_verified",
    expectedImportPath: "owner_a/smc_micro_profiles_generated/3",
    expectedVersion: 2,
  }), false);

  assert.equal(shouldPromotePublishConfirmationVersionEvidence({
    publishConfirmed: true,
    publishSurfaceClosedAfterConfirm: true,
    publishNoChangeDetected: false,
    identityVerificationMode: "script_context",
    versionVerificationMode: "not_verified",
    expectedImportPath: "owner_a/smc_micro_profiles_generated/12",
    expectedVersion: 2,
  }), false);
});

test("product-cut summary accepts an intentionally empty deprecated group list", () => {
  const summary = readProductCutSummary();

  assert.equal(summary.deprecatedFieldPolicy.mode, "compatibility_only");
  assert.equal(summary.deprecatedFieldPolicy.extensionAllowed, false);
  assert.deepEqual(summary.deprecatedFieldPolicy.deprecatedGroups, []);
  assert.ok(summary.mainlineFiles.length > 0);
  assert.ok(summary.contracts.engine.length > 0);
});

test("body fallback version evidence never upgrades publish status even with fallback version present", () => {
  assert.deepEqual(resolvePublishReportState({
    openGateAttempted: true,
    publishAttempted: true,
    identityVerificationMode: "script_context",
    versionVerificationMode: "body_fallback",
    publishedVersion: 7,
    expectedVersion: 7,
    repoCoreValidationOk: true,
  }), {
    ok: false,
    publishOk: false,
    publishStatus: "not_verified",
  });
});

test("manual publish semantics remain explicit when no open gate or publish attempt happened", () => {
  assert.deepEqual(resolvePublishReportState({
    openGateAttempted: false,
    publishAttempted: false,
    identityVerificationMode: "not_verified",
    versionVerificationMode: "not_verified",
    publishedVersion: null,
    expectedVersion: 7,
    repoCoreValidationOk: false,
  }), {
    ok: false,
    publishOk: false,
    publishStatus: "manual_publish_required",
  });
});

test("publish report keeps published status but overall ok false when repo core validation fails", () => {
  assert.deepEqual(resolvePublishReportState({
    openGateAttempted: true,
    publishAttempted: true,
    identityVerificationMode: "script_context",
    versionVerificationMode: "version_context",
    publishedVersion: 7,
    expectedVersion: 7,
    repoCoreValidationOk: false,
  }), {
    ok: false,
    publishOk: true,
    publishStatus: "published",
  });
});

test("official TS publish contract rejects duplicate real alias block", () => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "tv-publish-contract-"));
  const pineDir = path.join(tempDir, "pine", "generated");
  fs.mkdirSync(pineDir, { recursive: true });

  const manifestPath = path.join(pineDir, "smc_micro_profiles_generated.json");
  const snippetPath = path.join(pineDir, "smc_micro_profiles_core_import_snippet.pine");
  const libraryPath = path.join(pineDir, "smc_micro_profiles_generated.pine");
  const corePath = path.join(tempDir, "SMC_Long_Dip_Suite.pine");

  fs.writeFileSync(manifestPath, JSON.stringify(buildGeneratedLibraryManifest()), "utf-8");
  fs.writeFileSync(snippetPath, [
    "import owner_a/smc_micro_profiles_generated/2 as mp",
    "string clean_reclaim_tickers_effective = mp.CLEAN_RECLAIM_TICKERS",
    "string open_reclaim_tickers_effective = mp.OPEN_RECLAIM_TICKERS",
    "",
  ].join("\n"), "utf-8");
  fs.writeFileSync(libraryPath, "//@version=6\nlibrary(\"smc_micro_profiles_generated\")\n", "utf-8");
  fs.writeFileSync(corePath, [
    "//@version=6",
    "import owner_a/smc_micro_profiles_generated/2 as mp",
    "string clean_reclaim_tickers_effective = mp.CLEAN_RECLAIM_TICKERS",
    "string open_reclaim_tickers_effective = mp.OPEN_RECLAIM_TICKERS",
    "string spacer = \"ok\"",
    "string clean_reclaim_tickers_effective = mp.CLEAN_RECLAIM_TICKERS",
    "string open_reclaim_tickers_effective = mp.OPEN_RECLAIM_TICKERS",
    "",
  ].join("\n"), "utf-8");

  assert.throws(
    () => verifyPublishContract(manifestPath, corePath),
    /exactly once as real contiguous code/,
  );
});

test("official TS publish contract accepts a newer published core pin", () => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "tv-publish-version-skew-"));
  const pineDir = path.join(tempDir, "pine", "generated");
  fs.mkdirSync(pineDir, { recursive: true });
  const manifestPath = path.join(pineDir, "smc_micro_profiles_generated.json");
  const snippetPath = path.join(pineDir, "smc_micro_profiles_core_import_snippet.pine");
  const libraryPath = path.join(pineDir, "smc_micro_profiles_generated.pine");
  const corePath = path.join(tempDir, "SMC_Long_Dip_Suite.pine");
  fs.writeFileSync(manifestPath, JSON.stringify(buildGeneratedLibraryManifest({
    library_version: 1,
    recommended_import_path: "owner_a/smc_micro_profiles_generated/1",
  })), "utf-8");
  fs.writeFileSync(snippetPath, "import owner_a/smc_micro_profiles_generated/1 as mp\nstring value = mp.VALUE\n", "utf-8");
  fs.writeFileSync(libraryPath, "//@version=6\nlibrary(\"smc_micro_profiles_generated\")\n", "utf-8");
  fs.writeFileSync(corePath, "//@version=6\nimport owner_a/smc_micro_profiles_generated/152 as mp\nstring value = mp.VALUE\n", "utf-8");
  assert.equal(verifyPublishContract(manifestPath, corePath).alias, "mp");
});

test("official TS publish contract rejects non-productive generated source", () => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "tv-publish-productivity-"));
  const pineDir = path.join(tempDir, "pine", "generated");
  fs.mkdirSync(pineDir, { recursive: true });

  const manifestPath = path.join(pineDir, "smc_micro_profiles_generated.json");
  const snippetPath = path.join(pineDir, "smc_micro_profiles_core_import_snippet.pine");
  const libraryPath = path.join(pineDir, "smc_micro_profiles_generated.pine");
  const corePath = path.join(tempDir, "SMC_Long_Dip_Suite.pine");

  fs.writeFileSync(manifestPath, JSON.stringify(buildGeneratedLibraryManifest({
    input_path: "tests/fixtures/seed_base_snapshot.csv",
    universe_size: 3,
    event_risk_source: "defaults",
    productivity_gate: {
      publish_ready: false,
      blocking_reasons: ["fixture_input", "default_event_risk", "placeholder_symbols"],
      fixture_input_detected: true,
      default_event_risk_detected: true,
      placeholder_symbols: ["AAA", "BBB", "CCC"],
    },
  })), "utf-8");
  fs.writeFileSync(snippetPath, [
    "import owner_a/smc_micro_profiles_generated/2 as mp",
    "string clean_reclaim_tickers_effective = mp.CLEAN_RECLAIM_TICKERS",
    "",
  ].join("\n"), "utf-8");
  fs.writeFileSync(libraryPath, "//@version=6\nlibrary(\"smc_micro_profiles_generated\")\n", "utf-8");
  fs.writeFileSync(corePath, [
    "//@version=6",
    "import owner_a/smc_micro_profiles_generated/2 as mp",
    "string clean_reclaim_tickers_effective = mp.CLEAN_RECLAIM_TICKERS",
    "",
  ].join("\n"), "utf-8");

  assert.throws(
    () => verifyPublishContract(manifestPath, corePath),
    /not publish-ready: fixture_input, default_event_risk, placeholder_symbols/,
  );
});

test("pipeline phase resolves to completed when ok is true", () => {
  assert.deepEqual(resolvePublishPipelinePhase({
    ok: true,
    contractOk: true,
    openGateAttempted: true,
    openGateVerified: true,
    publishAttempted: true,
    identityVerificationMode: "script_context",
    versionVerificationMode: "version_context",
    repoCoreValidationOk: true,
  }), {
    completedPhase: "completed",
    failedAtStep: null,
    resumeFrom: null,
  });
});

test("pipeline phase detects contract validation failure", () => {
  const phase = resolvePublishPipelinePhase({
    ok: false,
    contractOk: false,
    openGateAttempted: false,
    openGateVerified: false,
    publishAttempted: false,
    identityVerificationMode: "not_verified",
    versionVerificationMode: "not_verified",
    repoCoreValidationOk: false,
  });
  assert.equal(phase.failedAtStep, "contract_validation");
  assert.equal(phase.resumeFrom, "contract_validation");
});

test("pipeline phase detects open gate failure", () => {
  const phase = resolvePublishPipelinePhase({
    ok: false,
    contractOk: true,
    openGateAttempted: true,
    openGateVerified: false,
    publishAttempted: false,
    identityVerificationMode: "not_verified",
    versionVerificationMode: "not_verified",
    repoCoreValidationOk: false,
  });
  assert.equal(phase.failedAtStep, "open_gate");
  assert.equal(phase.resumeFrom, "open_gate");
});

test("pipeline phase detects identity verification failure after publish", () => {
  const phase = resolvePublishPipelinePhase({
    ok: false,
    contractOk: true,
    openGateAttempted: true,
    openGateVerified: true,
    publishAttempted: true,
    identityVerificationMode: "not_verified",
    versionVerificationMode: "not_verified",
    repoCoreValidationOk: false,
  });
  assert.equal(phase.failedAtStep, "identity_verification");
  assert.equal(phase.resumeFrom, "publish");
});

test("pipeline phase detects version verification failure with identity ok", () => {
  const phase = resolvePublishPipelinePhase({
    ok: false,
    contractOk: true,
    openGateAttempted: true,
    openGateVerified: true,
    publishAttempted: true,
    identityVerificationMode: "script_context",
    versionVerificationMode: "not_verified",
    repoCoreValidationOk: false,
  });
  assert.equal(phase.failedAtStep, "version_verification");
  assert.equal(phase.resumeFrom, "publish");
  assert.equal(phase.completedPhase, "identity_verification");
});

test("pipeline phase detects core preflight failure after successful publish", () => {
  const phase = resolvePublishPipelinePhase({
    ok: false,
    contractOk: true,
    openGateAttempted: true,
    openGateVerified: true,
    publishAttempted: true,
    identityVerificationMode: "script_context",
    versionVerificationMode: "version_context",
    repoCoreValidationOk: false,
  });
  assert.equal(phase.failedAtStep, "core_preflight");
  assert.equal(phase.resumeFrom, "core_preflight");
  assert.equal(phase.completedPhase, "version_verification");
});

// --- stale version sentinel -------------------------------------------------
//
// The promote corroborates `expectedVersion` against `expectedImportPath` — but
// both come from the SAME generated artifact, so the check compared 1 against 1
// and could never fail. The generator runs BEFORE the publish, so it cannot know
// the version it is about to get and regenerates `library_version: 1` every
// time; on main the consumers pin /179 while the artifact still says 1.
//
// The only real evidence is the facade probe, which is documented fail-open.
// When it fell through, the promote wrote library_release_manifest.json with
// expectedVersion 1 — replacing a correct 179 with the sentinel.

test("the stale version-1 sentinel cannot be promoted as publish confirmation", () => {
  const base = {
    publishConfirmed: true,
    publishSurfaceClosedAfterConfirm: true,
    publishNoChangeDetected: false,
    identityVerificationMode: "script_context" as const,
    versionVerificationMode: "not_verified" as const,
  };

  assert.equal(
    shouldPromotePublishConfirmationVersionEvidence({
      ...base,
      expectedImportPath: "preuss_steffen/smc_micro_profiles_generated/1",
      expectedVersion: 1,
    }),
    false,
    "version 1 is the pre-publish generator default, never a real published version",
  );

  // A genuine version still promotes.
  assert.equal(
    shouldPromotePublishConfirmationVersionEvidence({
      ...base,
      expectedImportPath: "preuss_steffen/smc_micro_profiles_generated/180",
      expectedVersion: 180,
    }),
    true,
  );
});

test("the shipped generated artifact still carries the sentinel", () => {
  // The regression guard for the premise: if this ever stops being 1, the
  // generator started learning the published version and the guard above can be
  // revisited. Until then it is load-bearing.
  const artifact = JSON.parse(
    fs.readFileSync(
      path.resolve(
        path.dirname(fileURLToPath(import.meta.url)),
        "..", "..", "..", "pine/generated/smc_micro_profiles_generated.json",
      ),
      "utf-8",
    ),
  ) as { library_version: number; recommended_import_path: string };

  assert.equal(artifact.library_version, 1);
  assert.ok(artifact.recommended_import_path.endsWith("/1"));
});

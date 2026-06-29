import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  resolvePreMutationOpenGate,
  resolvePublishPipelinePhase,
  resolvePublishReportState,
  shouldPromoteNoChangeVersionEvidence,
  shouldReopenPublishedScriptAfterPublish,
  verifyPublishContract,
} from "../../../scripts/tv_publish_micro_library.js";

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

test("publish report success requires separate identity and version verification", () => {
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

test("no-change version promotion rejects missing identity and missing import-path evidence", () => {
  assert.equal(shouldPromoteNoChangeVersionEvidence({
    publishNoChangeDetected: true,
    identityVerificationMode: "not_verified",
    versionVerificationMode: "not_verified",
    bodyText: "no exact publish evidence here",
    expectedImportPath: "owner_a/smc_micro_profiles_generated/2",
  }), false);
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
  const corePath = path.join(tempDir, "SMC_Core_Engine.pine");

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

test("official TS publish contract rejects non-productive generated source", () => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "tv-publish-productivity-"));
  const pineDir = path.join(tempDir, "pine", "generated");
  fs.mkdirSync(pineDir, { recursive: true });

  const manifestPath = path.join(pineDir, "smc_micro_profiles_generated.json");
  const snippetPath = path.join(pineDir, "smc_micro_profiles_core_import_snippet.pine");
  const libraryPath = path.join(pineDir, "smc_micro_profiles_generated.pine");
  const corePath = path.join(tempDir, "SMC_Core_Engine.pine");

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

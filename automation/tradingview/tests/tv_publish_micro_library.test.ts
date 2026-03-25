import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  resolvePreMutationOpenGate,
  resolvePublishReportState,
  verifyPublishContract,
} from "../../../scripts/tv_publish_micro_library.js";

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

test("publish report stays not_verified when repo core validation fails despite exact identity and version", () => {
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
    publishStatus: "not_verified",
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

  fs.writeFileSync(manifestPath, JSON.stringify({
    library_name: "smc_micro_profiles_generated",
    library_owner: "owner_a",
    library_version: 2,
    recommended_import_path: "owner_a/smc_micro_profiles_generated/2",
    core_import_snippet: "pine/generated/smc_micro_profiles_core_import_snippet.pine",
    pine_library: "pine/generated/smc_micro_profiles_generated.pine",
  }), "utf-8");
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
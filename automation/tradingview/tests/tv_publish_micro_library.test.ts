import assert from "node:assert/strict";
import test from "node:test";

import {
  resolvePreMutationOpenGate,
  resolvePublishReportState,
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
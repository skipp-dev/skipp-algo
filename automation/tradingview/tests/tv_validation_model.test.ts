import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  combineVerificationStatuses,
  computeTargetOverallPreflightOk,
  getRequiredLibraryReleaseManifestFields,
  getRequiredPreflightReportFields,
  getRequiredPreflightTargetFields,
  reportProvidesRepoSourceCompileEvidence,
  resolveTradingViewAuthResolution,
  statusesAllTrue,
  type LibraryReleaseManifest,
} from "../lib/tv_validation_model.js";

function makeTempDir(prefix: string): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

function writeJson(filePath: string, payload: unknown): void {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(payload, null, 2), "utf-8");
}

test("valid storage state takes precedence over persistent profile", () => {
  const tempDir = makeTempDir("tv-auth-prefer-storage-");
  const storageStatePath = path.join(tempDir, "storage-state.json");
  const profileDir = path.join(tempDir, "profile");
  fs.mkdirSync(profileDir, { recursive: true });
  writeJson(storageStatePath, {
    cookies: [{ name: "sessionid", value: "abc" }],
    origins: [],
  });

  const resolution = resolveTradingViewAuthResolution({
    TV_STORAGE_STATE: storageStatePath,
    TV_PERSISTENT_PROFILE_DIR: profileDir,
  });

  assert.equal(resolution.authMode, "storage_state");
  assert.equal(resolution.authSourcePath, storageStatePath);
  assert.equal(resolution.authReusedOk, true);
  assert.equal(resolution.fallbackUsed, false);
});

test("invalid storage state falls back to persistent profile", () => {
  const tempDir = makeTempDir("tv-auth-fallback-profile-");
  const storageStatePath = path.join(tempDir, "storage-state.json");
  const profileDir = path.join(tempDir, "profile");
  fs.mkdirSync(profileDir, { recursive: true });
  writeJson(storageStatePath, {
    cookies: [{ name: "cookiePrivacyPreferenceBannerProduction", value: "1" }],
    origins: [],
  });

  const resolution = resolveTradingViewAuthResolution({
    TV_STORAGE_STATE: storageStatePath,
    TV_PERSISTENT_PROFILE_DIR: profileDir,
  });

  assert.equal(resolution.authMode, "persistent_profile");
  assert.equal(resolution.authSourcePath, profileDir);
  assert.equal(resolution.authReusedOk, true);
  assert.equal(resolution.fallbackUsed, true);
  assert.equal(resolution.fallbackReason, "storage_state_invalid");
});

test("missing reusable auth sources resolves to fresh_login", () => {
  const resolution = resolveTradingViewAuthResolution({});

  assert.equal(resolution.authMode, "fresh_login");
  assert.equal(resolution.authSourcePath, null);
  assert.equal(resolution.authReusedOk, false);
});

test("chart-validated storage state metadata is accepted as reusable auth", () => {
  const tempDir = makeTempDir("tv-auth-chart-validated-");
  const storageStatePath = path.join(tempDir, "storage-state.json");
  writeJson(storageStatePath, {
    meta: {
      authValidatedByChartAccess: true,
      authValidatedAt: "2026-03-24T08:00:00.000Z",
      validationMode: "persistent_profile_chart_access",
      chartUrl: "https://www.tradingview.com/chart/",
    },
    cookies: [{ name: "cookiePrivacyPreferenceBannerProduction", value: "1" }],
    origins: [],
  });

  const resolution = resolveTradingViewAuthResolution({
    TV_STORAGE_STATE: storageStatePath,
  });

  assert.equal(resolution.authMode, "storage_state");
  assert.equal(resolution.authSourcePath, storageStatePath);
  assert.equal(resolution.authReusedOk, true);
  assert.equal(resolution.authSourceValid, true);
  assert.equal(resolution.storageStateInspection?.chartValidatedByMeta, true);
});

test("invalid storage state without fallback stays non-reusable", () => {
  const tempDir = makeTempDir("tv-auth-invalid-no-fallback-");
  const storageStatePath = path.join(tempDir, "storage-state.json");
  writeJson(storageStatePath, {
    cookies: [{ name: "cookiePrivacyPreferenceBannerProduction", value: "1" }],
    origins: [],
  });

  const resolution = resolveTradingViewAuthResolution({
    TV_STORAGE_STATE: storageStatePath,
  });

  assert.equal(resolution.authMode, "storage_state");
  assert.equal(resolution.authSourcePath, storageStatePath);
  assert.equal(resolution.authSourceExists, true);
  assert.equal(resolution.authSourceValid, false);
  assert.equal(resolution.authReusedOk, false);
  assert.equal(resolution.fallbackUsed, false);
  assert.equal(resolution.fallbackReason, "storage_state_invalid");
});

test("not_verified never aggregates to success", () => {
  assert.equal(combineVerificationStatuses([true, "not_verified", true]), "not_verified");
  assert.equal(statusesAllTrue([true, "not_verified", true]), false);
  assert.equal(combineVerificationStatuses([true, "not_run", true]), true);
});

test("target overall preflight fails when an error is present", () => {
  const passingStatuses = [
    true,
    true,
    true,
    true,
    true,
    true,
    true,
    true,
    true,
    true,
  ] as const;

  assert.equal(computeTargetOverallPreflightOk([...passingStatuses], undefined), true);
  assert.equal(
    computeTargetOverallPreflightOk([...passingStatuses], "editor write failed"),
    false,
  );
});

test("preflight schema helpers require staged report fields", () => {
  const target = {
    file: "SMC_Dashboard.pine",
    scriptName: "SMC Dashboard",
    execution_mode: "mutating",
    auth_mode: "storage_state",
    auth_source_path: "automation/tradingview/auth/storage-state.json",
    auth_reused_ok: true,
    auth_ok: true,
    chart_ok: true,
    editor_ok: true,
    compile_ok: true,
    script_found_on_chart_ok: true,
    settings_open_ok: true,
    inputs_tab_ok: true,
    bindings_count_ok: true,
    bindings_names_ok: true,
    bindings_names_not_verified: false,
    runtime_smoke_ok: true,
    ui_green: true,
    compile_green: true,
    binding_green: true,
    runtime_green: true,
    overall_preflight_ok: true,
    expected_input_labels: ["BUS Armed"],
    observed_input_labels: ["BUS Armed"],
    missing_input_labels: [],
    screenshots: [],
  };
  const report = {
    generatedAt: "2026-03-24T00:00:00.000Z",
    execution_mode: "mutating",
    auth_mode: "storage_state",
    auth_source_path: "automation/tradingview/auth/storage-state.json",
    auth_reused_ok: true,
    auth_ok: true,
    ui_green: true,
    compile_green: true,
    binding_green: true,
    runtime_green: true,
    overall_preflight_ok: true,
    targets: [target],
  };

  assert.deepEqual(getRequiredPreflightTargetFields(target), []);
  assert.deepEqual(getRequiredPreflightReportFields(report), []);
});

test("library release manifest helper enforces required fields", () => {
  const manifest: Partial<LibraryReleaseManifest> = {
    generatedAt: "2026-03-24T00:00:00.000Z",
    publishMode: "manual" as const,
    manifestVersion: 1,
    library: {
      scriptName: "smc_micro_profiles_generated",
      owner: "preuss_steffen",
      importPath: "preuss_steffen/smc_micro_profiles_generated/1",
      expectedVersion: 1,
      publishedVersion: null,
      publishStatus: "manual_publish_required" as const,
      sourceManifest: "pine/generated/smc_micro_profiles_generated.json",
      sourceSnippet: "pine/generated/smc_micro_profiles_core_import_snippet.pine",
    },
    consumers: [
      {
        scriptName: "SMC Core Engine",
        file: "SMC_Core_Engine.pine",
        role: "consumer",
      },
    ],
    lastPreflightReport: "automation/tradingview/reports/preflight-2026-03-24T04-39-33-983Z.json",
    notes: ["TradingView publish remains a manual step."],
  };

  assert.deepEqual(getRequiredLibraryReleaseManifestFields(manifest), []);
  assert.deepEqual(getRequiredLibraryReleaseManifestFields({ publishMode: "manual" }), [
    "generatedAt",
    "manifestVersion",
    "library",
    "consumers",
    "lastPreflightReport",
    "notes",
  ]);
});

test("library release manifest helper accepts automated publish mode", () => {
  const manifest: Partial<LibraryReleaseManifest> = {
    generatedAt: "2026-03-24T00:00:00.000Z",
    publishMode: "automated" as const,
    manifestVersion: 1,
    library: {
      scriptName: "smc_micro_profiles_generated",
      owner: "preuss_steffen",
      importPath: "preuss_steffen/smc_micro_profiles_generated/1",
      expectedVersion: 1,
      publishedVersion: 1,
      publishStatus: "published" as const,
      sourceManifest: "pine/generated/smc_micro_profiles_generated.json",
      sourceSnippet: "pine/generated/smc_micro_profiles_core_import_snippet.pine",
    },
    consumers: [
      {
        scriptName: "SMC Core Engine",
        file: "SMC_Core_Engine.pine",
        role: "consumer",
      },
    ],
    lastPreflightReport: "automation/tradingview/reports/preflight-2026-03-24T09-10-25-787Z.json",
    notes: ["Automated publish completed and core validation stayed green."],
  };

  assert.deepEqual(getRequiredLibraryReleaseManifestFields(manifest), []);
});

test("legacy full release path is no longer an official production entry point", () => {
  const packageJson = JSON.parse(
    fs.readFileSync(path.resolve("package.json"), "utf-8"),
  ) as { scripts?: Record<string, string> };
  const legacyScript = fs.readFileSync(path.resolve("scripts/99_full_release.ts"), "utf-8");

  assert.equal("tv:full-release" in (packageJson.scripts ?? {}), false);
  assert.match(legacyScript, /deprecated and blocked/);
  assert.equal(legacyScript.includes("publishPrivateScript"), false);
});

test("readonly preflight never counts as repo-source compile evidence", () => {
  assert.equal(reportProvidesRepoSourceCompileEvidence({
    execution_mode: "readonly",
    compile_green: true,
  }), false);
  assert.equal(reportProvidesRepoSourceCompileEvidence({
    execution_mode: "readonly",
    compile_green: "not_run",
  }), false);
  assert.equal(reportProvidesRepoSourceCompileEvidence({
    execution_mode: "mutating",
    compile_green: true,
  }), true);
});
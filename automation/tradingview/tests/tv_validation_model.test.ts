import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  combineVerificationStatuses,
  computeTargetOverallPreflightOk,
  describeBindingContract,
  getRequiredLibraryReleaseManifestFields,
  getRequiredPreflightReportFields,
  getRequiredPreflightTargetFields,
  reportProvidesRepoSourceCompileEvidence,
  resolveMissingBindingGroups,
  resolvePreflightExpectedInputLabels,
  resolvePreflightRequiredBindingCount,
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

function makeProductivityGate(
  overrides: Partial<LibraryReleaseManifest["library"]["productivityGate"]> = {},
): LibraryReleaseManifest["library"]["productivityGate"] {
  return {
    publishReady: false,
    blockingReasons: ["fixture_input", "default_event_risk", "placeholder_symbols"],
    fixtureInputDetected: true,
    defaultEventRiskDetected: true,
    placeholderSymbols: ["AAA", "BBB", "CCC"],
    inputPath: "tests/fixtures/seed_base_snapshot.csv",
    universeSize: 3,
    eventRiskSource: "defaults",
    ...overrides,
  };
}

function makeProductCutSummary(): LibraryReleaseManifest["productCut"] {
  return {
    manifestVersion: 2,
    manifestPath: "artifacts/tradingview/smc_product_cut_manifest.json",
    source: "scripts/smc_bus_manifest.py",
    mainlineFiles: ["SMC_Core_Engine.pine", "SMC_Dashboard.pine", "SMC_Long_Strategy.pine"],
    litePrimaryFiles: ["SMC_Core_Engine.pine"],
    proPrimaryFiles: ["SMC_Dashboard.pine", "SMC_Long_Strategy.pine"],
    companionOperatorOnlyFiles: ["SMC_Event_Overlay.pine"],
    internalFiles: ["SMC_TV_Bridge.pine"],
    legacyFiles: ["SMC++.pine"],
    contracts: {
      engine: ["BUS ZoneActive"],
      executable: ["BUS Armed"],
      liteSurface: ["BUS ZoneActive"],
      lite: ["BUS ZoneActive", "BUS Armed"],
      proOnly: ["BUS MetaPack"],
      dashboardBindings: ["BUS ZoneActive"],
      strategyBindings: ["BUS Armed"],
    },
    preflightScopes: {
      smcCoreDashboard: [{ file: "SMC_Core_Engine.pine", scriptName: "SMC Core", checkInputs: false, addToChart: false }],
      smcMainline: [{
        file: "SMC_Dashboard.pine",
        scriptName: "SMC Long-Dip Dashboard v7",
        savedScriptName: "SMC Long-Dip Dashboard v7",
        checkInputs: true,
        addToChart: true,
        minInputs: 58,
        bindingContractKey: "dashboardBindings",
        bindingContractName: "dashboard companion BUS bindings",
        bindingConsumerRole: "dashboard_companion",
        bindingContractLabels: ["BUS ZoneActive", "BUS Trigger", "BUS Invalidation"],
        bindingLabelGroups: [
          { label: "BUS ZoneActive", group: "g_bus_lifecycle", groupTitle: "Lifecycle BUS" },
          { label: "BUS Trigger", group: "g_bus_plan", groupTitle: "Trade Plan" },
          { label: "BUS Invalidation", group: "g_bus_plan", groupTitle: "Trade Plan" },
        ],
      }],
      smcDecisionFirst: [{
        file: "SMC_Long_Strategy.pine",
        scriptName: "SMC Long-Dip Strategy v7",
        savedScriptName: "SMC Long-Dip Strategy v7",
        checkInputs: true,
        addToChart: true,
        minInputs: 8,
        bindingContractKey: "strategyBindings",
        bindingContractName: "execution wrapper BUS bindings",
        bindingConsumerRole: "execution_wrapper",
        bindingContractLabels: ["BUS Armed", "BUS Trigger", "BUS Invalidation"],
        bindingLabelGroups: [
          { label: "BUS Armed", group: "g_bus_entry", groupTitle: "Entry States" },
          { label: "BUS Trigger", group: "g_bus_plan", groupTitle: "Trade Plan" },
          { label: "BUS Invalidation", group: "g_bus_plan", groupTitle: "Trade Plan" },
        ],
      }],
    },
    deprecatedFieldPolicy: {
      mode: "compatibility_only",
      preferredFieldVersion: "v5.5b",
      extensionAllowed: false,
      sunset_date: "2026-05-14",
      sunset_action: "remove_from_export",
      deprecatedGroups: ["event_risk_v5"],
    },
  };
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
      authReason: "account_probe_authenticated",
      authProbeStatuses: [200],
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

test("expired chart-validated storage state falls back to persistent profile", () => {
  const tempDir = makeTempDir("tv-auth-chart-expired-");
  const storageStatePath = path.join(tempDir, "storage-state.json");
  const profileDir = path.join(tempDir, "profile");
  fs.mkdirSync(profileDir, { recursive: true });
  writeJson(storageStatePath, {
    meta: {
      authValidatedByChartAccess: true,
      authValidatedAt: "2024-01-01T00:00:00.000Z",
      validationMode: "persistent_profile_chart_access",
      chartUrl: "https://www.tradingview.com/chart/",
    },
    cookies: [{ name: "sessionid", value: "abc" }],
    origins: [],
  });

  const resolution = resolveTradingViewAuthResolution({
    TV_STORAGE_STATE: storageStatePath,
    TV_PERSISTENT_PROFILE_DIR: profileDir,
    TV_STORAGE_STATE_MAX_AGE_HOURS: "1",
  });

  assert.equal(resolution.authMode, "persistent_profile");
  assert.equal(resolution.authSourcePath, profileDir);
  assert.equal(resolution.authReusedOk, true);
  assert.equal(resolution.fallbackUsed, true);
  assert.equal(resolution.fallbackReason, "storage_state_expired");
});

test("expired chart-validated storage state without fallback stays non-reusable", () => {
  const tempDir = makeTempDir("tv-auth-chart-expired-no-fallback-");
  const storageStatePath = path.join(tempDir, "storage-state.json");
  writeJson(storageStatePath, {
    meta: {
      authValidatedByChartAccess: true,
      authValidatedAt: "2024-01-01T00:00:00.000Z",
      validationMode: "persistent_profile_chart_access",
      chartUrl: "https://www.tradingview.com/chart/",
    },
    cookies: [{ name: "sessionid", value: "abc" }],
    origins: [],
  });

  const resolution = resolveTradingViewAuthResolution({
    TV_STORAGE_STATE: storageStatePath,
    TV_STORAGE_STATE_MAX_AGE_HOURS: "1",
  });

  assert.equal(resolution.authMode, "storage_state");
  assert.equal(resolution.authSourcePath, storageStatePath);
  assert.equal(resolution.authSourceValid, false);
  assert.equal(resolution.authReusedOk, false);
  assert.equal(resolution.fallbackUsed, false);
  assert.equal(resolution.fallbackReason, "storage_state_expired");
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

test("invalid storage state json falls back to persistent profile", () => {
  const tempDir = makeTempDir("tv-auth-invalid-json-fallback-");
  const storageStatePath = path.join(tempDir, "storage-state.json");
  const profileDir = path.join(tempDir, "profile");
  fs.mkdirSync(profileDir, { recursive: true });
  fs.writeFileSync(storageStatePath, "{ not-valid-json", "utf-8");

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

test("invalid storage state json without fallback stays non-reusable", () => {
  const tempDir = makeTempDir("tv-auth-invalid-json-no-fallback-");
  const storageStatePath = path.join(tempDir, "storage-state.json");
  fs.writeFileSync(storageStatePath, "{ not-valid-json", "utf-8");

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
    scriptName: "SMC Long-Dip Dashboard v7",
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
    binding_contract_key: "dashboardBindings",
    binding_contract_name: "dashboard companion BUS bindings",
    binding_consumer_role: "dashboard_companion",
    missing_binding_groups: [],
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

test("manifest binding contract labels override parsed source labels", () => {
  const target = makeProductCutSummary().preflightScopes.smcMainline[0];

  assert.deepEqual(resolvePreflightExpectedInputLabels(target, ["Legacy Trigger"]), [
    "BUS ZoneActive",
    "BUS Trigger",
    "BUS Invalidation",
  ]);
  assert.equal(resolvePreflightRequiredBindingCount(target, ["Legacy Trigger"]), 58);
  assert.equal(describeBindingContract(target), "dashboard companion BUS bindings (dashboard_companion)");
});

test("manifest binding groups localize missing contract sections", () => {
  const target = makeProductCutSummary().preflightScopes.smcDecisionFirst[0];

  assert.deepEqual(resolveMissingBindingGroups(target, ["BUS Trigger", "BUS Invalidation"]), ["Trade Plan"]);
});

test("library release manifest helper enforces required fields", () => {
  const manifest: Partial<LibraryReleaseManifest> = {
    generatedAt: "2026-03-24T00:00:00.000Z",
    publishMode: "manual" as const,
    manifestVersion: 2,
    library: {
      scriptName: "smc_micro_profiles_generated",
      owner: "preuss_steffen",
      importPath: "preuss_steffen/smc_micro_profiles_generated/1",
      expectedVersion: 1,
      publishedVersion: null,
      publishStatus: "manual_publish_required" as const,
      sourceManifest: "pine/generated/smc_micro_profiles_generated.json",
      sourceSnippet: "pine/generated/smc_micro_profiles_core_import_snippet.pine",
      productivityGate: makeProductivityGate(),
    },
    consumers: [
      {
        scriptName: "SMC Core",
        file: "SMC_Core_Engine.pine",
        role: "producer",
      },
    ],
    productCut: makeProductCutSummary(),
    lastPreflightReport: "automation/tradingview/reports/preflight-2026-03-24T04-39-33-983Z.json",
    notes: ["TradingView publish remains a manual step."],
  };

  assert.deepEqual(getRequiredLibraryReleaseManifestFields(manifest), []);
  assert.deepEqual(getRequiredLibraryReleaseManifestFields({ publishMode: "manual" }), [
    "generatedAt",
    "manifestVersion",
    "library",
    "consumers",
    "productCut",
    "lastPreflightReport",
    "notes",
  ]);
});

test("library release manifest helper accepts automated publish mode", () => {
  const manifest: Partial<LibraryReleaseManifest> = {
    generatedAt: "2026-03-24T00:00:00.000Z",
    publishMode: "automated" as const,
    manifestVersion: 2,
    library: {
      scriptName: "smc_micro_profiles_generated",
      owner: "preuss_steffen",
      importPath: "preuss_steffen/smc_micro_profiles_generated/1",
      expectedVersion: 1,
      publishedVersion: 1,
      publishStatus: "published" as const,
      sourceManifest: "pine/generated/smc_micro_profiles_generated.json",
      sourceSnippet: "pine/generated/smc_micro_profiles_core_import_snippet.pine",
      productivityGate: makeProductivityGate({
        publishReady: true,
        blockingReasons: [],
        fixtureInputDetected: false,
        defaultEventRiskDetected: false,
        placeholderSymbols: [],
        inputPath: "data/output/microstructure_features_2026-03-24.csv",
        universeSize: 240,
        eventRiskSource: "smc_event_risk_builder",
      }),
    },
    consumers: [
      {
        scriptName: "SMC Core",
        file: "SMC_Core_Engine.pine",
        role: "producer",
      },
    ],
    productCut: makeProductCutSummary(),
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
    compile_green: "not_verified",
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

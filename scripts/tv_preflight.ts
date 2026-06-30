#!/usr/bin/env -S node --enable-source-maps

import fs from "node:fs";
import path from "node:path";

import {
  addExistingScriptToChartViaIndicators,
  addCurrentScriptToChart,
  assertNoVisibleCompileError,
  closeModal,
  closeTradingViewSession,
  collectEditorDiagnostics,
  collectPageLifecycleDiagnostics,
  collectTradingViewPageAuthState,
  collectVisibleInputLabels,
  diagnoseInputContract,
  ensurePineEditor,
  gotoChart,
  isScriptVisibleOnChartSurface,
  isExactScriptNameMatch,
  newTradingViewSession,
  openFreshUntitledPineDraft,
  openExistingScript,
  openInputsTab,
  openSettingsForScript,
  parseInputSourceLabels,
  probeRuntimeSmoke,
  readOpenedScriptIdentity,
  refreshChartScriptInstance,
  removeVisibleChartScriptInstances,
  saveScript,
  setEditorContent,
  takeScreenshot,
  type AddExistingScriptToChartViaIndicatorsResult,
  utcNow,
  waitForPostSaveCompileSettlement,
  writeJson,
} from "../automation/tradingview/lib/tv_shared.js";
import {
  combineVerificationStatuses,
  computeTargetOverallPreflightOk,
  describeBindingContract,
  resolveMissingBindingGroups,
  resolvePreflightExpectedInputLabels,
  resolvePreflightRequiredBindingCount,
  resolveTradingViewAuthResolution,
  type LibraryReleaseConsumerRole,
  type ProductCutBindingContractKey,
  type ProductCutBindingLabelGroup,
  type TradingViewAuthResolution,
  type VerificationStatus,
} from "../automation/tradingview/lib/tv_validation_model.js";

type ReleaseTarget = {
  file: string;
  scriptName: string;
  savedScriptName?: string;
  checkInputs: boolean;
  addToChart: boolean;
  minInputs?: number;
  bindingContractKey?: ProductCutBindingContractKey;
  bindingContractName?: string;
  bindingConsumerRole?: LibraryReleaseConsumerRole;
  bindingContractLabels?: string[];
  bindingLabelGroups?: ProductCutBindingLabelGroup[];
  allowFreshDraftOnMissingExisting?: boolean;
};

type ProductCutManifest = {
  preflightScopes?: Record<string, ReleaseTarget[]>;
};

type PreflightConfig = {
  productCutScope?: string;
  productCutManifest?: string;
  targets?: ReleaseTarget[];
};

type CliArgs = {
  config?: string;
  out: string;
  openExisting: boolean;
  executionMode: "mutating" | "readonly";
};

type TargetResult = {
  file: string;
  scriptName: string;
  execution_mode: CliArgs["executionMode"];
  auth_mode: TradingViewAuthResolution["authMode"];
  auth_source_path: string | null;
  auth_reused_ok: boolean;
  auth_ok: VerificationStatus;
  auth_reason: string | null;
  auth_probe_statuses: number[];
  chart_ok: VerificationStatus;
  editor_ok: VerificationStatus;
  compile_ok: VerificationStatus;
  script_found_on_chart_ok: VerificationStatus;
  settings_open_ok: VerificationStatus;
  inputs_tab_ok: VerificationStatus;
  bindings_count_ok: VerificationStatus;
  bindings_names_ok: VerificationStatus;
  bindings_names_not_verified: boolean;
  binding_contract_key: ReleaseTarget["bindingContractKey"] | null;
  binding_contract_name: string | null;
  binding_consumer_role: ReleaseTarget["bindingConsumerRole"] | null;
  missing_binding_groups: string[];
  runtime_smoke_ok: VerificationStatus;
  ui_green: VerificationStatus;
  compile_green: VerificationStatus;
  binding_green: VerificationStatus;
  runtime_green: VerificationStatus;
  overall_preflight_ok: boolean;
  expected_input_labels: string[];
  observed_input_labels: string[];
  missing_input_labels: string[];
  legacy_input_labels: string[];
  contract_drift_likely: boolean;
  bindings_refresh_attempted: boolean;
  bindings_refresh_recovered: boolean;
  screenshots: string[];
  error?: string;
  editorDiagnostics?: Awaited<ReturnType<typeof collectEditorDiagnostics>>;
  lifecycleDiagnostics?: ReturnType<typeof collectPageLifecycleDiagnostics>;
};

type PreflightReport = {
  generatedAt: string;
  execution_mode: CliArgs["executionMode"];
  auth_mode: TradingViewAuthResolution["authMode"];
  auth_source_path: string | null;
  auth_reused_ok: boolean;
  auth_ok: VerificationStatus;
  ui_green: VerificationStatus;
  compile_green: VerificationStatus;
  binding_green: VerificationStatus;
  runtime_green: VerificationStatus;
  overall_preflight_ok: boolean;
  targets: TargetResult[];
};

const DEFAULT_PRODUCT_CUT_MANIFEST = path.resolve("artifacts/tradingview/smc_product_cut_manifest.json");
const DEFAULT_PRODUCT_CUT_SCOPE = "smcMainline";

function parseArgs(): CliArgs {
  const args = process.argv.slice(2);

  function getFlag(name: string): string | undefined {
    const index = args.indexOf(name);
    if (index === -1 || !args[index + 1]) {
      return undefined;
    }
    return args[index + 1];
  }

  function hasFlag(name: string): boolean {
    return args.includes(name);
  }

  return {
    config: getFlag("--config")
      ? path.resolve(getFlag("--config") as string)
      : process.env.TV_RELEASE_CONFIG
        ? path.resolve(process.env.TV_RELEASE_CONFIG)
        : undefined,
    out: path.resolve(
      getFlag("--out") ||
        process.env.TV_PREFLIGHT_REPORT ||
        `automation/tradingview/reports/preflight-${utcNow().replace(/[:.]/g, "-")}.json`,
    ),
    openExisting: hasFlag("--no-open-existing") ? false : true,
    executionMode: getFlag("--execution-mode") === "readonly" || hasFlag("--readonly")
      ? "readonly"
      : "mutating",
  };
}

function fallbackDefaultTargets(): ReleaseTarget[] {
  return [
    {
      file: "SMC_Core_Engine.pine",
      scriptName: "SMC Core",
      checkInputs: false,
      addToChart: false,
    },
    {
      file: "SMC_Dashboard.pine",
      scriptName: "SMC Decision Board",
      savedScriptName: "SMC Long-Dip Dashboard v7",
      checkInputs: true,
      addToChart: true,
      minInputs: 58,
      bindingContractKey: "dashboardBindings",
      bindingContractName: "dashboard companion BUS bindings",
      bindingConsumerRole: "dashboard_companion",
    },
    {
      file: "SMC_Long_Strategy.pine",
      scriptName: "SMC Long-Dip Strategy v7",
      savedScriptName: "SMC Long-Dip Strategy v7",
      checkInputs: true,
      addToChart: true,
      minInputs: 8,
      bindingContractKey: "strategyBindings",
      bindingContractName: "execution wrapper BUS bindings",
      bindingConsumerRole: "execution_wrapper",
    },
  ];
}

function loadProductCutTargets(scope: string, manifestPath: string): ReleaseTarget[] | null {
  if (!fs.existsSync(manifestPath)) {
    return null;
  }

  const payload = JSON.parse(fs.readFileSync(manifestPath, "utf-8")) as ProductCutManifest;
  const targets = payload.preflightScopes?.[scope];
  return Array.isArray(targets) && targets.length > 0 ? targets : null;
}

function defaultTargets(): ReleaseTarget[] {
  return loadProductCutTargets(DEFAULT_PRODUCT_CUT_SCOPE, DEFAULT_PRODUCT_CUT_MANIFEST) ?? fallbackDefaultTargets();
}

function loadTargets(configPath?: string): ReleaseTarget[] {
  if (!configPath) {
    return defaultTargets();
  }

  const payload = JSON.parse(fs.readFileSync(configPath, "utf-8")) as PreflightConfig;

  if (payload.productCutScope) {
    const manifestPath = payload.productCutManifest
      ? path.resolve(path.dirname(configPath), payload.productCutManifest)
      : DEFAULT_PRODUCT_CUT_MANIFEST;
    const targets = loadProductCutTargets(payload.productCutScope, manifestPath);
    if (!targets) {
      throw new Error(
        `No product-cut scope ${payload.productCutScope} found in manifest: ${manifestPath}`,
      );
    }
    return targets;
  }

  if (!payload.targets || payload.targets.length === 0) {
    throw new Error(`No targets defined in config: ${configPath}`);
  }

  return payload.targets;
}

function uniqueSorted(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))].sort((left, right) => left.localeCompare(right));
}

function normalizeLabel(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function uniqueNormalized(values: string[]): string[] {
  const seen = new Set<string>();
  const results: string[] = [];

  for (const value of values) {
    const normalized = normalizeLabel(value);
    if (!normalized) {
      continue;
    }

    const key = normalized.toLowerCase();
    if (seen.has(key)) {
      continue;
    }

    seen.add(key);
    results.push(normalized);
  }

  return results;
}

function resolveTradingViewSavedScriptName(target: ReleaseTarget): string {
  return normalizeLabel(target.savedScriptName ?? target.scriptName);
}

function describeTradingViewScriptTarget(target: ReleaseTarget): string {
  const targetScriptName = normalizeLabel(target.scriptName) || target.scriptName;
  const savedScriptName = resolveTradingViewSavedScriptName(target);
  return savedScriptName === targetScriptName
    ? targetScriptName
    : `${targetScriptName} (saved script: ${savedScriptName})`;
}

/**
 * Defensive identity guard for the 2026-04-22 substring-collision class.
 *
 * After openSettingsForScript() returns truthy, read the actual visible
 * settings-dialog title and require an EXACT (case-insensitive) match
 * against either `target.scriptName` or `target.savedScriptName`. If the
 * dialog title is non-empty but does not strictly match either candidate
 * — for example because TradingView opened the third-party
 *   "SMC Execution Engine (Free) by @abdallacrypto v1.3"
 * — fail loudly with a diagnostic message instead of letting the cryptic
 * "binding labels missing" assertion fire later.
 *
 * No-op if the dialog reports no title (back-compat: the existing
 * verifyOpenedSettingsDialogIdentity flow already handles that case).
 */
async function assertOpenedScriptIdentityOrThrow(
  page: import("playwright").Page,
  target: ReleaseTarget,
): Promise<void> {
  const actualScriptIdentity = await readOpenedScriptIdentity(page);
  if (actualScriptIdentity === null) {
    return;
  }
  const candidateNames = [target.scriptName, target.savedScriptName ?? ""].filter((name) => name && name.length > 0);
  if (isExactScriptNameMatch(actualScriptIdentity, ...candidateNames)) {
    return;
  }
  const candidateDescription = candidateNames
    .map((name) => `"${name}"`)
    .join(" or ");
  throw new Error(
    `TradingView opened the wrong script: expected ${candidateDescription}, ` +
    `but the settings dialog reports "${actualScriptIdentity}". ` +
    `This is the 2026-04-22 substring-collision class ` +
    `(third-party scripts whose title contains the preflight target name as a prefix). ` +
    `Ensure the saved TradingView script uses a unique, non-substring-of-third-party title ` +
    `and rerun the preflight.`,
  );
}

function buildMissingExistingScriptError(
  target: ReleaseTarget,
  executionMode: CliArgs["executionMode"],
  indicatorsResult: AddExistingScriptToChartViaIndicatorsResult | null,
): string {
  const targetDescription = describeTradingViewScriptTarget(target);
  const rerunHint = executionMode === "mutating"
    ? " Rerun with --no-open-existing only if a fresh untitled draft is intended."
    : "";

  if (!indicatorsResult || indicatorsResult.attempts.length === 0) {
    return `Could not open existing TradingView script: ${targetDescription}.${rerunHint}`;
  }

  const lookupNames = uniqueNormalized(indicatorsResult.attempts.map((attempt) => attempt.searchName));
  const lookupSummary = lookupNames.length > 0 ? lookupNames.join(", ") : targetDescription;
  const visiblePrivateScripts = uniqueNormalized(indicatorsResult.attempts.flatMap((attempt) => attempt.visiblePrivateScripts));
  const sawMatchingPrivateScript = indicatorsResult.attempts.some((attempt) => attempt.matchingPrivateScriptVisible);

  if (!sawMatchingPrivateScript) {
    const visibleSummary = visiblePrivateScripts.length > 0
      ? ` Visible private My scripts rows: ${visiblePrivateScripts.join(", ")}.`
      : " No private My scripts rows were visible for those searches.";
    return `Could not open existing TradingView script: ${targetDescription}. Indicators -> My scripts did not show a matching private USER script for ${lookupSummary}.${visibleSummary} Refresh TV_STORAGE_STATE to an account that owns the saved private scripts.`;
  }

  return `Could not open existing TradingView script: ${targetDescription}. Indicators -> My scripts showed a matching private USER script for ${lookupSummary} but it never settled on chart.${rerunHint}`;
}

function missingInputLabels(expected: string[], observed: string[]): string[] {
  const observedSet = new Set(observed.map((value) => normalizeLabel(value)));
  return expected.filter((label) => !observedSet.has(normalizeLabel(label)));
}

function inputContractDiagnosisSuffix(
  diagnosis: ReturnType<typeof diagnoseInputContract>,
): string {
  if (diagnosis.likelyDrift) {
    const legacyPreview = diagnosis.legacyLabels.slice(0, 5).join(", ") || "none";
    return ` Likely runtime contract drift; legacy labels: ${legacyPreview}.`;
  }
  if (diagnosis.likelyPartialSurface) {
    return " TradingView appears to be surfacing only a partial subset of the expected inputs.";
  }
  return "";
}

function bindingContractContext(target: ReleaseTarget): string {
  const description = describeBindingContract(target);
  return description ? ` for ${description}` : "";
}

function formatMissingBindingLabels(labels: string[], limit = 8): string {
  const normalized = uniqueNormalized(labels);
  const preview = normalized.slice(0, limit).join(", ");
  const remaining = normalized.length - Math.min(normalized.length, limit);
  return remaining > 0 ? `${preview} (+${remaining} more)` : preview;
}

function missingBindingGroupsSuffix(groups: string[]): string {
  return groups.length > 0 ? ` Missing groups: ${groups.join(", ")}.` : "";
}

function missingBindingLabelsSuffix(labels: string[]): string {
  const formatted = formatMissingBindingLabels(labels);
  return formatted ? ` Missing labels: ${formatted}.` : "";
}

function computeUiGreen(target: TargetResult): VerificationStatus {
  return combineVerificationStatuses([
    target.chart_ok,
    target.editor_ok,
    target.settings_open_ok,
    target.inputs_tab_ok,
  ]);
}

function computeCompileGreen(target: TargetResult): VerificationStatus {
  return combineVerificationStatuses([target.compile_ok]);
}

function computeBindingGreen(target: TargetResult): VerificationStatus {
  return combineVerificationStatuses([target.bindings_count_ok, target.bindings_names_ok]);
}

function computeRuntimeGreen(target: TargetResult): VerificationStatus {
  return combineVerificationStatuses([target.script_found_on_chart_ok, target.runtime_smoke_ok]);
}

function finalizeTargetResult(target: TargetResult): TargetResult {
  const ui_green = computeUiGreen(target);
  const compile_green = computeCompileGreen(target);
  const binding_green = computeBindingGreen(target);
  const runtime_green = computeRuntimeGreen(target);

  return {
    ...target,
    ui_green,
    compile_green,
    binding_green,
    runtime_green,
    overall_preflight_ok: computeTargetOverallPreflightOk([
      target.auth_ok,
      target.chart_ok,
      target.editor_ok,
      target.compile_ok,
      target.script_found_on_chart_ok,
      target.settings_open_ok,
      target.inputs_tab_ok,
      target.bindings_count_ok,
      target.bindings_names_ok,
      target.runtime_smoke_ok,
    ], target.error),
  };
}

function buildInitialTargetResult(
  target: ReleaseTarget,
  filePath: string,
  expectedInputLabels: string[],
  authResolution: TradingViewAuthResolution,
  executionMode: CliArgs["executionMode"],
): TargetResult {
  return finalizeTargetResult({
    file: filePath,
    scriptName: target.scriptName,
    execution_mode: executionMode,
    auth_mode: authResolution.authMode,
    auth_source_path: authResolution.authSourcePath,
    auth_reused_ok: authResolution.authReusedOk,
    auth_ok: "not_run",
    auth_reason: null,
    auth_probe_statuses: [],
    chart_ok: "not_run",
    editor_ok: "not_run",
    compile_ok: "not_run",
    script_found_on_chart_ok: target.addToChart || target.checkInputs ? "not_run" : "not_run",
    settings_open_ok: target.checkInputs ? "not_run" : "not_run",
    inputs_tab_ok: target.checkInputs ? "not_run" : "not_run",
    bindings_count_ok: target.checkInputs ? "not_run" : "not_run",
    bindings_names_ok: target.checkInputs ? "not_run" : "not_run",
    bindings_names_not_verified: false,
    binding_contract_key: target.bindingContractKey ?? null,
    binding_contract_name: target.bindingContractName ?? null,
    binding_consumer_role: target.bindingConsumerRole ?? null,
    missing_binding_groups: [],
    runtime_smoke_ok: target.addToChart || target.checkInputs ? "not_run" : "not_run",
    ui_green: "not_run",
    compile_green: "not_run",
    binding_green: "not_run",
    runtime_green: "not_run",
    overall_preflight_ok: false,
    expected_input_labels: expectedInputLabels,
    observed_input_labels: [],
    missing_input_labels: [],
    legacy_input_labels: [],
    contract_drift_likely: false,
    bindings_refresh_attempted: false,
    bindings_refresh_recovered: false,
    screenshots: [],
  });
}

function buildPreAuthFailureResult(
  target: ReleaseTarget,
  filePath: string,
  expectedInputLabels: string[],
  authResolution: TradingViewAuthResolution,
  executionMode: CliArgs["executionMode"],
): TargetResult {
  return finalizeTargetResult({
    ...buildInitialTargetResult(target, filePath, expectedInputLabels, authResolution, executionMode),
    auth_ok: false,
    error:
      authResolution.authMode === "fresh_login"
        ? "TradingView preflight requires a reusable authenticated session. Configure TV_STORAGE_STATE or TV_PERSISTENT_PROFILE_DIR first."
        : authResolution.fallbackReason === "storage_state_invalid"
          ? "TV_STORAGE_STATE is present but does not look authenticated, and no working fallback was selected. Refresh the storage state or use a persistent profile fallback."
          : "TradingView auth source is not reusable for preflight.",
  });
}

function buildReport(
  authResolution: TradingViewAuthResolution,
  targets: TargetResult[],
  executionMode: CliArgs["executionMode"],
): PreflightReport {
  const auth_ok = combineVerificationStatuses(targets.map((target) => target.auth_ok));
  const ui_green = combineVerificationStatuses(targets.map((target) => target.ui_green));
  const compile_green = combineVerificationStatuses(targets.map((target) => target.compile_green));
  const binding_green = combineVerificationStatuses(targets.map((target) => target.binding_green));
  const runtime_green = combineVerificationStatuses(targets.map((target) => target.runtime_green));
  const bindingTargets = targets.filter((target) =>
    target.settings_open_ok !== "not_run"
      || target.inputs_tab_ok !== "not_run"
      || target.bindings_count_ok !== "not_run"
      || target.bindings_names_ok !== "not_run"
  );
  const bindingGateSatisfied = bindingTargets.length === 0
    || bindingTargets.every((target) => target.binding_green === true);
  const runtimeTargets = targets.filter((target) =>
    target.script_found_on_chart_ok !== "not_run"
      || target.runtime_smoke_ok !== "not_run"
  );
  const runtimeGateSatisfied = runtimeTargets.length === 0
    || runtimeTargets.every((target) => target.runtime_green === true);

  return {
    generatedAt: utcNow(),
    execution_mode: executionMode,
    auth_mode: authResolution.authMode,
    auth_source_path: authResolution.authSourcePath,
    auth_reused_ok: authResolution.authReusedOk,
    auth_ok,
    ui_green,
    compile_green,
    binding_green,
    runtime_green,
    overall_preflight_ok:
      auth_ok === true &&
      ui_green === true &&
      (executionMode === "readonly" || compile_green === true) &&
      bindingGateSatisfied &&
      runtimeGateSatisfied &&
      targets.every((target) => target.overall_preflight_ok),
    targets,
  };
}

function authResolutionCanRun(authResolution: TradingViewAuthResolution): boolean {
  if (authResolution.authMode === "fresh_login") {
    return false;
  }
  if (!authResolution.authSourcePath) {
    return false;
  }
  if (!authResolution.authSourceExists) {
    return false;
  }
  if (authResolution.authMode === "storage_state" && !authResolution.authSourceValid) {
    return false;
  }
  return true;
}

function inferPineDraftKind(code: string): "indicator" | "strategy" | "library" {
  if (/\blibrary\s*\(/i.test(code)) {
    return "library";
  }
  if (/\bstrategy\s*\(/i.test(code)) {
    return "strategy";
  }
  return "indicator";
}

async function main(): Promise<number> {
  const cli = parseArgs();
  const targets = loadTargets(cli.config);
  const runId = utcNow().replace(/[:.]/g, "-");
  const authResolution = resolveTradingViewAuthResolution(process.env);

  if (cli.executionMode === "readonly" && !cli.openExisting) {
    throw new Error("Readonly preflight requires existing TradingView scripts. Remove --no-open-existing or use --execution-mode mutating.");
  }

  if (!authResolutionCanRun(authResolution)) {
    const failedTargets = targets.map((target) => {
      const filePath = path.resolve(target.file);
      const code = fs.readFileSync(filePath, "utf-8");
      const expectedInputLabels = resolvePreflightExpectedInputLabels(target, parseInputSourceLabels(code));
      return buildPreAuthFailureResult(target, filePath, expectedInputLabels, authResolution, cli.executionMode);
    });
    const report = buildReport(authResolution, failedTargets, cli.executionMode);
    writeJson(cli.out, report);
    console.error(`Preflight report written to ${cli.out}`);
    return 1;
  }

  const results: TargetResult[] = [];

  for (const target of targets) {
    const filePath = path.resolve(target.file);
    const code = fs.readFileSync(filePath, "utf-8");
    const expectedInputLabels = resolvePreflightExpectedInputLabels(target, parseInputSourceLabels(code));
    const targetResult = buildInitialTargetResult(target, filePath, expectedInputLabels, authResolution, cli.executionMode);
    const requiredBindingCount = resolvePreflightRequiredBindingCount(target, expectedInputLabels);
    const existingTradingViewScriptName = resolveTradingViewSavedScriptName(target);
    const session = await newTradingViewSession();

    try {
      let usedFreshDraftPath = false;

      await gotoChart(session.page);
      const pageAuthState = await collectTradingViewPageAuthState(session.page).catch(() => null);
      targetResult.auth_ok = Boolean(pageAuthState?.authenticated);
      targetResult.auth_reason = pageAuthState?.reason ?? "auth_state_probe_failed";
      targetResult.auth_probe_statuses = pageAuthState?.evidence.accountProbeStatuses ?? [];
      if (targetResult.auth_ok !== true) {
        throw new Error(
          `Reusable TradingView auth did not survive chart open for ${target.scriptName}: ${targetResult.auth_reason}`,
        );
      }

      targetResult.chart_ok = /tradingview\.com\/chart/i.test(session.page.url());
      if (targetResult.chart_ok !== true) {
        throw new Error(`TradingView chart surface is not active for ${target.scriptName}: ${session.page.url()}`);
      }

      await ensurePineEditor(session.page);
      targetResult.editor_ok = true;

      if (cli.openExisting) {
        let indicatorsFallbackResult: AddExistingScriptToChartViaIndicatorsResult | null = null;
        let openedExisting = await openExistingScript(session.page, existingTradingViewScriptName);
        if (!openedExisting && cli.executionMode === "readonly") {
          indicatorsFallbackResult = await addExistingScriptToChartViaIndicators(session.page, existingTradingViewScriptName);
          openedExisting = indicatorsFallbackResult.added;
        }
        if (!openedExisting) {
          if (cli.executionMode === "mutating" && target.allowFreshDraftOnMissingExisting) {
            await openFreshUntitledPineDraft(session.page, inferPineDraftKind(code));
            usedFreshDraftPath = true;
          } else {
            throw new Error(buildMissingExistingScriptError(target, cli.executionMode, indicatorsFallbackResult));
          }
        }
      } else if (cli.executionMode === "mutating") {
        await openFreshUntitledPineDraft(session.page, inferPineDraftKind(code));
        usedFreshDraftPath = true;
      }

      await ensurePineEditor(session.page);
      targetResult.editor_ok = true;
      if (cli.executionMode === "mutating") {
        await setEditorContent(session.page, code);
        await saveScript(session.page, target.scriptName);
        await waitForPostSaveCompileSettlement(session.page, target.scriptName);
        await assertNoVisibleCompileError(session.page);
        targetResult.compile_ok = true;
        await takeScreenshot(session.page, runId, `${target.scriptName}-compiled`, targetResult.screenshots);
      }

      if (target.addToChart || target.checkInputs) {
        if (usedFreshDraftPath && target.scriptName) {
          await removeVisibleChartScriptInstances(session.page, target.scriptName).catch(() => 0);
          await addCurrentScriptToChart(session.page, target.scriptName, { forceInsert: true, tolerateFailure: true });
        } else {
          await addCurrentScriptToChart(session.page, target.scriptName, { tolerateFailure: true });
        }
        targetResult.script_found_on_chart_ok = await isScriptVisibleOnChartSurface(session.page, target.scriptName);
        if (targetResult.script_found_on_chart_ok !== true) {
          const msg = `Script did not become visible on chart after add-to-chart for ${target.scriptName}`;
          console.error(`[preflight] ${msg} — skipping input checks for this target`);
          await takeScreenshot(session.page, runId, `${target.scriptName}-add-to-chart-failed`, targetResult.screenshots).catch(() => undefined);
          if (target.checkInputs) {
            targetResult.settings_open_ok = false;
            targetResult.inputs_tab_ok = false;
            targetResult.bindings_count_ok = false;
            targetResult.bindings_names_ok = false;
          }
          targetResult.error = msg;
        }
      }

      if (target.checkInputs && targetResult.script_found_on_chart_ok === true) {
        const settingsOpened = await openSettingsForScript(session.page, target.scriptName, {
          allowChartRefresh: cli.executionMode === "mutating",
        });
        if (settingsOpened !== true) {
          throw new Error(`Settings opened for the wrong TradingView script: ${target.scriptName}`);
        }
        await assertOpenedScriptIdentityOrThrow(session.page, target);
        targetResult.settings_open_ok = true;
        await openInputsTab(session.page);
        targetResult.inputs_tab_ok = true;

        let observedInputLabels = uniqueNormalized(await collectVisibleInputLabels(session.page, expectedInputLabels));
        let diagnosis = diagnoseInputContract(expectedInputLabels, observedInputLabels);

        if (cli.executionMode === "mutating" && diagnosis.likelyDrift) {
          targetResult.bindings_refresh_attempted = true;
          await closeModal(session.page).catch(() => undefined);
          await refreshChartScriptInstance(session.page, target.scriptName);
          targetResult.script_found_on_chart_ok = await isScriptVisibleOnChartSurface(session.page, target.scriptName);
          if (targetResult.script_found_on_chart_ok !== true) {
            throw new Error(`Script was not visible after refresh for ${target.scriptName}`);
          }

          const reopenedSettings = await openSettingsForScript(session.page, target.scriptName, {
            allowChartRefresh: cli.executionMode === "mutating",
          });
          if (reopenedSettings !== true) {
            throw new Error(`Settings reopened for the wrong TradingView script after refresh: ${target.scriptName}`);
          }
          await assertOpenedScriptIdentityOrThrow(session.page, target);
          targetResult.settings_open_ok = true;
          await openInputsTab(session.page);
          targetResult.inputs_tab_ok = true;
          observedInputLabels = uniqueNormalized(await collectVisibleInputLabels(session.page, expectedInputLabels));
          diagnosis = diagnoseInputContract(expectedInputLabels, observedInputLabels);
        }

        targetResult.observed_input_labels = observedInputLabels;
        targetResult.missing_input_labels = missingInputLabels(expectedInputLabels, observedInputLabels);
        targetResult.missing_binding_groups = resolveMissingBindingGroups(target, targetResult.missing_input_labels);
        targetResult.legacy_input_labels = diagnosis.legacyLabels;
        targetResult.contract_drift_likely = diagnosis.likelyDrift;
        targetResult.bindings_count_ok = observedInputLabels.length >= requiredBindingCount;
        targetResult.bindings_names_ok = targetResult.missing_input_labels.length === 0;
        targetResult.bindings_names_not_verified = false;
        targetResult.bindings_refresh_recovered = targetResult.bindings_refresh_attempted
          && targetResult.bindings_count_ok === true
          && targetResult.bindings_names_ok === true
          && !diagnosis.likelyDrift;

        if (targetResult.bindings_count_ok !== true) {
          throw new Error(
            `Observed only ${observedInputLabels.length}/${requiredBindingCount} TradingView input bindings for ${target.scriptName}${bindingContractContext(target)}.${missingBindingGroupsSuffix(targetResult.missing_binding_groups)}${missingBindingLabelsSuffix(targetResult.missing_input_labels)}${inputContractDiagnosisSuffix(diagnosis)}`,
          );
        }
        if (targetResult.bindings_names_ok !== true) {
          throw new Error(
            `TradingView input binding names are incomplete for ${target.scriptName}${bindingContractContext(target)}: missing ${formatMissingBindingLabels(targetResult.missing_input_labels)}.${missingBindingGroupsSuffix(targetResult.missing_binding_groups)}${inputContractDiagnosisSuffix(diagnosis)}`,
          );
        }

        await takeScreenshot(session.page, runId, `${target.scriptName}-inputs`, targetResult.screenshots);
        await closeModal(session.page);
      }

      if (target.addToChart || target.checkInputs) {
        const runtimeSmoke = await probeRuntimeSmoke(session.page, target.scriptName);
        targetResult.runtime_smoke_ok = runtimeSmoke.ok;
        if (targetResult.runtime_smoke_ok !== true) {
          throw new Error(
            `Runtime smoke failed for ${target.scriptName}: visible=${runtimeSmoke.scriptVisible}, signIn=${runtimeSmoke.signInModalVisible}, compileError=${runtimeSmoke.compileError ?? "none"}`,
          );
        }
      }

      results.push(finalizeTargetResult(targetResult));
    } catch (error: unknown) {
      await takeScreenshot(session.page, runId, `${target.scriptName}-error`, targetResult.screenshots).catch(() => undefined);
      await closeModal(session.page).catch(() => undefined);
      targetResult.error = error instanceof Error ? error.stack || error.message : String(error);
      targetResult.editorDiagnostics = /editor|pine|monaco/i.test(targetResult.error)
        ? await collectEditorDiagnostics(session.page).catch(() => undefined)
        : undefined;
      targetResult.lifecycleDiagnostics = collectPageLifecycleDiagnostics(session.page);
      results.push(finalizeTargetResult(targetResult));
    } finally {
      await closeTradingViewSession(session);
    }
  }

  const report = buildReport(authResolution, results, cli.executionMode);
  writeJson(cli.out, report);

  const failed = results.filter((result) => !result.overall_preflight_ok);
  if (failed.length > 0) {
    for (const result of failed) {
      console.error(`[preflight] ${result.scriptName}: ${result.error ?? "stage verification failed"}`);
    }
    console.error(`Preflight report written to ${cli.out}`);
    return 1;
  }

  console.log(`Preflight report written to ${cli.out}`);
  return 0;
}

main()
  .then((code) => process.exit(code))
  .catch((error: unknown) => {
    console.error(error instanceof Error ? error.stack || error.message : String(error));
    process.exit(1);
  });

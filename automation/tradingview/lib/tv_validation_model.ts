import fs from "node:fs";
import path from "node:path";

export type TradingViewStorageState = {
  meta?: {
    authValidatedByChartAccess?: boolean;
    authValidatedAt?: string;
    validationMode?: string;
    chartUrl?: string;
    authReason?: string;
    authProbeStatuses?: number[];
  };
  cookies?: Array<{
    name?: string;
    value?: string;
  }>;
  origins?: Array<{
    origin?: string;
    localStorage?: Array<{
      name?: string;
      value?: string;
    }>;
  }>;
};

export type TradingViewStorageStateInspection = {
  cookieNames: string[];
  localStorageKeys: string[];
  authLikeCookies: string[];
  authLikeStorageKeys: string[];
  chartValidatedByMeta: boolean;
  looksAuthenticated: boolean;
};

export type VerificationStatus = boolean | "not_run" | "not_verified";

export type TradingViewAuthMode = "storage_state" | "persistent_profile" | "fresh_login";

export type TradingViewAuthResolution = {
  authMode: TradingViewAuthMode;
  authSourcePath: string | null;
  authSourceExists: boolean;
  authSourceValid: boolean;
  authReusedOk: boolean;
  fallbackUsed: boolean;
  fallbackReason: string | null;
  storageStateInspection: TradingViewStorageStateInspection | null;
};

export type LibraryReleasePublishMode = "manual" | "automated";

export type LibraryReleaseConsumerRole =
  | "producer"
  | "dashboard_companion"
  | "execution_wrapper"
  | "overlay_companion"
  | "context_companion"
  | "exit_companion"
  | "companion_operator_only"
  | "internal"
  | "legacy";

export type ProductCutContracts = {
  engine: string[];
  executable: string[];
  liteSurface: string[];
  lite: string[];
  proOnly: string[];
  dashboardBindings: string[];
  strategyBindings: string[];
  holdManagerBindings: string[];
  eventOverlayBindings: string[];
  exitSignalBindings: string[];
  contextOverlayBindings: string[];
};

export type ProductCutBindingContractKey =
  | "dashboardBindings"
  | "strategyBindings"
  | "holdManagerBindings"
  | "eventOverlayBindings"
  | "exitSignalBindings"
  | "contextOverlayBindings";

export type ProductCutBindingLabelGroup = {
  label: string;
  group: string;
  groupTitle: string;
  tier?: string;
};

export type ProductCutPreflightTarget = {
  file: string;
  scriptName: string;
  checkInputs: boolean;
  addToChart: boolean;
  minInputs?: number;
  savedScriptName?: string;
  bindingContractKey?: ProductCutBindingContractKey;
  bindingContractName?: string;
  bindingConsumerRole?: LibraryReleaseConsumerRole;
  bindingContractLabels?: string[];
  bindingLabelGroups?: ProductCutBindingLabelGroup[];
  allowFreshDraftOnMissingExisting?: boolean;
};

export type ProductCutDeprecatedFieldPolicy = {
  mode: "compatibility_only";
  preferredFieldVersion: string;
  extensionAllowed: boolean;
  sunset_date: string;
  sunset_action: string;
  deprecatedGroups: string[];
};

export type ProductCutSummary = {
  manifestVersion: number;
  manifestPath: string;
  source: string;
  mainlineFiles: string[];
  litePrimaryFiles: string[];
  proPrimaryFiles: string[];
  companionOperatorOnlyFiles: string[];
  internalFiles: string[];
  legacyFiles: string[];
  contracts: ProductCutContracts;
  preflightScopes: Record<string, ProductCutPreflightTarget[]>;
  deprecatedFieldPolicy: ProductCutDeprecatedFieldPolicy;
};

export type LibraryProductivityGate = {
  publishReady: boolean;
  blockingReasons: string[];
  fixtureInputDetected: boolean;
  defaultEventRiskDetected: boolean;
  placeholderSymbols: string[];
  inputPath: string;
  universeSize: number | null;
  eventRiskSource: string | null;
};

export type LibraryReleaseManifest = {
  generatedAt: string;
  publishMode: LibraryReleasePublishMode;
  manifestVersion: number;
  library: {
    scriptName: string;
    owner: string;
    importPath: string;
    expectedVersion: number | null;
    publishedVersion: number | null;
    publishStatus: "not_verified" | "manual_publish_required" | "published";
    sourceManifest: string;
    sourceSnippet: string;
    productivityGate: LibraryProductivityGate;
  };
  consumers: Array<{
    scriptName: string;
    file: string;
    role: LibraryReleaseConsumerRole;
  }>;
  productCut: ProductCutSummary;
  lastPreflightReport: string | null;
  notes: string[];
};

const requiredPreflightTargetFields = [
  "file",
  "scriptName",
  "execution_mode",
  "auth_mode",
  "auth_source_path",
  "auth_reused_ok",
  "auth_ok",
  "chart_ok",
  "editor_ok",
  "compile_ok",
  "script_found_on_chart_ok",
  "settings_open_ok",
  "inputs_tab_ok",
  "bindings_count_ok",
  "bindings_names_ok",
  "bindings_names_not_verified",
  "binding_contract_key",
  "binding_contract_name",
  "binding_consumer_role",
  "missing_binding_groups",
  "runtime_smoke_ok",
  "ui_green",
  "compile_green",
  "binding_green",
  "runtime_green",
  "overall_preflight_ok",
  "expected_input_labels",
  "observed_input_labels",
  "missing_input_labels",
  "screenshots",
] as const;

const requiredPreflightReportFields = [
  "generatedAt",
  "execution_mode",
  "auth_mode",
  "auth_source_path",
  "auth_reused_ok",
  "auth_ok",
  "ui_green",
  "compile_green",
  "binding_green",
  "runtime_green",
  "overall_preflight_ok",
  "targets",
] as const;

function normalizeBindingLabel(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function uniqueNormalizedBindingLabels(values: string[]): string[] {
  const seen = new Set<string>();
  const results: string[] = [];

  for (const value of values) {
    const normalized = normalizeBindingLabel(value);
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

export function resolvePreflightExpectedInputLabels(
  target: ProductCutPreflightTarget,
  fallbackLabels: string[],
): string[] {
  const manifestLabels = uniqueNormalizedBindingLabels(target.bindingContractLabels ?? []);
  if (manifestLabels.length > 0) {
    return manifestLabels;
  }
  return uniqueNormalizedBindingLabels(fallbackLabels);
}

export function resolvePreflightRequiredBindingCount(
  target: ProductCutPreflightTarget,
  expectedLabels: string[],
): number {
  return typeof target.minInputs === "number" ? target.minInputs : expectedLabels.length;
}

export function resolveMissingBindingGroups(
  target: ProductCutPreflightTarget,
  missingLabels: string[],
): string[] {
  const missingSet = new Set(
    uniqueNormalizedBindingLabels(missingLabels).map((label) => label.toLowerCase()),
  );
  const labelGroups = target.bindingLabelGroups ?? [];
  const groupTitles: string[] = [];
  const seen = new Set<string>();

  for (const binding of labelGroups) {
    const normalizedLabel = normalizeBindingLabel(binding.label).toLowerCase();
    if (!missingSet.has(normalizedLabel)) {
      continue;
    }

    const groupTitle = normalizeBindingLabel(binding.groupTitle);
    if (!groupTitle) {
      continue;
    }

    const groupKey = groupTitle.toLowerCase();
    if (seen.has(groupKey)) {
      continue;
    }

    seen.add(groupKey);
    groupTitles.push(groupTitle);
  }

  return groupTitles;
}

export function describeBindingContract(target: ProductCutPreflightTarget): string | null {
  const contractName = target.bindingContractName?.trim();
  const consumerRole = target.bindingConsumerRole?.trim();

  if (contractName && consumerRole) {
    return `${contractName} (${consumerRole})`;
  }
  if (contractName) {
    return contractName;
  }
  if (consumerRole) {
    return consumerRole;
  }
  return null;
}

export function readJson<T>(filePath: string): T {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf-8")) as T;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`Invalid JSON in ${filePath}: ${message}`);
  }
}

export function inspectTradingViewStorageState(
  storageState: string | TradingViewStorageState,
): TradingViewStorageStateInspection {
  const payload = typeof storageState === "string" ? readJson<TradingViewStorageState>(storageState) : storageState;
  const cookieNames = (payload.cookies ?? []).map((cookie) => cookie.name?.trim() || "").filter(Boolean);
  const tradingViewOrigins = (payload.origins ?? []).filter((origin) => /tradingview\.com/i.test(origin.origin || ""));
  const localStorageKeys = tradingViewOrigins.flatMap((origin) =>
    (origin.localStorage ?? []).map((entry) => entry.name?.trim() || "").filter(Boolean),
  );

  const authCookiePatterns = [/session/i, /auth/i, /token/i, /user/i, /signed/i, /^device_t$/i];
  const authStoragePatterns = [/auth/i, /session/i, /user/i, /account/i, /profile/i, /signed/i];

  const authLikeCookies = cookieNames.filter((name) => authCookiePatterns.some((pattern) => pattern.test(name)));
  const authLikeStorageKeys = localStorageKeys.filter((name) => authStoragePatterns.some((pattern) => pattern.test(name)));
  const chartValidatedByMeta = payload.meta?.authValidatedByChartAccess === true;

  return {
    cookieNames,
    localStorageKeys,
    authLikeCookies,
    authLikeStorageKeys,
    chartValidatedByMeta,
    looksAuthenticated: chartValidatedByMeta || authLikeCookies.length > 0 || authLikeStorageKeys.length > 0,
  };
}

function resolvePath(value: string | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed ? path.resolve(trimmed) : null;
}

function parseStorageStateMaxAgeHours(value: string | undefined): number | null {
  const trimmed = value?.trim();
  if (!trimmed) {
    return null;
  }

  const parsed = Number.parseFloat(trimmed);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return null;
  }

  return parsed;
}

export function resolveTradingViewAuthResolution(env: NodeJS.ProcessEnv = process.env): TradingViewAuthResolution {
  const storageStatePath = resolvePath(env.TV_STORAGE_STATE);
  const persistentProfileDir = resolvePath(env.TV_PERSISTENT_PROFILE_DIR);
  const storageStateMaxAgeHours = parseStorageStateMaxAgeHours(env.TV_STORAGE_STATE_MAX_AGE_HOURS);

  const hasStorageState = Boolean(storageStatePath && fs.existsSync(storageStatePath));
  let storageStateInspection: TradingViewStorageStateInspection | null = null;
  let storageStatePayload: TradingViewStorageState | null = null;
  if (hasStorageState) {
    try {
      storageStatePayload = readJson<TradingViewStorageState>(storageStatePath as string);
      storageStateInspection = inspectTradingViewStorageState(storageStatePayload);
    } catch (error) {
      // A corrupt / truncated storage-state file collapses to
      // "storage_state_invalid" below — the exact same fallbackReason as a
      // file that is simply not authenticated. Surface readJson's rich
      // "Invalid JSON in <path>: …" message so the two are distinguishable in
      // logs instead of silently discarding the parse error.
      console.warn(
        `[tv-auth] storage-state at ${storageStatePath as string} could not be parsed/inspected; treating as invalid: ${
          error instanceof Error ? error.message : String(error)
        }`,
      );
      storageStatePayload = null;
      storageStateInspection = null;
    }
  }
  let storageStateInvalidReason: string | null = storageStateInspection?.looksAuthenticated ? null : "storage_state_invalid";

  if (
    storageStateInvalidReason === null
    && storageStateInspection?.chartValidatedByMeta
    && storageStateMaxAgeHours !== null
  ) {
    const validatedAtRaw = storageStatePayload?.meta?.authValidatedAt?.trim();
    if (!validatedAtRaw) {
      storageStateInvalidReason = "storage_state_validation_timestamp_missing";
    } else {
      const validatedAtMs = Date.parse(validatedAtRaw);
      if (Number.isNaN(validatedAtMs)) {
        storageStateInvalidReason = "storage_state_validation_timestamp_invalid";
      } else if ((Date.now() - validatedAtMs) > storageStateMaxAgeHours * 60 * 60 * 1000) {
        storageStateInvalidReason = "storage_state_expired";
      }
    }
  }

  const storageStateValid = storageStateInvalidReason === null;

  if (hasStorageState && storageStateValid) {
    return {
      authMode: "storage_state",
      authSourcePath: storageStatePath,
      authSourceExists: true,
      authSourceValid: true,
      authReusedOk: true,
      fallbackUsed: false,
      fallbackReason: null,
      storageStateInspection,
    };
  }

  if (persistentProfileDir) {
    return {
      authMode: "persistent_profile",
      authSourcePath: persistentProfileDir,
      authSourceExists: fs.existsSync(persistentProfileDir),
      authSourceValid: true,
      authReusedOk: fs.existsSync(persistentProfileDir),
      fallbackUsed: Boolean(hasStorageState && !storageStateValid),
      fallbackReason: hasStorageState && !storageStateValid ? storageStateInvalidReason : null,
      storageStateInspection,
    };
  }

  if (hasStorageState) {
    return {
      authMode: "storage_state",
      authSourcePath: storageStatePath,
      authSourceExists: true,
      authSourceValid: false,
      authReusedOk: false,
      fallbackUsed: false,
      fallbackReason: storageStateInvalidReason,
      storageStateInspection,
    };
  }

  return {
    authMode: "fresh_login",
    authSourcePath: null,
    authSourceExists: false,
    authSourceValid: false,
    authReusedOk: false,
    fallbackUsed: false,
    fallbackReason: null,
    storageStateInspection: null,
  };
}

export function combineVerificationStatuses(statuses: VerificationStatus[]): VerificationStatus {
  const relevant = statuses.filter((status) => status !== "not_run");
  if (relevant.length === 0) {
    return "not_run";
  }
  if (relevant.some((status) => status === false)) {
    return false;
  }
  if (relevant.some((status) => status === "not_verified")) {
    return "not_verified";
  }
  return true;
}

export function statusesAllTrue(statuses: VerificationStatus[]): boolean {
  return combineVerificationStatuses(statuses) === true;
}

export function computeTargetOverallPreflightOk(
  statuses: VerificationStatus[],
  error?: string | null,
): boolean {
  return statusesAllTrue(statuses) && !error;
}

export function getRequiredPreflightTargetFields(target: Record<string, unknown> | null | undefined): string[] {
  if (!target || typeof target !== "object") {
    return ["target"];
  }

  return requiredPreflightTargetFields.filter((field) => !(field in target));
}

export function getRequiredPreflightReportFields(report: Record<string, unknown> | null | undefined): string[] {
  if (!report || typeof report !== "object") {
    return ["report"];
  }

  return requiredPreflightReportFields.filter((field) => !(field in report));
}

export function getRequiredLibraryReleaseManifestFields(
  manifest: Partial<LibraryReleaseManifest> | null | undefined,
): string[] {
  const missing: string[] = [];
  if (!manifest || typeof manifest !== "object") {
    return ["manifest"];
  }

  if (!manifest.generatedAt) {
    missing.push("generatedAt");
  }
  if (manifest.publishMode !== "manual" && manifest.publishMode !== "automated") {
    missing.push("publishMode");
  }
  if (typeof manifest.manifestVersion !== "number") {
    missing.push("manifestVersion");
  }
  if (!manifest.library) {
    missing.push("library");
  } else {
    if (!manifest.library.scriptName) {
      missing.push("library.scriptName");
    }
    if (!manifest.library.owner) {
      missing.push("library.owner");
    }
    if (!manifest.library.importPath) {
      missing.push("library.importPath");
    }
    if (!("expectedVersion" in manifest.library)) {
      missing.push("library.expectedVersion");
    }
    if (!("publishedVersion" in manifest.library)) {
      missing.push("library.publishedVersion");
    }
    if (!manifest.library.publishStatus) {
      missing.push("library.publishStatus");
    }
    if (!manifest.library.sourceManifest) {
      missing.push("library.sourceManifest");
    }
    if (!manifest.library.sourceSnippet) {
      missing.push("library.sourceSnippet");
    }
      if (!manifest.library.productivityGate) {
        missing.push("library.productivityGate");
      } else {
        if (typeof manifest.library.productivityGate.publishReady !== "boolean") {
          missing.push("library.productivityGate.publishReady");
        }
        if (!Array.isArray(manifest.library.productivityGate.blockingReasons)) {
          missing.push("library.productivityGate.blockingReasons");
        }
        if (typeof manifest.library.productivityGate.fixtureInputDetected !== "boolean") {
          missing.push("library.productivityGate.fixtureInputDetected");
        }
        if (typeof manifest.library.productivityGate.defaultEventRiskDetected !== "boolean") {
          missing.push("library.productivityGate.defaultEventRiskDetected");
        }
        if (!Array.isArray(manifest.library.productivityGate.placeholderSymbols)) {
          missing.push("library.productivityGate.placeholderSymbols");
        }
        if (!manifest.library.productivityGate.inputPath) {
          missing.push("library.productivityGate.inputPath");
        }
        if (!("universeSize" in manifest.library.productivityGate)) {
          missing.push("library.productivityGate.universeSize");
        }
        if (!("eventRiskSource" in manifest.library.productivityGate)) {
          missing.push("library.productivityGate.eventRiskSource");
        }
      }
  }
  if (!Array.isArray(manifest.consumers) || manifest.consumers.length === 0) {
    missing.push("consumers");
  }
  if (!manifest.productCut) {
    missing.push("productCut");
  } else {
      if (typeof manifest.productCut.manifestVersion !== "number") {
        missing.push("productCut.manifestVersion");
      }
    if (!manifest.productCut.manifestPath) {
      missing.push("productCut.manifestPath");
    }
    if (!manifest.productCut.source) {
      missing.push("productCut.source");
    }
    if (!Array.isArray(manifest.productCut.mainlineFiles) || manifest.productCut.mainlineFiles.length === 0) {
      missing.push("productCut.mainlineFiles");
    }
    if (!Array.isArray(manifest.productCut.litePrimaryFiles) || manifest.productCut.litePrimaryFiles.length === 0) {
      missing.push("productCut.litePrimaryFiles");
    }
    if (!Array.isArray(manifest.productCut.proPrimaryFiles) || manifest.productCut.proPrimaryFiles.length === 0) {
      missing.push("productCut.proPrimaryFiles");
    }
    if (!Array.isArray(manifest.productCut.companionOperatorOnlyFiles)) {
      missing.push("productCut.companionOperatorOnlyFiles");
    }
    if (!Array.isArray(manifest.productCut.internalFiles)) {
      missing.push("productCut.internalFiles");
    }
    if (!Array.isArray(manifest.productCut.legacyFiles)) {
      missing.push("productCut.legacyFiles");
    }
    if (!manifest.productCut.contracts) {
      missing.push("productCut.contracts");
    } else {
      const requiredContracts = [
        "engine",
        "executable",
        "liteSurface",
        "lite",
        "proOnly",
        "dashboardBindings",
        "strategyBindings",
        "holdManagerBindings",
        "eventOverlayBindings",
        "exitSignalBindings",
        "contextOverlayBindings",
      ] as const;
      for (const contract of requiredContracts) {
        if (!Array.isArray(manifest.productCut.contracts[contract])) {
          missing.push(`productCut.contracts.${contract}`);
        }
      }
    }
    if (!manifest.productCut.preflightScopes || typeof manifest.productCut.preflightScopes !== "object") {
      missing.push("productCut.preflightScopes");
    } else {
      for (const scope of [
        "smcCoreDashboard",
        "smcMainline",
        "smcDecisionFirst",
        "smcHoldManagerShadow",
        "smcR1Companions",
        "smcR4ContextShadow",
        "smcR5HtfSession",
      ] as const) {
        if (!Array.isArray(manifest.productCut.preflightScopes[scope])) {
          missing.push(`productCut.preflightScopes.${scope}`);
        }
      }
    }
    if (!manifest.productCut.deprecatedFieldPolicy) {
      missing.push("productCut.deprecatedFieldPolicy");
    } else {
      if (!manifest.productCut.deprecatedFieldPolicy.mode) {
        missing.push("productCut.deprecatedFieldPolicy.mode");
      }
      if (!manifest.productCut.deprecatedFieldPolicy.preferredFieldVersion) {
        missing.push("productCut.deprecatedFieldPolicy.preferredFieldVersion");
      }
      if (typeof manifest.productCut.deprecatedFieldPolicy.extensionAllowed !== "boolean") {
        missing.push("productCut.deprecatedFieldPolicy.extensionAllowed");
      }
      if (!Array.isArray(manifest.productCut.deprecatedFieldPolicy.deprecatedGroups)) {
        missing.push("productCut.deprecatedFieldPolicy.deprecatedGroups");
      }
    }
  }
  if (!("lastPreflightReport" in manifest)) {
    missing.push("lastPreflightReport");
  }
  if (!Array.isArray(manifest.notes)) {
    missing.push("notes");
  }

  return missing;
}

export function reportProvidesRepoSourceCompileEvidence(report: {
  execution_mode?: unknown;
  compile_green?: unknown;
} | null | undefined): boolean {
  return report?.execution_mode === "mutating" && report?.compile_green === true;
}

// ── Bar Replay: pure decision layer ─────────────────────────────────────────
// The browser driver in tv_shared.ts owns the DOM; everything decidable
// without a page lives here so it is testable. Added 2026-07-31 for the
// R5-REBUILD replay cases — the repository previously had no replay
// automation at all, so the R2.4 evidence had to be produced interactively
// and left nothing reusable behind.

export type DataWindowItem = { title: string; value: string };

/**
 * Fold Data Window items into a label -> value map.
 *
 * The Data Window is the only DOM-readable value channel on a TradingView
 * chart: Pine `table` objects render on CANVAS (verified 2026-07-31 — the
 * chart carried 32 canvases and zero DOM occurrences of the status-table
 * headers), so table text cannot be scraped.
 *
 * TradingView writes "not available" as U+2205. That is mapped to null rather
 * than kept as text, so a case expecting a value can never be satisfied by an
 * empty cell. Later duplicates never overwrite an earlier resolved value.
 */
export function parseDataWindowItems(items: DataWindowItem[]): Record<string, string | null> {
  const out: Record<string, string | null> = {};
  for (const item of items) {
    const title = item.title?.trim();
    if (!title) continue;
    const raw = item.value?.trim() ?? "";
    const value = raw === "" || raw === "\u2205" ? null : raw;
    if (Object.prototype.hasOwnProperty.call(out, title) && out[title] !== null) continue;
    out[title] = value;
  }
  return out;
}

export type ReplayCaseDefinition = {
  caseId: string;
  mode: string;
  checkpointUtc?: string;
  chartTimeframe?: string;
  /** "regular" | "extended" — the chart data mode the case needs. */
  sessionMode?: string;
  expectedDiagnostics: string[];
};

export type ReplayCheckpointPlan = {
  runnable: boolean;
  caseId: string;
  checkpointUtc?: string;
  chartTimeframe?: string;
  /** The chart data mode the case needs; the caller must establish it. */
  sessionMode?: string;
  reason?: string;
};

const ISO_UTC = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;

/** Decide whether the Bar Replay driver can execute a manifest case at all. */
export function resolveReplayCheckpointPlan(input: ReplayCaseDefinition): ReplayCheckpointPlan {
  if (input.mode !== "replay") {
    return { runnable: false, caseId: input.caseId, reason: `mode ${input.mode} is not driven by Bar Replay` };
  }
  if (!input.checkpointUtc || !ISO_UTC.test(input.checkpointUtc)) {
    return {
      runnable: false,
      caseId: input.caseId,
      reason: `checkpointUtc must be an ISO-8601 UTC instant, got ${input.checkpointUtc ?? "none"}`,
    };
  }
  // An extended-hours case needs extended data ON THE CHART. Without it the
  // requested instant simply has no bar and Bar Replay clamps to the last
  // regular-session bar — measured 2026-07-31: asking for 2026-03-09T21:15Z
  // reported a source close of 19:55Z (15:55 ET, the last bar before the
  // regular close) and an NY PM session instead of Outside. The requirement is
  // carried through to the caller, which must switch the chart and fail closed
  // if it cannot; a case run against the wrong data mode is not a verdict.
  // Only ADD the key when the case declares one: the plan shape is pinned by
  // an existing deep-equality test, and an always-present `sessionMode:
  // undefined` is not the same object.
  return {
    runnable: true,
    caseId: input.caseId,
    checkpointUtc: input.checkpointUtc,
    chartTimeframe: input.chartTimeframe,
    ...(input.sessionMode === undefined ? {} : { sessionMode: input.sessionMode }),
  };
}

export type ReplayExpectationFailure = { key: string; expected: string; observed: string | null };
export type ReplayCaseResult = { passed: boolean; failures: ReplayExpectationFailure[] };

/**
 * Compare manifest expectations ("key=value") against observed diagnostics.
 * Fails closed: a missing diagnostic is a failure, and a case with no
 * expectations can never certify itself as passed.
 */
export function evaluateReplayCase(
  expectedDiagnostics: string[],
  observed: Record<string, string>,
): ReplayCaseResult {
  if (expectedDiagnostics.length === 0) {
    return { passed: false, failures: [{ key: "no_expectations", expected: "at least one", observed: null }] };
  }
  const failures: ReplayExpectationFailure[] = [];
  for (const entry of expectedDiagnostics) {
    const index = entry.indexOf("=");
    const key = index === -1 ? entry : entry.slice(0, index);
    const expected = index === -1 ? "" : entry.slice(index + 1);
    const actual = Object.prototype.hasOwnProperty.call(observed, key) ? observed[key] : null;
    if (actual !== expected) failures.push({ key, expected, observed: actual });
  }
  return { passed: failures.length === 0, failures };
}

/**
 * Session codes as declared by SMC_Session_Context.pine. The Data Window can
 * only carry numbers, so the human label the R5 DST cases assert
 * ("sessionLabel=NY AM") is derived here from the code using the script's own
 * _session_label mapping. Keep the two in lockstep.
 */
export const SESSION_CODE_LABELS: Readonly<Record<string, string>> = Object.freeze({
  "0": "Outside",
  "1": "Asia",
  "2": "London",
  "3": "NY AM",
  "4": "NY PM",
});

/**
 * TradingView renders Data Window numbers for a human: thousands separators
 * and two decimals ("1,785,440,700,000.00"). Recover the plain number, or
 * null when the cell is not one.
 */
export function parseDataWindowNumber(value: string | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  const cleaned = value.replace(/,/g, "").trim();
  if (!/^-?\d+(\.\d+)?$/.test(cleaned)) return null;
  const parsed = Number(cleaned);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * Format an epoch-millisecond Data Window value as an ISO-8601 UTC instant.
 *
 * Epoch milliseconds are timezone-independent, which is why the R5 DST
 * checkpoints are asserted against this and not against any on-chart clock:
 * the chart's own timezone cannot corrupt the answer.
 */
export function epochMsToIsoUtc(epochMs: number | null): string | null {
  if (epochMs === null || !Number.isFinite(epochMs)) return null;
  // Guard against a price being mistaken for a timestamp: anything below
  // 1e12 ms (2001-09) is not a chart timestamp this project will ever read.
  if (epochMs < 1_000_000_000_000) return null;
  const date = new Date(epochMs);
  const iso = date.toISOString();
  return `${iso.slice(0, 19)}Z`;
}

export type SessionDiagnostics = Record<string, string>;

/**
 * Translate parsed Data Window rows into the diagnostic keys the R5 rebuild
 * manifest asserts.
 *
 * Fails closed by omission: a row that is absent or not readable as the
 * expected type produces NO key, and {@link evaluateReplayCase} treats a
 * missing key as a failure. Nothing here invents a default.
 */
export function mapSessionDiagnostics(parsed: Record<string, string | null>): SessionDiagnostics {
  const out: SessionDiagnostics = {};

  const codeNumber = parseDataWindowNumber(parsed["Session Code"]);
  if (codeNumber !== null && Number.isInteger(codeNumber)) {
    const code = String(codeNumber);
    out.sessionCode = code;
    const label = SESSION_CODE_LABELS[code];
    if (label !== undefined) out.sessionLabel = label;
  }

  const sourceCloseIso = epochMsToIsoUtc(parseDataWindowNumber(parsed["Session Source Close"]));
  if (sourceCloseIso !== null) {
    out.sourceCloseUtc = sourceCloseIso;
    // A readable source-close timestamp IS the confirmation that the session
    // has published a closed source bar; the script writes it only then.
    out.sourceConfirmed = "1";
  }

  return out;
}

/**
 * Parse a TradingView timeframe label ("5m", "1h", "4h", "1D") into minutes,
 * or null when it is not one.
 */
export function timeframeLabelToMinutes(label: string | null | undefined): number | null {
  const match = /^\s*(\d+)\s*([smhdwSMHDW])\s*$/.exec(label ?? "");
  if (!match) return null;
  const amount = Number(match[1]);
  if (!Number.isFinite(amount) || amount <= 0) return null;
  switch (match[2].toLowerCase()) {
    case "s": return amount / 60;
    case "m": return amount;
    case "h": return amount * 60;
    case "d": return amount * 60 * 24;
    case "w": return amount * 60 * 24 * 7;
    default: return null;
  }
}

/**
 * Shift a UTC checkpoint forward by one chart bar.
 *
 * Measured on the private validation layout, 2026-07-31: Bar Replay's
 * "Select date" positions AT the bar containing the chosen instant, while
 * Session Context publishes the last CLOSED bar. Selecting 13:45 therefore
 * reported Source Close 13:40, and selecting 13:50 reported 13:45 — the value
 * the DST cases assert. A case that pins "the confirmed source close IS the
 * checkpoint" must consequently be driven to the bar AFTER it, so the
 * checkpoint bar has closed.
 *
 * Returns null for a malformed instant or timeframe rather than guessing.
 */
export function checkpointAfterClose(
  checkpointUtc: string,
  timeframeMinutes: number,
): { dateIso: string; timeHhMm: string } | null {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(checkpointUtc)) return null;
  if (!Number.isFinite(timeframeMinutes) || timeframeMinutes <= 0) return null;
  const shifted = new Date(Date.parse(checkpointUtc) + timeframeMinutes * 60_000);
  if (Number.isNaN(shifted.getTime())) return null;
  const iso = shifted.toISOString();
  return { dateIso: iso.slice(0, 10), timeHhMm: iso.slice(11, 16) };
}

/** Data Window title prefixes for the three HTF frames, as SMC_HTF_Confluence.pine plots them. */
export const HTF_FRAME_LABELS: Readonly<Record<string, string>> = Object.freeze({
  "15": "HTF 15m",
  "60": "HTF 1h",
  "240": "HTF 4h",
});

/**
 * Translate Data Window rows into the diagnostics the HTF availability cases
 * assert, for one requested frame.
 *
 * Fails closed by omission, like {@link mapSessionDiagnostics}: a row that is
 * absent or unreadable produces no key, and {@link evaluateReplayCase} treats a
 * missing key as a failure. `available` is deliberately NOT defaulted to 0 —
 * "the script says unavailable" and "the script is not on the chart" must not
 * look alike, or FAIL-CLOSED would pass against an empty chart.
 */
export function mapHtfDiagnostics(
  parsed: Record<string, string | null>,
  frame: string,
): Record<string, string> {
  const prefix = HTF_FRAME_LABELS[frame];
  if (prefix === undefined) return {};
  const out: Record<string, string> = {};

  const available = parseDataWindowNumber(parsed[`${prefix} Available`]);
  if (available !== null) out.available = String(available === 0 ? 0 : 1);

  const sourceCloseIso = epochMsToIsoUtc(parseDataWindowNumber(parsed[`${prefix} Source Close`]));
  if (sourceCloseIso !== null) {
    out.sourceCloseUtc = sourceCloseIso;
    // The script publishes a source close only for a CONFIRMED closed HTF bar.
    out.sourceConfirmed = "1";
  } else if (available === 0) {
    // Masked-unavailable is a confirmed *absence*, not an unknown.
    out.sourceConfirmed = "0";
  }

  return out;
}

export type BoundaryObservation = { atUtc: string; sourceCloseUtc: string | null; available: string | null };
export type BoundaryVerdict = {
  advancesOnlyAtBoundary: boolean;
  distinctSourceCloses: number;
  advances: number;
  violations: string[];
};

/**
 * Decide whether a confirmed HTF source close advanced ONLY at boundaries of
 * its own frame, over a sequence of chart-bar observations.
 *
 * This is the non-repainting property the HTF-15M/1H/4H cases pin: on a 5m
 * chart a 15m frame must hold its confirmed value for three chart bars and then
 * step by exactly one HTF interval.
 *
 * Fails closed: fewer than two DISTINCT values means the observation never
 * caught an advance and cannot certify anything, so it is a violation rather
 * than a vacuous pass. A backwards step, a step that is not a whole frame, and
 * a missing value are violations too.
 *
 * It deliberately does NOT require the value to sit on an absolute UTC grid.
 * That assumption was in the first version and the live chart disproved it:
 * TradingView aligns intraday bars to the SESSION, not to midnight UTC, so on
 * NASDAQ:AAPL the confirmed 1h close reads 19:30Z and the 4h close 17:30Z —
 * both correct, neither a whole multiple of its frame. The property the cases
 * actually pin is that the value ADVANCES by whole frames, and that survives
 * any session offset.
 */
export function evaluateSourceCloseBoundaries(
  observations: BoundaryObservation[],
  frameMinutes: number,
): BoundaryVerdict {
  const violations: string[] = [];
  if (!Number.isFinite(frameMinutes) || frameMinutes <= 0) {
    return { advancesOnlyAtBoundary: false, distinctSourceCloses: 0, advances: 0, violations: ["frameMinutes must be positive"] };
  }

  const seen: string[] = [];
  let advances = 0;
  let previous: string | null = null;

  for (const observation of observations) {
    const value = observation.sourceCloseUtc;
    if (value === null) {
      violations.push(`${observation.atUtc}: no source close published`);
      continue;
    }
    if (!seen.includes(value)) seen.push(value);
    if (previous !== null && value !== previous) {
      advances += 1;
      const deltaMs = Date.parse(value) - Date.parse(previous);
      if (!Number.isFinite(deltaMs) || deltaMs <= 0) {
        violations.push(`${observation.atUtc}: source close moved backwards ${previous} -> ${value}`);
      } else if (deltaMs % (frameMinutes * 60_000) !== 0) {
        violations.push(
          `${observation.atUtc}: source close advanced by ${deltaMs / 60_000}min, not a multiple of the ${frameMinutes}min frame (${previous} -> ${value})`,
        );
      }
    }
    previous = value;
  }

  if (seen.length < 2) {
    violations.push(`observed only ${seen.length} distinct source close(s); the run never caught an advance and proves nothing`);
  }

  return {
    advancesOnlyAtBoundary: violations.length === 0,
    distinctSourceCloses: seen.length,
    advances,
    violations,
  };
}

/**
 * The label TradingView's interval control SHOWS for a requested interval.
 *
 * Measured 2026-07-31: typing "15" leaves the control reading "15", but "60"
 * reads "1h" and "240" reads "4h". Comparing the control against the typed
 * value therefore reported applied=false for every hourly frame, which made
 * R5-REBUILD-FAIL-CLOSED fail on 60 and 240 — correctly, since the chart had
 * not moved, but for a reason that is a mapping gap rather than a chart fault.
 *
 * Minutes below 60 are shown as-is; whole hours as "<n>h"; whole days as
 * "<n>D". Anything that is not a positive integer count of minutes returns
 * null so a caller fails closed instead of comparing against a guess.
 */
export function chartIntervalDisplayLabel(interval: string): string | null {
  if (!/^\d+$/.test(interval)) return null;
  const minutes = Number(interval);
  if (!Number.isFinite(minutes) || minutes <= 0) return null;
  if (minutes < 60) return String(minutes);
  if (minutes % (60 * 24) === 0) return `${minutes / (60 * 24)}D`;
  if (minutes % 60 === 0) return `${minutes / 60}h`;
  return String(minutes);
}

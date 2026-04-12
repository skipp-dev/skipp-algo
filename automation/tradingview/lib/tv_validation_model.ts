import fs from "node:fs";
import path from "node:path";

export type TradingViewStorageState = {
  meta?: {
    authValidatedByChartAccess?: boolean;
    authValidatedAt?: string;
    validationMode?: string;
    chartUrl?: string;
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
};

export type ProductCutPreflightTarget = {
  file: string;
  scriptName: string;
  checkInputs: boolean;
  addToChart: boolean;
  minInputs?: number;
  savedScriptName?: string;
};

export type ProductCutDeprecatedFieldPolicy = {
  mode: "compatibility_only";
  preferredFieldVersion: string;
  extensionAllowed: boolean;
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

export function resolveTradingViewAuthResolution(env: NodeJS.ProcessEnv = process.env): TradingViewAuthResolution {
  const storageStatePath = resolvePath(env.TV_STORAGE_STATE);
  const persistentProfileDir = resolvePath(env.TV_PERSISTENT_PROFILE_DIR);

  const hasStorageState = Boolean(storageStatePath && fs.existsSync(storageStatePath));
  let storageStateInspection: TradingViewStorageStateInspection | null = null;
  if (hasStorageState) {
    try {
      storageStateInspection = inspectTradingViewStorageState(storageStatePath as string);
    } catch {
      storageStateInspection = null;
    }
  }
  const storageStateValid = Boolean(storageStateInspection?.looksAuthenticated);

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
      fallbackReason: hasStorageState && !storageStateValid ? "storage_state_invalid" : null,
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
      fallbackReason: "storage_state_invalid",
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
      for (const scope of ["smcCoreDashboard", "smcMainline", "smcDecisionFirst"] as const) {
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
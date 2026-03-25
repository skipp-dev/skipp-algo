#!/usr/bin/env -S node --enable-source-maps

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import {
  assertNoVisibleCompileError,
  closeTradingViewSession,
  collectOpenScriptIdentityTexts,
  collectPublishedVersionContextTexts,
  countOrderedCodeBlockOccurrences,
  containsOrderedCodeBlock,
  ensurePineEditor,
  gotoChart,
  newTradingViewSession,
  openExistingScript,
  publishPrivateScript,
  resolveOpenScriptIdentityEvidence,
  resolvePublishedVersionEvidence,
  saveScript,
  setEditorContent,
  takeScreenshot,
  utcNow,
  writeJson,
} from "../automation/tradingview/lib/tv_shared.js";
import {
  getRequiredLibraryReleaseManifestFields,
  reportProvidesRepoSourceCompileEvidence,
  type LibraryReleaseManifest,
} from "../automation/tradingview/lib/tv_validation_model.js";

export type IdentityVerificationMode = "script_context" | "not_verified";
export type VersionVerificationMode = "version_context" | "body_fallback" | "not_verified";

type GeneratedLibraryManifest = {
  library_name: string;
  library_owner: string;
  library_version: number;
  recommended_import_path: string;
  pine_library: string;
  core_import_snippet: string;
};

type PreflightReport = {
  execution_mode?: "mutating" | "readonly";
  auth_ok: boolean | "not_run" | "not_verified";
  targets: Array<{
    file: string;
    scriptName: string;
    auth_ok: boolean | "not_run" | "not_verified";
    chart_ok: boolean | "not_run" | "not_verified";
    editor_ok: boolean | "not_run" | "not_verified";
    compile_ok: boolean | "not_run" | "not_verified";
    compile_green: boolean | "not_run" | "not_verified";
    error?: string;
  }>;
};

type CliArgs = {
  manifest: string;
  core: string;
  releaseManifest: string;
  out: string;
  openExisting: boolean;
};

type ContractDetails = {
  manifestPath: string;
  corePath: string;
  snippetPath: string;
  libraryPath: string;
  recommendedImportPath: string;
  alias: string;
  libraryName: string;
  libraryOwner: string;
  libraryVersion: number;
};

type PublishReport = {
  generatedAt: string;
  ok: boolean;
  contractOk: boolean;
  openGateAttempted: boolean;
  openGateVerified: boolean;
  publishAttempted: boolean;
  publishOk: boolean;
  openedExistingScript: boolean;
  publishedScriptVerified: boolean;
  identityVerificationMode: IdentityVerificationMode;
  versionVerificationMode: VersionVerificationMode;
  publishVerificationMode: VersionVerificationMode;
  publishStatus: LibraryReleaseManifest["library"]["publishStatus"];
  expectedImportPath: string;
  expectedVersion: number;
  publishedVersion: number | null;
  fallbackPublishedVersion: number | null;
  identityEvidenceContext: string[];
  versionEvidenceContext: string[];
  publishEvidenceContext: string[];
  repoCoreValidationOk: boolean;
  repoCoreValidationReport: string | null;
  coreValidationOk: boolean;
  coreValidationReport: string | null;
  releaseManifestPath: string;
  screenshots: string[];
  error?: string;
};

function parseArgs(): CliArgs {
  const args = process.argv.slice(2);

  function getFlag(name: string, fallback: string): string {
    const index = args.indexOf(name);
    if (index === -1 || !args[index + 1]) {
      return fallback;
    }
    return args[index + 1];
  }

  function hasFlag(name: string): boolean {
    return args.includes(name);
  }

  return {
    manifest: path.resolve(getFlag("--manifest", "pine/generated/smc_micro_profiles_generated.json")),
    core: path.resolve(getFlag("--core", "SMC_Core_Engine.pine")),
    releaseManifest: path.resolve(getFlag("--release-manifest", "artifacts/tradingview/library_release_manifest.json")),
    out: path.resolve(
      getFlag(
        "--out",
        `automation/tradingview/reports/publish-micro-library-${utcNow().replace(/[:.]/g, "-")}.json`,
      ),
    ),
    openExisting: hasFlag("--no-open-existing") ? false : true,
  };
}

function readJson<T>(filePath: string): T {
  return JSON.parse(fs.readFileSync(filePath, "utf-8")) as T;
}

function normalizeLines(text: string): string[] {
  return text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
}

function parseImport(line: string): { importPath: string; alias: string } | null {
  const match = line.trim().match(/^import\s+([A-Za-z0-9_/-]+)\s+as\s+([A-Za-z_][A-Za-z0-9_]*)\s*$/);
  if (!match) {
    return null;
  }
  return {
    importPath: match[1],
    alias: match[2],
  };
}

function findImportPathForAlias(text: string, alias: string): string {
  for (const line of text.split(/\r?\n/)) {
    const parsed = parseImport(line);
    if (parsed?.alias === alias) {
      return parsed.importPath;
    }
  }
  throw new Error(`No import found for alias ${alias}`);
}

export function verifyPublishContract(manifestPath: string, corePath: string): ContractDetails {
  const manifest = readJson<GeneratedLibraryManifest>(manifestPath);
  const repoRoot = path.dirname(path.resolve(corePath));
  const snippetPath = path.resolve(repoRoot, manifest.core_import_snippet);
  const libraryPath = path.resolve(repoRoot, manifest.pine_library);

  if (!fs.existsSync(snippetPath)) {
    throw new Error(`Missing core import snippet: ${snippetPath}`);
  }
  if (!fs.existsSync(libraryPath)) {
    throw new Error(`Missing generated Pine library: ${libraryPath}`);
  }
  if (!fs.existsSync(corePath)) {
    throw new Error(`Missing core file: ${corePath}`);
  }

  const snippetLines = normalizeLines(fs.readFileSync(snippetPath, "utf-8"));
  if (snippetLines.length === 0) {
    throw new Error("Core import snippet is empty");
  }

  const snippetImport = parseImport(snippetLines[0]);
  if (!snippetImport) {
    throw new Error("Core import snippet does not start with a valid import line");
  }
  if (snippetImport.importPath !== manifest.recommended_import_path) {
    throw new Error(
      `Snippet import path mismatch: expected ${manifest.recommended_import_path}, found ${snippetImport.importPath}`,
    );
  }

  const coreText = fs.readFileSync(corePath, "utf-8");
  const coreImportPath = findImportPathForAlias(coreText, snippetImport.alias);
  if (coreImportPath !== manifest.recommended_import_path) {
    throw new Error(
      `Core import path mismatch for alias ${snippetImport.alias}: expected ${manifest.recommended_import_path}, found ${coreImportPath}`,
    );
  }

  const snippetBody = snippetLines.slice(1).join("\n");
  if (!containsOrderedCodeBlock(coreText, snippetBody)) {
    throw new Error(
      "Core file is missing the generated import snippet as a contiguous alias block. "
      + `Expected block: ${JSON.stringify(snippetLines)}`,
    );
  }

  const occurrenceCount = countOrderedCodeBlockOccurrences(coreText, snippetBody);
  if (occurrenceCount !== 1) {
    throw new Error(
      "Core file must contain the generated import snippet alias block exactly once as real contiguous code. "
      + `Observed occurrences: ${occurrenceCount}`,
    );
  }

  return {
    manifestPath,
    corePath,
    snippetPath,
    libraryPath,
    recommendedImportPath: manifest.recommended_import_path,
    alias: snippetImport.alias,
    libraryName: manifest.library_name,
    libraryOwner: manifest.library_owner,
    libraryVersion: Number(manifest.library_version),
  };
}

function buildDefaultConsumers(): LibraryReleaseManifest["consumers"] {
  return [
    {
      scriptName: "SMC Core Engine",
      file: "SMC_Core_Engine.pine",
      role: "consumer",
    },
    {
      scriptName: "SMC Dashboard",
      file: "SMC_Dashboard.pine",
      role: "consumer",
    },
    {
      scriptName: "SMC Long Strategy",
      file: "SMC_Long_Strategy.pine",
      role: "consumer",
    },
  ];
}

function uniqueNotes(notes: string[]): string[] {
  return [...new Set(notes.filter(Boolean))];
}

function writeReleaseManifest(
  releaseManifestPath: string,
  details: ContractDetails,
  options: {
    publishMode: LibraryReleaseManifest["publishMode"];
    publishStatus: LibraryReleaseManifest["library"]["publishStatus"];
    publishedVersion: number | null;
    lastPreflightReport: string | null;
  },
): void {
  const existing = fs.existsSync(releaseManifestPath)
    ? readJson<Partial<LibraryReleaseManifest>>(releaseManifestPath)
    : null;

  const payload: LibraryReleaseManifest = {
    generatedAt: utcNow(),
    publishMode: options.publishMode,
    manifestVersion: typeof existing?.manifestVersion === "number" ? existing.manifestVersion : 1,
    library: {
      scriptName: details.libraryName,
      owner: details.libraryOwner,
      importPath: details.recommendedImportPath,
      expectedVersion: details.libraryVersion,
      publishedVersion: options.publishedVersion,
      publishStatus: options.publishStatus,
      sourceManifest: path.relative(path.dirname(releaseManifestPath), details.manifestPath).replace(/\\/g, "/") === ""
        ? "pine/generated/smc_micro_profiles_generated.json"
        : path.relative(path.resolve(process.cwd(), "artifacts/tradingview"), details.manifestPath).replace(/\\/g, "/"),
      sourceSnippet: path.relative(path.resolve(process.cwd(), "artifacts/tradingview"), details.snippetPath).replace(/\\/g, "/"),
    },
    consumers: existing?.consumers && existing.consumers.length > 0 ? existing.consumers : buildDefaultConsumers(),
    lastPreflightReport: options.lastPreflightReport,
    notes: uniqueNotes([
      ...(existing?.notes ?? []),
      "Manifest, generated import snippet, and SMC_Core_Engine import path must stay identical.",
      "Pine library import version is explicit; TradingView does not auto-resolve the newest version in the core import.",
      "Owner/version changes require regenerating the library artifacts before publish.",
    ]),
  };

  payload.library.sourceManifest = "pine/generated/smc_micro_profiles_generated.json";
  payload.library.sourceSnippet = "pine/generated/smc_micro_profiles_core_import_snippet.pine";

  const missing = getRequiredLibraryReleaseManifestFields(payload);
  if (missing.length > 0) {
    throw new Error(`Library release manifest is incomplete: ${missing.join(", ")}`);
  }

  writeJson(releaseManifestPath, payload);
}

function buildCoreOnlyPreflightConfig(tempDir: string): string {
  const configPath = path.join(tempDir, "tv-micro-library-core-preflight.json");
  writeJson(configPath, {
    targets: [
      {
        file: "SMC_Core_Engine.pine",
        scriptName: "SMC Core Engine",
        checkInputs: false,
        addToChart: false,
      },
    ],
  });
  return configPath;
}

function runRepoCorePreflightValidation(reportPath: string): { ok: boolean; reportPath: string; error?: string } {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "tv-micro-library-"));
  const configPath = buildCoreOnlyPreflightConfig(tempDir);

  try {
    execFileSync(
      "npm",
      ["run", "tv:preflight", "--", "--config", configPath, "--out", reportPath, "--no-open-existing"],
      {
        cwd: process.cwd(),
        encoding: "utf-8",
        stdio: "pipe",
      },
    );
  } catch (error: unknown) {
    if (!fs.existsSync(reportPath)) {
      const message = error instanceof Error ? error.message : String(error);
      return { ok: false, reportPath, error: `Core preflight did not emit a report: ${message}` };
    }
  } finally {
    fs.rmSync(tempDir, { recursive: true, force: true });
  }

  const report = readJson<PreflightReport>(reportPath);
  const target = report.targets[0];
  if (!target) {
    return { ok: false, reportPath, error: "Core preflight report did not contain a target result." };
  }

  const ok = report.auth_ok === true
    && reportProvidesRepoSourceCompileEvidence(report)
    && target.auth_ok === true
    && target.chart_ok === true
    && target.editor_ok === true
    && target.compile_ok === true
    && target.compile_green === true
    && !target.error;

  if (!ok) {
    return {
      ok: false,
      reportPath,
      error: target.error || `Core preflight failed. auth_ok=${report.auth_ok}, compile_ok=${target.compile_ok}`,
    };
  }

  return { ok: true, reportPath };
}

export function resolvePreMutationOpenGate(options: {
  openExisting: boolean;
  openGateVerified: boolean;
  scriptName: string;
}): {
  openGateAttempted: boolean;
  openGateVerified: boolean;
  allowEditorMutation: boolean;
  error: string | null;
} {
  if (!options.openExisting) {
    return {
      openGateAttempted: false,
      openGateVerified: false,
      allowEditorMutation: true,
      error: null,
    };
  }

  if (options.openGateVerified) {
    return {
      openGateAttempted: true,
      openGateVerified: true,
      allowEditorMutation: true,
      error: null,
    };
  }

  return {
    openGateAttempted: true,
    openGateVerified: false,
    allowEditorMutation: false,
    error: `Could not open existing TradingView script: ${options.scriptName}. Aborted before first editor mutation at the exact-open gate. Rerun with --no-open-existing only if a fresh untitled draft is intended.`,
  };
}

export function resolvePublishReportState(options: {
  openGateAttempted: boolean;
  publishAttempted: boolean;
  identityVerificationMode: IdentityVerificationMode;
  versionVerificationMode: VersionVerificationMode;
  publishedVersion: number | null;
  expectedVersion: number | null;
  repoCoreValidationOk: boolean;
}): {
  ok: boolean;
  publishOk: boolean;
  publishStatus: LibraryReleaseManifest["library"]["publishStatus"];
} {
  const publishOk = options.identityVerificationMode === "script_context"
    && options.versionVerificationMode === "version_context"
    && options.publishedVersion !== null
    && options.publishedVersion === options.expectedVersion;

  const publishStatus = publishOk && options.repoCoreValidationOk
    ? "published"
    : options.openGateAttempted || options.publishAttempted
      ? "not_verified"
      : "manual_publish_required";

  return {
    ok: publishOk && options.repoCoreValidationOk,
    publishOk,
    publishStatus,
  };
}

export async function runPublishMicroLibraryCli(): Promise<number> {
  const cli = parseArgs();
  const runId = utcNow().replace(/[:.]/g, "-");
  const screenshots: string[] = [];
  const preflightReportPath = path.resolve(`automation/tradingview/reports/preflight-micro-library-${runId}.json`);
  let details: ContractDetails | null = null;
  let openGateAttempted = false;
  let openGateVerified = false;
  let openedExistingScript = false;
  let publishAttempted = false;
  let publishedScriptVerified = false;
  let identityVerificationMode: PublishReport["identityVerificationMode"] = "not_verified";
  let versionVerificationMode: PublishReport["versionVerificationMode"] = "not_verified";
  let publishedVersion: number | null = null;
  let fallbackPublishedVersion: number | null = null;
  let identityEvidenceContext: string[] = [];
  let versionEvidenceContext: string[] = [];
  let publishEvidenceContext: string[] = [];
  let publishStatus: LibraryReleaseManifest["library"]["publishStatus"] = "manual_publish_required";
  let repoCoreValidationOk = false;
  let repoCoreValidationError: string | undefined;

  try {
    details = verifyPublishContract(cli.manifest, cli.core);

    const session = await newTradingViewSession();
    try {
      if (!session.authResolution.authReusedOk) {
        throw new Error("TradingView publish requires a reusable authenticated session. Refresh TV_STORAGE_STATE or TV_PERSISTENT_PROFILE_DIR first.");
      }

      await gotoChart(session.page);
      await ensurePineEditor(session.page);

      if (cli.openExisting) {
        openGateAttempted = true;
        openedExistingScript = await openExistingScript(session.page, details.libraryName).catch(() => false);
        openGateVerified = openedExistingScript;
        const preMutationOpenGate = resolvePreMutationOpenGate({
          openExisting: cli.openExisting,
          openGateVerified,
          scriptName: details.libraryName,
        });
        if (!preMutationOpenGate.allowEditorMutation) {
          throw new Error(preMutationOpenGate.error ?? `Could not open existing TradingView script: ${details.libraryName}`);
        }
      }

      const code = fs.readFileSync(details.libraryPath, "utf-8");
      await setEditorContent(session.page, code);
      await saveScript(session.page, details.libraryName);
      await assertNoVisibleCompileError(session.page);
      await takeScreenshot(session.page, runId, `${details.libraryName}-compiled`, screenshots);

      publishAttempted = true;
      await publishPrivateScript(session.page, {
        title: details.libraryName,
        description: `Automated private release of ${details.libraryName} at ${utcNow()}.`,
      });
      await takeScreenshot(session.page, runId, `${details.libraryName}-published`, screenshots);

      publishedScriptVerified = await openExistingScript(session.page, details.libraryName).catch(() => false);
      identityEvidenceContext = await collectOpenScriptIdentityTexts(session.page, details.libraryName).catch(() => []);
      versionEvidenceContext = await collectPublishedVersionContextTexts(session.page, details.libraryName).catch(() => []);
      publishEvidenceContext = versionEvidenceContext;
      const bodyText = await session.page.locator("body").innerText().catch(() => "");
      const identityEvidence = resolveOpenScriptIdentityEvidence(details.libraryName, {
        dialogStillVisible: false,
        editorContextTexts: identityEvidenceContext,
        bodyText,
      });
      const publishEvidence = resolvePublishedVersionEvidence({
        scriptName: details.libraryName,
        versionContextTexts: versionEvidenceContext,
        bodyText,
      });
      identityVerificationMode = identityEvidence.verificationMode;
      versionVerificationMode = publishEvidence.verificationMode;
      publishedVersion = publishEvidence.publishedVersion;
      fallbackPublishedVersion = publishEvidence.fallbackVersion;
      if (!publishedScriptVerified || identityVerificationMode !== "script_context" || versionVerificationMode !== "version_context" || publishedVersion !== details.libraryVersion) {
        throw new Error(
          `Published TradingView library could not be verified exactly: live_script_verified=${publishedScriptVerified}, identity_mode=${identityVerificationMode}, version_mode=${versionVerificationMode}, expected_version=${details.libraryVersion}, detected_version=${publishedVersion ?? "unknown"}`,
        );
      }
    } finally {
      await closeTradingViewSession(session);
    }

    const repoCoreValidation = runRepoCorePreflightValidation(preflightReportPath);
    repoCoreValidationOk = repoCoreValidation.ok;
    repoCoreValidationError = repoCoreValidation.error;
    const publishState = resolvePublishReportState({
      openGateAttempted,
      publishAttempted,
      identityVerificationMode,
      versionVerificationMode,
      publishedVersion,
      expectedVersion: details.libraryVersion,
      repoCoreValidationOk,
    });
    publishStatus = publishState.publishStatus;

    writeReleaseManifest(cli.releaseManifest, details, {
      publishMode: "automated",
      publishStatus,
      publishedVersion,
      lastPreflightReport: repoCoreValidation.reportPath,
    });

    const report: PublishReport = {
      generatedAt: utcNow(),
      ok: publishState.ok,
      contractOk: true,
      openGateAttempted,
      openGateVerified,
      publishAttempted,
      publishOk: publishState.publishOk,
      openedExistingScript,
      publishedScriptVerified,
      identityVerificationMode,
      versionVerificationMode,
      publishVerificationMode: versionVerificationMode,
      publishStatus,
      expectedImportPath: details.recommendedImportPath,
      expectedVersion: details.libraryVersion,
      publishedVersion,
      fallbackPublishedVersion,
      identityEvidenceContext,
      versionEvidenceContext,
      publishEvidenceContext,
      repoCoreValidationOk,
      repoCoreValidationReport: repoCoreValidation.reportPath,
      coreValidationOk: repoCoreValidationOk,
      coreValidationReport: repoCoreValidation.reportPath,
      releaseManifestPath: cli.releaseManifest,
      screenshots,
      error: repoCoreValidation.error,
    };
    writeJson(cli.out, report);

    process.stdout.write(JSON.stringify(report, null, 2));
    process.stdout.write("\n");
    return repoCoreValidation.ok ? 0 : 1;
  } catch (error: unknown) {
    if (details) {
      const publishState = resolvePublishReportState({
        openGateAttempted,
        publishAttempted,
        identityVerificationMode,
        versionVerificationMode,
        publishedVersion,
        expectedVersion: details.libraryVersion,
        repoCoreValidationOk,
      });
      publishStatus = publishState.publishStatus;
      try {
        writeReleaseManifest(cli.releaseManifest, details, {
          publishMode: openGateAttempted || publishAttempted ? "automated" : "manual",
          publishStatus,
          publishedVersion,
          lastPreflightReport: fs.existsSync(preflightReportPath) ? preflightReportPath : null,
        });
      } catch {
        // Best-effort manifest update; the main failure is reported below.
      }
    }

    const message = error instanceof Error ? error.stack || error.message : String(error);
    const publishState = resolvePublishReportState({
      openGateAttempted,
      publishAttempted,
      identityVerificationMode,
      versionVerificationMode,
      publishedVersion,
      expectedVersion: details?.libraryVersion ?? null,
      repoCoreValidationOk,
    });
    const report: PublishReport = {
      generatedAt: utcNow(),
      ok: false,
      contractOk: Boolean(details),
      openGateAttempted,
      openGateVerified,
      publishAttempted,
      publishOk: publishState.publishOk,
      openedExistingScript,
      publishedScriptVerified,
      identityVerificationMode,
      versionVerificationMode,
      publishVerificationMode: versionVerificationMode,
      publishStatus: publishState.publishStatus,
      expectedImportPath: details?.recommendedImportPath ?? "",
      expectedVersion: details?.libraryVersion ?? 0,
      publishedVersion,
      fallbackPublishedVersion,
      identityEvidenceContext,
      versionEvidenceContext,
      publishEvidenceContext,
      repoCoreValidationOk,
      repoCoreValidationReport: fs.existsSync(preflightReportPath) ? preflightReportPath : null,
      coreValidationOk: repoCoreValidationOk,
      coreValidationReport: fs.existsSync(preflightReportPath) ? preflightReportPath : null,
      releaseManifestPath: cli.releaseManifest,
      screenshots,
      error: repoCoreValidationError ? `${message}\n${repoCoreValidationError}` : message,
    };
    writeJson(cli.out, report);
    process.stdout.write(JSON.stringify(report, null, 2));
    process.stdout.write("\n");
    return 1;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runPublishMicroLibraryCli()
    .then((code) => process.exit(code))
    .catch((error: unknown) => {
      console.error(error instanceof Error ? error.stack || error.message : String(error));
      process.exit(1);
    });
}
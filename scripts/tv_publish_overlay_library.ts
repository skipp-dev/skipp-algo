#!/usr/bin/env -S node --enable-source-maps

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  addCurrentScriptToChart,
  assertNoVisibleCompileError,
  closeTradingViewSession,
  collectOpenScriptIdentityTexts,
  collectPublishedVersionContextTexts,
  ensurePineEditor,
  gotoChart,
  newTradingViewSession,
  openExistingScript,
  openFreshUntitledPineDraft,
  publishPrivateScript,
  resolveOpenScriptIdentityEvidence,
  resolvePublishedVersionEvidence,
  saveScript,
  setEditorContent,
  takeScreenshot,
  utcNow,
  waitForPostSaveCompileSettlement,
  writeJson,
} from "../automation/tradingview/lib/tv_shared.js";

// Fast overlay companion publisher (Option-A fast/slow split, step 3).
//
// Publishes the lean smc_overlay_generated library (imported as `ov`) derived
// by scripts/bake_overlay_library.py from the slow micro-profiles artifact. The
// publish/verify flow mirrors tv_publish_utils_library.ts verbatim (same proven
// fail-closed identity + version verification). The ONLY contract difference is
// that the overlay is validated against its own generated MANIFEST rather than a
// committed core consumer file — the overlay is a new companion library and is
// consumed by user charts, not by SMC_Core_Engine.pine.
//
// CI-only: node/npm are not part of the local toolchain, so this file is built
// and exercised exclusively in the TradingView publish workflow.

type IdentityVerificationMode = "script_context" | "not_verified";
type VersionVerificationMode = "version_context" | "idempotent_no_change" | "body_fallback" | "not_verified";
type OpenMode = "existing" | "fresh_draft";

type CliArgs = {
  library: string;
  manifest: string;
  scriptName: string;
  importPath: string;
  alias: string;
  version: number;
  description: string;
  out: string;
  openExisting: boolean;
  allowCreate: boolean;
};

type ContractDetails = {
  libraryPath: string;
  manifestPath: string;
  scriptName: string;
  importPath: string;
  alias: string;
  version: number;
};

type PublishOverlayReport = {
  generatedAt: string;
  ok: boolean;
  contractOk: boolean;
  publishAttempted: boolean;
  publishOk: boolean;
  openMode: OpenMode;
  openExistingRequested: boolean;
  openedExistingScript: boolean;
  createdFreshDraft: boolean;
  publishedScriptVerified: boolean;
  identityVerificationMode: IdentityVerificationMode;
  versionVerificationMode: VersionVerificationMode;
  expectedImportPath: string;
  expectedVersion: number;
  publishedVersion: number | null;
  fallbackPublishedVersion: number | null;
  noChangeDetected: boolean;
  identityEvidenceContext: string[];
  versionEvidenceContext: string[];
  publishBodyText: string;
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
    library: path.resolve(getFlag("--library", "pine/generated/smc_overlay_generated.pine")),
    manifest: path.resolve(getFlag("--manifest", "pine/generated/smc_overlay_generated.json")),
    scriptName: getFlag("--script-name", "smc_overlay_generated"),
    importPath: getFlag("--import-path", "preuss_steffen/smc_overlay_generated/1"),
    alias: getFlag("--alias", "ov"),
    version: Number(getFlag("--version", "1")),
    description: getFlag(
      "--description",
      "Fast overlay companion library (macro / news / calendar / layering) derived from smc_micro_profiles_generated.",
    ),
    out: path.resolve(
      getFlag(
        "--out",
        `automation/tradingview/reports/publish-overlay-library-${utcNow().replace(/[:.]/g, "-")}.json`,
      ),
    ),
    openExisting: hasFlag("--no-open-existing") ? false : true,
    allowCreate: hasFlag("--no-allow-create") ? false : true,
  };
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function hasExpectedImportPathEvidence(bodyText: string, expectedImportPath: string): boolean {
  const normalizedBodyText = bodyText.replace(/\s+/g, " ");
  const trimmedImportPath = expectedImportPath.trim();
  if (trimmedImportPath.length === 0) {
    return false;
  }

  const importPathPattern = new RegExp(`(^|[^A-Za-z0-9_./-])${escapeRegExp(trimmedImportPath)}(?=$|[^A-Za-z0-9_./-])`);
  return importPathPattern.test(normalizedBodyText);
}

// Narrow input so the contract can be unit-tested without constructing a full
// CliArgs. CliArgs satisfies this shape, so the production call site is unchanged.
export type OverlayContractInput = Pick<
  CliArgs,
  "library" | "manifest" | "scriptName" | "importPath" | "alias" | "version"
>;

export function verifyOverlayPublishContract(cli: OverlayContractInput): ContractDetails {
  if (!fs.existsSync(cli.library)) {
    throw new Error(`Missing overlay library source: ${cli.library}`);
  }
  if (!fs.existsSync(cli.manifest)) {
    throw new Error(`Missing overlay manifest: ${cli.manifest}`);
  }

  const libraryText = fs.readFileSync(cli.library, "utf-8");
  const expectedLibraryHeader = `library("${cli.scriptName}"`;
  const expectedImportLine = `import ${cli.importPath} as ${cli.alias}`;

  if (!libraryText.includes(expectedLibraryHeader)) {
    throw new Error(`Overlay library header mismatch: expected ${expectedLibraryHeader}`);
  }

  // Cross-validate against the generated manifest instead of a core consumer.
  let manifest: Record<string, unknown>;
  try {
    manifest = JSON.parse(fs.readFileSync(cli.manifest, "utf-8")) as Record<string, unknown>;
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`Overlay manifest is not valid JSON (${cli.manifest}): ${message}`);
  }

  if (manifest.library_name !== cli.scriptName) {
    throw new Error(
      `Overlay manifest library_name mismatch: expected ${cli.scriptName}, got ${String(manifest.library_name)}`,
    );
  }
  if (manifest.recommended_import_path !== cli.importPath) {
    throw new Error(
      `Overlay manifest recommended_import_path mismatch: expected ${cli.importPath}, got ${String(manifest.recommended_import_path)}`,
    );
  }
  const snippet = String(manifest.core_import_snippet ?? "");
  if (!snippet.includes(expectedImportLine)) {
    throw new Error(
      `Overlay manifest core_import_snippet must contain "${expectedImportLine}", got "${snippet}"`,
    );
  }
  if (!Number.isFinite(cli.version) || cli.version < 1) {
    throw new Error(`Overlay library version must be a positive integer, received: ${cli.version}`);
  }
  if (manifest.library_version !== cli.version) {
    throw new Error(
      `Overlay manifest library_version mismatch: expected ${cli.version}, got ${String(manifest.library_version)}`,
    );
  }

  return {
    libraryPath: cli.library,
    manifestPath: cli.manifest,
    scriptName: cli.scriptName,
    importPath: cli.importPath,
    alias: cli.alias,
    version: cli.version,
  };
}

export async function runPublishOverlayLibraryCli(): Promise<number> {
  const cli = parseArgs();
  const runId = utcNow().replace(/[:.]/g, "-");
  const screenshots: string[] = [];
  let details: ContractDetails | null = null;
  let publishAttempted = false;
  let openMode: OpenMode = "fresh_draft";
  let openedExistingScript = false;
  let createdFreshDraft = false;
  let publishedScriptVerified = false;
  let identityVerificationMode: IdentityVerificationMode = "not_verified";
  let versionVerificationMode: VersionVerificationMode = "not_verified";
  let publishedVersion: number | null = null;
  let fallbackPublishedVersion: number | null = null;
  let noChangeDetected = false;
  let identityEvidenceContext: string[] = [];
  let versionEvidenceContext: string[] = [];
  let publishBodyText = "";

  try {
    details = verifyOverlayPublishContract(cli);
    const session = await newTradingViewSession();
    try {
      if (!session.authResolution.authReusedOk) {
        throw new Error("TradingView overlay publish requires a reusable authenticated session. Refresh TV_STORAGE_STATE or TV_PERSISTENT_PROFILE_DIR first.");
      }

      await gotoChart(session.page);
      await ensurePineEditor(session.page);

      if (cli.openExisting) {
        openedExistingScript = await openExistingScript(session.page, details.scriptName).catch(() => false);
        if (openedExistingScript) {
          openMode = "existing";
        } else if (!cli.allowCreate) {
          throw new Error(`Could not open existing TradingView script: ${details.scriptName}`);
        } else {
          await openFreshUntitledPineDraft(session.page, "library");
          createdFreshDraft = true;
          openMode = "fresh_draft";
        }
      } else {
        await openFreshUntitledPineDraft(session.page, "library");
        createdFreshDraft = true;
        openMode = "fresh_draft";
      }

      const code = fs.readFileSync(details.libraryPath, "utf-8");
      await setEditorContent(session.page, code);
      await saveScript(session.page, details.scriptName);
      await waitForPostSaveCompileSettlement(session.page, details.scriptName);
      await assertNoVisibleCompileError(session.page);
      await addCurrentScriptToChart(session.page, details.scriptName);
      await takeScreenshot(session.page, runId, `${details.scriptName}-compiled`, screenshots);

      publishAttempted = true;
      const publishResult = await publishPrivateScript(session.page, {
        scriptName: details.scriptName,
        title: details.scriptName,
        description: cli.description,
      });
      noChangeDetected = publishResult.noChangeDetected;
      publishBodyText = publishResult.bodyText;
      await takeScreenshot(session.page, runId, `${details.scriptName}-published`, screenshots);

      identityEvidenceContext = await collectOpenScriptIdentityTexts(session.page, details.scriptName).catch(() => []);
      versionEvidenceContext = [
        ...new Set([
          ...publishResult.versionContextTexts,
          ...(await collectPublishedVersionContextTexts(session.page, details.scriptName).catch(() => [])),
        ]),
      ];

      let bodyText = publishResult.bodyText || await session.page.locator("body").innerText().catch(() => "");
      let identityEvidence = resolveOpenScriptIdentityEvidence(details.scriptName, {
        dialogStillVisible: false,
        editorContextTexts: identityEvidenceContext,
        bodyText,
      });
      let versionEvidence = resolvePublishedVersionEvidence({
        scriptName: details.scriptName,
        versionContextTexts: versionEvidenceContext,
        bodyText,
      });
      identityVerificationMode = identityEvidence.verificationMode;
      versionVerificationMode = versionEvidence.verificationMode;
      publishedVersion = versionEvidence.publishedVersion;
      fallbackPublishedVersion = versionEvidence.fallbackVersion;

      if (
        noChangeDetected
        && versionVerificationMode === "not_verified"
        && (identityVerificationMode === "script_context" || hasExpectedImportPathEvidence(bodyText, details.importPath))
      ) {
        versionVerificationMode = "idempotent_no_change";
        publishedVersion = details.version;
      }

      if (!noChangeDetected && identityVerificationMode === "script_context" && versionVerificationMode === "not_verified") {
        await ensurePineEditor(session.page);
        const retryPublishResult = await publishPrivateScript(session.page, {
          scriptName: details.scriptName,
          title: details.scriptName,
          description: cli.description,
        });
        noChangeDetected = noChangeDetected || retryPublishResult.noChangeDetected;
        publishBodyText = retryPublishResult.bodyText || publishBodyText;
        await takeScreenshot(session.page, runId, `${details.scriptName}-published-retry`, screenshots);

        identityEvidenceContext = await collectOpenScriptIdentityTexts(session.page, details.scriptName).catch(() => []);
        versionEvidenceContext = [
          ...new Set([
            ...versionEvidenceContext,
            ...retryPublishResult.versionContextTexts,
            ...(await collectPublishedVersionContextTexts(session.page, details.scriptName).catch(() => [])),
          ]),
        ];

        bodyText = retryPublishResult.bodyText || await session.page.locator("body").innerText().catch(() => "");
        identityEvidence = resolveOpenScriptIdentityEvidence(details.scriptName, {
          dialogStillVisible: false,
          editorContextTexts: identityEvidenceContext,
          bodyText,
        });
        versionEvidence = resolvePublishedVersionEvidence({
          scriptName: details.scriptName,
          versionContextTexts: versionEvidenceContext,
          bodyText,
        });
        identityVerificationMode = identityEvidence.verificationMode;
        versionVerificationMode = versionEvidence.verificationMode;
        publishedVersion = versionEvidence.publishedVersion;
        fallbackPublishedVersion = versionEvidence.fallbackVersion;

        if (
          noChangeDetected
          && versionVerificationMode === "not_verified"
          && (identityVerificationMode === "script_context" || hasExpectedImportPathEvidence(bodyText, details.importPath))
        ) {
          versionVerificationMode = "idempotent_no_change";
          publishedVersion = details.version;
        }
      }

      let exactScriptVerified = identityVerificationMode === "script_context";
      let exactVersionVerified = (versionVerificationMode === "version_context" || versionVerificationMode === "idempotent_no_change")
        && publishedVersion === details.version;

      if (!noChangeDetected || !exactScriptVerified || !exactVersionVerified) {
        publishedScriptVerified = await openExistingScript(session.page, details.scriptName).catch(() => false);
        identityEvidenceContext = await collectOpenScriptIdentityTexts(session.page, details.scriptName).catch(() => []);
        versionEvidenceContext = await collectPublishedVersionContextTexts(session.page, details.scriptName).catch(() => []);
        bodyText = await session.page.locator("body").innerText().catch(() => "");

        identityEvidence = resolveOpenScriptIdentityEvidence(details.scriptName, {
          dialogStillVisible: false,
          editorContextTexts: identityEvidenceContext,
          bodyText,
        });
        versionEvidence = resolvePublishedVersionEvidence({
          scriptName: details.scriptName,
          versionContextTexts: versionEvidenceContext,
          bodyText,
        });
        identityVerificationMode = identityEvidence.verificationMode;
        versionVerificationMode = versionEvidence.verificationMode;
        publishedVersion = versionEvidence.publishedVersion;
        fallbackPublishedVersion = versionEvidence.fallbackVersion;

        if (
          noChangeDetected
          && versionVerificationMode === "not_verified"
          && (identityVerificationMode === "script_context" || hasExpectedImportPathEvidence(bodyText, details.importPath))
        ) {
          versionVerificationMode = "idempotent_no_change";
          publishedVersion = details.version;
        }

        exactScriptVerified = publishedScriptVerified || identityVerificationMode === "script_context";
        exactVersionVerified = (versionVerificationMode === "version_context" || versionVerificationMode === "idempotent_no_change")
          && publishedVersion === details.version;
      }

      if (!exactScriptVerified || !exactVersionVerified) {
        throw new Error(
          `Published TradingView overlay library could not be verified exactly: live_script_verified=${publishedScriptVerified}, identity_mode=${identityVerificationMode}, version_mode=${versionVerificationMode}, expected_version=${details.version}, detected_version=${publishedVersion ?? "unknown"}, no_change_detected=${noChangeDetected}`,
        );
      }
    } finally {
      await closeTradingViewSession(session);
    }

    const report: PublishOverlayReport = {
      generatedAt: utcNow(),
      ok: true,
      contractOk: true,
      publishAttempted,
      publishOk: true,
      openMode,
      openExistingRequested: cli.openExisting,
      openedExistingScript,
      createdFreshDraft,
      publishedScriptVerified,
      identityVerificationMode,
      versionVerificationMode,
      expectedImportPath: details.importPath,
      expectedVersion: details.version,
      publishedVersion,
      fallbackPublishedVersion,
      noChangeDetected,
      identityEvidenceContext,
      versionEvidenceContext,
      publishBodyText,
      screenshots,
    };
    writeJson(cli.out, report);
    process.stdout.write(JSON.stringify(report, null, 2));
    process.stdout.write("\n");
    return 0;
  } catch (error: unknown) {
    const message = error instanceof Error ? error.stack || error.message : String(error);
    const report: PublishOverlayReport = {
      generatedAt: utcNow(),
      ok: false,
      contractOk: details !== null,
      publishAttempted,
      publishOk: false,
      openMode,
      openExistingRequested: cli.openExisting,
      openedExistingScript,
      createdFreshDraft,
      publishedScriptVerified,
      identityVerificationMode,
      versionVerificationMode,
      expectedImportPath: details?.importPath ?? cli.importPath,
      expectedVersion: details?.version ?? cli.version,
      publishedVersion,
      fallbackPublishedVersion,
      noChangeDetected,
      identityEvidenceContext,
      versionEvidenceContext,
      publishBodyText,
      screenshots,
      error: message,
    };
    writeJson(cli.out, report);
    process.stdout.write(JSON.stringify(report, null, 2));
    process.stdout.write("\n");
    return 1;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runPublishOverlayLibraryCli()
    .then((code) => process.exit(code))
    .catch((error: unknown) => {
      console.error(error instanceof Error ? error.stack || error.message : String(error));
      process.exit(1);
    });
}

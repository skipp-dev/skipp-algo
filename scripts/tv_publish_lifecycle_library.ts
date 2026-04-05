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

type IdentityVerificationMode = "script_context" | "not_verified";
type VersionVerificationMode = "version_context" | "idempotent_no_change" | "body_fallback" | "not_verified";
type OpenMode = "existing" | "fresh_draft";

type CliArgs = {
  library: string;
  core: string;
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
  corePath: string;
  scriptName: string;
  importPath: string;
  alias: string;
  version: number;
};

type PublishLifecycleReport = {
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
    library: path.resolve(getFlag("--library", "SMC++/smc_lifecycle_private.pine")),
    core: path.resolve(getFlag("--core", "SMC_Core_Engine.pine")),
    scriptName: getFlag("--script-name", "smc_lifecycle_private"),
    importPath: getFlag("--import-path", "preuss_steffen/smc_lifecycle_private/1"),
    alias: getFlag("--alias", "ll"),
    version: Number(getFlag("--version", "1")),
    description: getFlag(
      "--description",
      "Private lifecycle, readiness, blocker, and risk-plan helpers consumed by SMC Core Engine.",
    ),
    out: path.resolve(
      getFlag(
        "--out",
        `automation/tradingview/reports/publish-lifecycle-library-${utcNow().replace(/[:.]/g, "-")}.json`,
      ),
    ),
    openExisting: hasFlag("--no-open-existing") ? false : true,
    allowCreate: hasFlag("--no-allow-create") ? false : true,
  };
}

function hasExpectedImportPathEvidence(bodyText: string, expectedImportPath: string): boolean {
  return bodyText.replace(/\s+/g, " ").includes(expectedImportPath);
}

function verifyLifecyclePublishContract(cli: CliArgs): ContractDetails {
  if (!fs.existsSync(cli.library)) {
    throw new Error(`Missing lifecycle library source: ${cli.library}`);
  }
  if (!fs.existsSync(cli.core)) {
    throw new Error(`Missing core consumer source: ${cli.core}`);
  }

  const libraryText = fs.readFileSync(cli.library, "utf-8");
  const coreText = fs.readFileSync(cli.core, "utf-8");
  const expectedLibraryHeader = `library("${cli.scriptName}"`;
  const expectedImportLine = `import ${cli.importPath} as ${cli.alias}`;

  if (!libraryText.includes(expectedLibraryHeader)) {
    throw new Error(`Lifecycle library header mismatch: expected ${expectedLibraryHeader}`);
  }
  if (!coreText.includes(expectedImportLine)) {
    throw new Error(`Core import mismatch: expected ${expectedImportLine}`);
  }
  if (!Number.isFinite(cli.version) || cli.version < 1) {
    throw new Error(`Lifecycle library version must be a positive integer, received: ${cli.version}`);
  }

  return {
    libraryPath: cli.library,
    corePath: cli.core,
    scriptName: cli.scriptName,
    importPath: cli.importPath,
    alias: cli.alias,
    version: cli.version,
  };
}

export async function runPublishLifecycleLibraryCli(): Promise<number> {
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
    details = verifyLifecyclePublishContract(cli);
    const session = await newTradingViewSession();
    try {
      if (!session.authResolution.authReusedOk) {
        throw new Error("TradingView lifecycle publish requires a reusable authenticated session. Refresh TV_STORAGE_STATE or TV_PERSISTENT_PROFILE_DIR first.");
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
          `Published TradingView lifecycle library could not be verified exactly: live_script_verified=${publishedScriptVerified}, identity_mode=${identityVerificationMode}, version_mode=${versionVerificationMode}, expected_version=${details.version}, detected_version=${publishedVersion ?? "unknown"}, no_change_detected=${noChangeDetected}`,
        );
      }
    } finally {
      await closeTradingViewSession(session);
    }

    const report: PublishLifecycleReport = {
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
    const report: PublishLifecycleReport = {
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
  runPublishLifecycleLibraryCli()
    .then((code) => process.exit(code))
    .catch((error: unknown) => {
      console.error(error instanceof Error ? error.stack || error.message : String(error));
      process.exit(1);
    });
}
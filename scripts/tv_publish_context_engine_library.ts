#!/usr/bin/env -S node --enable-source-maps

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { hasExpectedImportPathEvidence } from "./tv_publish_import_path_evidence.js";
import {
  addCurrentScriptToChart,
  assertNoVisibleCompileError,
  closeTradingViewSession,
  collectOpenScriptIdentityTexts,
  collectPublishedVersionContextTexts,
  ensurePineEditor,
  fetchPublishedLibraryVersionViaFacade,
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
type VersionVerificationMode = "version_context" | "idempotent_no_change" | "body_fallback" | "not_verified" | "facade_list";
type OpenMode = "existing" | "fresh_draft";

type CliArgs = {
  library: string;
  core: string;
  repoRoot: string;
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

type PublishContextEngineReport = {
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
    library: path.resolve(getFlag("--library", "SMC++/smc_context_engine_private.pine")),
    core: path.resolve(getFlag("--core", "SMC_Long_Dip_Suite.pine")),
    repoRoot: path.resolve(getFlag("--repo-root", ".")),
    scriptName: getFlag("--script-name", "smc_context_engine_private"),
    importPath: getFlag("--import-path", "preuss_steffen/smc_context_engine_private/2"),
    alias: getFlag("--alias", "cx"),
    // 2, not 1: the library was first published manually on 2026-07-15, and the
    // CE10132 fix (#3673) was published as an update, which TradingView bumped
    // to /2. Must stay in step with importPath above.
    version: Number(getFlag("--version", "2")),
    description: getFlag(
      "--description",
      "Private live context frames (structure / imbalance / zone) derived from the SMC engine primitives.",
    ),
    out: path.resolve(
      getFlag(
        "--out",
        `automation/tradingview/reports/publish-context-engine-library-${utcNow().replace(/[:.]/g, "-")}.json`,
      ),
    ),
    openExisting: hasFlag("--no-open-existing") ? false : true,
    allowCreate: hasFlag("--no-allow-create") ? false : true,
  };
}

/**
 * Every repo `.pine` that could pin a hand-lib: repo root + `SMC++/`.
 *
 * Mirrors the scope of `consumerPineFiles` in
 * tv_publish_hand_authored_libraries.ts, which is what actually rewrites the
 * pins after a publish. Kept local rather than imported: publishers are
 * standalone CLIs the orchestrator spawns, and this is a read-only scan.
 */
function consumerPineFiles(repoRoot: string): string[] {
  const out: string[] = [];
  for (const dir of [repoRoot, path.join(repoRoot, "SMC++")]) {
    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const e of entries) {
      if (e.isFile() && e.name.endsWith(".pine")) {
        out.push(path.join(dir, e.name));
      }
    }
  }
  return out;
}

/** Every consumer pin of `scriptName`, with the version each one names. */
function consumerPins(repoRoot: string, scriptName: string): { file: string; version: number }[] {
  const re = new RegExp(`import\\s+[A-Za-z0-9_]+\\/${scriptName}\\/(\\d+)`, "g");
  const pins: { file: string; version: number }[] = [];
  for (const file of consumerPineFiles(repoRoot)) {
    // The library declares itself; it is not its own consumer.
    if (path.basename(file) === `${scriptName}.pine`) {
      continue;
    }
    const text = fs.readFileSync(file, "utf-8");
    for (const m of text.matchAll(re)) {
      pins.push({ file, version: Number(m[1]) });
    }
  }
  return pins;
}

function verifyContextEnginePublishContract(cli: CliArgs): ContractDetails {
  if (!fs.existsSync(cli.library)) {
    throw new Error(`Missing context_engine library source: ${cli.library}`);
  }
  if (!fs.existsSync(cli.core)) {
    throw new Error(`Missing core consumer source: ${cli.core}`);
  }

  const libraryText = fs.readFileSync(cli.library, "utf-8");
  const expectedLibraryHeader = `library("${cli.scriptName}"`;
  const expectedImportLine = `import ${cli.importPath} as ${cli.alias}`;

  if (!libraryText.includes(expectedLibraryHeader)) {
    throw new Error(`Context engine library header mismatch: expected ${expectedLibraryHeader}`);
  }

  // Consumer pins: verified across EVERY repo .pine, not just the core.
  //
  // The siblings each hard-require SMC_Long_Dip_Suite to pin their library.
  // Two reasons that shape is wrong here:
  //
  //   1. Nothing pins this library yet (bus-v3 3.2 — the aggregated
  //      build_context_frame() and its consumers are a later slice). Requiring a
  //      pin inverts the order: a library must be published before any consumer
  //      can pin a real version. Unconditional, the check would make this
  //      publisher permanently unusable and force the manual paste it replaces.
  //
  //   2. The planned consumer is SMC_Context_Bus.pine (docs/smc-bus-roadmap.md),
  //      NOT the Suite. A core-only check would stay blind exactly when the
  //      library IS wired — the Suite would still not pin it, so a Context-Bus
  //      pin at the wrong version would sail through. That is the opposite of
  //      what the check is for.
  //
  // So: zero pins is a legal bootstrap; any pin that exists must name the
  // version being published. Repinning itself is not this script's job —
  // tv_publish_hand_authored_libraries.ts rewrites pins across every consumer
  // .pine after the ordered publish.
  const mismatched = consumerPins(cli.repoRoot, cli.scriptName).filter(
    (pin) => pin.version !== cli.version,
  );
  if (mismatched.length > 0) {
    const detail = mismatched
      .map((p) => `${path.relative(cli.repoRoot, p.file)} pins /${p.version}`)
      .join(", ");
    throw new Error(
      `Consumer pin mismatch: expected every consumer to pin ` +
        `${cli.scriptName}/${cli.version} (${expectedImportLine}), but ${detail}`,
    );
  }
  if (!Number.isFinite(cli.version) || cli.version < 1) {
    throw new Error(`Context engine library version must be a positive integer, received: ${cli.version}`);
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

export async function runPublishContextEngineLibraryCli(): Promise<number> {
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
    details = verifyContextEnginePublishContract(cli);
    const session = await newTradingViewSession();
    try {
      if (!session.authResolution.authReusedOk) {
        throw new Error("TradingView context_engine publish requires a reusable authenticated session. Refresh TV_STORAGE_STATE or TV_PERSISTENT_PROFILE_DIR first.");
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
      await addCurrentScriptToChart(session.page, details.scriptName, { tolerateFailure: true });
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

      // Facade authority (#3603/#3606 follow-up): the UI-text version
      // evidence settles on the hardcoded expected version, so a hand-lib
      // already past /1 on TV exits rc=1 not_verified despite a successful
      // publish. The pine-facade filter=published listing is authoritative
      // (filter=saved counts editor save revisions, not the importable
      // version) -- let it override; UI evidence stays the fallback.
      const facadeVersion = await fetchPublishedLibraryVersionViaFacade(session.page, details.scriptName).catch(() => null);
      if (facadeVersion !== null) {
        publishedVersion = facadeVersion;
        versionVerificationMode = "facade_list";
        exactVersionVerified = true;
      }

      if (!exactScriptVerified || !exactVersionVerified) {
        throw new Error(
          `Published TradingView context_engine library could not be verified exactly: live_script_verified=${publishedScriptVerified}, identity_mode=${identityVerificationMode}, version_mode=${versionVerificationMode}, expected_version=${details.version}, detected_version=${publishedVersion ?? "unknown"}, no_change_detected=${noChangeDetected}`,
        );
      }
    } finally {
      await closeTradingViewSession(session);
    }

    const report: PublishContextEngineReport = {
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
    const report: PublishContextEngineReport = {
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
  runPublishContextEngineLibraryCli()
    .then((code) => process.exit(code))
    .catch((error: unknown) => {
      console.error(error instanceof Error ? error.stack || error.message : String(error));
      process.exit(1);
    });
}

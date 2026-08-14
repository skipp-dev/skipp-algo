import fs from "node:fs";
import path from "node:path";

import { hasExpectedImportPathEvidence } from "../../../scripts/tv_publish_import_path_evidence.js";
import {
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
} from "./tv_shared.js";

export type ConsumerPin = { file: string; version: number };

/** Every repo .pine that may import a hand-authored library. */
export function consumerPineFiles(repoRoot: string): string[] {
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
export function consumerPins(repoRoot: string, scriptName: string): ConsumerPin[] {
  const re = new RegExp(`import\\s+[A-Za-z0-9_]+\\/${scriptName}\\/(\\d+)`, "g");
  const pins: ConsumerPin[] = [];
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

/**
 * The version the repo declares for `scriptName`.
 *
 * Zero pins is a legal bootstrap (a newly introduced private library version
 * that nothing imports yet) and yields `null`. Disagreement is a repo
 * inconsistency and aborts before any TradingView write, because publishing
 * against a guess would pick a winner silently.
 */
export function deriveExpectedVersion(
  repoRoot: string,
  scriptName: string,
): { version: number | null; pins: ConsumerPin[] } {
  const pins = consumerPins(repoRoot, scriptName);
  const distinct = [...new Set(pins.map((p) => p.version))];
  if (distinct.length > 1) {
    const detail = pins
      .map((p) => `${path.relative(repoRoot, p.file)} pins /${p.version}`)
      .join(", ");
    throw new Error(
      `Consumer pins disagree for ${scriptName}: ${detail}. `
        + `Reconcile the repo before publishing.`,
    );
  }
  return { version: distinct.length === 1 ? distinct[0] : null, pins };
}

/**
 * Whether a publish counts as verified.
 *
 * The pre-existing facade override (#3603/#3606) set acceptance to true
 * whenever the facade answered, without looking at the direction of the
 * difference. That kept bumped libraries from exiting rc=1, but it also
 * accepted a version BELOW every consumer pin — which means the wrong script
 * was addressed, not that content changed. This states both halves explicitly.
 *
 * `mode` restores the whitelist the source enforced alongside the numeric
 * comparison (`versionVerificationMode === "version_context" ||
 * "idempotent_no_change"`): without a facade answer, only those two modes
 * are exact evidence. `body_fallback` can carry a non-null, even
 * numerically-matching version, but it is a weaker signal that should not
 * pass on its own — the facade (or a stronger mode) has to back it up.
 */
export function resolveVersionAcceptance(input: {
  expected: number | null;
  published: number | null;
  mode: "version_context" | "idempotent_no_change" | "body_fallback" | "not_verified" | "facade_list";
  facadeAnswered: boolean;
}): { accepted: boolean; reason: string } {
  const { expected, published, mode, facadeAnswered } = input;
  if (published === null) {
    return { accepted: false, reason: "published version not verified" };
  }
  if (!facadeAnswered && mode !== "version_context" && mode !== "idempotent_no_change") {
    return {
      accepted: false,
      reason: `version mode ${mode} is not exact evidence and the facade did not verify the version`,
    };
  }
  if (expected === null) {
    return { accepted: true, reason: `bootstrap: no consumer pin, published /${published}` };
  }
  if (published < expected) {
    return {
      accepted: false,
      reason: `published /${published} is below the expected /${expected}`,
    };
  }
  if (published > expected) {
    if (facadeAnswered) {
      return { accepted: true, reason: `publish advanced /${expected} to /${published}` };
    }
    return {
      accepted: false,
      reason: `published /${published} exceeds the consumer pin /${expected} but the facade did not verify the version`,
    };
  }
  return { accepted: true, reason: `published /${published} matches the consumer pin` };
}

export type HandLibDescriptor = {
  scriptName: string;
  source: string;
  alias: string;
  noun: string;
  reportStem: string;
  description: string;
  /**
   * Opt-in to the advance-exactly-one contract that only
   * smc_context_engine_private has today (see
   * tv_publish_context_engine_library.ts:218-230): require
   * --expected-current-version and refuse unless it equals version - 1.
   */
  requiresExplicitVersionAdvance?: boolean;
};

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

type HandLibPublishReport = {
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

/**
 * The default `--version` when the flag is absent: the repo's consumer pins.
 *
 * Zero pins is a legal state (see `deriveExpectedVersion`'s docstring), but
 * it is not a legal *default* here — there is nothing to derive a target
 * version from, and the facade can only answer after the write while the
 * pre-publish contract check needs a concrete target before touching
 * TradingView. So an operator publishing a library nothing imports yet must
 * pass `--version` explicitly; this only supplies the default when the pins
 * agree.
 */
function resolveDefaultVersion(descriptor: HandLibDescriptor, repoRoot: string): number {
  const derived = deriveExpectedVersion(repoRoot, descriptor.scriptName).version;
  if (derived === null) {
    throw new Error(
      `No consumer pins found for ${descriptor.scriptName}. Publishing a library nothing imports yet requires passing --version explicitly.`,
    );
  }
  return derived;
}

function parseArgs(descriptor: HandLibDescriptor, argv: string[]): CliArgs {
  const args = argv;

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

  const repoRoot = path.resolve(getFlag("--repo-root", "."));
  // --version and --import-path have no literal default: an explicit flag
  // still wins. Absent --version, the repo's consumer pins decide it (see
  // resolveDefaultVersion) — disagreement aborts instead of guessing, and
  // zero pins requires --version explicitly rather than inventing one.
  const version = hasFlag("--version")
    ? Number(getFlag("--version", ""))
    : resolveDefaultVersion(descriptor, repoRoot);
  const importPath = hasFlag("--import-path")
    ? getFlag("--import-path", "")
    : `preuss_steffen/${descriptor.scriptName}/${version}`;

  return {
    library: path.resolve(getFlag("--library", descriptor.source)),
    core: path.resolve(getFlag("--core", "SMC_Long_Dip_Suite.pine")),
    repoRoot,
    scriptName: getFlag("--script-name", descriptor.scriptName),
    importPath,
    alias: getFlag("--alias", descriptor.alias),
    version,
    description: getFlag("--description", descriptor.description),
    out: path.resolve(
      getFlag(
        "--out",
        `automation/tradingview/reports/${descriptor.reportStem}-${utcNow().replace(/[:.]/g, "-")}.json`,
      ),
    ),
    openExisting: hasFlag("--no-open-existing") ? false : true,
    allowCreate: hasFlag("--no-allow-create") ? false : true,
  };
}

function verifyHandLibPublishContract(descriptor: HandLibDescriptor, cli: CliArgs): ContractDetails {
  if (!fs.existsSync(cli.library)) {
    throw new Error(`Missing ${descriptor.noun} library source: ${cli.library}`);
  }
  if (!fs.existsSync(cli.core)) {
    throw new Error(`Missing core consumer source: ${cli.core}`);
  }

  const libraryText = fs.readFileSync(cli.library, "utf-8");
  const expectedLibraryHeader = `library("${cli.scriptName}"`;
  const expectedImportLine = `import ${cli.importPath} as ${cli.alias}`;

  if (!libraryText.includes(expectedLibraryHeader)) {
    throw new Error(`${descriptor.noun} library header mismatch: expected ${expectedLibraryHeader}`);
  }

  // Consumer pins: verified across EVERY repo .pine, not just the core.
  //
  // The siblings each hard-require SMC_Long_Dip_Suite to pin their library.
  // Two reasons that shape is wrong here:
  //
  //   1. During the R3 bootstrap nothing pinned this library. The R4 Context
  //      Bus now does; keeping zero pins legal still preserves the ordered
  //      bootstrap path for a newly introduced private library version.
  //
  //   2. The consumer is SMC_Context_Bus.pine (docs/smc-bus-roadmap.md),
  //      NOT the Suite. A core-only check would stay blind exactly when the
  //      library IS wired — the Suite would still not pin it, so a Context-Bus
  //      pin at the wrong version would sail through. That is the opposite of
  //      what the check is for.
  //
  // So: zero pins is legal but requires an explicit --version here — there
  // is nothing to derive a target from (see resolveDefaultVersion) — and any
  // pin that exists must name the version being published. Repinning itself
  // is not this script's job — tv_publish_hand_authored_libraries.ts
  // rewrites pins across every consumer .pine after the ordered publish.
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
    throw new Error(`${descriptor.noun} library version must be a positive integer, received: ${cli.version}`);
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

export async function runHandLibPublish(descriptor: HandLibDescriptor, argv: string[]): Promise<number> {
  const runId = utcNow().replace(/[:.]/g, "-");
  const screenshots: string[] = [];
  let cli: CliArgs | null = null;
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
    if (descriptor.requiresExplicitVersionAdvance) {
      throw new Error(
        `${descriptor.scriptName} sets requiresExplicitVersionAdvance, but runHandLibPublish does not implement ` +
          "the advance-exactly-one contract yet (see tv_publish_context_engine_library.ts:218-230 for the shape " +
          "it opts into: --expected-current-version, refuse unless it equals version - 1). Refusing to publish " +
          "rather than silently skipping that check.",
      );
    }
    cli = parseArgs(descriptor, argv);
    details = verifyHandLibPublishContract(descriptor, cli);
    const session = await newTradingViewSession();
    try {
      if (!session.authResolution.authReusedOk) {
        throw new Error(`TradingView ${descriptor.noun} publish requires a reusable authenticated session. Refresh TV_STORAGE_STATE or TV_PERSISTENT_PROFILE_DIR first.`);
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

      if (
        !noChangeDetected
        || !exactScriptVerified
        || !resolveVersionAcceptance({ expected: details.version, published: publishedVersion, mode: versionVerificationMode, facadeAnswered: false }).accepted
      ) {
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
      }

      const versionAcceptance = resolveVersionAcceptance({
        expected: details.version,
        published: publishedVersion,
        mode: versionVerificationMode,
        facadeAnswered: facadeVersion !== null,
      });

      if (!exactScriptVerified || !versionAcceptance.accepted) {
        throw new Error(
          `Published TradingView ${descriptor.noun} library could not be verified exactly: live_script_verified=${publishedScriptVerified}, identity_mode=${identityVerificationMode}, version_mode=${versionVerificationMode}, expected_version=${details.version}, detected_version=${publishedVersion ?? "unknown"}, no_change_detected=${noChangeDetected}, version_acceptance=${versionAcceptance.reason}`,
        );
      }
    } finally {
      await closeTradingViewSession(session);
    }

    const report: HandLibPublishReport = {
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
    // cli can still be null here: parseArgs itself now runs inside this try
    // (it calls deriveExpectedVersion, which throws on disagreeing pins or
    // an underivable bootstrap version) and the requiresExplicitVersionAdvance
    // guard above it can also throw before parseArgs ever runs. Every other
    // failure path still writes a report, so fall back instead of crashing
    // the crash-report itself.
    const out = cli?.out ?? path.resolve(
      `automation/tradingview/reports/${descriptor.reportStem}-${utcNow().replace(/[:.]/g, "-")}.json`,
    );
    const report: HandLibPublishReport = {
      generatedAt: utcNow(),
      ok: false,
      contractOk: details !== null,
      publishAttempted,
      publishOk: false,
      openMode,
      openExistingRequested: cli?.openExisting ?? true,
      openedExistingScript,
      createdFreshDraft,
      publishedScriptVerified,
      identityVerificationMode,
      versionVerificationMode,
      expectedImportPath: details?.importPath ?? cli?.importPath ?? "",
      expectedVersion: details?.version ?? cli?.version ?? NaN,
      publishedVersion,
      fallbackPublishedVersion,
      noChangeDetected,
      identityEvidenceContext,
      versionEvidenceContext,
      publishBodyText,
      screenshots,
      error: message,
    };
    writeJson(out, report);
    process.stdout.write(JSON.stringify(report, null, 2));
    process.stdout.write("\n");
    return 1;
  }
}

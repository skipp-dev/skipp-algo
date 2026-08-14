import fs from "node:fs";
import path from "node:path";

import { hasExpectedImportPathEvidence } from "../../../scripts/tv_publish_import_path_evidence.js";
import {
  assertNoVisibleCompileError,
  closeTradingViewSession,
  collectOpenScriptIdentityTexts,
  collectPublishedVersionContextTexts,
  collectTradingViewPageAuthState,
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

/**
 * The committed record of what a verified publish observed on TradingView.
 *
 * Until 2026-08-14 the hand-authored tier had no equivalent of the generated
 * library's `library_release_manifest.json`: every publisher verified the
 * published version via the facade and then threw the number away into a
 * timestamped, uncommitted report. The repo could therefore prove that every
 * pin has an owner (tests/test_pine_pin_repin_ownership.py) but never that a
 * pin is CURRENT — the exact blindness behind the 2026-07 chain
 * (#3599/#3603, /1 against a live /152 for ~4 months).
 *
 * One file for all ten libraries, keyed by script name, rewritten
 * entry-by-entry as each publish verifies. `git add` in
 * pine-library-publish-handlibs.yml commits it in the same bot PR as the
 * repinned consumers, so the record and the pins move together. Entries are
 * only ever written from a live, facade-or-exact-evidence-verified publish —
 * never seeded by hand, which would be dated evidence nobody observed
 * (the vacuous-gates lesson: datierte Evidenz nie nachziehen).
 */
export const HANDLIB_RELEASE_MANIFEST = "artifacts/tradingview/handlib_release_manifest.json";

export type HandLibReleaseEntry = {
  publishedVersion: number;
  publishedAt: string;
  versionVerificationMode: string;
};

export type HandLibReleaseManifest = {
  schemaVersion: 1;
  libraries: Record<string, HandLibReleaseEntry>;
};

/**
 * Merge one library's verified publish observation into the manifest.
 *
 * Keys are sorted so ten publishes in any order produce byte-identical
 * output — the file is reviewed as a diff in the weekly repin PR, and an
 * order-dependent serialization would make every run's diff noise.
 */
export function recordHandLibRelease(
  repoRoot: string,
  scriptName: string,
  entry: HandLibReleaseEntry,
): string {
  const manifestPath = path.join(repoRoot, HANDLIB_RELEASE_MANIFEST);
  let manifest: HandLibReleaseManifest = { schemaVersion: 1, libraries: {} };
  if (fs.existsSync(manifestPath)) {
    manifest = JSON.parse(fs.readFileSync(manifestPath, "utf-8")) as HandLibReleaseManifest;
  }
  manifest.libraries[scriptName] = entry;
  const sorted: HandLibReleaseManifest = {
    schemaVersion: 1,
    libraries: Object.fromEntries(
      Object.entries(manifest.libraries).sort(([a], [b]) => a.localeCompare(b)),
    ),
  };
  writeJson(manifestPath, sorted);
  return manifestPath;
}

export type HandLibDescriptor = {
  scriptName: string;
  source: string;
  alias: string;
  noun: string;
  reportStem: string;
  description: string;
  /**
   * Opt-in to the extra-scrutiny path that only smc_context_engine_private
   * has today (2026-08-14 controller ruling). It bundles three behaviors
   * that were unique to the pre-conversion tv_publish_context_engine_library.ts
   * and have no equivalent for the other nine hand-libs, so this single flag
   * gates all three rather than inventing three descriptor fields for one
   * caller:
   *
   *   1. The advance-exactly-one contract itself: when `--version` is passed
   *      EXPLICITLY, `--expected-current-version` becomes required and must
   *      equal `version - 1` (see `assertVersionAdvance`). When the version
   *      is instead DERIVED from consumer pins (the orchestrator's actual
   *      call shape — see tv_publish_hand_authored_libraries.ts, which
   *      passes only --out and --no-allow-create), the contract does not
   *      apply; `ContractDetails.versionAdvanceContract` records which of
   *      the two happened rather than silently assuming either.
   *   2. A live page-auth probe (`collectTradingViewPageAuthState`) right
   *      after `gotoChart`, in addition to the static
   *      `session.authResolution.authReusedOk` check every publisher already
   *      has. `authReusedOk` only proves a local storage-state/profile file
   *      exists; it says nothing about whether TradingView still honors that
   *      session. This catches a locally-valid-looking session TradingView
   *      has actually expired/logged out server-side.
   *   3. A preflight fetch of the CURRENTLY published version via the facade
   *      — before the editor is touched — compared against
   *      `expectedCurrentVersion` (only meaningful when the advance contract
   *      is enforced, see (1)). Fails closed: a stale operator assumption
   *      about the current published version must never turn an intended
   *      /3 publish into /4, or overwrite a newer private release, by
   *      mutation.
   */
  requiresExplicitVersionAdvance?: boolean;
};

/**
 * The advance-exactly-one contract: `expectedCurrentVersion` must equal
 * `version - 1`. Thrown message keeps the substring "must advance exactly
 * one version" — matched by operator runbooks.
 */
export function assertVersionAdvance(input: {
  expectedCurrentVersion: number;
  version: number;
  noun: string;
}): void {
  const { expectedCurrentVersion, version, noun } = input;
  if (!Number.isInteger(expectedCurrentVersion) || expectedCurrentVersion < 1) {
    throw new Error(
      `${noun} expected current version must be a positive integer, received: ${expectedCurrentVersion}`,
    );
  }
  if (expectedCurrentVersion !== version - 1) {
    throw new Error(
      `${noun} publish must advance exactly one version: expected_current=${expectedCurrentVersion}, target=${version}`,
    );
  }
}

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
  /** Whether `--version` was passed explicitly, vs. derived from consumer pins. */
  versionExplicit?: boolean;
  /** Only meaningful (and only ever set) when `versionExplicit` is true. */
  expectedCurrentVersion?: number;
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
  /** Ported into the report only when the advance contract is enforced. */
  expectedCurrentVersion?: number;
  /**
   * Whether the advance-exactly-one contract ran ("enforced") or was
   * skipped because the version came from consumer pins rather than an
   * explicit --version ("skipped_derived_version"). Absent entirely for
   * descriptors that do not opt into `requiresExplicitVersionAdvance`.
   */
  versionAdvanceContract?: "enforced" | "skipped_derived_version";
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
  /** Only meaningful for descriptors with requiresExplicitVersionAdvance. */
  expectedCurrentVersion?: number;
  versionAdvanceContract?: "enforced" | "skipped_derived_version";
  /** Live TradingView page-auth probe; only run for requiresExplicitVersionAdvance descriptors. */
  pageAuthenticated?: boolean;
  /** Pre-editor-mutation facade read of the currently published version; enforced-contract only. */
  preflightPublishedVersion?: number | null;
  preflightVersionOk?: boolean;
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
  const versionExplicit = hasFlag("--version");
  const version = versionExplicit
    ? Number(getFlag("--version", ""))
    : resolveDefaultVersion(descriptor, repoRoot);
  const importPath = hasFlag("--import-path")
    ? getFlag("--import-path", "")
    : `preuss_steffen/${descriptor.scriptName}/${version}`;
  // Only captured here, not validated: verifyHandLibPublishContract decides
  // whether it is required (only when the descriptor opts into the advance
  // contract AND --version was explicit) so that the "missing" error stays
  // next to every other contract check instead of splitting flag-presence
  // logic across two functions.
  const expectedCurrentVersion = hasFlag("--expected-current-version")
    ? Number(getFlag("--expected-current-version", ""))
    : undefined;

  return {
    library: path.resolve(getFlag("--library", descriptor.source)),
    core: path.resolve(getFlag("--core", "SMC_Long_Dip_Suite.pine")),
    repoRoot,
    scriptName: getFlag("--script-name", descriptor.scriptName),
    importPath,
    alias: getFlag("--alias", descriptor.alias),
    version,
    versionExplicit,
    expectedCurrentVersion,
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

export function verifyHandLibPublishContract(descriptor: HandLibDescriptor, cli: CliArgs): ContractDetails {
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
  if (!Number.isInteger(cli.version) || cli.version < 1) {
    throw new Error(`${descriptor.noun} library version must be a positive integer, received: ${cli.version}`);
  }

  // Import-path coherence, ported from the pre-conversion smc_engine_private
  // publisher (the only one of the ten hand-authored publishers that had it;
  // every other publisher scored zero on this check). The default
  // --import-path is always coherent by construction (see resolveDefaultVersion
  // / parseArgs, which derive it from scriptName and version), so this only
  // bites an operator who explicitly passes --import-path naming the wrong
  // library or the wrong version -- exactly the case none of the checks above
  // catch, since the header check, the consumer-pin check, and the
  // integer-version check never look at the import path's own text.
  const importIdentity = cli.importPath.match(/^([^/]+)\/([^/]+)\/(\d+)$/);
  if (!importIdentity || importIdentity[2] !== cli.scriptName || Number(importIdentity[3]) !== cli.version) {
    throw new Error(
      `${descriptor.noun} import path must name ${cli.scriptName}/${cli.version}, received: ${cli.importPath}`,
    );
  }

  // The advance-exactly-one contract (controller ruling, 2026-08-14):
  // enforced only when --version was passed explicitly. When the version is
  // derived from consumer pins there is nothing an operator asserted about
  // "the current version" to check against — inventing expectedCurrentVersion
  // = derived - 1 would make the check true by construction, a vacuous guard
  // that looks alive. So the derived path records an explicit skip instead
  // of a silent pass.
  let expectedCurrentVersion: number | undefined;
  let versionAdvanceContract: "enforced" | "skipped_derived_version" | undefined;
  if (descriptor.requiresExplicitVersionAdvance) {
    if (!cli.versionExplicit) {
      versionAdvanceContract = "skipped_derived_version";
    } else if (cli.expectedCurrentVersion === undefined) {
      throw new Error(
        `${descriptor.noun} publish requires --expected-current-version when --version is passed explicitly.`,
      );
    } else {
      assertVersionAdvance({
        expectedCurrentVersion: cli.expectedCurrentVersion,
        version: cli.version,
        noun: descriptor.noun,
      });
      expectedCurrentVersion = cli.expectedCurrentVersion;
      versionAdvanceContract = "enforced";
    }
  }

  return {
    libraryPath: cli.library,
    corePath: cli.core,
    scriptName: cli.scriptName,
    importPath: cli.importPath,
    alias: cli.alias,
    version: cli.version,
    expectedCurrentVersion,
    versionAdvanceContract,
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
  // Only ever set for descriptors with requiresExplicitVersionAdvance (see
  // that field's docstring for why these three ride along with it).
  let pageAuthenticated: boolean | undefined;
  let preflightPublishedVersion: number | null | undefined;
  let preflightVersionOk: boolean | undefined;

  try {
    cli = parseArgs(descriptor, argv);
    details = verifyHandLibPublishContract(descriptor, cli);
    const session = await newTradingViewSession();
    try {
      if (!session.authResolution.authReusedOk) {
        throw new Error(`TradingView ${descriptor.noun} publish requires a reusable authenticated session. Refresh TV_STORAGE_STATE or TV_PERSISTENT_PROFILE_DIR first.`);
      }

      await gotoChart(session.page);

      if (descriptor.requiresExplicitVersionAdvance) {
        // Live page-auth probe, in addition to the static authReusedOk check
        // above: authReusedOk only proves a local storage-state/profile file
        // exists, not that TradingView still honors that session.
        const pageAuthState = await collectTradingViewPageAuthState(session.page);
        pageAuthenticated = pageAuthState.authenticated;
        if (!pageAuthenticated) {
          throw new Error(
            "TradingView rejected the configured auth source as anonymous. " +
              "Refresh TV_STORAGE_STATE or use an authenticated persistent profile before publishing.",
          );
        }

        if (details.versionAdvanceContract === "enforced") {
          // Fail closed before touching the editor. A stale operator
          // assumption about the current published version must never turn
          // an intended /3 publish into /4 (or overwrite a newer private
          // release).
          preflightPublishedVersion = await fetchPublishedLibraryVersionViaFacade(
            session.page,
            details.scriptName,
          ).catch(() => null);
          preflightVersionOk = preflightPublishedVersion === details.expectedCurrentVersion;
          if (!preflightVersionOk) {
            throw new Error(
              `${descriptor.noun} publish predecessor mismatch: expected_current=${details.expectedCurrentVersion}, ` +
                `detected_current=${preflightPublishedVersion ?? "unknown"}, target=${details.version}. ` +
                "No editor or publish mutation was attempted.",
            );
          }
        }
      }

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

    // Reached only past the acceptance throw above, so this is a VERIFIED
    // observation of what TradingView holds right now — the one fact the
    // repo could never state about the hand libs. resolveVersionAcceptance
    // rejects a null published version, so the guard is for the type system,
    // not a reachable skip.
    if (publishedVersion !== null) {
      recordHandLibRelease(cli.repoRoot, details.scriptName, {
        publishedVersion,
        publishedAt: utcNow(),
        versionVerificationMode,
      });
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
      expectedCurrentVersion: details.expectedCurrentVersion,
      versionAdvanceContract: details.versionAdvanceContract,
      pageAuthenticated,
      preflightPublishedVersion,
      preflightVersionOk,
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
    // cli can still be null here: parseArgs itself runs inside this try (it
    // calls deriveExpectedVersion, which throws on disagreeing pins or an
    // underivable bootstrap version, and verifyHandLibPublishContract's own
    // advance-contract check can throw before details is assigned). Every
    // other failure path still writes a report, so fall back instead of
    // crashing the crash-report itself.
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
      expectedCurrentVersion: details?.expectedCurrentVersion ?? cli?.expectedCurrentVersion,
      versionAdvanceContract: details?.versionAdvanceContract,
      pageAuthenticated,
      preflightPublishedVersion,
      preflightVersionOk,
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

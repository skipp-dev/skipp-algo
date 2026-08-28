/**
 * Save a hand-authored consumer's repo source into an existing TradingView
 * saved script. Consumers are saved indicators/strategies, not published
 * libraries, so this deliberately opens an exact saved name and never creates
 * a replacement when that name is missing.
 */
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

import { normalizedPineSha256 } from "../automation/tradingview/lib/tv_consumer_rollout_evidence.js";
import {
  assertNoVisibleCompileError,
  closeTradingViewSession,
  ensurePineEditor,
  extractPineDeclarationTitle,
  fetchSavedScriptSourceViaFacade,
  gotoChart,
  newTradingViewSession,
  openExistingScript,
  pineDeclarationTitlePattern,
  readEditorContent,
  saveScript,
  setEditorContent,
  tracePageEvent,
  waitForPostSaveCompileSettlement,
  type TradingViewSession,
} from "../automation/tradingview/lib/tv_shared.js";

export type SaveConsumerTarget = {
  source: string;
  scriptName: string;
  /**
   * Pine declaration title, when it differs from the saved-document name.
   *
   * For every default rollout consumer the two are identical, and the drift
   * machinery treats a mismatch as repairable contamination. The Hold Manager
   * validation script is the measured exception (run 31868334987,
   * 2026-08-15): the saved document is "SMC Hold Manager R2.4 Validation"
   * while the source declares "SMC Hold Manager", so the name-derived
   * identity check refused a perfectly correct document. With an explicit
   * declarationTitle the identity proof stays two-legged -- exact saved-
   * document title via the picker, buffer declaration STRICTLY against this
   * value -- but both legs are named instead of assumed equal.
   */
  declarationTitle?: string;
};

export function expectedDeclarationOf(target: SaveConsumerTarget): string {
  return target.declarationTitle ?? target.scriptName;
}
export type SaveConsumerResult = {
  ok: true;
  scriptName: string;
  sourcePath: string;
  bytes: number;
  expectedSha256: string;
  preWriteIdentityVerified: true;
  preWriteIdentityMode: "declaration" | "document_title_model_transition";
  stagedSourceVerified: true;
  postSaveSourceVerified: true;
  /**
   * True only when the pine-facade saved-script store returned this slot
   * after the save and it carried the target declaration AND the expected
   * hash. False means the facade was unavailable (traced) — the buffer
   * checks above still passed, but they cannot see WHERE TradingView bound
   * the save (run 33031264859 wrote one consumer's source into a sibling
   * slot with every buffer check green).
   */
  persistedSourceVerified: boolean;
};
export type VerifyConsumerSourceResult = {
  ok: boolean;
  matches: boolean;
  scriptName: string;
  sourcePath: string;
  expectedSha256: string;
  actualSha256: string;
  expectedBytes: number;
  actualBytes: number;
  /**
   * Where actualSha256 came from: the pine-facade saved-script store (the
   * persisted state the Indicators dialog serves) or the Pine-editor
   * fallback (chooser + Monaco buffer — the surface that verified this
   * run's own writes in run 33031264859 while the store held a cross-write).
   */
  readbackAuthority: "facade_saved_store" | "editor_fallback";
  persistedVersion: number | null;
};

/** Trace-event name for a fail-closed readback identity refusal. */
export const SOURCE_READBACK_IDENTITY_MISMATCH_EVENT = "source-readback-identity-mismatch";
/** Trace-event name for a fail-closed post-save persisted-slot refusal. */
export const SOURCE_SAVE_PERSISTED_MISMATCH_EVENT = "source-save-persisted-mismatch";

export type PersistedReadbackVerdict =
  | { verdict: "match"; actualSha256: string }
  | { verdict: "identity-mismatch"; foundTitle: string | null; traceDetail: string }
  | { verdict: "sha-mismatch"; actualSha256: string };

/**
 * Judge a PERSISTED source (facade store, or a freshly loaded editor buffer)
 * against a consumer target. Identity first: whatever the slot serves must
 * DECLARE the target's own title before any hash comparison — a slot serving
 * a sibling consumer's source (the proven 2026-08-27 cross-write:
 * "SMC Long-Dip Mobile" carrying strategy("SMC Long-Dip Strategy")) is an
 * identity mismatch, never merely a stale hash. Pure and exported for
 * hermetic tests.
 */
export function judgePersistedConsumerSource(
  target: SaveConsumerTarget,
  persistedSource: string,
  expectedSha256: string,
): PersistedReadbackVerdict {
  const expectedTitle = expectedDeclarationOf(target);
  const foundTitle = extractPineDeclarationTitle(persistedSource);
  if (foundTitle !== expectedTitle) {
    return {
      verdict: "identity-mismatch",
      foundTitle,
      traceDetail: `${target.scriptName}:${foundTitle ?? "no-declaration"}`,
    };
  }
  const actualSha256 = pineSourceSha256(persistedSource);
  return actualSha256 === expectedSha256
    ? { verdict: "match", actualSha256 }
    : { verdict: "sha-mismatch", actualSha256 };
}

export function pineSourceSha256(source: string): string {
  return normalizedPineSha256(source);
}

export function assertConsumerEditorSource(
  phase: "staged source" | "post-save source",
  target: SaveConsumerTarget,
  actual: string,
  expectedSha256?: string,
): string {
  const declaration = pineDeclarationTitlePattern(expectedDeclarationOf(target));
  if (!declaration.test(actual)) {
    throw new Error(
      `${phase} verification failed for ${target.scriptName}: active Pine model has a different declaration`,
    );
  }

  const actualSha256 = pineSourceSha256(actual);
  if (expectedSha256 && actualSha256 !== expectedSha256) {
    throw new Error(
      `${phase} verification failed for ${target.scriptName}: expected SHA-256 ${expectedSha256}, got ${actualSha256}`,
    );
  }
  return actualSha256;
}

export function assertConsumerPreWriteSource(
  target: SaveConsumerTarget,
  actual: string,
): "declaration" | "document_title_model_transition" {
  if (pineDeclarationTitlePattern(expectedDeclarationOf(target)).test(actual)) {
    return "declaration";
  }
  if (target.declarationTitle) {
    // An explicit declarationTitle is a strict claim: the drift-repair
    // fallback below exists for name==declaration consumers whose saved
    // document got contaminated, not for a document whose declared identity
    // the mapping already states. Failing here is the fix, not drift.
    throw new Error(
      `pre-write identity verification failed for ${target.scriptName}: active Pine model does not declare ${target.declarationTitle}`,
    );
  }
  if (!/\b(?:indicator|strategy|library)\s*\(\s*["']/m.test(actual)) {
    throw new Error(
      `pre-write identity verification failed for ${target.scriptName}: active Pine model has no declaration`,
    );
  }
  // openExistingScript supplied the other two independent identity signals:
  // the exact canonical saved-document title with a closed picker, and a
  // stable visible Monaco-buffer transition from the pre-selection source.
  // A different declaration is therefore repairable drift, not proof that
  // the wrong TradingView document is selected.
  return "document_title_model_transition";
}

function getFlag(name: string, fallback = ""): string {
  const args = process.argv.slice(2);
  const index = args.indexOf(name);
  return index === -1 || !args[index + 1] ? fallback : args[index + 1];
}

export async function saveConsumerSource(
  session: TradingViewSession,
  target: SaveConsumerTarget,
): Promise<SaveConsumerResult> {
  const sourcePath = path.resolve(target.source);
  if (!fs.existsSync(sourcePath)) throw new Error(`Missing source: ${sourcePath}`);
  const code = fs.readFileSync(sourcePath, "utf-8");
  const expectedSha256 = pineSourceSha256(code);

  const nameIsDeclaration = expectedDeclarationOf(target) === target.scriptName;
  const opened = await openExistingScript(session.page, target.scriptName, {
    forceSelection: true,
    // With an explicit declarationTitle the name-derived declaration check
    // would refuse the correct document (measured: run 31868334987); the
    // strict buffer-declaration assertion below carries that leg instead.
    requireVisibleDeclarationIdentity: nameIsDeclaration,
    allowDeclarationDriftRepair: nameIsDeclaration,
  });
  if (!opened) throw new Error(`Could not open existing saved script: ${target.scriptName}`);

  // Prefer declaration identity. If the saved document itself is contaminated
  // (observed 2026-07-27: the canonical Suite document contained the Alerts
  // declaration), openExistingScript permits repair only after proving the
  // exact canonical document title, a closed picker, and a stable visible
  // Monaco-buffer transition from the pre-selection source.
  const preWriteSource = await readEditorContent(session.page, {
    editorAlreadyOpen: true,
    requireVisibleEditor: true,
  });
  const preWriteIdentityMode = assertConsumerPreWriteSource(target, preWriteSource);

  // The model assertion above proves the editor surface is ready. Re-running
  // ensurePineEditor here costs ~26s per consumer on the live chart.
  await setEditorContent(session.page, code, { editorAlreadyOpen: true });

  // Prove the paste landed in the declaration-pinned target model before
  // invoking TradingView's save command.
  const stagedSource = await readEditorContent(session.page, {
    editorAlreadyOpen: true,
    expectedDeclarationTitle: expectedDeclarationOf(target),
    requireVisibleEditor: true,
  });
  assertConsumerEditorSource("staged source", target, stagedSource, expectedSha256);

  await saveScript(session.page, target.scriptName);
  await waitForPostSaveCompileSettlement(session.page, target.scriptName);
  await assertNoVisibleCompileError(session.page);

  // Verify the editor after TradingView acknowledged the save. The coordinated
  // batch then reloads the chart before its authoritative hash verification,
  // so an in-memory edit that did not persist cannot turn the rollout green.
  const postSaveSource = await readEditorContent(session.page, {
    editorAlreadyOpen: true,
    expectedDeclarationTitle: expectedDeclarationOf(target),
    requireVisibleEditor: true,
  });
  assertConsumerEditorSource("post-save source", target, postSaveSource, expectedSha256);

  // Persisted-store proof. Every check above reads the Monaco buffer, and the
  // buffer cannot see WHERE TradingView bound the save: run 33031264859
  // (2026-08-27) persisted one consumer's source into a sibling's slot with
  // pre-write, staged and post-save checks all green. The pine-facade
  // saved-script store is the state the Indicators dialog serves, so it is
  // the surface the operator's cross-write proof came from. Facade outage is
  // traced and non-fatal — the batch verify pass re-checks every slot — but a
  // resolved slot that carries a foreign declaration or the wrong hash fails
  // the save immediately.
  const persisted = await fetchSavedScriptSourceViaFacade(session.page, target.scriptName);
  let persistedSourceVerified = false;
  if (persisted) {
    const judged = judgePersistedConsumerSource(target, persisted.source, expectedSha256);
    if (judged.verdict === "identity-mismatch") {
      tracePageEvent(session.page, SOURCE_SAVE_PERSISTED_MISMATCH_EVENT, judged.traceDetail);
      throw new Error(
        `post-save persisted verification failed for ${target.scriptName}: saved-script slot declares `
        + `${judged.foundTitle ?? "no title"} instead of ${expectedDeclarationOf(target)}`,
      );
    }
    if (judged.verdict === "sha-mismatch") {
      tracePageEvent(
        session.page,
        SOURCE_SAVE_PERSISTED_MISMATCH_EVENT,
        `${target.scriptName}:sha:${judged.actualSha256}`,
      );
      throw new Error(
        `post-save persisted verification failed for ${target.scriptName}: saved-script slot holds `
        + `SHA-256 ${judged.actualSha256}, expected ${expectedSha256}`,
      );
    }
    persistedSourceVerified = true;
    tracePageEvent(session.page, "source-save-persisted-verified", `${target.scriptName}:v${persisted.version}`);
  } else {
    tracePageEvent(session.page, "source-save-persisted-unverified", `${target.scriptName}:facade-unavailable`);
  }

  return {
    ok: true,
    scriptName: target.scriptName,
    sourcePath,
    bytes: code.length,
    expectedSha256,
    preWriteIdentityVerified: true,
    preWriteIdentityMode,
    stagedSourceVerified: true,
    postSaveSourceVerified: true,
    persistedSourceVerified,
  };
}

/**
 * Compare the PERSISTED saved TradingView script source with the repo source.
 *
 * Authority order (2026-08-28, after run 33031264859):
 *
 *  1. pine-facade saved-script store — the persisted state the Indicators
 *     dialog serves. This bypasses the Pine editor entirely, because the
 *     editor serves per-script working buffers that survive even a hard page
 *     reload: run 33031264859 reloaded at 11:08:02Z and its verify pass STILL
 *     hashed this run's own staged content for "SMC Long-Dip Mobile"
 *     (matches=true, report 11:25:36Z) while the persisted slot held the
 *     "SMC Long-Dip Strategy" source at the same run's pin /364 (operator
 *     proof 2026-08-28: Pine-editor open AND a fresh add from the Indicators
 *     dialog). The old chooser+Monaco read was structurally unable to see
 *     that: readEditorContent SELECTS the buffer BY the expected declaration
 *     pattern, so it answers "does any visible buffer look like what I
 *     expect", never "what does the slot contain".
 *  2. Editor fallback (facade unavailable, reason traced): fresh chooser
 *     open, then read WITHOUT an expected-declaration filter so the loaded
 *     buffer itself — not a buffer hunted down by expectation — is judged.
 *
 * Both paths are identity-gated fail-closed: whatever the slot serves must
 * declare the target's own title before the hash comparison; a foreign
 * declaration throws with SOURCE_READBACK_IDENTITY_MISMATCH_EVENT
 * (`source-readback-identity-mismatch <name>:<foundTitle>`).
 */
export async function verifyConsumerSource(
  session: TradingViewSession,
  target: SaveConsumerTarget,
): Promise<VerifyConsumerSourceResult> {
  const sourcePath = path.resolve(target.source);
  if (!fs.existsSync(sourcePath)) throw new Error(`Missing source: ${sourcePath}`);
  const expected = fs.readFileSync(sourcePath, "utf-8");
  const expectedSha256 = pineSourceSha256(expected);

  const persisted = await fetchSavedScriptSourceViaFacade(session.page, target.scriptName);
  let actual: string;
  let readbackAuthority: VerifyConsumerSourceResult["readbackAuthority"];
  let persistedVersion: number | null;
  if (persisted) {
    tracePageEvent(session.page, "source-readback-authority", `facade:${target.scriptName}:v${persisted.version}`);
    actual = persisted.source;
    readbackAuthority = "facade_saved_store";
    persistedVersion = persisted.version;
  } else {
    tracePageEvent(session.page, "source-readback-authority", `editor-fallback:${target.scriptName}`);
    const opened = await openExistingScript(session.page, target.scriptName, {
      forceSelection: true,
      requireVisibleDeclarationIdentity: expectedDeclarationOf(target) === target.scriptName,
    });
    if (!opened) throw new Error(`Could not open existing saved script for source verification: ${target.scriptName}`);
    // Deliberately NO expectedDeclarationTitle: filtering by the expected
    // declaration is how the blind readback selected this session's own
    // buffer. Read what the open actually loaded; the identity judgement
    // below rejects a foreign buffer instead of hunting for a matching one.
    actual = await readEditorContent(session.page, {
      editorAlreadyOpen: true,
      requireVisibleEditor: true,
    });
    readbackAuthority = "editor_fallback";
    persistedVersion = null;
  }

  const judged = judgePersistedConsumerSource(target, actual, expectedSha256);
  if (judged.verdict === "identity-mismatch") {
    tracePageEvent(session.page, SOURCE_READBACK_IDENTITY_MISMATCH_EVENT, judged.traceDetail);
    throw new Error(
      `persisted source for ${target.scriptName} declares ${judged.foundTitle ?? "no title"} instead of `
      + `${expectedDeclarationOf(target)} (${readbackAuthority}) — refusing the hash comparison fail-closed`,
    );
  }
  const actualSha256 = judged.actualSha256;
  const matches = judged.verdict === "match";
  return {
    ok: matches,
    matches,
    scriptName: target.scriptName,
    sourcePath,
    expectedSha256,
    actualSha256,
    expectedBytes: Buffer.byteLength(expected, "utf-8"),
    actualBytes: Buffer.byteLength(actual, "utf-8"),
    readbackAuthority,
    persistedVersion,
  };
}

export async function runSaveConsumerSourceCli(): Promise<number> {
  const source = getFlag("--source");
  const scriptName = getFlag("--script-name");
  if (!source) throw new Error("Missing --source");
  if (!scriptName) throw new Error("Missing --script-name");

  const session = await newTradingViewSession();
  try {
    if (!session.authResolution.authReusedOk) {
      throw new Error("Save requires a reusable authenticated TradingView session");
    }
    await gotoChart(session.page);
    await ensurePineEditor(session.page);
    console.log(JSON.stringify(await saveConsumerSource(session, { source, scriptName })));
    return 0;
  } finally {
    await closeTradingViewSession(session);
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runSaveConsumerSourceCli()
    .then((rc) => process.exit(rc))
    .catch((error) => {
      console.error(JSON.stringify({ ok: false, error: String(error?.message ?? error) }));
      process.exit(1);
    });
}

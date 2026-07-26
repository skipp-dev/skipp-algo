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
  gotoChart,
  newTradingViewSession,
  openExistingScript,
  pineDeclarationTitlePattern,
  readEditorContent,
  saveScript,
  setEditorContent,
  waitForPostSaveCompileSettlement,
  type TradingViewSession,
} from "../automation/tradingview/lib/tv_shared.js";

export type SaveConsumerTarget = { source: string; scriptName: string };
export type SaveConsumerResult = {
  ok: true;
  scriptName: string;
  sourcePath: string;
  bytes: number;
  expectedSha256: string;
  preWriteIdentityVerified: true;
  stagedSourceVerified: true;
  postSaveSourceVerified: true;
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
};

export function pineSourceSha256(source: string): string {
  return normalizedPineSha256(source);
}

export function assertConsumerEditorSource(
  phase: "pre-write identity" | "staged source" | "post-save source",
  target: SaveConsumerTarget,
  actual: string,
  expectedSha256?: string,
): string {
  const declaration = pineDeclarationTitlePattern(target.scriptName);
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

  const opened = await openExistingScript(session.page, target.scriptName, { forceSelection: true }).catch(() => false);
  if (!opened) throw new Error(`Could not open existing saved script: ${target.scriptName}`);

  // UI title/context evidence is not sufficient write authority. TradingView
  // can repaint the requested saved-script title while Monaco still exposes a
  // different script buffer (observed 2026-07-26: selecting Suite left Alerts
  // active). Pin the actual Monaco model by its Pine declaration BEFORE paste;
  // a stale/wrong model therefore fails closed without changing any source.
  const preWriteSource = await readEditorContent(session.page, {
    editorAlreadyOpen: true,
    expectedDeclarationTitle: target.scriptName,
    requireVisibleEditor: true,
  });
  assertConsumerEditorSource("pre-write identity", target, preWriteSource);

  // The model assertion above proves the editor surface is ready. Re-running
  // ensurePineEditor here costs ~26s per consumer on the live chart.
  await setEditorContent(session.page, code, { editorAlreadyOpen: true });

  // Prove the paste landed in the declaration-pinned target model before
  // invoking TradingView's save command.
  const stagedSource = await readEditorContent(session.page, {
    editorAlreadyOpen: true,
    expectedDeclarationTitle: target.scriptName,
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
    expectedDeclarationTitle: target.scriptName,
    requireVisibleEditor: true,
  });
  assertConsumerEditorSource("post-save source", target, postSaveSource, expectedSha256);

  return {
    ok: true,
    scriptName: target.scriptName,
    sourcePath,
    bytes: code.length,
    expectedSha256,
    preWriteIdentityVerified: true,
    stagedSourceVerified: true,
    postSaveSourceVerified: true,
  };
}

/** Compare the actual saved TradingView editor source with the repo source. */
export async function verifyConsumerSource(
  session: TradingViewSession,
  target: SaveConsumerTarget,
): Promise<VerifyConsumerSourceResult> {
  const sourcePath = path.resolve(target.source);
  if (!fs.existsSync(sourcePath)) throw new Error(`Missing source: ${sourcePath}`);
  const expected = fs.readFileSync(sourcePath, "utf-8");
  const opened = await openExistingScript(session.page, target.scriptName, { forceSelection: true }).catch(() => false);
  if (!opened) throw new Error(`Could not open existing saved script for source verification: ${target.scriptName}`);
  // The saved script name IS the Pine declaration title for every rollout
  // consumer (asserted by the tv:test declaration-title contract), so it pins
  // the Monaco model of THIS script instead of an arbitrary page buffer.
  const actual = await readEditorContent(session.page, {
    editorAlreadyOpen: true,
    expectedDeclarationTitle: target.scriptName,
  });
  const expectedSha256 = pineSourceSha256(expected);
  const actualSha256 = pineSourceSha256(actual);
  const matches = expectedSha256 === actualSha256;
  return {
    ok: matches,
    matches,
    scriptName: target.scriptName,
    sourcePath,
    expectedSha256,
    actualSha256,
    expectedBytes: Buffer.byteLength(expected, "utf-8"),
    actualBytes: Buffer.byteLength(actual, "utf-8"),
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

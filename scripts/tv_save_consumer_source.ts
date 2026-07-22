/**
 * Save a hand-authored consumer's repo source into an existing TradingView
 * saved script. Consumers are saved indicators/strategies, not published
 * libraries, so this deliberately opens an exact saved name and never creates
 * a replacement when that name is missing.
 */
import * as fs from "node:fs";
import * as path from "node:path";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";

import {
  assertNoVisibleCompileError,
  closeTradingViewSession,
  ensurePineEditor,
  gotoChart,
  newTradingViewSession,
  openExistingScript,
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
  return createHash("sha256").update(source.replace(/\r\n/g, "\n"), "utf-8").digest("hex");
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

  const opened = await openExistingScript(session.page, target.scriptName, { forceSelection: true }).catch(() => false);
  if (!opened) throw new Error(`Could not open existing saved script: ${target.scriptName}`);
  // openExistingScript above proves the editor surface is ready. Re-running
  // ensurePineEditor here costs ~26s per consumer on the live chart.
  await setEditorContent(session.page, code, { editorAlreadyOpen: true });
  await saveScript(session.page, target.scriptName);
  await waitForPostSaveCompileSettlement(session.page, target.scriptName);
  await assertNoVisibleCompileError(session.page);
  return { ok: true, scriptName: target.scriptName, sourcePath, bytes: code.length };
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

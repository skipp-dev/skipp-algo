/**
 * Save a hand-authored consumer's repo source into an existing TradingView
 * saved script. Consumers are saved indicators/strategies, not published
 * libraries, so this deliberately opens an exact saved name and never creates
 * a replacement when that name is missing.
 */
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

import {
  assertNoVisibleCompileError,
  closeTradingViewSession,
  ensurePineEditor,
  gotoChart,
  newTradingViewSession,
  openExistingScript,
  saveScript,
  setEditorContent,
  waitForPostSaveCompileSettlement,
} from "../automation/tradingview/lib/tv_shared.js";

function getFlag(name: string, fallback = ""): string {
  const args = process.argv.slice(2);
  const index = args.indexOf(name);
  return index === -1 || !args[index + 1] ? fallback : args[index + 1];
}

export async function runSaveConsumerSourceCli(): Promise<number> {
  const sourceFlag = getFlag("--source");
  const scriptName = getFlag("--script-name");
  if (!sourceFlag) throw new Error("Missing --source");
  if (!scriptName) throw new Error("Missing --script-name");

  const sourcePath = path.resolve(sourceFlag);
  if (!fs.existsSync(sourcePath)) throw new Error(`Missing source: ${sourcePath}`);
  const code = fs.readFileSync(sourcePath, "utf-8");

  const session = await newTradingViewSession();
  try {
    if (!session.authResolution.authReusedOk) {
      throw new Error("Save requires a reusable authenticated TradingView session");
    }
    await gotoChart(session.page);
    await ensurePineEditor(session.page);
    const opened = await openExistingScript(session.page, scriptName, { forceSelection: true }).catch(() => false);
    if (!opened) throw new Error(`Could not open existing saved script: ${scriptName}`);
    await setEditorContent(session.page, code);
    await saveScript(session.page, scriptName);
    await waitForPostSaveCompileSettlement(session.page, scriptName);
    await assertNoVisibleCompileError(session.page);
    console.log(JSON.stringify({ ok: true, scriptName, sourcePath, bytes: code.length }));
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

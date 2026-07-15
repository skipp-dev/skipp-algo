/** Verify an existing chart consumer's input.source selections exactly. */
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

import {
  closeModal,
  closeTradingViewSession,
  ensurePineEditor,
  gotoChart,
  isScriptVisibleOnChartSurface,
  newTradingViewSession,
  openExistingScript,
  openInputsTab,
  openSettingsForScript,
} from "../automation/tradingview/lib/tv_shared.js";

type Binding = { label: string; actual: string | null; expected: string; ok: boolean };

function getFlag(name: string, fallback = ""): string {
  const args = process.argv.slice(2);
  const index = args.indexOf(name);
  return index === -1 || !args[index + 1] ? fallback : args[index + 1];
}

export function parseInputSourceLabels(source: string): string[] {
  return [...source.matchAll(/input\.source\([^,]+,\s*"([^"]+)"/g)]
    .map((match) => match[1])
    .filter((label) => label.startsWith("BUS "));
}

async function readSelectedSource(page: Parameters<typeof openInputsTab>[0], label: string): Promise<string | null> {
  const matches = page.getByText(label, { exact: true });
  const count = await matches.count();
  for (let index = 0; index < count; index += 1) {
    const value = await matches.nth(index).evaluate((element) => {
      const labelCell = element.parentElement;
      const valueCell = labelCell?.nextElementSibling;
      const combo = valueCell?.querySelector('button[role="combobox"]');
      return combo?.textContent?.replace(/\s+/g, " ").trim() || null;
    });
    if (value) return value;
  }
  return null;
}

export async function runVerifyConsumerBindingsCli(): Promise<number> {
  const sourceFlag = getFlag("--source");
  const scriptName = getFlag("--script-name");
  const savedScriptName = getFlag("--saved-script-name", scriptName);
  const producerName = getFlag("--producer-name", "SMC Long-Dip Suite");
  if (!sourceFlag) throw new Error("Missing --source");
  if (!scriptName) throw new Error("Missing --script-name");

  const sourcePath = path.resolve(sourceFlag);
  if (!fs.existsSync(sourcePath)) throw new Error(`Missing source: ${sourcePath}`);
  const labels = parseInputSourceLabels(fs.readFileSync(sourcePath, "utf-8"));
  if (labels.length === 0) throw new Error(`No BUS input.source labels found: ${sourcePath}`);

  const session = await newTradingViewSession();
  try {
    if (!session.authResolution.authReusedOk) {
      throw new Error("Binding verification requires an authenticated TradingView session");
    }
    await gotoChart(session.page);
    await ensurePineEditor(session.page);
    const opened = await openExistingScript(session.page, savedScriptName, { forceSelection: true }).catch(() => false);
    if (!opened) throw new Error(`Could not open existing saved script: ${savedScriptName}`);
    if (!(await isScriptVisibleOnChartSurface(session.page, scriptName))) {
      throw new Error(`Existing chart instance not found: ${scriptName}`);
    }
    const settingsOpened = await openSettingsForScript(session.page, scriptName, { allowChartRefresh: false });
    if (!settingsOpened) throw new Error(`Could not open exact chart settings: ${scriptName}`);
    await openInputsTab(session.page);

    const bindings: Binding[] = [];
    for (const label of labels) {
      const actual = await readSelectedSource(session.page, label);
      const expected = `${producerName}: ${label}`;
      bindings.push({ label, actual, expected, ok: actual === expected });
    }
    const mismatches = bindings.filter((binding) => !binding.ok);
    console.log(JSON.stringify({
      ok: mismatches.length === 0,
      scriptName,
      savedScriptName,
      sourcePath,
      checked: bindings.length,
      mismatches,
      bindings,
    }));
    if (mismatches.length > 0) {
      throw new Error(`${mismatches.length}/${bindings.length} BUS source bindings do not match ${producerName}`);
    }
    await closeModal(session.page);
    return 0;
  } finally {
    await closeTradingViewSession(session);
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runVerifyConsumerBindingsCli()
    .then((rc) => process.exit(rc))
    .catch((error) => {
      console.error(JSON.stringify({ ok: false, error: String(error?.message ?? error) }));
      process.exit(1);
    });
}

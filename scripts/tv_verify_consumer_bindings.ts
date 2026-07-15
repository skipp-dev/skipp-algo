/** Verify an existing chart consumer's input.source selections exactly. */
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

import {
  closeModal,
  closeTradingViewSession,
  gotoChart,
  isScriptVisibleOnChartSurface,
  newTradingViewSession,
  openInputsTab,
  openSettingsForScript,
  type TradingViewSession,
} from "../automation/tradingview/lib/tv_shared.js";

export type Binding = { label: string; actual: string | null; expected: string; ok: boolean };
export type VerifyConsumerTarget = {
  source: string;
  savedScriptName: string;
  scriptName: string;
  producerName?: string;
};
export type VerifyConsumerResult = {
  ok: boolean;
  repair: boolean;
  forceRebind: boolean;
  repaired: string[];
  unknownParentRuntimeError: boolean;
  scriptName: string;
  savedScriptName: string;
  sourcePath: string;
  checked: number;
  mismatches: Binding[];
  bindings: Binding[];
};

function getFlag(name: string, fallback = ""): string {
  const args = process.argv.slice(2);
  const index = args.indexOf(name);
  return index === -1 || !args[index + 1] ? fallback : args[index + 1];
}

function hasFlag(name: string): boolean {
  return process.argv.slice(2).includes(name);
}

export function parseInputSourceLabels(source: string): string[] {
  return [...source.matchAll(/input\.source\([^,]+,\s*(["'])(.*?)\1/g)]
    .map((match) => match[2])
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

async function repairSelectedSource(
  page: Parameters<typeof openInputsTab>[0],
  label: string,
  expected: string,
): Promise<void> {
  const labels = page.getByText(label, { exact: true });
  const count = await labels.count();
  for (let index = 0; index < count; index += 1) {
    const combo = labels.nth(index).locator("xpath=parent::*/following-sibling::*[1]//button[@role='combobox']");
    if (await combo.count() === 0 || !(await combo.first().isVisible().catch(() => false))) continue;
    await combo.first().click();
    const exactOption = page.getByRole("option", { name: expected, exact: true });
    const fallbackOption = page.getByText(expected, { exact: true });
    if (await exactOption.count() > 0) {
      await exactOption.first().click();
    } else if (await fallbackOption.count() > 0) {
      await fallbackOption.last().click();
    } else {
      throw new Error(`Source option not found for ${label}: ${expected}`);
    }
    return;
  }
  throw new Error(`Source combobox not found for ${label}`);
}

export async function setConsumerBindingForTest(
  session: TradingViewSession,
  target: VerifyConsumerTarget,
  label: string,
  sourceName: string,
): Promise<void> {
  const settingsOpened = await openSettingsForScript(session.page, target.scriptName, { allowChartRefresh: false });
  if (!settingsOpened) throw new Error(`Could not open exact chart settings: ${target.scriptName}`);
  await openInputsTab(session.page);
  await repairSelectedSource(session.page, label, sourceName);
  const submit = session.page.locator('button[name="submit"], button[data-name="submit-button"]').first();
  if (!(await submit.isVisible().catch(() => false))) {
    throw new Error("Could not find settings submit button after controlled binding mutation");
  }
  await submit.click();
}

export async function verifyConsumerBindings(
  session: TradingViewSession,
  target: VerifyConsumerTarget,
  repair = false,
  forceRebind = false,
): Promise<VerifyConsumerResult> {
  const producerName = target.producerName ?? "SMC Long-Dip Suite";
  const sourcePath = path.resolve(target.source);
  if (!fs.existsSync(sourcePath)) throw new Error(`Missing source: ${sourcePath}`);
  const labels = parseInputSourceLabels(fs.readFileSync(sourcePath, "utf-8"));
  if (labels.length === 0) throw new Error(`No BUS input.source labels found: ${sourcePath}`);

  if (!(await isScriptVisibleOnChartSurface(session.page, target.scriptName))) {
    throw new Error(`Existing chart instance not found: ${target.scriptName}`);
  }
  const settingsOpened = await openSettingsForScript(session.page, target.scriptName, { allowChartRefresh: false });
  if (!settingsOpened) throw new Error(`Could not open exact chart settings: ${target.scriptName}`);
  await openInputsTab(session.page);

  const bindings: Binding[] = [];
  for (const label of labels) {
    const actual = await readSelectedSource(session.page, label);
    const expected = `${producerName}: ${label}`;
    bindings.push({ label, actual, expected, ok: actual === expected });
  }
  let mismatches = bindings.filter((binding) => !binding.ok);
  const repaired: string[] = [];
  // A matching dropdown label does not prove a live parent: TradingView keeps the text
  // while the stored input.source parent study id is dead. --force-rebind re-selects every
  // source so those stale-but-identical bindings are re-pointed too.
  const bindingsToRepair = forceRebind ? bindings : mismatches;
  if (repair && bindingsToRepair.length > 0) {
    for (const binding of bindingsToRepair) {
      await repairSelectedSource(session.page, binding.label, binding.expected);
      repaired.push(binding.label);
    }
    const submit = session.page.locator('button[name="submit"], button[data-name="submit-button"]').first();
    if (!(await submit.isVisible().catch(() => false))) {
      throw new Error("Could not find settings submit button after binding repair");
    }
    await submit.click();

    const reopened = await openSettingsForScript(session.page, target.scriptName, { allowChartRefresh: false });
    if (!reopened) throw new Error(`Could not reopen chart settings after repair: ${target.scriptName}`);
    await openInputsTab(session.page);
    for (const binding of bindings) {
      binding.actual = await readSelectedSource(session.page, binding.label);
      binding.ok = binding.actual === binding.expected;
    }
    mismatches = bindings.filter((binding) => !binding.ok);
  }
  const chartBody = await session.page.locator("body").innerText();
  const unknownParentRuntimeError = /unknown parent id/i.test(chartBody);
  const result: VerifyConsumerResult = {
    ok: mismatches.length === 0 && !unknownParentRuntimeError,
    repair,
    forceRebind,
    repaired,
    unknownParentRuntimeError,
    scriptName: target.scriptName,
    savedScriptName: target.savedScriptName,
    sourcePath,
    checked: bindings.length,
    mismatches,
    bindings,
  };
  await closeModal(session.page);
  return result;
}

export async function runVerifyConsumerBindingsCli(): Promise<number> {
  const source = getFlag("--source");
  const scriptName = getFlag("--script-name");
  const savedScriptName = getFlag("--saved-script-name", scriptName);
  const producerName = getFlag("--producer-name", "SMC Long-Dip Suite");
  const forceRebind = hasFlag("--force-rebind");
  const repair = hasFlag("--repair") || forceRebind;
  if (!source) throw new Error("Missing --source");
  if (!scriptName) throw new Error("Missing --script-name");

  const session = await newTradingViewSession();
  try {
    if (!session.authResolution.authReusedOk) {
      throw new Error("Binding verification requires an authenticated TradingView session");
    }
    await gotoChart(session.page);
    const result = await verifyConsumerBindings(
      session,
      { source, savedScriptName, scriptName, producerName },
      repair,
      forceRebind,
    );
    console.log(JSON.stringify(result));
    if (result.mismatches.length > 0) {
      throw new Error(`${result.mismatches.length}/${result.checked} BUS source bindings do not match ${producerName}`);
    }
    if (result.unknownParentRuntimeError) {
      throw new Error(`TradingView still reports unknown parent id after binding verification: ${scriptName}`);
    }
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

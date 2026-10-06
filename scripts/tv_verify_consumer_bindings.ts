/** Verify an existing chart consumer's input.source selections exactly. */
import * as fs from "node:fs";
import * as path from "node:path";

import { parseBusBindingLabels } from "../automation/tradingview/lib/bus_binding_labels.mjs";

import {
  closeDockedPineEditor,
  closeModal,
  closeTradingViewSession,
  countChartScriptInstances,
  gotoChart,
  isScriptVisibleOnChartSurface,
  newTradingViewSession,
  openInputsTab,
  openSettingsForScript,
  type TradingViewSession,
} from "../automation/tradingview/lib/tv_shared.js";

export type Binding = { label: string; actual: string | null; expected: string; ok: boolean };
export type VerifyConsumerTarget = {
  source?: string;
  bindingLabels?: string[];
  savedScriptName: string;
  scriptName: string;
  chartUrl?: string;
  producerName?: string;
};
export type VerifyConsumerResult = {
  ok: boolean;
  repair: boolean;
  forceRebind: boolean;
  repaired: string[];
  unknownParentRuntimeError: boolean;
  runtimeErrors: Array<{ at: string; studyId: string | null; message: string }>;
  scriptName: string;
  savedScriptName: string;
  sourcePath: string | null;
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
  return parseBusBindingLabels(source);
}

function resolveBindingContract(target: VerifyConsumerTarget): { labels: string[]; sourcePath: string | null } {
  if (target.bindingLabels && target.bindingLabels.length > 0) {
    return { labels: [...target.bindingLabels], sourcePath: target.source ? path.resolve(target.source) : null };
  }
  if (!target.source) throw new Error(`No BUS binding contract configured: ${target.scriptName}`);
  const sourcePath = path.resolve(target.source);
  if (!fs.existsSync(sourcePath)) throw new Error(`Missing source: ${sourcePath}`);
  return { labels: parseInputSourceLabels(fs.readFileSync(sourcePath, "utf-8")), sourcePath };
}

function sourceComboboxForLabel(page: Parameters<typeof openInputsTab>[0], label: string) {
  return page.getByText(label, { exact: true })
    .locator("xpath=parent::*/following-sibling::*[1]//button[@role='combobox']");
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

// TradingView may put the producer's status-line arguments between the script
// name and the plot name: "SMC Long-Dip Suite · 411.0: BUS Armed" (measured
// 2026-10-01 on vWgAWyfC, run 36859274386; the same dropdown read
// "SMC Long-Dip Suite: BUS Armed" on 2026-09-21 and still does on the other
// layouts). The separator must follow the name directly, so a longer script
// name that merely starts with the producer's ("… Suite Pro") stays foreign.
const SOURCE_ARGUMENT_START = /^\s*[·•|(\[]/;

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Reduce a combobox text to the identity the binding contract is written in:
 * "<producer>: <plot>". Anything that is not this producer's plot — "Close",
 * another script, an unreadable row — is returned untouched.
 */
export function canonicalSourceSelection(raw: string | null, producerName: string): string | null {
  if (raw === null || !raw.startsWith(producerName)) return raw;
  const rest = raw.slice(producerName.length);
  if (!SOURCE_ARGUMENT_START.test(rest)) return raw;
  const plotStart = rest.lastIndexOf(": ");
  if (plotStart < 0) return raw;
  return `${producerName}${rest.slice(plotStart)}`;
}

/** Options that are `expected` with status-line arguments in between, or null if `expected` names no producer. */
function sourceOptionsWithArguments(
  page: Parameters<typeof openInputsTab>[0],
  label: string,
  expected: string,
) {
  const suffix = `: ${label}`;
  if (!expected.endsWith(suffix) || expected.length === suffix.length) return null;
  const producer = expected.slice(0, -suffix.length);
  const pattern = new RegExp(`^\\s*${escapeRegExp(producer)}\\s*[·•|(\\[].*:\\s${escapeRegExp(label)}\\s*$`);
  return page.getByRole("option").filter({ hasText: pattern });
}

export type MissingSourceRowEvidence = {
  label: string;
  renderedBefore: readonly string[];
  renderedAfter: readonly string[];
  appearedAfterScroll: boolean;
  dialogScrolled: boolean;
};

/**
 * "Source combobox not found" conflates two failures with opposite fixes:
 * TradingView virtualizing the row out of the DOM (it exists, scroll to it),
 * and the applied chart instance genuinely not carrying the input (re-apply,
 * or the source never compiled). Run 30700161400 died on `CTX SessionMssBull`
 * — row 61 of 62 — against an instance inserted seconds earlier from the
 * verified current source, which rules out staleness and leaves both of those
 * open. One run against the live account costs ~5 minutes and touches a
 * layout, so the next one has to SETTLE this rather than narrow it.
 */
export function formatMissingSourceRowEvidence(evidence: MissingSourceRowEvidence): string {
  const tail = (rows: readonly string[]): string =>
    rows.length === 0 ? "none" : JSON.stringify(rows.slice(-3).join(" | "));
  const verdict = evidence.appearedAfterScroll
    ? "the row EXISTS and was only virtualized out of the DOM"
    : evidence.dialogScrolled
      ? "the row is ABSENT from the applied instance even at the end of the dialog"
      : "no scrollable settings dialog was found, so virtualization stays untested";

  return [
    `Source combobox not found for ${evidence.label}`,
    `rendered rows ${evidence.renderedBefore.length} -> ${evidence.renderedAfter.length} after scrolling to the dialog end`,
    `last before ${tail(evidence.renderedBefore)}, last after ${tail(evidence.renderedAfter)}`,
    verdict,
  ].join("; ");
}

async function collectRenderedSourceRowLabels(
  page: Parameters<typeof openInputsTab>[0],
): Promise<string[]> {
  return await page
    .getByText(/^CTX /)
    .allInnerTexts()
    .then((texts) => texts.map((text) => text.replace(/\s+/g, " ").trim()).filter(Boolean))
    .catch(() => []);
}

async function scrollOpenSettingsDialogToEnd(
  page: Parameters<typeof openInputsTab>[0],
): Promise<boolean> {
  return await page
    .evaluate(() => {
      let scrolled = false;
      for (const dialog of Array.from(document.querySelectorAll('[role="dialog"]'))) {
        for (const element of Array.from(dialog.querySelectorAll("*"))) {
          if (element.scrollHeight > element.clientHeight + 8) {
            element.scrollTop = element.scrollHeight;
            scrolled = true;
          }
        }
      }
      return scrolled;
    })
    .catch(() => false);
}

async function describeMissingSourceRow(
  page: Parameters<typeof openInputsTab>[0],
  label: string,
): Promise<string> {
  const renderedBefore = await collectRenderedSourceRowLabels(page);
  const dialogScrolled = await scrollOpenSettingsDialogToEnd(page);
  await page.waitForTimeout(400);
  const renderedAfter = await collectRenderedSourceRowLabels(page);
  const appearedAfterScroll = await page
    .getByText(label, { exact: true })
    .count()
    .then((count) => count > 0)
    .catch(() => false);

  return formatMissingSourceRowEvidence({
    label,
    renderedBefore,
    renderedAfter,
    appearedAfterScroll,
    dialogScrolled,
  });
}

export type InstanceContractCoverage = {
  ok: boolean;
  present: number;
  total: number;
  missing: readonly string[];
};

/**
 * Whether the applied instance's settings dialog carries every contract input
 * at all — regardless of what each one is bound to. `actual: null` means
 * readSelectedSource found no row for the label, and rows do not go missing
 * from a current build: a new instance shows every input defaulted to
 * `close`. Missing rows mean an older build, and rebinding an older build is
 * 60 mutations toward a wrong outcome.
 */
export function assessInstanceContractCoverage(
  bindings: ReadonlyArray<{ label: string; actual: string | null }>,
): InstanceContractCoverage {
  const missing = bindings.filter((binding) => binding.actual === null).map((binding) => binding.label);
  return {
    ok: missing.length === 0,
    present: bindings.length - missing.length,
    total: bindings.length,
    missing,
  };
}

export function formatInstanceContractCoverage(
  scriptName: string,
  coverage: InstanceContractCoverage,
): string {
  const shown = coverage.missing.slice(0, 8);
  const overflow = coverage.missing.length - shown.length;
  const missingList = shown.join(", ") + (overflow > 0 ? ` (+${overflow} more)` : "");
  const scale = coverage.present === 0
    ? `none of the ${coverage.total} contract inputs`
    : `only ${coverage.present} of ${coverage.total} contract inputs`;

  return (
    `Applied instance of ${scriptName} carries ${scale} — it is an older build than the source this run saved. `
    + `Missing: ${missingList}. Refusing to rebind it; re-apply the instance from the saved source first.`
  );
}

export async function repairSelectedSource(
  page: Parameters<typeof openInputsTab>[0],
  label: string,
  expected: string,
): Promise<void> {
  const labels = page.getByText(label, { exact: true });
  const count = await labels.count();
  for (let index = 0; index < count; index += 1) {
    const combo = sourceComboboxForLabel(page, label).nth(index);
    if (await combo.count() === 0 || !(await combo.first().isVisible().catch(() => false))) continue;
    await combo.first().scrollIntoViewIfNeeded();
    // TradingView virtualizes long Inputs dialogs. The scroll can replace the
    // off-screen combobox, so let that render settle before opening its menu.
    await page.waitForTimeout(100);
    const visibleCombo = sourceComboboxForLabel(page, label).nth(index).first();
    if (!(await visibleCombo.isVisible().catch(() => false))) continue;
    await visibleCombo.click();
    await page.getByRole("option").first().waitFor({ state: "visible", timeout: 2_500 }).catch(() => undefined);
    const exactOption = page.getByRole("option", { name: expected, exact: true });
    let withArguments: ReturnType<typeof sourceOptionsWithArguments> = null;
    // The list can still be filling in when its first option is visible, so
    // look for both spellings together for a moment instead of waiting out
    // the exact one first — on a layout that shows arguments that would cost
    // seconds per binding, 108 times.
    const deadline = Date.now() + 2_500;
    let exactCount = 0;
    let argumentCount = 0;
    for (;;) {
      exactCount = await exactOption.count().catch(() => 0);
      if (exactCount === 0) {
        withArguments ??= sourceOptionsWithArguments(page, label, expected);
        argumentCount = withArguments ? await withArguments.count().catch(() => 0) : 0;
      }
      if (exactCount > 0 || argumentCount > 0 || Date.now() >= deadline) break;
      await page.waitForTimeout(100);
    }
    if (exactCount > 0) {
      await exactOption.first().click();
      return;
    }
    if (argumentCount === 1 && withArguments) {
      await withArguments.first().click();
      return;
    }
    if (argumentCount > 1) {
      await page.keyboard.press("Escape").catch(() => undefined);
      throw new Error(
        `Ambiguous source option for ${label}: ${argumentCount} options read as ${expected} with different `
        + "status-line arguments — more than one producer instance is offered",
      );
    }
    const fallbackOption = page.getByText(expected, { exact: true });
    if (await fallbackOption.last().waitFor({ state: "visible", timeout: 1_000 })
      .then(() => true)
      .catch(() => false)) {
      await fallbackOption.last().click();
      return;
    }
    await page.keyboard.press("Escape").catch(() => undefined);
    throw new Error(`Source option not found for ${label}: ${expected}`);
  }
  // Still fail-closed — the probe only decides WHAT the failure says, never
  // whether it fails. A probe that throws must not swallow the real error.
  throw new Error(
    await describeMissingSourceRow(page, label).catch(
      (error) => `Source combobox not found for ${label}; evidence probe failed: ${String(error)}`,
    ),
  );
}

/** Confirm that a live producer output is offered before mutating any consumer bindings. */
export async function isConsumerSourceOptionAvailable(
  session: TradingViewSession,
  target: VerifyConsumerTarget,
  label: string,
  expected: string,
): Promise<boolean> {
  if (!(await isScriptVisibleOnChartSurface(session.page, target.scriptName))) return false;
  const settingsOpened = await openSettingsForScript(session.page, target.scriptName, { allowChartRefresh: false });
  if (!settingsOpened) return false;
  try {
    await openInputsTab(session.page);
    const combo = sourceComboboxForLabel(session.page, label).first();
    if (!(await combo.isVisible().catch(() => false))) return false;
    await combo.click();
    await session.page.getByRole("option").first().waitFor({ state: "visible", timeout: 2_500 }).catch(() => undefined);
    const exactOption = session.page.getByRole("option", { name: expected, exact: true });
    const fallbackOption = session.page.getByText(expected, { exact: true });
    const withArguments = sourceOptionsWithArguments(session.page, label, expected);
    return (await exactOption.count()) > 0
      || (await fallbackOption.count()) > 0
      || (withArguments !== null && (await withArguments.count()) === 1);
  } finally {
    await session.page.keyboard.press("Escape").catch(() => undefined);
    await closeModal(session.page).catch(() => undefined);
  }
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
  const { labels, sourcePath } = resolveBindingContract(target);
  if (labels.length === 0) throw new Error(`No BUS input.source labels found: ${sourcePath ?? target.scriptName}`);

  const [producerInstances, consumerInstances] = await Promise.all([
    countChartScriptInstances(session.page, producerName),
    countChartScriptInstances(session.page, target.scriptName),
  ]);
  if (producerInstances > 1 || consumerInstances > 1) {
    throw new Error(
      `Ambiguous multi-pane SMC layout: ${producerName}=${producerInstances}, `
      + `${target.scriptName}=${consumerInstances}. Keep one suite and one consumer in the same chart pane before binding.`,
    );
  }

  // A docked Pine editor (account UI state) squeezes the chart until the legend has no
  // height; every consumer's settings then fail to open (tv-save 37510785146, 2026-10-06).
  if (await closeDockedPineEditor(session.page)) console.error(`[tv-trace] closed-docked-pine-editor before ${target.scriptName}`);
  if (!(await isScriptVisibleOnChartSurface(session.page, target.scriptName))) {
    throw new Error(`Existing chart instance not found: ${target.scriptName}`);
  }
  const settingsOpened = await openSettingsForScript(session.page, target.scriptName, { allowChartRefresh: false });
  if (!settingsOpened) throw new Error(`Could not open exact chart settings: ${target.scriptName}`);
  await openInputsTab(session.page);

  const bindings: Binding[] = [];
  for (const label of labels) {
    const actual = canonicalSourceSelection(await readSelectedSource(session.page, label), producerName);
    const expected = `${producerName}: ${label}`;
    bindings.push({ label, actual, expected, ok: actual === expected });
  }
  let mismatches = bindings.filter((binding) => !binding.ok);
  const repaired: string[] = [];
  // Refuse to rebind an instance that is not the version this run saved.
  // Reading a label as null means its row is not in the dialog at all, and an
  // instance missing contract rows is by definition an older build. Repairing
  // it anyway is what runs 30694013096 / 30696257671 / 30698519321 /
  // 30700161400 / 30702240413 all did: 60 sources rebound on a pre-#4263
  // instance before dying on the 61st. Verify-only runs are left alone — they
  // mutate nothing and the per-label table is the more useful answer there.
  const coverage = assessInstanceContractCoverage(bindings);
  if (repair && !coverage.ok) {
    throw new Error(formatInstanceContractCoverage(target.scriptName, coverage));
  }
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
    // Only errors TradingView emits AFTER the committed rebind prove the NEW
    // parent is still dead. The monitor accumulates for the whole session, so
    // without this the consumer's own pre-repair "unknown parent id" (the exact
    // condition this force-rebind fixes) — plus errors from other not-yet-repaired
    // consumers sharing the session — would sink a successful repair. Drop them,
    // then observe a short residual-risk window: TradingView usually re-emits a
    // still-dead parent promptly, but a quiet window is not proof of liveness.
    session.runtimeErrors.clear();

    const reopened = await openSettingsForScript(session.page, target.scriptName, { allowChartRefresh: false });
    if (!reopened) throw new Error(`Could not reopen chart settings after repair: ${target.scriptName}`);
    await openInputsTab(session.page);
    for (const binding of bindings) {
      binding.actual = canonicalSourceSelection(await readSelectedSource(session.page, binding.label), producerName);
      binding.ok = binding.actual === binding.expected;
    }
    mismatches = bindings.filter((binding) => !binding.ok);
  }
  // TradingView reports dead input.source parents on the chart WebSocket. The
  // red UI marker is hidden behind a popover, so body-text inspection is not a
  // reliable runtime check.
  await session.page.waitForTimeout(1_000);
  const runtimeErrors = session.runtimeErrors.snapshot().map(({ at, studyId, message }) => ({ at, studyId, message }));
  const unknownParentRuntimeError = runtimeErrors.some((error) => /unknown parent id/i.test(error.message));
  const result: VerifyConsumerResult = {
    ok: mismatches.length === 0 && !unknownParentRuntimeError,
    repair,
    forceRebind,
    repaired,
    unknownParentRuntimeError,
    runtimeErrors,
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

const invokedAsVerifierCli = process.argv[1]
  ? /tv_verify_consumer_bindings\.(?:[cm]?js|ts)$/.test(path.basename(process.argv[1]))
  : false;

if (invokedAsVerifierCli) {
  runVerifyConsumerBindingsCli()
    .then((rc) => process.exit(rc))
    .catch((error) => {
      console.error(JSON.stringify({ ok: false, error: String(error?.message ?? error) }));
      process.exit(1);
    });
}

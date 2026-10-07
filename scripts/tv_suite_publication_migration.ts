#!/usr/bin/env -S node --enable-source-maps

// Move the operator layouts from the SAVED "SMC Long-Dip Suite" script to a
// PRIVATE PUBLICATION of it, so later Suite versions reach the charts by update.
//
// Why (measured 2026-10-05): chart instances of a saved, unpublished script stay
// on the version they were added with. A source save never reaches them, and the
// producer refresh (remove + re-add) cannot persist: removing the Suite removes
// every dependent consumer with it. Operator decisions 2026-10-05: private
// publication; vWgAWyfC keeps only its LEFT pane (1h); twh98JLB (Hold Manager +
// its live webhook shadow alert) is NOT migrated for now.
//
// Phases (one per run, --phase):
//   inventory  read-only: per layout and pane every SMC instance with entity id,
//              visibility, applied-source hash and all input values.
//   migrate    one chart: remove the Suite (TradingView removes its dependants with
//              it), re-add Suite and dependants, compare before/after. With
//              --dry-run nothing is saved; closing the session discards it.
//              Without it the layout is saved ONLY if every check passed (all scripts
//              back, inputs identical by position, visibility restored, every binding
//              repaired, the Suite instance on the repository source).
//   publish    privately publish "SMC Long-Dip Suite" from the repository source
//              (saved slot is brought to the repository source first). Run BEFORE
//              migrate, so the re-added Suite comes from the publication.
//
// Usage: tsx scripts/tv_suite_publication_migration.ts --phase inventory --out <dir>
//          [--charts vWgAWyfC,hKHTmKhu,twh98JLB]

import fs from "node:fs";
import path from "node:path";
import type { Locator, Page } from "playwright";
import { verifyConsumerBindings, type VerifyConsumerTarget } from "./tv_verify_consumer_bindings.js";
import {
  closeTradingViewSession,
  type TradingViewSession,
  dismissPromotionOverlay,
  gotoChartAndAwaitScript,
  gotoChartClosingDockedEditor,
  newTradingViewSession,
  ensurePineEditor,
  openExistingScript,
  publishPrivateScript,
  readAppliedInstanceSources,
  readEditorContent,
  saveChangedChartLayout,
  saveScript,
  setEditorContent,
  waitForPostSaveCompileSettlement,
} from "../automation/tradingview/lib/tv_shared.js";
import { normalizedPineSha256 } from "../automation/tradingview/lib/tv_consumer_rollout_evidence.js";

const expectedSuiteSha = () => normalizedPineSha256(fs.readFileSync("SMC_Long_Dip_Suite.pine", "utf-8"));

export const SUITE = "SMC Long-Dip Suite";
export const DEFAULT_CHARTS = ["vWgAWyfC", "hKHTmKhu", "twh98JLB"];

export type MigrationArgs = { phase: "inventory" | "migrate" | "publish"; out: string; charts: string[]; dryRun: boolean; acceptNewSuiteInputs: string[] };

export function parseMigrationArgs(argv: string[]): MigrationArgs {
  const get = (flag: string): string | undefined => {
    const i = argv.indexOf(flag);
    return i >= 0 ? argv[i + 1] : undefined;
  };
  const phase = get("--phase");
  if (phase !== "inventory" && phase !== "migrate" && phase !== "publish") throw new Error(`unknown --phase: ${phase ?? "(missing)"}`);
  const out = get("--out");
  if (!out) throw new Error("--out <dir> is required");
  const charts = (get("--charts") ?? DEFAULT_CHARTS.join(",")).split(",").map((c) => c.trim()).filter(Boolean);
  for (const chart of charts) {
    if (!/^[A-Za-z0-9]{6,12}$/.test(chart)) throw new Error(`not a chart id: ${chart}`);
  }
  if (phase === "migrate" && charts.length !== 1) throw new Error("--phase migrate takes exactly one chart");
  if (phase === "migrate" && charts[0] === "twh98JLB") throw new Error("twh98JLB carries the live Hold Manager shadow alert and is not migrated (operator decision 2026-10-05)");
  // Names (getInputsInfo) of inputs the new Suite version adds on purpose (repeatable).
  const acceptNewSuiteInputs = argv.flatMap((a, i) => (a === "--accept-new-suite-input" ? [argv[i + 1] ?? ""] : []));
  if (acceptNewSuiteInputs.some((l) => !l.trim())) throw new Error("--accept-new-suite-input needs an input name");
  return { phase, out, charts, dryRun: argv.includes("--dry-run"), acceptNewSuiteInputs };
}

export type InputValue = { label: string; kind: string; value: string };
export type InstanceRecord = {
  pane: number;
  name: string;
  entityId: string | null;
  hidden: boolean;
  inputs: InputValue[];
  inputsError: string;
};

/** "SMC Long-Dip Suite · 242.0" -> "SMC Long-Dip Suite" */
export function legendScriptName(rowText: string): string {
  return rowText.replace(/\s+/g, " ").trim().split(" · ")[0].trim();
}

const closeDockedEditor = async (page: Page) => {
  if (await page.locator("#pine-editor-dialog").first().isVisible().catch(() => false)) {
    await page.locator('button[aria-label="Close"][title="Close"]').first().click().catch(() => undefined);
    await page.waitForTimeout(1_500);
  }
};


/**
 * One study's inputs as records for the before/after comparison, from the chart API
 * (getInputValues + getInputsInfo). The settings dialog was read before 2026-10-07 and
 * MISSED the first checkbox of every inline pair: around "Require Internal Break For
 * Confirm" it returned two checkboxes (false, false) where the API shows four
 * (in_105..in_108 = true, false, true, false), so a change there went unseen. Only the
 * script's own inputs (in_N) count; pineVersion & co. change with every migration.
 * Source inputs (BUS bindings) are rebound separately and keep kind "source".
 */
export function apiInputsToRecords(
  values: Array<{ id: string; value: unknown }>, info: Array<{ id: string; name?: string; type?: string }>,
): InputValue[] {
  const byId = new Map(info.map((x) => [x.id, x]));
  return values
    .filter((v) => /^in_[0-9]+$/.test(v.id))
    .sort((a, b) => Number(a.id.slice(3)) - Number(b.id.slice(3)))
    .map((v) => {
      const meta = byId.get(v.id);
      return { label: meta?.name ?? v.id, kind: meta?.type ?? typeof v.value, value: String(v.value) };
    });
}

const READ_API_INPUTS_SOURCE = `
  const [chartIndex, entityId] = arguments[0];
  const chart = window.TradingViewApi.chart(chartIndex);
  let study;
  try { study = chart.getStudyById(entityId); } catch (e) { return { error: "no study " + entityId + " on chart " + chartIndex }; }
  if (!study || typeof study.getInputsInfo !== "function") return { error: "no input API for " + entityId };
  return { values: study.getInputValues(), info: study.getInputsInfo().map((x) => ({ id: x.id, name: x.name, type: x.type })) };
`;

async function readInstanceInputs(page: Page, pane: number, entityId: string | null): Promise<{ inputs: InputValue[]; error: string }> {
  if (!entityId) return { inputs: [], error: "legend row without data-entity-id" };
  const res = await page.evaluate(([src, arg]) => new Function(src as string).call(null, arg), [READ_API_INPUTS_SOURCE, [pane, entityId]] as const)
    .catch((e: unknown) => ({ error: String(e).slice(0, 300) })) as { values?: Array<{ id: string; value: unknown }>; info?: Array<{ id: string; name?: string; type?: string }>; error?: string };
  if (res.error || !res.values || !res.info) return { inputs: [], error: res.error ?? "no inputs read" };
  const inputs = apiInputsToRecords(res.values, res.info);
  return inputs.length > 0 ? { inputs, error: "" } : { inputs: [], error: "no in_N inputs" };
}

async function inventoryChart(page: Page, chartId: string) {
  await gotoChartClosingDockedEditor(page, `https://www.tradingview.com/chart/${chartId}/`, SUITE);
  await page.waitForTimeout(5_000);
  await dismissPromotionOverlay(page).catch(() => undefined);
  await closeDockedEditor(page);
  const panes = page.locator('[data-qa-id="chart-container"]');
  const instances: InstanceRecord[] = [];
  for (let pane = 0; pane < (await panes.count()); pane += 1) {
    const rows = panes.nth(pane).locator('[data-qa-id="legend-source-item"]');
    for (let r = 0; r < (await rows.count()); r += 1) {
      const row = rows.nth(r);
      const name = legendScriptName(await row.innerText().catch(() => ""));
      if (!name.startsWith("SMC")) continue;
      const entityId = await row.getAttribute("data-entity-id");
      const hidden = (await row.locator('[data-qa-id="legend-show-hide-action"]').getAttribute("aria-label").catch(() => null)) === "Show";
      const { inputs, error } = await readInstanceInputs(page, pane, entityId);
      instances.push({ pane, name, entityId, hidden, inputs, inputsError: error });
    }
  }
  const suiteSources = await readAppliedInstanceSources(page, SUITE);
  return { chartId, paneCount: await panes.count(), instances, suiteSources };
}

export type InputDiff = { name: string; label: string; before: string; after: string };

/** Non-source input differences between two inventories of the same script set. */
export function diffInputs(
  before: InstanceRecord[], after: InstanceRecord[], acceptNew: Record<string, string[]> = {},
): { missing: string[]; added: string[]; diffs: InputDiff[]; acceptedNew: string[] } {
  const byName = (list: InstanceRecord[]) => new Map(list.map((i) => [i.name, i]));
  const b = byName(before);
  const a = byName(after);
  const missing = [...b.keys()].filter((n) => !a.has(n));
  const added = [...a.keys()].filter((n) => !b.has(n));
  const diffs: InputDiff[] = [];
  const acceptedNew: string[] = [];
  for (const [name, inst] of b) {
    let other = a.get(name);
    if (!other) continue;
    // A new script version may add inputs on purpose. Drop exactly the named rows that
    // did not exist before, then compare every remaining row by position as usual.
    const allowed = acceptNew[name] ?? [];
    if (allowed.length > 0 && other.inputs.length > inst.inputs.length) {
      const known = new Set(inst.inputs.map((x) => x.label));
      const kept = other.inputs.filter((x) => !(allowed.includes(x.label) && !known.has(x.label)));
      acceptedNew.push(...other.inputs.filter((x) => !kept.includes(x)).map((x) => `${name}: ${x.label}=${x.value}`));
      other = { ...other, inputs: kept };
    }
    // Same script => same input order. Labels repeat ("Length") or are empty (session
    // fields), so a label map mis-pairs them; compare by position.
    if (other.inputs.length !== inst.inputs.length) {
      diffs.push({ name, label: "(input count)", before: String(inst.inputs.length), after: String(other.inputs.length) });
      continue;
    }
    inst.inputs.forEach((input, index) => {
      const after = other.inputs[index];
      if (input.label.startsWith("BUS ") || input.kind === "source") return; // bindings are rebound separately
      if (after.kind !== input.kind || after.value !== input.value) {
        diffs.push({ name, label: `${index}:${input.label}`, before: input.value, after: after.value });
      }
    });
  }
  return { missing, added, diffs, acceptedNew };
}

async function removeSuite(page: Page): Promise<void> {
  const row = page.locator('[data-qa-id="chart-container"]').first()
    .locator('[data-qa-id="legend-source-item"]').filter({ hasText: SUITE }).first();
  await row.locator('[data-qa-id*="legend-source-title"]').first().hover({ force: true });
  await page.waitForTimeout(400);
  await row.locator('[data-qa-id="legend-delete-action"]').click({ force: true });
  await page.waitForTimeout(1_500);
  // TradingView asks before removing an indicator that others depend on
  const confirm = page.locator('button[data-qa-id="yes-btn"]').first();
  if (await confirm.isVisible().catch(() => false)) await confirm.click({ force: true });
  await page.waitForTimeout(2_500);
}

async function inventoryChartInPlaceLight(page: Page): Promise<Array<{ pane: number; name: string }>> {
  const panes = page.locator('[data-qa-id="chart-container"]');
  const out: Array<{ pane: number; name: string }> = [];
  for (let pane = 0; pane < (await panes.count()); pane += 1) {
    const texts = await panes.nth(pane).locator('[data-qa-id="legend-source-item"]').evaluateAll((els) => els.map((e) => (e as HTMLElement).innerText));
    for (const t of texts) { const name = legendScriptName(t); if (name.startsWith("SMC")) out.push({ pane, name }); }
  }
  return out;
}

async function inventoryChartInPlace(page: Page, chartId: string) {
  const panes = page.locator('[data-qa-id="chart-container"]');
  const instances: InstanceRecord[] = [];
  for (let pane = 0; pane < (await panes.count()); pane += 1) {
    const rows = panes.nth(pane).locator('[data-qa-id="legend-source-item"]');
    for (let r = 0; r < (await rows.count()); r += 1) {
      const row = rows.nth(r);
      const name = legendScriptName(await row.innerText().catch(() => ""));
      if (!name.startsWith("SMC")) continue;
      const entityId = await row.getAttribute("data-entity-id");
      const hidden = (await row.locator('[data-qa-id="legend-show-hide-action"]').getAttribute("aria-label").catch(() => null)) === "Show";
      const { inputs, error } = await readInstanceInputs(page, pane, entityId);
      instances.push({ pane, name, entityId, hidden, inputs, inputsError: error });
    }
  }
  const suiteSources = await readAppliedInstanceSources(page, SUITE);
  return { chartId, paneCount: await panes.count(), instances, suiteSources };
}

const smcLegendNames = async (page: Page): Promise<string[]> =>
  (await page.locator('[data-qa-id="legend-source-item"]').evaluateAll((els) => els.map((e) => (e as HTMLElement).innerText)))
    .map(legendScriptName).filter((t) => t.startsWith("SMC"));

/**
 * The private publication of the Suite (https://www.tradingview.com/script/FH5Mbqkz-SMC-Long-Dip-Suite/).
 * Measured 2026-10-05/06: adding it from "My scripts" AND from "Favorites" both yield an
 * instance backed by the SAVED script (pineId USER;…), which never takes publication
 * updates. `fromPublication` in the result records which one a migration produced; it
 * is not gated (operator decision 2026-10-05 "A").
 */
export const SUITE_PUBLICATION_ID = "PUB;9ce21213fa54457496aae1941b828682";

/**
 * Add one of the account's OWN scripts by exact name: Indicators dialog -> section
 * -> search -> click the row whose text IS the name. Refuses anything else.
 *
 * Written because addExistingScriptToChartViaIndicators searches ALL scripts and, when
 * its row click misses, falls back to the keyboard and adds the first hit — in the
 * 2026-10-05 dry run that was a community script, five times over.
 */

async function addOwnScript(page: Page, name: string, section: "My scripts" | "Favorites" = "My scripts"): Promise<void> {
  const countBefore = (await smcLegendNames(page)).filter((n) => n === name).length;
  await page.locator('[data-name="open-indicators-dialog"]:visible').first().click();
  await page.waitForTimeout(1_500);
  const dialog = page.locator('[data-name="indicators-dialog"], [role="dialog"]').last();
  await dialog.getByText(section, { exact: true }).first().click();
  await page.waitForTimeout(1_000);
  await page.keyboard.type(name, { delay: 25 });
  await page.waitForTimeout(2_000);
  const rows = dialog.locator('[data-role="list-item"]').filter({ hasText: new RegExp(`^\\s*${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*$`) });
  const n = await rows.count();
  if (n !== 1) {
    await page.keyboard.press("Escape");
    throw new Error(`"${section}" shows ${n} rows named exactly ${name}`);
  }
  await rows.first().click();
  await page.waitForTimeout(2_500);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(1_000);
  const countAfter = (await smcLegendNames(page)).filter((x) => x === name).length;
  if (countAfter !== countBefore + 1) throw new Error(`adding ${name}: legend count ${countBefore} -> ${countAfter}`);
}

/** Chart whose RIGHT pane (index 1) loses its SMC scripts first (operator decision 2026-10-05). */
export const PRUNE_RIGHT_PANE = new Set(["vWgAWyfC"]);

async function pruneRightPane(page: Page): Promise<string[]> {
  const pane = page.locator('[data-qa-id="chart-container"]').nth(1);
  const removed: string[] = [];
  for (let guard = 0; guard < 12; guard += 1) {
    const rows = pane.locator('[data-qa-id="legend-source-item"]');
    let target: Locator | null = null;
    // the Suite first: TradingView removes its dependants with it
    for (let r = 0; r < (await rows.count()); r += 1) {
      const name = legendScriptName(await rows.nth(r).innerText().catch(() => ""));
      if (name === SUITE) { target = rows.nth(r); break; }
      if (!target && name.startsWith("SMC")) target = rows.nth(r);
    }
    if (!target) break;
    const name = legendScriptName(await target.innerText());
    await target.locator('[data-qa-id*="legend-source-title"]').first().hover({ force: true });
    await page.waitForTimeout(400);
    await target.locator('[data-qa-id="legend-delete-action"]').click({ force: true });
    await page.waitForTimeout(1_500);
    const confirm = page.locator('button[data-qa-id="yes-btn"]').first();
    if (await confirm.isVisible().catch(() => false)) await confirm.click({ force: true });
    await page.waitForTimeout(2_000);
    removed.push(name);
  }
  return removed;
}

async function setHidden(page: Page, name: string, hidden: boolean): Promise<void> {
  const row = page.locator('[data-qa-id="chart-container"]').first()
    .locator('[data-qa-id="legend-source-item"]').filter({ hasText: name }).first();
  const eye = row.locator('[data-qa-id="legend-show-hide-action"]');
  await row.locator('[data-qa-id*="legend-source-title"]').first().hover({ force: true });
  await page.waitForTimeout(300);
  const isHidden = (await eye.getAttribute("aria-label")) === "Show";
  if (isHidden !== hidden) await eye.click({ force: true });
  await page.waitForTimeout(500);
}

function consumerTargets(): Map<string, VerifyConsumerTarget> {
  const config = JSON.parse(fs.readFileSync("automation/tradingview/config/consumer-rollout.json", "utf-8")) as { verifyTargets: VerifyConsumerTarget[] };
  return new Map(config.verifyTargets.map((t) => [t.scriptName, { ...t, producerName: SUITE }]));
}

async function migrateChart(session: TradingViewSession, chartId: string, out: string, dryRun: boolean, acceptNewSuiteInputs: string[] = []) {
  const page = session.page;
  const before = await inventoryChart(page, chartId);
  const pruned = PRUNE_RIGHT_PANE.has(chartId) ? await pruneRightPane(page) : [];
  const smcPanes = new Set(
    (await inventoryChartInPlaceLight(page)).map((i) => i.pane),
  );
  if (smcPanes.size !== 1 || !smcPanes.has(0)) throw new Error(`${chartId}: SMC scripts in panes ${[...smcPanes]} after pruning; need only pane 0`);
  const kept = before.instances.filter((i) => i.pane === 0);
  const order = kept.map((i) => i.name);
  await removeSuite(page);
  await page.screenshot({ path: path.join(out, `${chartId}-after-remove.png`) });
  const left = await smcLegendNames(page);
  const toAdd = [SUITE, ...order.filter((n) => n !== SUITE && !left.includes(n))];
  const addResults: Record<string, string> = {};
  for (const name of toAdd) {
    addResults[name] = await addOwnScript(page, name, name === SUITE ? "Favorites" : "My scripts").then(() => "ok").catch((e) => String((e as Error)?.message ?? e).slice(0, 160));
    if (addResults[name] !== "ok") break; // never stack further adds on a failed one
  }
  await page.screenshot({ path: path.join(out, `${chartId}-after-add.png`) });
  // rebind every consumer to the new Suite (the existing, single-pane binding repair)
  const targets = consumerTargets();
  const rebind: Record<string, string> = {};
  for (const name of order.filter((n) => n !== SUITE)) {
    const target = targets.get(name);
    if (!target) { rebind[name] = "no target config"; continue; }
    rebind[name] = await verifyConsumerBindings(session, target, true, true)
      .then((r) => `${r.ok ? "ok" : "NOT ok"} checked=${r.checked} repaired=${r.repaired.length}`)
      .catch((e) => `error: ${String((e as Error)?.message ?? e).slice(0, 160)}`);
  }
  // Which script and version the new Suite instance is pinned to, read from its own
  // pineId/pineVersion inputs (a coarse search of the chart model gave a false
  // "publication" positive on 2026-10-05). Recorded, not gated: operator decision
  // 2026-10-05 (A) accepts the saved script at the current version; the gate is the
  // source hash below.
  const PIN_SOURCE = `
    const api = window.TradingViewApi; const out = [];
    const n = api.chartsCount ? api.chartsCount() : 1;
    for (let i = 0; i < n; i += 1) {
      const chart = api.chart ? api.chart(i) : api.activeChart();
      for (const st of chart.getAllStudies()) {
        if (st.name !== "SMC Long-Dip Suite") continue;
        const inputs = chart.getStudyById(st.id).getInputValues();
        const get = (id) => (inputs.find((x) => x.id === id) || {}).value || null;
        out.push({ chart: i, id: st.id, pineId: get("pineId"), pineVersion: get("pineVersion") });
      }
    }
    return out;
  `;
  const suitePin = await page.evaluate((src) => new Function(src)(), PIN_SOURCE).catch((e) => ({ error: String(e).slice(0, 160) }));
  // restore visibility
  for (const inst of kept) await setHidden(page, inst.name, inst.hidden);
  const after = await inventoryChartInPlace(page, chartId);
  const keptForDiff = kept;
  const diff = diffInputs(keptForDiff, after.instances.filter((i) => i.pane === 0), { [SUITE]: acceptNewSuiteInputs });
  const visibility = kept.filter((k) => after.instances.find((a) => a.name === k.name)?.hidden !== k.hidden).map((k) => k.name);
  const bindingsOk = Object.values(rebind).every((v) => v.startsWith("ok"));
  const suiteCurrent = after.suiteSources.length === 1 && after.suiteSources[0].sha256 === expectedSuiteSha();
  const fromPublication = Array.isArray(suitePin) && suitePin.length === 1 && suitePin[0].pineId === SUITE_PUBLICATION_ID;
  const clean = Array.isArray(suitePin) && suitePin.length === 1 && diff.missing.length === 0 && diff.added.length === 0 && diff.diffs.length === 0 && visibility.length === 0 && bindingsOk && suiteCurrent
    && Object.values(addResults).every((v) => v === "ok");
  let saved = false;
  if (!dryRun && clean) {
    await saveChangedChartLayout(page);
    saved = true;
  }
  const result = {
    chartId, dryRun, clean, saved, pruned, fromPublication, suitePin, removedLeft: left, addResults, rebind, visibilityMismatch: visibility, suiteCurrent,
    before: before.instances.map((i) => `${i.name}#${i.entityId}${i.hidden ? "(hidden)" : ""}`),
    after: after.instances.map((i) => `${i.name}#${i.entityId}${i.hidden ? "(hidden)" : ""}`),
    suiteAfter: after.suiteSources.map((x) => `${x.pane}:${x.entityId}:${x.sha256?.slice(0, 12)}`),
    ...diff,
  };
  fs.writeFileSync(path.join(out, `${chartId}-migrate.json`), JSON.stringify({ result, before, after }, null, 2));
  return result;
}

async function publishSuite(page: Page, out: string) {
  await gotoChartAndAwaitScript(page, "https://www.tradingview.com/chart/hKHTmKhu/", SUITE);
  await page.waitForTimeout(4_000);
  await dismissPromotionOverlay(page).catch(() => undefined);
  await ensurePineEditor(page);
  await openExistingScript(page, SUITE);
  const repoSource = fs.readFileSync("SMC_Long_Dip_Suite.pine", "utf-8");
  let editorSha = normalizedPineSha256(await readEditorContent(page, { expectedDeclarationTitle: SUITE }));
  let savedNow = false;
  if (editorSha !== expectedSuiteSha()) {
    await setEditorContent(page, repoSource);
    await saveScript(page, SUITE);
    await waitForPostSaveCompileSettlement(page, SUITE);
    editorSha = normalizedPineSha256(await readEditorContent(page, { expectedDeclarationTitle: SUITE }));
    savedNow = true;
  }
  if (editorSha !== expectedSuiteSha()) throw new Error(`editor holds ${editorSha.slice(0, 12)}, repository ${expectedSuiteSha().slice(0, 12)}`);
  await page.screenshot({ path: path.join(out, "publish-before.png") });
  const result = await publishPrivateScript(page, {
    scriptName: SUITE,
    title: SUITE,
    description: "SMC Long-Dip Suite — private publication of the repository source (skipp-algo).",
  });
  await page.screenshot({ path: path.join(out, "publish-after.png") });
  // The docked editor is account-wide UI state: left open it squeezes vWgAWyfC's chart for every
  // later session, and the CI save flow then cannot open any consumer's settings (tv-save run
  // 37510785146, 2026-10-06 20:29 UTC, after this phase had run).
  await closeDockedEditor(page);
  return { savedNow, editorSha: editorSha.slice(0, 12), publishConfirmed: result.publishConfirmed, noChangeDetected: result.noChangeDetected, versionContext: result.versionContextTexts.slice(0, 5) };
}

async function main(): Promise<void> {
  const args = parseMigrationArgs(process.argv.slice(2));
  fs.mkdirSync(args.out, { recursive: true });
  const session = await newTradingViewSession();
  try {
    if (args.phase === "publish") {
      if (args.dryRun) throw new Error("publish has no dry run");
      const res = await publishSuite(session.page, args.out);
      console.log(JSON.stringify(res));
      if (!res.publishConfirmed) process.exitCode = 1;
      return;
    }
    if (args.phase === "migrate") {
      const res = await migrateChart(session, args.charts[0], args.out, args.dryRun, args.acceptNewSuiteInputs);
      console.log(JSON.stringify({ ...res, diffs: res.diffs.length, diffSample: res.diffs.slice(0, 40) }));
      return;
    }
    const report = [];
    for (const chartId of args.charts) {
      const chart = await inventoryChart(session.page, chartId);
      report.push(chart);
      console.log(JSON.stringify({
        chartId,
        panes: chart.paneCount,
        instances: chart.instances.map((i) => `${i.pane}:${i.name}#${i.entityId}${i.hidden ? "(hidden)" : ""}:${i.inputs.length}in${i.inputsError ? "!" : ""}`),
        suite: chart.suiteSources.map((s) => `${s.pane}:${s.entityId}:${s.sha256?.slice(0, 12)}`),
      }));
    }
    fs.writeFileSync(path.join(args.out, "inventory.json"), JSON.stringify({ takenAt: new Date().toISOString(), charts: report }, null, 2));
  } finally {
    await closeTradingViewSession(session);
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(new URL(import.meta.url).pathname)) {
  await main();
}

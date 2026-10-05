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
//
// Usage: tsx scripts/tv_suite_publication_migration.ts --phase inventory --out <dir>
//          [--charts vWgAWyfC,hKHTmKhu,twh98JLB]

import fs from "node:fs";
import path from "node:path";
import type { Locator, Page } from "playwright";
import {
  closeTradingViewSession,
  dismissPromotionOverlay,
  gotoChartAndAwaitScript,
  newTradingViewSession,
  readAppliedInstanceSources,
} from "../automation/tradingview/lib/tv_shared.js";

export const SUITE = "SMC Long-Dip Suite";
export const DEFAULT_CHARTS = ["vWgAWyfC", "hKHTmKhu", "twh98JLB"];

export type MigrationArgs = { phase: "inventory"; out: string; charts: string[] };

export function parseMigrationArgs(argv: string[]): MigrationArgs {
  const get = (flag: string): string | undefined => {
    const i = argv.indexOf(flag);
    return i >= 0 ? argv[i + 1] : undefined;
  };
  const phase = get("--phase");
  if (phase !== "inventory") throw new Error(`unknown --phase: ${phase ?? "(missing)"}`);
  const out = get("--out");
  if (!out) throw new Error("--out <dir> is required");
  const charts = (get("--charts") ?? DEFAULT_CHARTS.join(",")).split(",").map((c) => c.trim()).filter(Boolean);
  for (const chart of charts) {
    if (!/^[A-Za-z0-9]{6,12}$/.test(chart)) throw new Error(`not a chart id: ${chart}`);
  }
  return { phase, out, charts };
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

const READ_INPUTS_SOURCE = `
  const dialog = Array.from(document.querySelectorAll('[data-name="indicator-properties-dialog"], [role="dialog"]')).pop();
  if (!dialog) return { error: "no dialog" };
  const norm = (v) => (v || "").replace(/\\s+/g, " ").trim();
  const out = [];
  // Each input row: a label cell followed by its control(s). TradingView renders
  // label and control as siblings; walk controls and take the nearest preceding label text.
  const controls = Array.from(dialog.querySelectorAll('input, button[class*="button"], [role="combobox"]'))
    .filter((e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; })
    .filter((e) => !/^(Defaults|Cancel|Ok|Close menu)$/.test(norm(e.innerText)) && !e.closest('[role="tablist"]'));
  for (const c of controls) {
    let label = "";
    let node = c;
    for (let k = 0; k < 6 && node && !label; k += 1) {
      let prev = node.previousElementSibling;
      while (prev && !label) { label = norm(prev.innerText); prev = prev.previousElementSibling; }
      node = node.parentElement;
    }
    const kind = c.tagName === "INPUT" ? (c.type || "text") : "select";
    const value = kind === "checkbox" ? String(c.checked) : c.tagName === "INPUT" ? c.value : norm(c.innerText);
    out.push({ label: label.slice(0, 80), kind, value: String(value).slice(0, 200) });
  }
  return { inputs: out };
`;

async function readInstanceInputs(page: Page, row: Locator): Promise<{ inputs: InputValue[]; error: string }> {
  try {
    await row.locator('[data-qa-id*="legend-source-title"]').first().hover({ force: true });
    await page.waitForTimeout(400);
    await row.locator('[data-qa-id="legend-settings-action"]').click({ force: true });
    await page.locator('[data-id="indicator-properties-dialog-tabs-inputs"]').first().click({ timeout: 10_000 }).catch(() => undefined);
    await page.waitForTimeout(1_200);
    // the dialog virtualises long input lists: scroll it to the end while collecting
    const collected = new Map<string, InputValue>();
    for (let step = 0; step < 60; step += 1) {
      const res = await page.evaluate((src) => new Function(src)(), READ_INPUTS_SOURCE) as { inputs?: InputValue[]; error?: string };
      if (res.error) throw new Error(res.error);
      // A row seen again in the next scroll window carries the same label, kind and
      // value; keep the first sighting. (Two genuinely identical rows collapse —
      // acceptable for a before/after comparison, which is what this feeds.)
      for (const input of res.inputs ?? []) {
        const key = `${input.label}|${input.kind}|${input.value}`;
        if (!collected.has(key)) collected.set(key, input);
      }
      const moved = await page.evaluate(() => {
        const dialog = Array.from(document.querySelectorAll('[data-name="indicator-properties-dialog"], [role="dialog"]')).pop();
        const scroller = dialog ? Array.from(dialog.querySelectorAll("*")).find((e) => e.scrollHeight > e.clientHeight + 20 && getComputedStyle(e).overflowY !== "visible") : null;
        if (!scroller) return false;
        const before = scroller.scrollTop;
        scroller.scrollTop = before + scroller.clientHeight * 0.8;
        return scroller.scrollTop !== before;
      });
      if (!moved) break;
      await page.waitForTimeout(250);
    }
    await page.locator('[data-name="indicator-properties-dialog"], [role="dialog"]').last()
      .locator("button").filter({ hasText: /^Cancel$/ }).first().click().catch(() => page.keyboard.press("Escape"));
    await page.waitForTimeout(500);
    return { inputs: [...collected.values()], error: "" };
  } catch (error) {
    await page.keyboard.press("Escape").catch(() => undefined);
    return { inputs: [], error: String((error as Error)?.message ?? error).slice(0, 300) };
  }
}

async function inventoryChart(page: Page, chartId: string) {
  await gotoChartAndAwaitScript(page, `https://www.tradingview.com/chart/${chartId}/`, SUITE);
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
      const { inputs, error } = await readInstanceInputs(page, row);
      instances.push({ pane, name, entityId, hidden, inputs, inputsError: error });
    }
  }
  const suiteSources = await readAppliedInstanceSources(page, SUITE);
  return { chartId, paneCount: await panes.count(), instances, suiteSources };
}

async function main(): Promise<void> {
  const args = parseMigrationArgs(process.argv.slice(2));
  fs.mkdirSync(args.out, { recursive: true });
  const session = await newTradingViewSession();
  try {
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

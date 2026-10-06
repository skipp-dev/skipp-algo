#!/usr/bin/env -S node --enable-source-maps

// Long-engine log readout for the SMC Long-Dip Suite.
//
// The Suite writes one Pine log line per lifecycle event (LONG ARMED /
// CONFIRMED / READY / INVALID, with the ready and strict blocker texts and the
// invalidation reason) when "Show long engine debug" is on and "Focus View" is
// off. This script turns both on IN THE SESSION, opens the Suite's Pine logs and
// collects every line by scrolling the list. Nothing is saved; the stored layout
// keeps both inputs as they are.
//
// Risk note: automated read of TradingView output, operator decision
// 2026-10-04; ADR-0034, addendum 2026-10-04 (second bullet list).
//
// Usage: tsx scripts/tv_long_engine_log_readout.ts --out <dir>
//          [--symbols NASDAQ:AAPL,NYSE:JPM] [--interval 15] [--session keep|Regular|Extended]
//          [--suite-input "Require Internal Break For Confirm=false" ...]  (session only, never saved)

import fs from "node:fs";
import path from "node:path";
import type { Locator, Page } from "playwright";
import {
  closeTradingViewSession,
  closePineEditorIfVisible,
  dismissPromotionOverlay,
  gotoChartClosingDockedEditor,
  newTradingViewSession,
  setChartSessionMode,
} from "../automation/tradingview/lib/tv_shared.js";
import {
  applySuiteInputOverrides,
  getAllFlagValues,
  parseSuiteInputOverride,
  type SuiteInputOverride,
} from "../automation/tradingview/lib/tv_suite_input_overrides.js";
import { DEFAULT_SYMBOLS, symbolSlug } from "./tv_strategy_report_readout.js";

export const SUITE_NAME = "SMC Long-Dip Suite";

export type LogArgs = { out: string; symbols: string[]; interval: string; session: string; suiteInputs: SuiteInputOverride[] };

export function parseLogArgs(argv: string[]): LogArgs {
  const get = (flag: string): string | undefined => {
    const i = argv.indexOf(flag);
    return i >= 0 ? argv[i + 1] : undefined;
  };
  const out = get("--out");
  if (!out) throw new Error("--out <dir> is required");
  const session = get("--session") ?? "keep";
  if (!["keep", "Regular", "Extended"].includes(session)) throw new Error(`unknown session: ${session}`);
  const symbols = (get("--symbols") ?? DEFAULT_SYMBOLS.join(",")).split(",").map((s) => s.trim()).filter(Boolean);
  if (symbols.length === 0) throw new Error("no symbols");
  const suiteInputs = getAllFlagValues(argv, "--suite-input").map(parseSuiteInputOverride);
  return { out, symbols, interval: get("--interval") ?? "15", session, suiteInputs };
}

/** Split a panel text into log lines; a line starts with "[<ISO time>]: ". */
export function splitLogLines(text: string): string[] {
  return text.split("\n").map((l) => l.trim()).filter((l) => /^\[\d{4}-\d{2}-\d{2}T[^\]]+\]: /.test(l));
}

export type LongEvent = { time: string; event: string; fields: Record<string, string> };

/** Parse "[t]: LONG ARMED | src=OB | ... | reason=..." into a structured event; other lines -> null. */
export function parseLongEvent(line: string): LongEvent | null {
  const m = line.match(/^\[([^\]]+)\]: (LONG [A-Z]+)((?: \| [^|]*)*)$/);
  if (!m) return null;
  const fields: Record<string, string> = {};
  for (const part of m[3].split(" | ").map((p) => p.trim()).filter(Boolean)) {
    const eq = part.indexOf("=");
    if (eq > 0) fields[part.slice(0, eq)] = part.slice(eq + 1);
  }
  return { time: m[1], event: m[2], fields };
}

const suiteRow = (page: Page): Locator =>
  page.locator('[data-qa-id="chart-container"]').first()
    .locator('[data-qa-id="legend-source-item"]').filter({ hasText: SUITE_NAME }).first();

async function setCheckbox(dialog: Locator, label: string, wanted: boolean): Promise<void> {
  const text = dialog.getByText(label, { exact: true }).first();
  await text.scrollIntoViewIfNeeded();
  const box = text.locator("xpath=ancestor::*[.//input[@type='checkbox']][1]//input[@type='checkbox']").first();
  if ((await box.isChecked()) !== wanted) await text.click();
  if ((await box.isChecked()) !== wanted) throw new Error(`could not set "${label}" to ${wanted}`);
}

async function enableDebugLogs(page: Page): Promise<void> {
  const row = suiteRow(page);
  await row.locator('[data-qa-id*="legend-source-title"]').first().hover();
  await page.waitForTimeout(400);
  await row.locator('[data-qa-id="legend-settings-action"]').click();
  await page.locator('[data-id="indicator-properties-dialog-tabs-inputs"]').click();
  await page.waitForTimeout(800);
  const dialog = page.locator('[data-name="indicator-properties-dialog"], [role="dialog"]').last();
  await setCheckbox(dialog, "Focus View", false);
  await setCheckbox(dialog, "Show long engine debug", true);
  await dialog.locator("button").filter({ hasText: /^Ok$/ }).first().click();
}

const COLLECT_SOURCE = `
  return (async () => {
    const anchor = document.querySelector('[data-name="button-toggle-logs"]');
    let panel = anchor;
    for (let k = 0; k < 8 && panel; k += 1) { if (panel.getBoundingClientRect().height > 500) break; panel = panel.parentElement; }
    if (!panel) return { error: "no logs panel" };
    const scrollers = Array.from(panel.querySelectorAll("*")).filter((e) => e.scrollHeight > e.clientHeight + 20 && getComputedStyle(e).overflowY !== "visible");
    const scroller = scrollers.sort((a, b) => b.scrollHeight - a.scrollHeight)[0];
    const seen = new Set();
    const lines = [];
    const take = () => {
      for (const l of panel.innerText.split("\\n")) {
        const t = l.trim();
        if (/^\\[\\d{4}-\\d{2}-\\d{2}T[^\\]]+\\]: /.test(t) && !seen.has(t)) { seen.add(t); lines.push(t); }
      }
    };
    if (!scroller) { take(); return { lines, scrolled: false }; }
    scroller.scrollTop = 0;
    await new Promise((r) => setTimeout(r, 600));
    let guard = 0;
    let stuck = 0;
    for (;;) {
      take();
      const before = scroller.scrollTop;
      scroller.scrollTop = before + Math.max(50, scroller.clientHeight * 0.5);
      await new Promise((r) => setTimeout(r, 300));
      if (scroller.scrollTop === before) {
        // a lazily growing list: give it time before calling the end
        stuck += 1;
        await new Promise((r) => setTimeout(r, 1000));
        if (stuck >= 5) break;
      } else stuck = 0;
      if ((guard += 1) > 50000) break;
    }
    take();
    return { lines, scrolled: true, scrollHeight: scroller.scrollHeight, atEnd: scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 2 };
  })();
`;

async function readLogs(page: Page): Promise<{ lines: string[]; scrolled: boolean }> {
  const row = suiteRow(page);
  await row.locator('[data-qa-id*="legend-source-title"]').first().hover();
  await page.waitForTimeout(500);
  await row.locator('[data-qa-id="legend-more-action"]').click({ force: true });
  await page.waitForTimeout(800);
  await page.getByText(/^Pine logs/).first().click();
  // wait until the panel shows lines and their count stops growing
  let last = -1;
  const deadline = Date.now() + 120_000;
  for (;;) {
    await page.waitForTimeout(3_000);
    const n = await page.evaluate(() => (document.body.innerText.match(/\n\[\d{4}-\d{2}-\d{2}T/g) ?? []).length);
    if (n > 0 && n === last) break;
    if (Date.now() >= deadline) throw new Error(`pine logs did not settle (visible lines ${n})`);
    last = n;
  }
  const res = await page.evaluate((src) => new Function(src)(), COLLECT_SOURCE) as { lines?: string[]; scrolled?: boolean; error?: string };
  if (res.error) throw new Error(res.error);
  return { lines: res.lines ?? [], scrolled: Boolean(res.scrolled) };
}

async function main(): Promise<void> {
  const args = parseLogArgs(process.argv.slice(2));
  fs.mkdirSync(args.out, { recursive: true });
  const base = process.env.TV_CHART_URL || "https://www.tradingview.com/chart/vWgAWyfC/";
  const summary: Record<string, unknown>[] = [];
  const suiteSource = fs.readFileSync("SMC_Long_Dip_Suite.pine", "utf-8");
  for (const symbol of args.symbols) {
    // a fresh session per symbol: the logs panel keeps the previous symbol's lines otherwise
    const session = await newTradingViewSession();
    try {
      const { page } = session;
      await gotoChartClosingDockedEditor(page, `${base}?symbol=${encodeURIComponent(symbol)}&interval=${args.interval}`, SUITE_NAME);
      await page.waitForTimeout(4_000);
      await dismissPromotionOverlay(page).catch(() => undefined);
      // A docked Pine editor squeezes the chart until the legend rows have no height.
      if (!(await closePineEditorIfVisible(page).catch(() => false))) {
        // closePineEditorIfVisible cannot reach the X of a DOCKED editor (title bar outside its scope);
        // its own Close button (aria-label/title "Close") above the dialog closes it. Measured 2026-10-05.
        const editorOpen = await page.locator('#pine-editor-dialog').first().isVisible().catch(() => false);
        if (editorOpen) await page.locator('button[aria-label="Close"][title="Close"]').first().click().catch(() => undefined);
        await page.waitForTimeout(2_000);
      }
      if (args.session !== "keep") await setChartSessionMode(page, args.session as "Regular" | "Extended");
      await enableDebugLogs(page);
      await page.waitForTimeout(5_000);
      // after the dialog: its Ok would re-apply the dialog's values
      const suiteInputs = await applySuiteInputOverrides(page, SUITE_NAME, suiteSource, args.suiteInputs);
      const { lines, scrolled } = await readLogs(page);
      const stem = `${symbolSlug(symbol)}_${args.interval}_${args.session}`;
      fs.writeFileSync(path.join(args.out, `${stem}.log`), lines.join("\n") + "\n");
      const events = lines.map(parseLongEvent).filter((e): e is LongEvent => e !== null);
      const counts: Record<string, number> = {};
      for (const e of events) counts[e.event] = (counts[e.event] ?? 0) + 1;
      const row = { symbol, interval: args.interval, session: args.session, lines: lines.length, scrolled,
        first: lines[0]?.slice(1, 26) ?? null, last: lines.at(-1)?.slice(1, 26) ?? null, counts, suiteInputs, readAt: new Date().toISOString() };
      summary.push(row);
      console.log(JSON.stringify(row));
      fs.writeFileSync(path.join(args.out, "summary.json"), JSON.stringify(summary, null, 2));
    } finally {
      await closeTradingViewSession(session);
    }
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(new URL(import.meta.url).pathname)) {
  await main();
}

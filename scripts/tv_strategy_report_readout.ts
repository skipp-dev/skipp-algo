#!/usr/bin/env -S node --enable-source-maps

// Strategy-report readout for the SMC Long-Dip Strategy.
//
// For each symbol the chart is loaded with `?symbol=…&interval=…`, the (hidden)
// strategy is shown IN THE SESSION, and for each execution stage the strategy
// report is recalculated and downloaded via the report's own "Download data as
// XLSX". Nothing is saved: the layout keeps its stored symbol, interval,
// visibility and inputs (instance adds would persist immediately — this script
// adds none).
//
// Risk note: this reads backtest results from TradingView by script. Operator
// decision 2026-10-04 ("Ja, bauen und fahren"); see ADR
// tradingview-onboarding-automation-risk-acceptance, addendum 2026-10-04.
//
// Usage: tsx scripts/tv_strategy_report_readout.ts --out <dir>
//          [--symbols NASDAQ:AAPL,NYSE:JPM] [--stages Armed,Confirmed,Ready,Best,Strict]
//          [--interval 15] [--session keep|Regular|Extended]

import fs from "node:fs";
import path from "node:path";
import type { Page } from "playwright";
import {
  closeTradingViewSession,
  closePineEditorIfVisible,
  dismissPromotionOverlay,
  gotoChartAndAwaitScript,
  newTradingViewSession,
  setChartSessionMode,
} from "../automation/tradingview/lib/tv_shared.js";

export const STRATEGY_NAME = "SMC Long-Dip Strategy";
export const STAGES = ["Armed", "Confirmed", "Ready", "Best", "Strict"] as const;
export const DEFAULT_SYMBOLS = ["NASDAQ:AAPL", "NASDAQ:NVDA", "NYSE:JPM", "NYSE:XOM", "NYSE:UNH"];

export type ReadoutArgs = { out: string; symbols: string[]; stages: string[]; interval: string; session: string };

export function parseReadoutArgs(argv: string[]): ReadoutArgs {
  const get = (flag: string): string | undefined => {
    const i = argv.indexOf(flag);
    return i >= 0 ? argv[i + 1] : undefined;
  };
  const out = get("--out");
  if (!out) throw new Error("--out <dir> is required");
  const stages = (get("--stages") ?? STAGES.join(",")).split(",").map((s) => s.trim()).filter(Boolean);
  for (const stage of stages) {
    if (!(STAGES as readonly string[]).includes(stage)) throw new Error(`unknown stage: ${stage}`);
  }
  // A repeated stage is served from TradingView's cache without a recalculation,
  // which the loading-edge wait would (correctly) refuse.
  if (new Set(stages).size !== stages.length) throw new Error("duplicate stage");
  const session = get("--session") ?? "keep";
  if (!["keep", "Regular", "Extended"].includes(session)) throw new Error(`unknown session: ${session}`);
  const symbols = (get("--symbols") ?? DEFAULT_SYMBOLS.join(",")).split(",").map((s) => s.trim()).filter(Boolean);
  if (symbols.length === 0) throw new Error("no symbols");
  return { out, symbols, stages, interval: get("--interval") ?? "15", session };
}

/** "NASDAQ:AAPL" -> "AAPL"; file-name safe. */
export function symbolSlug(symbol: string): string {
  return symbol.split(":").pop()!.replace(/[^A-Za-z0-9._-]/g, "_");
}

/** The report's state as read from the bottom panel text. */
export function classifyReportText(text: string): { state: "no_trades" | "trades" | "unknown"; totalTrades: number | null; range: string | null } {
  const range = text.match(/[A-Z][a-z]{2} \d{1,2}, \d{4} — [A-Z][a-z]{2} \d{1,2}, \d{4}/)?.[0] ?? null;
  if (/This report requires trade data/i.test(text)) return { state: "no_trades", totalTrades: 0, range };
  const total = text.match(/\n(\d[\d,]*)\nTotal trades/);
  if (total) return { state: "trades", totalTrades: Number(total[1].replace(/,/g, "")), range };
  // TradingView remembers the last report tab; on "List of trades" the count is not shown
  // (seen 2026-10-05). The XLSX download carries the trades either way.
  if (/\nList of trades\n/.test(text) && /\nTrade number\n/.test(text)) return { state: "trades", totalTrades: null, range };
  return { state: "unknown", totalTrades: null, range };
}

const bottomText = (page: Page): Promise<string> =>
  page.evaluate(() => {
    const b = document.querySelector("#bottom-area, .layout__area--bottom");
    return b ? (b as HTMLElement).innerText : "";
  });

const STRATEGY_STATUS_SOURCE = `
  const rows = Array.from(document.querySelectorAll('[data-qa-id="chart-container"]'))[0]
    ?.querySelectorAll('[data-qa-id="legend-source-item"]') ?? [];
  for (const row of rows) {
    if (row.innerText.includes(${JSON.stringify(STRATEGY_NAME)})) return row.getAttribute("data-status");
  }
  return "missing";
`;

const strategyStatus = (page: Page): Promise<string> =>
  page.evaluate((source) => new Function(source)(), STRATEGY_STATUS_SOURCE) as Promise<string>;

/**
 * Wait for the recalculation that an input change triggers, then for a settled report.
 *
 * The report text alone is NOT a usable signal: it keeps showing the previous
 * run until the new one lands, and two stages can legitimately yield the same
 * text. Measured 2026-10-04: a text-only wait read Armed's 27 trades for
 * Confirmed/Ready/Best, and read Strict's "no trades" for every stage after it.
 * The legend row's `data-status` flips to "loading" while the strategy
 * recalculates; that edge is required here (fail-closed if it never shows).
 */
async function awaitRecalculatedReport(page: Page, timeoutMs = 120_000): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  let sawLoading = false;
  const loadingDeadline = Date.now() + 20_000;
  while (!sawLoading) {
    if ((await strategyStatus(page)) === "loading") sawLoading = true;
    else if (Date.now() >= loadingDeadline) throw new Error("strategy never entered the loading state after the input change");
    else await page.waitForTimeout(100);
  }
  while ((await strategyStatus(page)) === "loading") {
    if (Date.now() >= deadline) throw new Error(`strategy still loading after ${timeoutMs}ms`);
    await page.waitForTimeout(250);
  }
  return awaitStableReport(page, deadline);
}

/** A report whose range is a single day is still loading its data (seen 2026-10-04: "Oct 4, 2026 — Oct 4, 2026"). */
export function reportRangeIsDegenerate(range: string | null): boolean {
  if (!range) return true;
  const [from, to] = range.split(" — ");
  return from === to;
}

async function awaitStableReport(page: Page, deadline = Date.now() + 90_000): Promise<string> {
  let previous = "";
  for (;;) {
    await page.waitForTimeout(1_500);
    const now = await bottomText(page);
    const verdict = classifyReportText(now);
    if (now === previous && verdict.state !== "unknown" && !reportRangeIsDegenerate(verdict.range)) return now;
    if (Date.now() >= deadline) throw new Error(`strategy report did not settle; last text: ${now.slice(0, 300)}`);
    previous = now;
  }
}

async function showStrategy(page: Page): Promise<void> {
  const row = page.locator('[data-qa-id="chart-container"]').first()
    .locator('[data-qa-id="legend-source-item"]').filter({ hasText: STRATEGY_NAME }).first();
  // The row box is wider than its text; the canvas intercepts the pointer at
  // its centre, so hover the title to reveal the row's actions.
  await row.locator('[data-qa-id*="legend-source-title"]').first().hover();
  await page.waitForTimeout(500);
  const eye = row.locator('[data-qa-id="legend-show-hide-action"]');
  if ((await eye.getAttribute("aria-label")) !== "Show") throw new Error("strategy is already visible; expected the stored layout to keep it hidden");
  await eye.click();
  await page.locator('[data-qa-id="backtesting"]').first().waitFor({ state: "visible", timeout: 30_000 });
  await awaitRecalculatedReport(page);
}

/** Returns false when the stage was already selected (no recalculation follows). */
async function setStage(page: Page, stage: string): Promise<boolean> {
  await page.locator('[data-qa-id="backtesting-strategy-settings-button"]').click();
  await page.locator('[data-id="indicator-properties-dialog-tabs-inputs"]').click();
  await page.waitForTimeout(1_000);
  const dialog = page.locator('[data-name="indicator-properties-dialog"], [role="dialog"]').last();
  const text = await dialog.innerText();
  // Refuse to measure an unbound strategy: an unbound source input reads "close".
  const bound = (text.match(/SMC Long-Dip Suite[^\n]*: BUS (Armed|Confirmed|Ready|EntryBest|EntryStrict|Trigger|Invalidation|QualityScore)/g) ?? []).length;
  if (bound !== 8) throw new Error(`strategy inputs are not bound to the Suite (${bound}/8 BUS rows)`);
  const stageButton = dialog.locator("button").filter({ hasText: /^(Armed|Confirmed|Ready|Best|Strict)$/ }).first();
  if ((await stageButton.innerText()).trim() === stage) {
    await dialog.locator("button").filter({ hasText: /^Cancel$/ }).first().click();
    return false;
  }
  await stageButton.click();
  await page.waitForTimeout(500);
  await page.locator('[role="option"]').filter({ hasText: stage }).first().click();
  await page.waitForTimeout(300);
  await dialog.locator("button").filter({ hasText: /^Ok$/ }).first().click();
  return true;
}

async function downloadXlsx(page: Page, target: string): Promise<void> {
  await page.locator('[data-qa-id="backtesting-open-context-menu"]').first().click();
  const [download] = await Promise.all([
    page.waitForEvent("download", { timeout: 60_000 }),
    page.getByText("Download data as XLSX").first().click(),
  ]);
  await download.saveAs(target);
}

async function main(): Promise<void> {
  const args = parseReadoutArgs(process.argv.slice(2));
  fs.mkdirSync(args.out, { recursive: true });
  const base = process.env.TV_CHART_URL || "https://www.tradingview.com/chart/vWgAWyfC/";
  const summary: Record<string, unknown>[] = [];
  const session = await newTradingViewSession();
  try {
    const { page } = session;
    for (const symbol of args.symbols) {
      await gotoChartAndAwaitScript(page, `${base}?symbol=${encodeURIComponent(symbol)}&interval=${args.interval}`, STRATEGY_NAME);
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
      await showStrategy(page);
      for (const stage of args.stages) {
        const changed = await setStage(page, stage);
        const text = changed ? await awaitRecalculatedReport(page) : await awaitStableReport(page);
        const verdict = classifyReportText(text);
        const stem = `${symbolSlug(symbol)}_${args.interval}_${stage.toLowerCase()}`;
        fs.writeFileSync(path.join(args.out, `${stem}.txt`), text);
        if (verdict.state === "trades") await downloadXlsx(page, path.join(args.out, `${stem}.xlsx`));
        const row = { symbol, interval: args.interval, session: args.session, stage, ...verdict, readAt: new Date().toISOString() };
        summary.push(row);
        console.log(JSON.stringify(row));
        fs.writeFileSync(path.join(args.out, "summary.json"), JSON.stringify(summary, null, 2));
      }
    }
  } finally {
    await closeTradingViewSession(session);
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(new URL(import.meta.url).pathname)) {
  await main();
}

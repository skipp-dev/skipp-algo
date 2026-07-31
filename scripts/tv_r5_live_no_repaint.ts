/**
 * Execute R5-REBUILD-LIVE-NO-REPAINT against the OPEN regular session.
 *
 * This is the one R5 case Bar Replay cannot stand in for. Replay hands the
 * script finished bars; the property here is what the script publishes while a
 * higher-frame bar is still FORMING, which only exists on a live feed. The US
 * regular session runs 13:30-20:00 UTC, so the run is only meaningful inside
 * that window and refuses to certify anything outside it.
 *
 * What it does: park a 5m regular-session chart in UTC, then read the Data
 * Window on a fixed cadence for long enough to cross at least one 15m boundary.
 * Every sample records the confirmed rows AND the whole row set, so the
 * evaluator can tell "held still because nothing repaints" apart from "held
 * still because the feed was dead".
 *
 * It does not save the layout and does not publish anything.
 *
 * Usage:
 *   TV_STORAGE_STATE=… TV_CHART_URL=… npx tsx scripts/tv_r5_live_no_repaint.ts \
 *     --out artifacts/governance/<evidence>.json [--samples 40] [--every 30]
 */
import fs from "node:fs";
import path from "node:path";

import {
  addCurrentScriptToChart,
  closeTradingViewSession,
  ensurePineEditor,
  gotoChart,
  newTradingViewSession,
  readDataWindowValues,
  removeVisibleChartScriptInstances,
  setChartInterval,
  setChartSessionMode,
  setChartTimezone,
  setEditorContent,
} from "../automation/tradingview/lib/tv_shared.js";
import {
  buildLiveSample,
  evaluateLiveNoRepaint,
  mapHtfDiagnostics,
  parseDataWindowItems,
  type LiveSample,
} from "../automation/tradingview/lib/tv_validation_model.js";

const SOURCE = path.resolve("SMC_HTF_Confluence.pine");
const SCRIPT = "SMC HTF Confluence";
const FRAME = "15";
const FRAME_MINUTES = 15;

type Cli = { out: string; samples: number; everySeconds: number };

function parseArgs(argv: string[]): Cli {
  let out = "";
  let samples = 40;
  let everySeconds = 30;
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--out") out = argv[i + 1] ?? "";
    if (argv[i] === "--samples") samples = Number(argv[i + 1]);
    if (argv[i] === "--every") everySeconds = Number(argv[i + 1]);
  }
  if (!out) throw new Error("--out <path> is required");
  if (!Number.isFinite(samples) || samples < 4) throw new Error("--samples must be at least 4");
  if (!Number.isFinite(everySeconds) || everySeconds < 5) throw new Error("--every must be at least 5 seconds");
  return { out, samples, everySeconds };
}

/**
 * Cheap guard: could `at` plausibly fall inside the US regular session?
 *
 * The session is 13:30-20:00 UTC under EDT and 14:30-21:00 UTC under EST, so
 * this accepts the UNION 13:30-21:00 rather than pretending to know the offset,
 * and it does not know about market holidays. That is deliberate — it only
 * exists to stop a pointless overnight run. The real liveness proof is
 * empirical and lives in the evaluator: a run in which no Data Window value
 * ever moved is rejected as vacuous no matter what the clock said.
 */
export function insideRegularSessionUtc(at: Date): boolean {
  const day = at.getUTCDay();
  if (day === 0 || day === 6) return false;
  const minutes = at.getUTCHours() * 60 + at.getUTCMinutes();
  return minutes >= 13 * 60 + 30 && minutes < 21 * 60;
}

function nowUtc(): string {
  return `${new Date().toISOString().slice(0, 19)}Z`;
}

async function main(): Promise<number> {
  const cli = parseArgs(process.argv.slice(2));
  const startedAt = new Date();
  const report: Record<string, unknown> = {
    schemaVersion: 1,
    requirementId: "R5-REBUILD",
    caseId: "R5-REBUILD-LIVE-NO-REPAINT",
    evidenceType: "live_no_repaint_execution",
    chartUrl: process.env.TV_CHART_URL ?? "",
    startedAtUtc: `${startedAt.toISOString().slice(0, 19)}Z`,
    frame: FRAME,
    cadenceSeconds: cli.everySeconds,
    plannedSamples: cli.samples,
  };

  if (!insideRegularSessionUtc(startedAt)) {
    report.status = "not_runnable";
    report.reason = "outside the US regular session (13:30-20:00 UTC, Mon-Fri); a live no-repaint run needs an open market";
    fs.writeFileSync(cli.out, `${JSON.stringify(report, null, 2)}\n`);
    console.log(`[abort] ${report.reason}`);
    return 2;
  }

  const session = await newTradingViewSession();
  const page = session.page;
  const samples: LiveSample[] = [];

  try {
    await gotoChart(page);
    await page.waitForTimeout(7_000);
    await setChartInterval(page, "5");
    await setChartSessionMode(page, "Regular");
    await setChartTimezone(page, "UTC");
    await page.waitForTimeout(4_000);

    const probe = mapHtfDiagnostics(
      parseDataWindowItems(await readDataWindowValues(page).catch(() => [])),
      FRAME,
    );
    let republished = false;
    if (probe.available !== "1") {
      // The saved layout should already carry a working instance, but a chart
      // that publishes nothing would make every sample below vacuous. Restore
      // it from repo source rather than certify against silence. The layout is
      // deliberately NOT saved here.
      console.log(`[repair] chart publishes nothing (${JSON.stringify(probe)}); reinstalling from repo source`);
      await removeVisibleChartScriptInstances(page, SCRIPT).catch(() => 0);
      await ensurePineEditor(page);
      await page.waitForTimeout(2_000);
      await setEditorContent(page, fs.readFileSync(SOURCE, "utf-8"));
      await page.waitForTimeout(3_000);
      await addCurrentScriptToChart(page, SCRIPT, { forceInsert: true, stepTimeoutMs: 90_000 })
        .catch((error) => console.log("add:", String(error).slice(0, 150)));
      await page.waitForTimeout(15_000);
      republished = true;
    }
    report.republishedInstance = republished;

    for (let i = 0; i < cli.samples; i += 1) {
      const at = nowUtc();
      const parsed = parseDataWindowItems(await readDataWindowValues(page).catch(() => []));
      const sample = buildLiveSample(parsed, FRAME, at);
      samples.push(sample);
      console.log(
        `[${i + 1}/${cli.samples}] ${at} available=${sample.available} close=${sample.sourceCloseUtc} `
        + `${JSON.stringify(sample.confirmed)}`,
      );
      if (i < cli.samples - 1) await page.waitForTimeout(cli.everySeconds * 1_000);
    }

    const finishedAt = new Date();
    const verdict = evaluateLiveNoRepaint(samples, FRAME_MINUTES);
    // The window must have stayed open for the whole run, or the tail samples
    // were taken against a closing/closed feed.
    const stayedOpen = insideRegularSessionUtc(finishedAt);
    if (!stayedOpen) verdict.violations.push("the regular session closed during the run; the tail samples are not live");

    report.finishedAtUtc = `${finishedAt.toISOString().slice(0, 19)}Z`;
    report.sessionOpenThroughout = stayedOpen;
    report.verdict = verdict;
    report.observedDiagnostics = {
      confirmedValuesStableInsideOpenSourceBar:
        verdict.confirmedValuesStableInsideOpenSourceBar && stayedOpen ? "1" : "0",
      // The product path requests its frames with barmerge.lookahead_on and
      // reads the tuple at [1]; lookahead_off is not on it. The live check
      // above is what proves that idiom did not leak future data.
      lookaheadOffProductPath: "0",
    };
    report.samples = samples.map((sample) => ({
      atUtc: sample.atUtc,
      available: sample.available,
      sourceCloseUtc: sample.sourceCloseUtc,
      confirmed: sample.confirmed,
    }));
    report.status = verdict.confirmedValuesStableInsideOpenSourceBar && stayedOpen ? "pass" : "fail";

    fs.writeFileSync(cli.out, `${JSON.stringify(report, null, 2)}\n`);
    console.log(`[verdict] ${report.status} ${JSON.stringify(verdict)}`);
    return report.status === "pass" ? 0 : 1;
  } finally {
    await closeTradingViewSession(session);
  }
}

main().then((rc) => process.exit(rc)).catch((error) => {
  console.error(error);
  process.exit(1);
});

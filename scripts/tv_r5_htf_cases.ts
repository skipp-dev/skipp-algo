/**
 * Repair the R5 validation layout and execute the four HTF availability cases.
 *
 * The layout is in a known-defective state: it still carries the pre-fix
 * CE10156 instance of SMC HTF Confluence from 2026-07-30. Anything that adds a
 * script only when missing sees that legend row and skips, so the chart keeps
 * publishing nothing — which is why these four cases could never run. Step one
 * is therefore to clear it, publish a working instance from the repo source,
 * and SAVE the layout so the defect does not come back.
 *
 * Then:
 *   R5-REBUILD-FAIL-CLOSED  — move the chart onto 15m / 60m / 240m and require
 *     the equally-framed request to report unavailable. This is the
 *     _strictly_higher rule; no replay involved.
 *   R5-REBUILD-HTF-15M/1H/4H — step Bar Replay and require the confirmed source
 *     close to advance ONLY by whole frames. Each frame is stepped from a chart
 *     timeframe ONE LEVEL BELOW it, so a boundary is a few bars away and the
 *     frame still stays strictly higher than the chart.
 *
 * Fails closed everywhere: a chart whose script publishes nothing yields no
 * diagnostics at all (mapHtfDiagnostics never defaults `available`), so a
 * broken chart cannot be mistaken for a passing FAIL-CLOSED.
 *
 * Usage:
 *   TV_STORAGE_STATE=… TV_CHART_URL=… npx tsx scripts/tv_r5_htf_cases.ts \
 *     --out artifacts/governance/<evidence>.json [--no-save]
 */
import fs from "node:fs";
import path from "node:path";

import {
  addCurrentScriptToChart,
  closeTradingViewSession,
  enterBarReplay,
  ensurePineEditor,
  exitBarReplay,
  gotoChart,
  jumpToReplayCheckpoint,
  newTradingViewSession,
  readDataWindowValues,
  removeVisibleChartScriptInstances,
  saveChangedChartLayout,
  setChartInterval,
  setChartTimezone,
  setEditorContent,
  stepReplayForward,
  waitForBarReplayToolbar,
} from "../automation/tradingview/lib/tv_shared.js";
import {
  evaluateReplayCase,
  evaluateSourceCloseBoundaries,
  mapHtfDiagnostics,
  parseDataWindowItems,
  type BoundaryObservation,
} from "../automation/tradingview/lib/tv_validation_model.js";

const SOURCE = path.resolve("SMC_HTF_Confluence.pine");
const SCRIPT = "SMC HTF Confluence";
/** chartTimeframe -> the frame that becomes equal-or-lower there. */
const EQUAL_FRAME_AT: ReadonlyArray<{ interval: string; frame: string }> = [
  { interval: "15", frame: "15" },
  { interval: "60", frame: "60" },
  { interval: "240", frame: "240" },
];

function parseArgs(argv: string[]): { out: string; save: boolean } {
  let out = "";
  let save = true;
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--out") out = argv[i + 1] ?? "";
    if (argv[i] === "--no-save") save = false;
  }
  if (!out) throw new Error("--out <path> is required");
  return { out, save };
}

async function main(): Promise<number> {
  const cli = parseArgs(process.argv.slice(2));
  const session = await newTradingViewSession();
  const page = session.page;
  const report: Record<string, unknown> = {
    schemaVersion: 1,
    requirementId: "R5-REBUILD",
    evidenceType: "htf_availability_and_fail_closed_execution",
    chartUrl: process.env.TV_CHART_URL ?? "",
  };

  const readFrame = async (frame: string) =>
    mapHtfDiagnostics(parseDataWindowItems(await readDataWindowValues(page).catch(() => [])), frame);

  try {
    await gotoChart(page);
    await page.waitForTimeout(7_000);

    // ---- repair the layout ------------------------------------------------
    const staleRemoved = await removeVisibleChartScriptInstances(page, SCRIPT).catch(() => 0);
    await ensurePineEditor(page);
    await page.waitForTimeout(2_000);
    await setEditorContent(page, fs.readFileSync(SOURCE, "utf-8"));
    await page.waitForTimeout(3_000);
    await addCurrentScriptToChart(page, SCRIPT, { forceInsert: true, stepTimeoutMs: 90_000 })
      .catch((error) => console.log("add:", String(error).slice(0, 150)));
    await page.waitForTimeout(15_000);
    await setChartInterval(page, "5");
    await setChartTimezone(page, "UTC");

    const afterRepair = await readFrame("15");
    const repaired = afterRepair.available === "1";
    report.layoutRepair = { staleInstancesRemoved: staleRemoved, publishesAfterRepair: repaired, diagnostics: afterRepair };
    console.log(`[repair] removed=${staleRemoved} publishes=${repaired} ${JSON.stringify(afterRepair)}`);
    if (!repaired) {
      throw new Error("the repaired chart still publishes no HTF diagnostics; refusing to run cases against it");
    }
    if (cli.save) {
      await saveChangedChartLayout(page);
      report.layoutSaved = true;
      console.log("[repair] layout saved");
    }

    // ---- R5-REBUILD-FAIL-CLOSED ------------------------------------------
    const failClosed: Array<Record<string, unknown>> = [];
    for (const { interval, frame } of EQUAL_FRAME_AT) {
      const moved = await setChartInterval(page, interval);
      await page.waitForTimeout(8_000);
      const diagnostics = moved ? await readFrame(frame) : {};
      const result = evaluateReplayCase(["available=0"], diagnostics);
      failClosed.push({ chartInterval: interval, requestedFrame: frame, intervalApplied: moved, observed: diagnostics, passed: result.passed, failures: result.failures });
      console.log(`[fail-closed] chart=${interval}m frame=${frame} applied=${moved} ${JSON.stringify(diagnostics)} -> ${result.passed ? "PASS" : "FAIL"}`);
    }
    const failClosedPassed = failClosed.length === EQUAL_FRAME_AT.length && failClosed.every((entry) => entry.passed === true);
    report.failClosed = { passed: failClosedPassed, observations: failClosed };

    // ---- R5-REBUILD-HTF-15M / 1H / 4H ------------------------------------
    // Step on a chart timeframe ONE LEVEL BELOW the frame under test. A
    // boundary is then 3-4 chart bars away instead of 12 or 48, while the
    // frame stays strictly higher than the chart so it remains available at
    // all. Driving every frame from 5m (the first attempt) crossed a 1h
    // boundary in none of 16 steps and would have needed 48 for 4h.
    const htfCases: Array<Record<string, unknown>> = [];
    for (const [frame, minutes, chartInterval, steps] of [
      ["15", 15, "5", 6],
      ["60", 60, "15", 6],
      ["240", 240, "60", 6],
    ] as Array<[string, number, string, number]>) {
      await exitBarReplay(page).catch(() => undefined);
      const onInterval = await setChartInterval(page, chartInterval);
      await page.waitForTimeout(8_000);
      if (!onInterval) {
        htfCases.push({ frame, executed: false, reason: `could not put the chart on ${chartInterval}m to step the ${frame}m frame` });
        console.log(`[htf ${frame}] not executed (chart would not move to ${chartInterval}m)`);
        continue;
      }
      if (!(await enterBarReplay(page))) {
        htfCases.push({ frame, executed: false, reason: "could not enter Bar Replay" });
        continue;
      }
      await waitForBarReplayToolbar(page);
      await jumpToReplayCheckpoint(page, { dateIso: "2025-10-27", timeHhMm: "14:00" });
      await page.waitForTimeout(4_000);

      const observations: BoundaryObservation[] = [];
      for (let step = 0; step <= steps; step += 1) {
        const diagnostics = await readFrame(frame);
        observations.push({ atUtc: `step-${step}`, sourceCloseUtc: diagnostics.sourceCloseUtc ?? null, available: diagnostics.available ?? null });
        if (step === steps) break;
        if ((await stepReplayForward(page, 1)) !== 1) break;
      }
      const verdict = evaluateSourceCloseBoundaries(observations, minutes);
      const available = observations.every((entry) => entry.available === "1");
      htfCases.push({ frame, executed: true, chartInterval, available, observations, verdict, passed: available && verdict.advancesOnlyAtBoundary });
      console.log(`[htf ${frame}] chart=${chartInterval}m available=${available} advances=${verdict.advances} clean=${verdict.advancesOnlyAtBoundary} ${verdict.violations.join("; ")}`);
    }
    report.htfCases = htfCases;

    return failClosedPassed && htfCases.filter((c) => c.executed).every((c) => c.passed === true) ? 0 : 1;
  } finally {
    await exitBarReplay(page).catch(() => undefined);
    fs.writeFileSync(cli.out, `${JSON.stringify(report, null, 2)}\n`, "utf-8");
    console.error(`Evidence written to ${cli.out}`);
    await closeTradingViewSession(session);
  }
}

main().then((rc) => process.exit(rc));

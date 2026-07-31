/**
 * Execute the R5-REBUILD Bar Replay cases against the private validation
 * layout and write an evidence report.
 *
 * The cases assert Session Context diagnostics at pinned UTC checkpoints
 * (the EU/US autumn DST pair and an extended-session instant). Two things make
 * the answer trustworthy rather than merely plausible:
 *
 *  - the chart is put on UTC first, because the Bar Replay date/time dialog
 *    reads in chart-local time and typing a UTC instant into a UTC+2 chart
 *    lands on the wrong bar — the exact confusion these cases exist to detect;
 *  - the assertion is made against `Session Source Close`, an epoch-millisecond
 *    value, which no chart-side clock can corrupt.
 *
 * Fails closed throughout: a checkpoint that does not apply, a Data Window that
 * does not yield the diagnostic, or a case with no expectations is a failure.
 *
 * Usage:
 *   TV_STORAGE_STATE=… TV_CHART_URL=… npx tsx scripts/tv_r5_replay_cases.ts \
 *     --out artifacts/governance/<evidence>.json [--case R5-REBUILD-DST-EU-GAP]
 */
import fs from "node:fs";
import path from "node:path";

import {
  closeTradingViewSession,
  enterBarReplay,
  exitBarReplay,
  gotoChart,
  jumpToReplayCheckpoint,
  newTradingViewSession,
  readDataWindowValues,
  readReplayTimeframeLabel,
  setChartTimezone,
} from "../automation/tradingview/lib/tv_shared.js";
import {
  checkpointAfterClose,
  evaluateReplayCase,
  mapSessionDiagnostics,
  parseDataWindowItems,
  resolveReplayCheckpointPlan,
  timeframeLabelToMinutes,
  type ReplayCaseDefinition,
} from "../automation/tradingview/lib/tv_validation_model.js";

const MANIFEST = path.resolve("artifacts/governance/smc_r5_htf_session_rebuild_manifest.json");

type CaseReport = {
  caseId: string;
  runnable: boolean;
  reason?: string;
  checkpointUtc?: string;
  /** The instant actually selected: one bar past the checkpoint, so it has closed. */
  drivenToUtc?: string;
  checkpointApplied?: boolean;
  /** How many jump attempts the landing needed. */
  attempts?: number;
  dataWindowRows?: number;
  observed?: Record<string, string>;
  expected?: string[];
  passed: boolean;
  failures?: Array<{ key: string; expected: string; observed: string | null }>;
};

function parseArgs(argv: string[]): { out: string; only: string[] } {
  let out = "";
  const only: string[] = [];
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--out") out = argv[i + 1] ?? "";
    if (argv[i] === "--case") only.push(argv[i + 1] ?? "");
  }
  if (!out) throw new Error("--out <path> is required");
  return { out, only: only.filter(Boolean) };
}

/** Split an ISO-8601 UTC instant into the dialog's date and time fields. */
export function splitCheckpoint(utc: string): { dateIso: string; timeHhMm: string } {
  return { dateIso: utc.slice(0, 10), timeHhMm: utc.slice(11, 16) };
}

async function main(): Promise<number> {
  const cli = parseArgs(process.argv.slice(2));
  const manifest = JSON.parse(fs.readFileSync(MANIFEST, "utf-8")) as {
    cases: ReplayCaseDefinition[];
  };
  const candidates = manifest.cases
    .filter((entry) => entry.mode === "replay")
    .filter((entry) => (cli.only.length === 0 ? true : cli.only.includes(entry.caseId)));

  const reports: CaseReport[] = [];
  const session = await newTradingViewSession();
  const page = session.page;
  let timezoneUtc = false;

  try {
    await gotoChart(page);
    await page.waitForTimeout(7_000);

    timezoneUtc = await setChartTimezone(page, "UTC");
    if (!timezoneUtc) {
      // Refuse to guess: without a UTC chart every checkpoint below would be
      // typed in an unknown offset, and a passing case would mean nothing.
      throw new Error("Could not put the chart on UTC; refusing to run UTC checkpoints against an unknown offset");
    }

    for (const entry of candidates) {
      // One replay session PER CASE. Measured 2026-07-31: driving a second
      // checkpoint inside the same replay session returned the previous
      // trading day's values (asking for 2025-11-03T14:50Z reported a source
      // close of 2025-10-31T19:15Z), while the same checkpoint in a fresh
      // session resolved correctly. Cross-case replay state is therefore not
      // trustworthy, and a case must never inherit it.
      await exitBarReplay(page).catch(() => undefined);
      await page.waitForTimeout(2_000);
      if (!(await enterBarReplay(page))) {
        reports.push({
          caseId: entry.caseId,
          runnable: true,
          passed: false,
          reason: "could not enter Bar Replay for this case",
        });
        console.log(`[FAIL] ${entry.caseId}: could not enter Bar Replay`);
        continue;
      }

      const plan = resolveReplayCheckpointPlan(entry);
      if (!plan.runnable || !plan.checkpointUtc) {
        reports.push({ caseId: entry.caseId, runnable: false, reason: plan.reason, passed: false });
        console.log(`[skip] ${entry.caseId}: ${plan.reason}`);
        continue;
      }

      // Drive to the bar AFTER the checkpoint so the checkpoint bar has
      // closed — Bar Replay positions at the bar containing the chosen
      // instant, while Session Context publishes the last CLOSED bar
      // (measured: selecting 13:45 reported Source Close 13:40; selecting
      // 13:50 reported 13:45, which is what the case asserts).
      const timeframeLabel = await readReplayTimeframeLabel(page);
      const timeframeMinutes = timeframeLabelToMinutes(timeframeLabel);
      const target = timeframeMinutes === null
        ? null
        : checkpointAfterClose(plan.checkpointUtc, timeframeMinutes);
      if (target === null) {
        reports.push({
          caseId: entry.caseId,
          runnable: true,
          checkpointUtc: plan.checkpointUtc,
          checkpointApplied: false,
          passed: false,
          reason: `could not resolve the chart timeframe (label ${JSON.stringify(timeframeLabel)})`,
        });
        console.log(`[FAIL] ${entry.caseId}: unresolved chart timeframe ${JSON.stringify(timeframeLabel)}`);
        continue;
      }

      // A committed dialog is not proof the chart moved. Observed twice:
      // the jump reported success while the Data Window still described the
      // PREVIOUS trading day (asking for 2025-11-03 reported a source close of
      // 2025-10-31T19:15Z). Verify the landing by its own date and retry;
      // reporting a stale reading as a verdict is exactly the failure this
      // whole gate has already been burned by once.
      let items: Awaited<ReturnType<typeof readDataWindowValues>> = [];
      let observed: Record<string, string> = {};
      let landed = false;
      let attempts = 0;
      for (; attempts < 3 && !landed; attempts += 1) {
        if (attempts > 0) {
          await exitBarReplay(page).catch(() => undefined);
          await page.waitForTimeout(2_000);
          if (!(await enterBarReplay(page))) break;
        }
        if (!(await jumpToReplayCheckpoint(page, target))) continue;
        await page.waitForTimeout(4_000);
        items = await readDataWindowValues(page);
        observed = mapSessionDiagnostics(parseDataWindowItems(items));
        landed = (observed.sourceCloseUtc ?? "").slice(0, 10) === target.dateIso;
        if (!landed) {
          console.log(
            `[retry] ${entry.caseId}: asked for ${target.dateIso}, landed on ${JSON.stringify(observed.sourceCloseUtc ?? null)}`,
          );
        }
      }

      if (!landed) {
        reports.push({
          caseId: entry.caseId,
          runnable: true,
          checkpointUtc: plan.checkpointUtc,
          drivenToUtc: `${target.dateIso}T${target.timeHhMm}:00Z`,
          checkpointApplied: false,
          observed,
          passed: false,
          reason: `checkpoint did not take after ${attempts} attempt(s); last reading was ${JSON.stringify(observed.sourceCloseUtc ?? null)}`,
        });
        console.log(`[FAIL] ${entry.caseId}: checkpoint ${plan.checkpointUtc} never took`);
        continue;
      }

      const result = evaluateReplayCase(entry.expectedDiagnostics, observed);
      reports.push({
        caseId: entry.caseId,
        runnable: true,
        checkpointUtc: plan.checkpointUtc,
        drivenToUtc: `${target.dateIso}T${target.timeHhMm}:00Z`,
        checkpointApplied: true,
        attempts,
        dataWindowRows: items.length,
        observed,
        expected: entry.expectedDiagnostics,
        passed: result.passed,
        failures: result.failures,
      });
      console.log(
        `[${result.passed ? "PASS" : "FAIL"}] ${entry.caseId} @${plan.checkpointUtc} rows=${items.length} observed=${JSON.stringify(observed)}`,
      );
      for (const failure of result.failures) {
        console.log(`    ${failure.key}: expected ${JSON.stringify(failure.expected)}, observed ${JSON.stringify(failure.observed)}`);
      }
    }
  } finally {
    await exitBarReplay(page).catch(() => undefined);
    const report = {
      schemaVersion: 1,
      requirementId: "R5-REBUILD",
      evidenceType: "bar_replay_checkpoint_execution",
      chartTimezone: timezoneUtc ? "UTC" : "not_set",
      chartUrl: process.env.TV_CHART_URL ?? "",
      caseCount: reports.length,
      passedCount: reports.filter((entry) => entry.passed).length,
      cases: reports,
      notDone: ["layout not saved", "no publication", "no alerts"],
    };
    fs.writeFileSync(cli.out, `${JSON.stringify(report, null, 2)}\n`, "utf-8");
    console.error(`Replay evidence written to ${cli.out}`);
    await closeTradingViewSession(session);
  }

  return reports.length > 0 && reports.every((entry) => entry.passed) ? 0 : 1;
}

main().then((rc) => process.exit(rc));

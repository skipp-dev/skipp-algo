/**
 * Execute R5-REBUILD-ROLLBACK: capture, perturb, restore, save, reload, verify.
 *
 * The runbook's step 1 — "record the current chart symbol, timeframe, layout,
 * and attached scripts" — was never executed, so there is no record of the
 * state that preceded this validation. Worse, the state that DID precede it was
 * the defective layout carrying the pre-CE10156-fix instance (found and
 * repaired in #4248); restoring that would reinstate the very defect the gate
 * exists to have fixed.
 *
 * So the baseline is captured NOW, from the repaired chart, and the drill
 * proves the capability the exit gate actually asks for — "rollback and reload
 * verification" — rather than pretending to restore an unrecorded past.
 *
 * The order is deliberate: the layout is saved ONLY after the in-session
 * restore already matches the capture. A drill that failed to restore must not
 * persist the perturbed chart.
 *
 * Usage:
 *   TV_STORAGE_STATE=… TV_CHART_URL=… npx tsx scripts/tv_r5_rollback_drill.ts \
 *     --out artifacts/governance/<evidence>.json [--dry-run]
 */
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

import {
  addCurrentScriptToChart,
  closeTradingViewSession,
  ensurePineEditor,
  gotoChart,
  newTradingViewSession,
  readChartStateSnapshot,
  removeVisibleChartScriptInstances,
  saveChangedChartLayout,
  setChartInterval,
  setEditorContent,
} from "../automation/tradingview/lib/tv_shared.js";
import {
  chartIntervalFromDisplayLabel,
  compareChartState,
  perturbationInterval,
  type ChartStateSnapshot,
} from "../automation/tradingview/lib/tv_validation_model.js";

const SOURCE = path.resolve("SMC_HTF_Confluence.pine");
const SCRIPT = "SMC HTF Confluence";
const MANIFEST = path.resolve("artifacts/governance/smc_r5_htf_session_rebuild_manifest.json");

function parseArgs(argv: string[]): { out: string; dryRun: boolean } {
  let out = "";
  let dryRun = false;
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--out") out = argv[i + 1] ?? "";
    if (argv[i] === "--dry-run") dryRun = true;
  }
  if (!out) throw new Error("--out <path> is required");
  return { out, dryRun };
}

async function main(): Promise<number> {
  const cli = parseArgs(process.argv.slice(2));

  // sourceHashVerified: the source about to be reinstalled is the one the
  // manifest pins. Checked BEFORE touching the chart — a hash mismatch means
  // the drill would restore something other than what was certified.
  const sourceText = fs.readFileSync(SOURCE, "utf-8");
  const sourceHash = crypto.createHash("sha256").update(sourceText).digest("hex");
  const pinnedHash = JSON.parse(fs.readFileSync(MANIFEST, "utf-8")).sources.htfConfluence.sha256 as string;
  const sourceHashVerified = sourceHash === pinnedHash;

  const report: Record<string, unknown> = {
    schemaVersion: 1,
    requirementId: "R5-REBUILD",
    caseId: "R5-REBUILD-ROLLBACK",
    evidenceType: "layout_restore_drill",
    chartUrl: process.env.TV_CHART_URL ?? "",
    startedAtUtc: `${new Date().toISOString().slice(0, 19)}Z`,
    baselineOrigin:
      "Captured from the repaired chart at drill time. The runbook's step-1 record was never taken, "
      + "and the state that preceded validation was the defective pre-CE10156-fix layout, so there is "
      + "no earlier state that would be correct to restore.",
    sourceHash,
    pinnedHash,
    sourceHashVerified,
  };

  if (!sourceHashVerified) {
    report.status = "fail";
    report.reason = "the local source does not match the hash the manifest pins; refusing to install it";
    fs.writeFileSync(cli.out, `${JSON.stringify(report, null, 2)}\n`);
    console.log(`[abort] ${report.reason}`);
    return 1;
  }

  const session = await newTradingViewSession();
  let page = session.page;

  try {
    await gotoChart(page);
    await page.waitForTimeout(9_000);

    // ---- capture -----------------------------------------------------------
    const captured = await readChartStateSnapshot(page);
    report.captured = captured;
    console.log(`[capture] ${JSON.stringify(captured)}`);
    if (captured.studies.length === 0 || captured.interval === null) {
      throw new Error("the chart state could not be read; refusing to run a drill whose baseline is blank");
    }
    // The control shows "1h", setChartInterval wants "60".
    const capturedInterval = chartIntervalFromDisplayLabel(captured.interval);
    if (capturedInterval === null) {
      throw new Error(`cannot map the captured interval "${captured.interval}" back to a chart interval`);
    }

    // ---- perturb -----------------------------------------------------------
    // Both axes the case cares about: the chart settings AND an attached study.
    const target = perturbationInterval(captured.interval);
    await setChartInterval(page, target);
    await page.waitForTimeout(4_000);
    const removed = await removeVisibleChartScriptInstances(page, SCRIPT).catch(() => 0);
    await page.waitForTimeout(4_000);

    const perturbed = await readChartStateSnapshot(page);
    const perturbation = compareChartState(captured, perturbed);
    report.perturbed = perturbed;
    report.perturbationTook = !perturbation.restored;
    report.perturbationDifferences = perturbation.differences;
    console.log(`[perturb] interval->${target} removedInstances=${removed} changed=${!perturbation.restored}`);
    if (perturbation.restored) {
      // Nothing actually moved, so a later "restored" verdict would be vacuous.
      throw new Error("the perturbation did not change the chart; the drill would prove nothing");
    }

    // ---- restore -----------------------------------------------------------
    await ensurePineEditor(page);
    await page.waitForTimeout(2_000);
    await setEditorContent(page, sourceText);
    await page.waitForTimeout(3_000);
    await addCurrentScriptToChart(page, SCRIPT, { forceInsert: true, stepTimeoutMs: 90_000 })
      .catch((error) => console.log("add:", String(error).slice(0, 150)));
    await page.waitForTimeout(12_000);
    await setChartInterval(page, capturedInterval);
    await page.waitForTimeout(6_000);

    const restoredInSession = await readChartStateSnapshot(page);
    const inSession = compareChartState(captured, restoredInSession);
    report.restoredInSession = restoredInSession;
    report.inSessionComparison = inSession;
    console.log(`[restore] matches=${inSession.restored} ${inSession.differences.join("; ")}`);

    // ---- save --------------------------------------------------------------
    // Only ever persist a chart that already matches the capture.
    let layoutSaved = false;
    if (inSession.restored && !cli.dryRun) {
      await saveChangedChartLayout(page);
      layoutSaved = true;
      console.log("[save] layout saved");
    } else if (cli.dryRun) {
      console.log("[save] skipped (--dry-run)");
    } else {
      console.log("[save] REFUSED: the in-session state does not match the capture");
    }
    report.layoutSaved = layoutSaved;

    // ---- reload and verify -------------------------------------------------
    let afterReload: ChartStateSnapshot | null = null;
    let reloadComparison: ReturnType<typeof compareChartState> | null = null;
    if (layoutSaved) {
      await page.reload({ waitUntil: "domcontentloaded" }).catch(() => undefined);
      await page.waitForTimeout(14_000);
      afterReload = await readChartStateSnapshot(page);
      reloadComparison = compareChartState(captured, afterReload);
      console.log(`[reload] matches=${reloadComparison.restored} ${reloadComparison.differences.join("; ")}`);
    }
    report.afterReload = afterReload;
    report.reloadComparison = reloadComparison;

    const priorChartStateRestored = inSession.restored && reloadComparison?.restored === true;
    report.observedDiagnostics = {
      sourceHashVerified: sourceHashVerified ? "1" : "0",
      priorChartStateRestored: priorChartStateRestored ? "1" : "0",
      layoutSaved: layoutSaved ? "1" : "0",
    };
    report.status = sourceHashVerified && priorChartStateRestored && layoutSaved ? "pass" : "fail";
    report.finishedAtUtc = `${new Date().toISOString().slice(0, 19)}Z`;

    fs.writeFileSync(cli.out, `${JSON.stringify(report, null, 2)}\n`);
    console.log(`[verdict] ${report.status} ${JSON.stringify(report.observedDiagnostics)}`);
    return report.status === "pass" ? 0 : 1;
  } catch (error) {
    report.status = "fail";
    report.error = String(error).slice(0, 400);
    fs.writeFileSync(cli.out, `${JSON.stringify(report, null, 2)}\n`);
    console.error(error);
    return 1;
  } finally {
    void page;
    await closeTradingViewSession(session);
  }
}

main().then((rc) => process.exit(rc));

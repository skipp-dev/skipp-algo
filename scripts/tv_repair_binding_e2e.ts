#!/usr/bin/env -S node --enable-source-maps
//
// Controlled repair E2E.
//
// Until 2026-08-01 this drill drifted a binding, repaired it, and re-verified —
// all inside ONE session, without ever reloading the chart or saving the
// layout. That made it structurally unable to observe the very failure the
// rollout's layout save exists to prevent: a repair that reads back as bound
// in-session and is discarded the moment the layout is left. It passed on every
// day the primary operator layout was never saved (see the 2026-07-25 incident
// and the per-layout save in tv_batch_consumer_rollout.ts).
//
// The drill therefore persists its deliberate drift and re-reads across a hard
// reload on BOTH sides:
//
//   drift -> save -> reload -> the drift must still be there   (a real precondition)
//   repair -> save -> reload -> it must be gone                (the assertion that matters)
//
// Cost of that, stated plainly: between the first save and the second, the
// operator's chart genuinely carries the drifted binding, where the old
// in-session drill was rolled back for free by any reload. The run is
// opt-in (workflow_dispatch, repair_e2e=true, off-hours window) and the finally
// block below repairs, saves and RE-READS before giving up; if it cannot, it
// says so with the chart and label named rather than exiting quietly.

import fs from "node:fs";

import type { Page } from "playwright";

import {
  closeTradingViewSession,
  gotoChart,
  isScriptVisibleOnChartSurface,
  newTradingViewSession,
  saveChangedChartLayout,
} from "../automation/tradingview/lib/tv_shared.js";
import {
  parseInputSourceLabels,
  setConsumerBindingForTest,
  verifyConsumerBindings,
  type VerifyConsumerTarget,
} from "./tv_verify_consumer_bindings.js";

type Config = { producerName: string; primaryChartUrl: string; repairE2ETarget: VerifyConsumerTarget };

const SETTLE_TIMEOUT_MS = Number(process.env.TV_DRILL_SETTLE_TIMEOUT_MS ?? 30_000);

/**
 * gotoChart resolves on `domcontentloaded` plus a FIXED 3s wait, which is
 * sometimes before TradingView has rebuilt the legend. Every read afterwards
 * then dies on `Existing chart instance not found` against a chart that is
 * perfectly healthy: CI run 30684930443 failed that way 8s in, and the
 * identical retry (30685141166) was green. Re-rolling the dice costs a whole
 * browser run, so wait for the condition instead of paying for another one.
 *
 * The wait is deliberately the SAME predicate that throws inside
 * verifyConsumerBindings, not a stricter proxy for it: waiting on a different
 * signal would only move the guess. If it never becomes true the error says
 * how long it waited, so a genuinely missing indicator still reads as missing
 * rather than as a slow one.
 */
async function gotoChartAndAwaitInstance(page: Page, chartUrl: string, scriptName: string): Promise<void> {
  await gotoChart(page, chartUrl);
  const deadline = Date.now() + SETTLE_TIMEOUT_MS;
  for (;;) {
    if (await isScriptVisibleOnChartSurface(page, scriptName).catch(() => false)) return;
    if (Date.now() >= deadline) {
      throw new Error(
        `Chart did not surface ${scriptName} within ${SETTLE_TIMEOUT_MS}ms of loading ${chartUrl}`,
      );
    }
    await page.waitForTimeout(500);
  }
}

async function main(): Promise<void> {
  const config = JSON.parse(fs.readFileSync("automation/tradingview/config/consumer-rollout.json", "utf-8")) as Config;
  const target = { ...config.repairE2ETarget, producerName: config.producerName };
  if (!target.source) throw new Error("Repair E2E target is missing its Pine source path");
  const labels = parseInputSourceLabels(fs.readFileSync(target.source, "utf-8"));
  const testLabel = labels[0];
  if (!testLabel) throw new Error(`Repair E2E target has no BUS bindings: ${target.source}`);
  const chartUrl = target.chartUrl ?? config.primaryChartUrl;
  const session = await newTradingViewSession();
  let deliberatelyDrifted = false;
  try {
    if (!session.authResolution.authReusedOk) throw new Error("Repair E2E requires authenticated TradingView state");
    await gotoChartAndAwaitInstance(session.page, chartUrl, target.scriptName);
    const baseline = await verifyConsumerBindings(session, target, false);
    if (!baseline.ok) throw new Error("Repair E2E precondition failed: target was already drifted");

    await setConsumerBindingForTest(session, target, testLabel, "Close");
    deliberatelyDrifted = true;
    const inSession = await verifyConsumerBindings(session, target, false);
    if (inSession.mismatches.length !== 1 || inSession.mismatches[0]?.label !== testLabel) {
      throw new Error("Repair E2E failed to observe exactly the deliberately drifted binding");
    }

    // Persist the drift, then discard the session state by reloading. Without
    // this the drill measures an in-memory round trip: the drift would revert
    // on its own and the repair below would have nothing to prove.
    await saveChangedChartLayout(session.page);
    await gotoChartAndAwaitInstance(session.page, chartUrl, target.scriptName);
    const before = await verifyConsumerBindings(session, target, false);
    if (before.mismatches.length !== 1 || before.mismatches[0]?.label !== testLabel) {
      throw new Error("Repair E2E drift did not survive the reload, so the repair below would prove nothing");
    }

    const repaired = await verifyConsumerBindings(session, target, true);
    if (!repaired.ok || repaired.repaired.length === 0) throw new Error("Repair E2E did not repair and reverify bindings");

    // The load-bearing half. `repaired` above is an in-session read and was
    // green throughout the 2026-07-25 incident; only what survives this save
    // and reload is what the operator's chart actually holds.
    await saveChangedChartLayout(session.page);
    await gotoChartAndAwaitInstance(session.page, chartUrl, target.scriptName);
    const after = await verifyConsumerBindings(session, target, false);
    if (!after.ok) {
      throw new Error(
        `Repair E2E repaired in-session but the repair did not survive the reload: ${after.mismatches
          .map((mismatch) => `${mismatch.label}=${mismatch.actual}`)
          .join(", ")}`,
      );
    }
    deliberatelyDrifted = false;
    console.log(JSON.stringify({ ok: true, target: target.scriptName, chartUrl, deliberatelyDrifted: testLabel, driftSurvivedReload: true, mismatchesBefore: before.mismatches.length, repaired: repaired.repaired.length, checkedAfter: after.checked }));
  } finally {
    if (deliberatelyDrifted) {
      // Repair, persist, and PROVE it — a best-effort repair that is not saved
      // and not re-read would leave the chart drifted while looking handled.
      const recovered = await verifyConsumerBindings(session, target, true)
        .then(async (result) => {
          await saveChangedChartLayout(session.page);
          await gotoChartAndAwaitInstance(session.page, chartUrl, target.scriptName);
          return (await verifyConsumerBindings(session, target, false)).ok && result.ok;
        })
        .catch(() => false);
      console.error(
        recovered
          ? "deliberate drift repaired, persisted and re-read after the failure"
          : `MANUAL REPAIR REQUIRED: ${target.scriptName} input "${testLabel}" may still be bound to Close on ${chartUrl}`,
      );
    }
    await closeTradingViewSession(session);
  }
}

main().catch((error) => {
  console.error(JSON.stringify({ ok: false, error: String(error?.message ?? error) }));
  process.exit(1);
});

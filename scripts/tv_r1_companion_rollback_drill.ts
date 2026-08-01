#!/usr/bin/env -S node --enable-source-maps
//
// R1 companion rollback drill.
//
// The R1 evidence of 2026-07-29 recorded a rollback under `rollback`: both
// companions removed from the managed layout, the Suite left untouched, then
// both restored from their saved scripts with all ten BUS bindings back. That
// was performed by hand in an attended session. Nothing in the repository could
// repeat it, so when the 2026-08-01 re-attestation asked the same question it
// had to answer "not_run" and carry the gate open (#4290).
//
// This is that drill as code. It follows the shape #4289 gave the repair drill,
// for the same reason: an in-session read was green all through the 2026-07-25
// incident. Removing an indicator and reading the legend back without leaving
// the layout proves only that the UI accepted a click. Both halves therefore
// cross a hard reload (gotoChart is a page.goto):
//
//   remove  -> save -> reload -> the companions must STILL be gone,
//                                and the Suite must still be there
//   restore -> rebind -> save -> reload -> both back, ten bindings, no
//                                          unknown-parent runtime errors
//
// The first half is not ceremony. Without persisting the removal, the reload
// would put the companions back on its own and the restore below would have
// nothing real to do — the drill would be measuring an in-memory round trip.
//
// Cost, stated rather than hidden: between the two saves the managed layout
// genuinely carries no companions, so no Exit Signal and no Event Overlay is
// evaluating. That is the drill, not a side effect of it. The run is opt-in
// (workflow_dispatch, r1_rollback_drill=true, blocked when verify_only=true),
// and the finally block below restores, SAVES and RE-READS before giving up; if
// it cannot, it names the chart and the scripts instead of exiting quietly.

import fs from "node:fs";

import {
  addExistingScriptToChartViaIndicators,
  closeTradingViewSession,
  countChartScriptInstances,
  gotoChartAndAwaitScript,
  isScriptVisibleOnChartSurface,
  newTradingViewSession,
  removeVisibleChartScriptInstances,
  saveChangedChartLayout,
} from "../automation/tradingview/lib/tv_shared.js";
import {
  verifyConsumerBindings,
  type VerifyConsumerResult,
  type VerifyConsumerTarget,
} from "./tv_verify_consumer_bindings.js";

type Config = {
  producerName: string;
  primaryChartUrl: string;
  verifyTargets: VerifyConsumerTarget[];
};

const COMPANIONS = ["SMC Event Overlay", "SMC Exit Signal"] as const;

/** Bindings that read back as bound to the producer, across all companions. */
function countRestoredBindings(results: VerifyConsumerResult[]): number {
  return results.reduce(
    (total, result) => total + result.bindings.filter((binding) => binding.ok).length,
    0,
  );
}

async function verifyAll(
  session: Awaited<ReturnType<typeof newTradingViewSession>>,
  targets: VerifyConsumerTarget[],
  repair: boolean,
): Promise<VerifyConsumerResult[]> {
  const results: VerifyConsumerResult[] = [];
  for (const target of targets) {
    results.push(await verifyConsumerBindings(session, target, repair, repair));
  }
  return results;
}

async function restoreCompanions(
  session: Awaited<ReturnType<typeof newTradingViewSession>>,
  targets: VerifyConsumerTarget[],
): Promise<string[]> {
  const restored: string[] = [];
  for (const name of COMPANIONS) {
    const result = await addExistingScriptToChartViaIndicators(session.page, name);
    if (result.added) restored.push(name);
  }
  // force-rebind: a freshly inserted instance comes back with DEFAULT inputs,
  // so every BUS parent has to be re-selected. This is the step the manual
  // 2026-07-29 drill recorded as "bindingsRestored: 10".
  await verifyAll(session, targets, true);
  return restored;
}

async function main(): Promise<void> {
  const config = JSON.parse(
    fs.readFileSync("automation/tradingview/config/consumer-rollout.json", "utf-8"),
  ) as Config;

  const targets = config.verifyTargets
    .filter((target) => (COMPANIONS as readonly string[]).includes(target.scriptName))
    .map((target) => ({ ...target, producerName: config.producerName }));
  if (targets.length !== COMPANIONS.length) {
    throw new Error(`R1 rollback drill needs both companions in the rollout config, found ${targets.length}`);
  }
  const chartUrls = new Set(targets.map((target) => target.chartUrl ?? config.primaryChartUrl));
  if (chartUrls.size !== 1) {
    throw new Error(`R1 companions must share one managed layout, found ${[...chartUrls].join(", ")}`);
  }
  const chartUrl = [...chartUrls][0] as string;

  const session = await newTradingViewSession();
  let companionsRemoved = false;
  try {
    if (!session.authResolution.authReusedOk) {
      throw new Error("R1 rollback drill requires authenticated TradingView state");
    }
    await gotoChartAndAwaitScript(session.page, chartUrl, config.producerName);

    const baseline = await verifyAll(session, targets, false);
    const baselineBindings = countRestoredBindings(baseline);
    if (baseline.some((result) => !result.ok)) {
      throw new Error("R1 rollback drill precondition failed: companions were already drifted");
    }

    // ── remove ────────────────────────────────────────────────────────────
    for (const name of COMPANIONS) {
      await removeVisibleChartScriptInstances(session.page, name);
    }
    companionsRemoved = true;
    await saveChangedChartLayout(session.page);
    // Wait for the PRODUCER, which is never removed. This half asserts that
    // two scripts are absent, and on a chart whose legend has not been rebuilt
    // yet absence is indistinguishable from "not drawn": the assertion would
    // pass on a chart that still carries both companions. Settling on
    // something expected to be PRESENT is what makes the absence readable.
    await gotoChartAndAwaitScript(session.page, chartUrl, config.producerName);

    const stillPresent: string[] = [];
    for (const name of COMPANIONS) {
      if (await isScriptVisibleOnChartSurface(session.page, name)) stillPresent.push(name);
    }
    if (stillPresent.length > 0) {
      throw new Error(
        `R1 rollback drill removal did not survive the reload, so the restore below would prove nothing: ${stillPresent.join(", ")}`,
      );
    }
    // The whole point of a rollback is that it leaves the rest alone.
    const suiteInstances = await countChartScriptInstances(session.page, config.producerName);
    if (suiteInstances !== 1) {
      throw new Error(
        `R1 rollback drill removed more than the companions: ${config.producerName} instances = ${suiteInstances}`,
      );
    }

    // ── restore ───────────────────────────────────────────────────────────
    const restored = await restoreCompanions(session, targets);
    if (restored.length !== COMPANIONS.length) {
      throw new Error(
        `R1 rollback drill could not restore both companions from their saved scripts: restored ${restored.join(", ") || "none"}`,
      );
    }

    // The load-bearing half. The reads inside restoreCompanions are in-session
    // and were green throughout the 2026-07-25 incident; only what survives
    // this save and reload is what the managed layout actually holds.
    await saveChangedChartLayout(session.page);
    await gotoChartAndAwaitScript(session.page, chartUrl, COMPANIONS[0]);

    const after = await verifyAll(session, targets, false);
    const missing: string[] = [];
    for (const name of COMPANIONS) {
      if (!(await isScriptVisibleOnChartSurface(session.page, name))) missing.push(name);
    }
    if (missing.length > 0) {
      throw new Error(`R1 rollback drill restored in-session but the layout came back without: ${missing.join(", ")}`);
    }
    const mismatches = after.flatMap((result) => result.mismatches.map((m) => `${m.label}=${m.actual}`));
    if (mismatches.length > 0) {
      throw new Error(`R1 rollback drill rebound in-session but the bindings did not survive the reload: ${mismatches.join(", ")}`);
    }
    if (after.some((result) => result.unknownParentRuntimeError)) {
      throw new Error("R1 rollback drill read back clean but TradingView reported an unknown parent after the reload");
    }
    const restoredBindings = countRestoredBindings(after);
    if (restoredBindings !== baselineBindings) {
      throw new Error(
        `R1 rollback drill restored ${restoredBindings} bindings, baseline had ${baselineBindings}`,
      );
    }

    companionsRemoved = false;
    console.log(JSON.stringify({
      ok: true,
      chartUrl,
      producerName: config.producerName,
      companionsRemoved: [...COMPANIONS],
      removalSurvivedReload: true,
      suiteRemainedPresent: true,
      suiteOnlyInventoryAfterReload: [config.producerName],
      companionsRestoredFromSavedScripts: true,
      bindingsRestored: restoredBindings,
      finalReloadStatus: "passed",
      finalInventoryRestored: true,
    }));
  } finally {
    if (companionsRemoved) {
      // Restore, persist, and PROVE it — a best-effort restore that is not
      // saved and not re-read would leave the managed layout without its
      // companions while looking handled.
      const recovered = await restoreCompanions(session, targets)
        .then(async (restored) => {
          await saveChangedChartLayout(session.page);
          await gotoChartAndAwaitScript(session.page, chartUrl, COMPANIONS[0]);
          const reread = await verifyAll(session, targets, false);
          return restored.length === COMPANIONS.length && reread.every((result) => result.ok);
        })
        .catch(() => false);
      console.error(
        recovered
          ? "companions restored, persisted and re-read after the failure"
          : `MANUAL REPAIR REQUIRED: ${COMPANIONS.join(" and ")} may still be missing from ${chartUrl}`,
      );
    }
    await closeTradingViewSession(session);
  }
}

main().catch((error) => {
  console.error(JSON.stringify({ ok: false, error: String(error?.message ?? error) }));
  process.exit(1);
});

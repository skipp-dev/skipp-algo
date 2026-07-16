#!/usr/bin/env -S node --enable-source-maps

import fs from "node:fs";

import {
  closeTradingViewSession,
  gotoChart,
  newTradingViewSession,
} from "../automation/tradingview/lib/tv_shared.js";
import {
  parseInputSourceLabels,
  setConsumerBindingForTest,
  verifyConsumerBindings,
  type VerifyConsumerTarget,
} from "./tv_verify_consumer_bindings.js";

type Config = { producerName: string; primaryChartUrl: string; repairE2ETarget: VerifyConsumerTarget };

async function main(): Promise<void> {
  const config = JSON.parse(fs.readFileSync("automation/tradingview/config/consumer-rollout.json", "utf-8")) as Config;
  const target = { ...config.repairE2ETarget, producerName: config.producerName };
  const labels = parseInputSourceLabels(fs.readFileSync(target.source, "utf-8"));
  const testLabel = labels[0];
  if (!testLabel) throw new Error(`Repair E2E target has no BUS bindings: ${target.source}`);
  const session = await newTradingViewSession();
  let deliberatelyDrifted = false;
  try {
    if (!session.authResolution.authReusedOk) throw new Error("Repair E2E requires authenticated TradingView state");
    await gotoChart(session.page, config.primaryChartUrl);
    const baseline = await verifyConsumerBindings(session, target, false);
    if (!baseline.ok) throw new Error("Repair E2E precondition failed: target was already drifted");
    await setConsumerBindingForTest(session, target, testLabel, "Close");
    deliberatelyDrifted = true;
    const before = await verifyConsumerBindings(session, target, false);
    if (before.mismatches.length !== 1 || before.mismatches[0]?.label !== testLabel) {
      throw new Error("Repair E2E failed to observe exactly the deliberately drifted binding");
    }
    const repaired = await verifyConsumerBindings(session, target, true);
    if (!repaired.ok || repaired.repaired.length === 0) throw new Error("Repair E2E did not repair and reverify bindings");
    deliberatelyDrifted = false;
    const after = await verifyConsumerBindings(session, target, false);
    if (!after.ok) throw new Error("Repair E2E final read-only verification failed");
    console.log(JSON.stringify({ ok: true, target: target.scriptName, deliberatelyDrifted: testLabel, mismatchesBefore: before.mismatches.length, repaired: repaired.repaired.length, checkedAfter: after.checked }));
  } finally {
    if (deliberatelyDrifted) await verifyConsumerBindings(session, target, true).catch(() => undefined);
    await closeTradingViewSession(session);
  }
}

main().catch((error) => {
  console.error(JSON.stringify({ ok: false, error: String(error?.message ?? error) }));
  process.exit(1);
});

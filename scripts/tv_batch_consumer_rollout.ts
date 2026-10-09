#!/usr/bin/env -S node --enable-source-maps

import fs from "node:fs";
import path from "node:path";

import {
  closeTradingViewSession,
  ensurePineEditor,
  gotoChart,
  newTradingViewSession,
} from "../automation/tradingview/lib/tv_shared.js";
import { saveConsumerSource, type SaveConsumerResult, type SaveConsumerTarget } from "./tv_save_consumer_source.js";
import {
  verifyConsumerBindings,
  type VerifyConsumerResult,
  type VerifyConsumerTarget,
} from "./tv_verify_consumer_bindings.js";

type RolloutConfig = {
  producerName: string;
  primaryChartUrl: string;
  saveTargets: SaveConsumerTarget[];
  verifyTargets: VerifyConsumerTarget[];
};

type FailedTarget = { target: string; error: string };
type RolloutReport = {
  generatedAt: string;
  generated_at_unix: number;
  durationSeconds: number;
  ok: boolean;
  save: { expected: number; succeeded: SaveConsumerResult[]; failed: FailedTarget[] };
  bindings: {
    expectedConsumers: number;
    checkedConsumers: number;
    checkedBindings: number;
    mismatches: number;
    consumers: VerifyConsumerResult[];
    failed: FailedTarget[];
  };
};

function getFlag(name: string, fallback: string): string {
  const args = process.argv.slice(2);
  const index = args.indexOf(name);
  return index === -1 || !args[index + 1] ? fallback : args[index + 1];
}

async function main(): Promise<void> {
  const started = Date.now();
  const configPath = path.resolve(getFlag("--config", "automation/tradingview/config/consumer-rollout.json"));
  const outPath = path.resolve(getFlag("--out", "artifacts/monitoring/tradingview_consumer_bindings.json"));
  const config = JSON.parse(fs.readFileSync(configPath, "utf-8")) as RolloutConfig;
  const override = process.env.TV_CONSUMER_MAPPING_JSON?.trim();
  if (override) config.saveTargets = JSON.parse(override) as SaveConsumerTarget[];
  config.verifyTargets = config.verifyTargets.map((target) => ({ ...target, producerName: config.producerName }));

  const report: RolloutReport = {
    generatedAt: new Date().toISOString(),
    generated_at_unix: Math.floor(Date.now() / 1000),
    durationSeconds: 0,
    ok: false,
    save: { expected: config.saveTargets.length, succeeded: [], failed: [] },
    bindings: {
      expectedConsumers: config.verifyTargets.length,
      checkedConsumers: 0,
      checkedBindings: 0,
      mismatches: 0,
      consumers: [],
      failed: [],
    },
  };

  const session = await newTradingViewSession();
  try {
    if (!session.authResolution.authReusedOk) throw new Error("Rollout requires authenticated TradingView state");
    await gotoChart(session.page, config.primaryChartUrl);
    await ensurePineEditor(session.page);

    for (const target of config.saveTargets) {
      let lastError = "unknown save failure";
      for (let attempt = 1; attempt <= 2; attempt += 1) {
        try {
          report.save.succeeded.push(await saveConsumerSource(session, target));
          lastError = "";
          break;
        } catch (error) {
          lastError = String((error as Error)?.message ?? error);
          if (attempt < 2) {
            await gotoChart(session.page, config.primaryChartUrl).catch(() => undefined);
            await ensurePineEditor(session.page).catch(() => undefined);
          }
        }
      }
      if (lastError) report.save.failed.push({ target: target.scriptName, error: lastError });
    }

    if (report.save.failed.length === 0) {
      // Opt-in only: TV_FORCE_REBIND re-selects every BUS source, so a stale parent study id
      // behind a correct-looking dropdown label is re-pointed. Default stays read-only.
      const forceRebind = process.env.TV_FORCE_REBIND === "true";
      for (const target of config.verifyTargets) {
        const targetChartUrl = target.chartUrl ?? config.primaryChartUrl;
        if (!session.page.url().startsWith(targetChartUrl)) {
          await gotoChart(session.page, targetChartUrl);
        }
        let result: VerifyConsumerResult | null = null;
        let lastError = "unknown verification failure";
        for (let attempt = 1; attempt <= 2; attempt += 1) {
          try {
            result = await verifyConsumerBindings(session, target, forceRebind, forceRebind);
            lastError = "";
            break;
          } catch (error) {
            lastError = String((error as Error)?.message ?? error);
            if (attempt < 2) await gotoChart(session.page, targetChartUrl).catch(() => undefined);
          }
        }
        if (result) report.bindings.consumers.push(result);
        else report.bindings.failed.push({ target: target.scriptName, error: lastError });
      }
    }
  } finally {
    await closeTradingViewSession(session);
    report.bindings.checkedConsumers = report.bindings.consumers.length;
    report.bindings.checkedBindings = report.bindings.consumers.reduce((sum, item) => sum + item.checked, 0);
    report.bindings.mismatches = report.bindings.consumers.reduce((sum, item) => sum + item.mismatches.length, 0);
    report.durationSeconds = Math.round((Date.now() - started) / 100) / 10;
    report.ok = report.save.failed.length === 0
      && report.bindings.failed.length === 0
      && report.bindings.checkedConsumers === report.bindings.expectedConsumers
      && report.bindings.mismatches === 0;
    fs.mkdirSync(path.dirname(outPath), { recursive: true });
    fs.writeFileSync(outPath, `${JSON.stringify(report, null, 2)}\n`, "utf-8");
    console.log(JSON.stringify(report));
  }

  if (!report.ok) process.exitCode = 1;
}

main().catch((error) => {
  console.error(JSON.stringify({ ok: false, error: String(error?.message ?? error) }));
  process.exit(1);
});

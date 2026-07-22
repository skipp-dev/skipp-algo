#!/usr/bin/env -S node --enable-source-maps

import fs from "node:fs";
import path from "node:path";

import {
  closeTradingViewSession,
  ensurePineEditor,
  gotoChart,
  newTradingViewSession,
  refreshChartScriptInstance,
  resolveProducerRefreshChartUrls,
} from "../automation/tradingview/lib/tv_shared.js";
import {
  saveConsumerSource,
  verifyConsumerSource,
  type SaveConsumerResult,
  type SaveConsumerTarget,
  type VerifyConsumerSourceResult,
} from "./tv_save_consumer_source.js";
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
  producerRefresh: { requested: boolean; ok: boolean; removedInstances: number; error: string };
  sources: {
    expected: number;
    checked: number;
    drifted: number;
    consumers: VerifyConsumerSourceResult[];
    failed: FailedTarget[];
  };
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
  const sourceVerificationTargets = config.saveTargets.map((target) => ({ ...target }));
  const override = process.env.TV_CONSUMER_MAPPING_JSON?.trim();
  if (override) config.saveTargets = JSON.parse(override) as SaveConsumerTarget[];
  config.verifyTargets = config.verifyTargets.map((target) => ({ ...target, producerName: config.producerName }));
  const forceRebind = process.env.TV_FORCE_REBIND === "true";
  const refreshProducer = process.env.TV_REFRESH_PRODUCER === "true";

  const report: RolloutReport = {
    generatedAt: new Date().toISOString(),
    generated_at_unix: Math.floor(Date.now() / 1000),
    durationSeconds: 0,
    ok: false,
    save: { expected: config.saveTargets.length, succeeded: [], failed: [] },
    producerRefresh: { requested: refreshProducer, ok: !refreshProducer, removedInstances: 0, error: "" },
    sources: {
      expected: sourceVerificationTargets.length,
      checked: 0,
      drifted: 0,
      consumers: [],
      failed: [],
    },
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
    if (refreshProducer && !forceRebind) {
      throw new Error("TV_REFRESH_PRODUCER=true requires TV_FORCE_REBIND=true so child BUS sources follow the new parent instance");
    }
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

    if (report.save.failed.length === 0 && refreshProducer) {
      // The applied producer instance lives in EVERY layout that carries
      // consumers (desktop primary + e.g. the Mobile layout the operator
      // actually watches). Refreshing only primaryChartUrl left the visible
      // instance frozen (live run 29929470730, 2026-07-22).
      try {
        for (const producerChartUrl of resolveProducerRefreshChartUrls(config)) {
          if (!session.page.url().startsWith(producerChartUrl)) {
            await gotoChart(session.page, producerChartUrl);
            await ensurePineEditor(session.page);
          }
          report.producerRefresh.removedInstances += await refreshChartScriptInstance(session.page, config.producerName);
        }
        report.producerRefresh.ok = true;
      } catch (error) {
        report.producerRefresh.error = `${session.page.url()}: ${String((error as Error)?.message ?? error)}`;
      }
    }

    if (report.save.failed.length === 0 && report.producerRefresh.ok) {
      for (const target of sourceVerificationTargets) {
        let result: VerifyConsumerSourceResult | null = null;
        let lastError = "unknown source verification failure";
        for (let attempt = 1; attempt <= 2; attempt += 1) {
          try {
            result = await verifyConsumerSource(session, target);
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
        if (result) report.sources.consumers.push(result);
        else report.sources.failed.push({ target: target.scriptName, error: lastError });
      }

      // Opt-in only: TV_FORCE_REBIND re-selects every BUS source, so a stale parent study id
      // behind a correct-looking dropdown label is re-pointed. Default stays read-only.
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
    report.sources.checked = report.sources.consumers.length;
    report.sources.drifted = report.sources.consumers.filter((item) => !item.matches).length;
    report.bindings.checkedConsumers = report.bindings.consumers.length;
    report.bindings.checkedBindings = report.bindings.consumers.reduce((sum, item) => sum + item.checked, 0);
    report.bindings.mismatches = report.bindings.consumers.reduce((sum, item) => sum + item.mismatches.length, 0);
    report.durationSeconds = Math.round((Date.now() - started) / 100) / 10;
    report.ok = report.save.failed.length === 0
      && report.producerRefresh.ok
      && report.sources.failed.length === 0
      && report.sources.checked === report.sources.expected
      && report.sources.drifted === 0
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

#!/usr/bin/env -S node --enable-source-maps

import fs from "node:fs";
import path from "node:path";

import {
  buildRolloutProvenance,
  resolveExecutionPlan,
  type RolloutExecutionMode,
  type RolloutProvenance,
} from "../automation/tradingview/lib/tv_consumer_rollout_evidence.js";
import {
  closeTradingViewSession,
  ensurePineEditor,
  gotoChart,
  isTrackedStepTimeoutError,
  newTradingViewSession,
  refreshChartScriptInstance,
  resolveProducerRefreshChartUrls,
  saveChangedChartLayout,
} from "../automation/tradingview/lib/tv_shared.js";
import {
  saveConsumerSource,
  verifyConsumerSource,
  type SaveConsumerResult,
  type SaveConsumerTarget,
  type VerifyConsumerSourceResult,
} from "./tv_save_consumer_source.js";
import {
  parseInputSourceLabels,
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
  schemaVersion: 2;
  executionMode: RolloutExecutionMode;
  observedAt: string;
  generatedAt: string;
  generated_at_unix: number;
  durationSeconds: number;
  ok: boolean;
  repoCommitSha: string;
  rolloutConfigSha256: string;
  productManifestVersion: number;
  libraryReleaseVersion: number;
  inputsMatchCommit: boolean;
  repositoryExpected: RolloutProvenance["repositoryExpected"];
  tradingViewObserved: {
    sources: Array<{
      scriptName: string;
      actualSha256: string;
      actualBytes: number;
      matchesRepository: boolean;
    }>;
    bindings: Array<{
      scriptName: string;
      selections: Array<{ label: string; actual: string | null; expected: string; matches: boolean }>;
      runtimeErrors: Array<{ at: string; studyId: string | null; message: string }>;
    }>;
  };
  mutations: {
    sourceSaveRequested: boolean;
    sourceSavesCompleted: number;
    producerRefreshRequested: boolean;
    producerInstancesRemoved: number;
    bindingRepairRequested: boolean;
    bindingsRepaired: number;
    layoutSaveRequested: boolean;
    layoutSaved: boolean;
  };
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
  const executionPlan = resolveExecutionPlan(process.argv.slice(2), process.env);
  const repoRoot = process.cwd();
  const configPath = path.resolve(getFlag("--config", "automation/tradingview/config/consumer-rollout.json"));
  const outPath = path.resolve(getFlag("--out", "artifacts/monitoring/tradingview_consumer_bindings.json"));
  const productManifestPath = path.resolve(
    getFlag("--product-manifest", "artifacts/tradingview/smc_product_cut_manifest.json"),
  );
  const libraryReleaseManifestPath = path.resolve(
    getFlag("--release-manifest", "artifacts/tradingview/library_release_manifest.json"),
  );
  const config = JSON.parse(fs.readFileSync(configPath, "utf-8")) as RolloutConfig;
  const sourceVerificationTargets = config.saveTargets.map((target) => ({ ...target }));
  const override = process.env.TV_CONSUMER_MAPPING_JSON?.trim();
  if (executionPlan.saveSources && override) {
    config.saveTargets = JSON.parse(override) as SaveConsumerTarget[];
  } else if (!executionPlan.saveSources) {
    config.saveTargets = [];
  }
  config.verifyTargets = config.verifyTargets.map((target) => ({ ...target, producerName: config.producerName }));
  const bindingEvidenceTargets = config.verifyTargets.map((target) => {
    if (!target.source) throw new Error(`Binding evidence target has no source: ${target.scriptName}`);
    return {
      source: target.source,
      scriptName: target.scriptName,
      labels: target.bindingLabels ?? parseInputSourceLabels(fs.readFileSync(path.resolve(target.source), "utf-8")),
    };
  });
  const provenance = buildRolloutProvenance({
    repoRoot,
    configPath,
    productManifestPath,
    libraryReleaseManifestPath,
    sourceTargets: sourceVerificationTargets,
    bindingTargets: bindingEvidenceTargets,
    producerName: config.producerName,
  });
  const refreshProducer = executionPlan.refreshProducer;
  const observedAt = new Date().toISOString();

  const report: RolloutReport = {
    schemaVersion: 2,
    executionMode: executionPlan.mode,
    observedAt,
    generatedAt: observedAt,
    generated_at_unix: Math.floor(Date.parse(observedAt) / 1000),
    durationSeconds: 0,
    ok: false,
    repoCommitSha: provenance.repoCommitSha,
    rolloutConfigSha256: provenance.rolloutConfigSha256,
    productManifestVersion: provenance.productManifestVersion,
    libraryReleaseVersion: provenance.libraryReleaseVersion,
    inputsMatchCommit: provenance.inputsMatchCommit,
    repositoryExpected: provenance.repositoryExpected,
    tradingViewObserved: { sources: [], bindings: [] },
    mutations: {
      sourceSaveRequested: executionPlan.saveSources,
      sourceSavesCompleted: 0,
      producerRefreshRequested: executionPlan.refreshProducer,
      producerInstancesRemoved: 0,
      bindingRepairRequested: executionPlan.repairBindings,
      bindingsRepaired: 0,
      layoutSaveRequested: executionPlan.saveLayout,
      layoutSaved: false,
    },
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
    await gotoChart(session.page, config.primaryChartUrl);
    await ensurePineEditor(session.page);

    if (executionPlan.saveSources) {
      let saveSessionTimedOut = false;
      for (const target of config.saveTargets) {
        let lastError = "unknown save failure";
        for (let attempt = 1; attempt <= 2; attempt += 1) {
          try {
            report.save.succeeded.push(await saveConsumerSource(session, target));
            report.mutations.sourceSavesCompleted = report.save.succeeded.length;
            lastError = "";
            break;
          } catch (error) {
            lastError = String((error as Error)?.message ?? error);
            // Promise.race cannot cancel the timed-out Playwright action. A
            // retry on the same page would overlap the still-settling script
            // picker and can select a different Monaco model. Stop the write
            // phase and let finally close the session instead.
            saveSessionTimedOut = isTrackedStepTimeoutError(error) || session.page.isClosed();
            if (saveSessionTimedOut) break;
            if (attempt < 2) {
              await gotoChart(session.page, config.primaryChartUrl).catch(() => undefined);
              await ensurePineEditor(session.page).catch(() => undefined);
            }
          }
        }
        if (lastError) report.save.failed.push({ target: target.scriptName, error: lastError });
        if (saveSessionTimedOut) break;
      }
    }

    if (report.save.failed.length === 0 && executionPlan.refreshProducer) {
      // The applied producer instance lives in EVERY layout that carries
      // consumers (desktop primary + e.g. the Mobile layout the operator
      // actually watches). Refreshing only primaryChartUrl left the visible
      // instance frozen (live run 29929470730, 2026-07-22).
      try {
        for (const producerChartUrl of resolveProducerRefreshChartUrls(config)) {
          if (!session.page.url().startsWith(producerChartUrl)) {
            // No ensurePineEditor here: refreshChartScriptInstance opens the
            // editor itself FAULT-TOLERANTLY. An intolerant outer call
            // stranded run 29946386778 on /pine-screener/ (editor recovery)
            // and aborted the whole block before the second layout.
            await gotoChart(session.page, producerChartUrl);
          }
          report.producerRefresh.removedInstances += await refreshChartScriptInstance(session.page, config.producerName);
        }
        report.producerRefresh.ok = true;
        report.mutations.producerInstancesRemoved = report.producerRefresh.removedInstances;
      } catch (error) {
        report.producerRefresh.error = `${session.page.url()}: ${String((error as Error)?.message ?? error)}`;
        // Best-effort, but never silent: the refresh only re-applies an ALREADY
        // published script so the chart shows the new version. Its failure costs
        // one manual "add to chart" on the next version bump — it must not hide
        // the source/binding truth below, so it warns instead of failing the run.
        console.warn(`[rollout] producer refresh failed (cosmetic, non-fatal): ${report.producerRefresh.error}`);
      }
    }

    // Gated on saves ALONE. The cosmetic refresh above used to gate this block too,
    // so a single refresh timeout reported `sources.checked 0` / `bindings 0` and
    // skipped the load-bearing verification entirely (live runs 29929470730 and
    // 29946386778, 2026-07-22).
    if (report.save.failed.length === 0) {
      if (executionPlan.saveSources && report.save.succeeded.length > 0) {
        // Do not verify against the same in-memory Monaco buffers we just
        // edited. Reload the chart first so source hashes are reconstructed
        // from TradingView's persisted saved-script state. This catches a Save
        // command that appears successful but does not survive navigation.
        await gotoChart(session.page, config.primaryChartUrl);
        await ensurePineEditor(session.page);
      }

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

      // Opt-in only: the immutable execution plan permits repair only in write
      // mode. Verify-only always passes false/false and therefore only reads
      // the currently selected BUS sources.
      for (const target of config.verifyTargets) {
        const targetChartUrl = target.chartUrl ?? config.primaryChartUrl;
        if (!session.page.url().startsWith(targetChartUrl)) {
          await gotoChart(session.page, targetChartUrl);
        }
        let result: VerifyConsumerResult | null = null;
        let lastError = "unknown verification failure";
        for (let attempt = 1; attempt <= 2; attempt += 1) {
          try {
            result = await verifyConsumerBindings(
              session,
              target,
              executionPlan.repairBindings,
              executionPlan.repairBindings,
            );
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

      // Persist the rebinds. The per-consumer settings "submit" only mutates the
      // in-session indicator instance; without an explicit layout save the
      // changes revert on reload, so the operator's chart (and the next
      // read-only verify) still show the stale "Close" sources even though this
      // run read them back as bound (2026-07-25 incident). Only writing runs
      // save; a save failure must not report green, so it lands in
      // bindings.failed and gates report.ok.
      if (executionPlan.saveLayout && report.bindings.failed.length === 0) {
        try {
          await saveChangedChartLayout(session.page);
          report.mutations.layoutSaved = true;
        } catch (error) {
          report.bindings.failed.push({
            target: "chart-layout",
            error: `layout save failed (rebinds not persisted): ${String((error as Error)?.message ?? error)}`,
          });
        }
      }
    }
  } finally {
    await closeTradingViewSession(session);
    report.sources.checked = report.sources.consumers.length;
    report.sources.drifted = report.sources.consumers.filter((item) => !item.matches).length;
    report.bindings.checkedConsumers = report.bindings.consumers.length;
    report.bindings.checkedBindings = report.bindings.consumers.reduce((sum, item) => sum + item.checked, 0);
    report.bindings.mismatches = report.bindings.consumers.reduce((sum, item) => sum + item.mismatches.length, 0);
    report.mutations.bindingsRepaired = report.bindings.consumers.reduce(
      (sum, item) => sum + item.repaired.length,
      0,
    );
    report.tradingViewObserved.sources = report.sources.consumers.map((item) => ({
      scriptName: item.scriptName,
      actualSha256: item.actualSha256,
      actualBytes: item.actualBytes,
      matchesRepository: item.matches,
    }));
    report.tradingViewObserved.bindings = report.bindings.consumers.map((item) => ({
      scriptName: item.scriptName,
      selections: item.bindings.map((binding) => ({
        label: binding.label,
        actual: binding.actual,
        expected: binding.expected,
        matches: binding.ok,
      })),
      runtimeErrors: item.runtimeErrors,
    }));
    report.durationSeconds = Math.round((Date.now() - started) / 100) / 10;
    // producerRefresh is deliberately NOT a factor: it is a cosmetic re-apply of an
    // already-published script, and TradingView's SPA makes it the flakiest step in
    // the run. Its outcome stays in report.producerRefresh.{ok,error} as evidence.
    report.ok = report.save.failed.length === 0
      && report.inputsMatchCommit
      && report.repositoryExpected.libraryRelease.matches
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

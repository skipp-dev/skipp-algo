#!/usr/bin/env -S node --enable-source-maps

import fs from "node:fs";
import path from "node:path";

import {
  buildRolloutProvenance,
  groupTargetsByLayout,
  resolveExecutionPlan,
  resolveLayoutSavePoints,
  resolveLibraryPublishObservation,
  type LibraryPublishObservation,
  type RolloutExecutionMode,
  type RolloutProvenance,
} from "../automation/tradingview/lib/tv_consumer_rollout_evidence.js";
import {
  closeTradingViewSession,
  ensurePineEditor,
  fetchPublishedLibraryVersionViaFacade,
  gotoChart,
  isTrackedStepTimeoutError,
  newTradingViewSession,
  refreshChartScriptInstance,
  resolveConsumerRefreshTargets,
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
    /**
     * The only field in this report that is read from outside the checkout.
     * repositoryExpected.libraryRelease.matches compares two fields of one
     * manifest file, so it is true for any internally consistent tree,
     * including a stale one.
     */
    libraryRelease: LibraryPublishObservation;
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
    consumerInstancesRemoved: number;
    bindingRepairRequested: boolean;
    bindingsRepaired: number;
    layoutSaveRequested: boolean;
    layoutSaved: boolean;
    /** Every chart layout actually persisted, in visit order. */
    savedChartUrls: string[];
    /**
     * Layouts whose rebinds were deliberately discarded because not every
     * target on them came back clean. These charts are unchanged, not
     * half rebound — and repair stopped at the first of them.
     */
    abandonedChartUrls: string[];
    /**
     * Sources this run SAVED even though the registered R1 evidence attests
     * different content — so the evidence stops describing what is deployed
     * the moment the run finishes. #4286 guards the pull-request path; a
     * dispatch, a schedule and the post-refresh chain reach TradingView
     * without one, which is how 2026-08-01 happened.
     *
     * Deliberately a report, not a skip: skipping would freeze these scripts
     * on an old pinned library while the producer moves on. The run ends red
     * so a human re-attests.
     */
    savedWithoutAttestation: string[];
  };
  save: { expected: number; succeeded: SaveConsumerResult[]; failed: FailedTarget[] };
  producerRefresh: { requested: boolean; ok: boolean; removedInstances: number; error: string };
  consumerRefresh: { requested: boolean; ok: boolean; removedInstances: number; errors: string[] };
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
  // Named here rather than threaded through buildRolloutProvenance so the
  // provenance payload shape (and its pins) stays untouched.
  const libraryScriptName = String(
    (JSON.parse(fs.readFileSync(libraryReleaseManifestPath, "utf-8")).library ?? {}).scriptName ?? "",
  );
  if (!libraryScriptName) throw new Error("library release manifest has no library.scriptName");
  const sourceVerificationTargets = config.saveTargets.map((target) => ({ ...target }));
  const override = process.env.TV_CONSUMER_MAPPING_JSON?.trim();
  if (executionPlan.saveSources && override) {
    config.saveTargets = JSON.parse(override) as SaveConsumerTarget[];
  } else if (!executionPlan.saveSources) {
    config.saveTargets = [];
  }
  // Computed AFTER the mapping override and the verify-only reset, so it
  // describes what this run actually writes: a read-only run saves nothing and
  // therefore un-attests nothing, and an explicit mapping cannot hide a target
  // from the report by naming it late.
  const unattested = new Set<string>(
    JSON.parse(process.env.TV_UNATTESTED_SOURCES?.trim() || "[]") as string[],
  );
  const savedWithoutAttestation = config.saveTargets
    .filter((target) => unattested.has(target.scriptName))
    .map((target) => target.scriptName);
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
    tradingViewObserved: {
      // Starts as an honest "not looked yet": unknown, with no observed value.
      // If the probe below never runs, this stays unknown rather than pretending.
      libraryRelease: resolveLibraryPublishObservation({
        scriptName: libraryScriptName,
        manifestPublishedVersion: provenance.repositoryExpected.libraryRelease.publishedVersion,
        observedVersion: null,
      }),
      sources: [],
      bindings: [],
    },
    mutations: {
      sourceSaveRequested: executionPlan.saveSources,
      sourceSavesCompleted: 0,
      producerRefreshRequested: executionPlan.refreshProducer,
      producerInstancesRemoved: 0,
      consumerInstancesRemoved: 0,
      bindingRepairRequested: executionPlan.repairBindings,
      bindingsRepaired: 0,
      layoutSaveRequested: executionPlan.saveLayout,
      layoutSaved: false,
      savedChartUrls: [],
      abandonedChartUrls: [],
      savedWithoutAttestation,
    },
    save: { expected: config.saveTargets.length, succeeded: [], failed: [] },
    producerRefresh: { requested: refreshProducer, ok: !refreshProducer, removedInstances: 0, error: "" },
    consumerRefresh: { requested: executionPlan.repairBindings, ok: true, removedInstances: 0, errors: [] },
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

    // Read what TradingView actually publishes, BEFORE anything is written.
    // Every other provenance field in this report is derived from the checked-out
    // tree, so it is satisfied by any tree that agrees with itself -- including a
    // stale one (2026-08-01: matches=true at 180 while main was on 182).
    //
    // A known disagreement stops the run rather than colouring the report after
    // the fact: the consumers about to be saved carry `import .../<N>` pins, and
    // saving them against a version TradingView does not publish is the CE10272
    // class -- the scripts land and then fail to compile on the operator chart.
    //
    // An unreadable facade is NOT drift. It warns and the run continues, because
    // a probe outage is not evidence about the library. The verdict stays
    // "unknown" in the artifact rather than being rounded to "match".
    report.tradingViewObserved.libraryRelease = resolveLibraryPublishObservation({
      scriptName: libraryScriptName,
      manifestPublishedVersion: provenance.repositoryExpected.libraryRelease.publishedVersion,
      observedVersion: await fetchPublishedLibraryVersionViaFacade(session.page, libraryScriptName),
    });
    const libraryObservation = report.tradingViewObserved.libraryRelease;
    if (libraryObservation.verdict === "drift") {
      throw new Error(
        `Library publish drift: the manifest says ${libraryObservation.scriptName} is published at `
        + `version ${libraryObservation.manifestPublishedVersion}, but TradingView lists `
        + `${libraryObservation.observedVersion}. Refusing to roll consumers onto a pin that is not what is published.`,
      );
    }
    if (libraryObservation.verdict === "unknown") {
      console.warn(
        `[rollout] could not read the published version of ${libraryObservation.scriptName} from the pine facade — `
        + "the run continues, but its library-publish evidence is UNKNOWN, not confirmed.",
      );
    }

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

    // A saved consumer needs the same treatment as the producer, and for the
    // same reason: the applied instance stays on the version it was added with.
    // The producer got a refresh, the consumer never did — so a consumer whose
    // own source GAINED an input kept a stale instance whose settings dialog
    // has no row for the new label, and the rebind below died with "Source
    // combobox not found" (runs 30694013096, 30696257671 and 30698519321, all
    // on CTX SessionMssBull after #4263 appended two channels).
    //
    // Gated on repairBindings, not on refreshProducer: re-applying a script
    // DROPS its bindings, and only the repair pass below puts them back. Doing
    // this without that pass would leave the consumer unbound.
    if (report.save.failed.length === 0 && executionPlan.repairBindings) {
      for (const consumer of resolveConsumerRefreshTargets(config)) {
        try {
          if (!session.page.url().startsWith(consumer.chartUrl)) {
            await gotoChart(session.page, consumer.chartUrl);
          }
          report.consumerRefresh.removedInstances += await refreshChartScriptInstance(
            session.page,
            consumer.scriptName,
          );
        } catch (error) {
          // NOT cosmetic, unlike the producer pass: without the refresh the
          // rebind cannot see the new inputs at all. Record it and let the
          // binding failure below carry the run red, rather than pretending
          // the consumer was brought up to date.
          report.consumerRefresh.ok = false;
          report.consumerRefresh.errors.push(
            `${consumer.scriptName} @ ${consumer.chartUrl}: ${String((error as Error)?.message ?? error)}`,
          );
        }
      }
      report.mutations.consumerInstancesRemoved = report.consumerRefresh.removedInstances;
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
      //
      // The chart layout is the unit this loop can act on atomically. The
      // per-consumer settings "submit" mutates only the in-session indicator
      // instance; an explicit layout save persists every rebind on that layout
      // at once, and gotoChart -- a hard page.goto -- discards every unsaved
      // rebind on it at once. Without the save the operator's chart (and the
      // next read-only verify) still show the stale "Close" sources even though
      // this run read them back as bound (2026-07-25 incident).
      //
      // That cuts both ways, and the second edge is the useful one: NOT saving
      // is an exact, free rollback. So a layout is saved only when every target
      // on it came back clean. A layout with any failure is abandoned -- not
      // saved, then reloaded to discard -- and is left exactly as it was. No
      // chart is ever persisted half rebound.
      //
      // After an abandoned layout the run stops mutating and finishes
      // read-only, so what is persisted is always a complete PREFIX of the
      // rollout rather than an arbitrary subset. The shipped config visits the
      // primary operator chart first, so a late failure leaves the traded chart
      // repaired and the rest untouched, never the reverse. Repair is only ever
      // narrowed here, never widened, so the immutable execution plan still
      // bounds the run.
      const savedChartUrls: string[] = [];
      const abandonedChartUrls: string[] = [];
      let repairBindings = executionPlan.repairBindings;

      for (const layout of groupTargetsByLayout(config.verifyTargets, config.primaryChartUrl)) {
        if (!session.page.url().startsWith(layout.chartUrl)) {
          await gotoChart(session.page, layout.chartUrl);
        }
        // Captured before the targets run: it decides whether THIS layout was
        // mutated, and a failure inside the layout must not retroactively make
        // it look untouched.
        const mutatingLayout = repairBindings;
        let layoutRepairedCleanly = true;

        for (const target of layout.targets) {
          let result: VerifyConsumerResult | null = null;
          let lastError = "unknown verification failure";
          for (let attempt = 1; attempt <= 2; attempt += 1) {
            try {
              result = await verifyConsumerBindings(session, target, repairBindings, repairBindings);
              lastError = "";
              break;
            } catch (error) {
              lastError = String((error as Error)?.message ?? error);
              if (attempt < 2) await gotoChart(session.page, layout.chartUrl).catch(() => undefined);
            }
          }
          if (result) report.bindings.consumers.push(result);
          else report.bindings.failed.push({ target: target.scriptName, error: lastError });
          // Exactly the run's own success criterion, per target: report.ok is
          // gated on bindings.failed and bindings.mismatches. It deliberately
          // does NOT include result.ok, which also carries
          // unknownParentRuntimeError -- that signal is evidence only, because
          // the residual window after the repair still collects dead-parent
          // errors from the OTHER consumers this run has not repaired yet.
          // Abandoning on it would abandon every layout of a healthy rollout.
          if (!result || result.mismatches.length > 0) layoutRepairedCleanly = false;
        }

        if (!executionPlan.saveLayout || !mutatingLayout) continue;

        if (!layoutRepairedCleanly) {
          // Roll back by discarding: reload without saving. This is the same
          // mechanism that silently reverted rebinds before the save existed --
          // used deliberately, it is the reason a partial repair can never
          // reach the operator's chart.
          abandonedChartUrls.push(layout.chartUrl);
          repairBindings = false;
          await gotoChart(session.page, layout.chartUrl).catch(() => undefined);
          continue;
        }

        try {
          await saveChangedChartLayout(session.page);
          savedChartUrls.push(layout.chartUrl);
          report.mutations.layoutSaved = true;
        } catch (error) {
          // The save never confirmed, so what reached this layout is unknown.
          // Stop mutating rather than stack another layout on top of it; the
          // failure gates report.ok below.
          repairBindings = false;
          report.bindings.failed.push({
            target: `chart-layout:${layout.chartUrl}`,
            error: `layout save failed (rebinds not persisted): ${String((error as Error)?.message ?? error)}`,
          });
        }
      }

      if (executionPlan.saveLayout) {
        report.mutations.savedChartUrls = savedChartUrls;
        report.mutations.abandonedChartUrls = abandonedChartUrls;
        // A run that abandoned or failed nothing must have saved every layout
        // it planned to. Without this a green report could still cover a strict
        // subset -- the failure this whole block exists to prevent. When
        // something WAS abandoned, the layouts after it are unsaved on purpose
        // and report.ok is already false through the target that caused it.
        const planned = resolveLayoutSavePoints(config.verifyTargets, config.primaryChartUrl);
        const missed = planned.filter((chartUrl) => !savedChartUrls.includes(chartUrl));
        const nothingWentWrong = abandonedChartUrls.length === 0
          && report.bindings.failed.length === 0
          && report.bindings.consumers.every((item) => item.mismatches.length === 0);
        if (missed.length > 0 && nothingWentWrong) {
          report.bindings.failed.push({
            target: "chart-layout",
            error: `layouts never saved (rebinds not persisted): ${missed.join(", ")}`,
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
    // This one is load-bearing on its own: an un-attested save writes exactly
    // what the repository holds, so every other clause below stays satisfied
    // and the run would otherwise be green while the registered evidence has
    // just stopped describing what is deployed.
    report.ok = report.mutations.savedWithoutAttestation.length === 0
      && report.save.failed.length === 0
      && report.inputsMatchCommit
      && report.repositoryExpected.libraryRelease.matches
      // Explicit even though a drift already threw above: this is the condition
      // report.ok is meant to encode, and it must not rest on a control-flow
      // detail elsewhere in this file staying as it is today. "unknown"
      // deliberately does not gate -- see the probe.
      && report.tradingViewObserved.libraryRelease.verdict !== "drift"
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

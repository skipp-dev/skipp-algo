#!/usr/bin/env -S node --enable-source-maps

import fs from "node:fs";
import path from "node:path";

import {
  bindingsAreComplete,
  buildRolloutProvenance,
  groupTargetsByLayout,
  resolveExecutionPlan,
  resolveExpectedLayoutSavePoints,
  resolveLibraryPublishObservation,
  resolveLibraryDriftGate,
  resolveSkippedLayouts,
  type LibraryPublishObservation,
  type RolloutExecutionMode,
  type RolloutProvenance,
} from "../automation/tradingview/lib/tv_consumer_rollout_evidence.js";
import {
  closeTradingViewSession,
  ensurePineEditor,
  fetchPublishedLibraryVersionViaFacade,
  captureLegendFailureEvidence,
  writeLegendFailureEvidence,
  gotoChart,
  gotoChartAndAwaitScript,
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
import {
  compareAgainstBaseline,
  selectLayoutsNeedingRepair,
  type ObservedConsumer,
  type OutOfBandVerdict,
  type RepairCandidateConsumer,
} from "../automation/tradingview/lib/tv_out_of_band_drift.js";

type RolloutConfig = {
  producerName: string;
  primaryChartUrl: string;
  saveTargets: SaveConsumerTarget[];
  verifyTargets: VerifyConsumerTarget[];
};

/**
 * One entry per verification attempt of a target.
 *
 * Added 2026-08-22: the retry loop kept its per-attempt detail (exit, duration,
 * error text) only in the CI log, so the artifact alone could not tell one
 * flake from N identical deterministic failures — the distinction
 * preflight_retry_log.jsonl exists to make. `bindings.failed[].error` carries
 * only the LAST error.
 */
type VerifyAttempt = { attempt: number; durationMs: number; error: string };
type FailedTarget = { target: string; error: string; attempts?: VerifyAttempt[]; evidence?: string };
type RolloutReport = {
  schemaVersion: 2;
  executionMode: RolloutExecutionMode;
  observedAt: string;
  generatedAt: string;
  /**
   * When the run STOPPED observing. `observedAt`/`generatedAt` are both stamped
   * at the START (run 758: 05:25:03 stamped, last trace line 05:53:20 — a 28
   * minute run), which is enough to misorder cause and effect when correlating
   * a layout write against the operator's own browser or the next refresh.
   * Null until the report is finalised.
   */
  completedAt: string | null;
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
     * Layouts whose rebinds were discarded because the SAVE itself never
     * confirmed. Only that case remains: an incomplete repair is now saved,
     * not thrown away (see partiallyRepairedChartUrls).
     */
    abandonedChartUrls: string[];
    /**
     * Layouts saved even though not every target on them came back clean —
     * operator decision 2026-08-22, and the reversal of the rule that stood
     * here before ("a layout with any failure is abandoned").
     *
     * The old rule rested on "not saving is an exact, free rollback". That is
     * only true of BINDINGS. Measured on run 758 (2026-08-22): the instances
     * this run re-inserted at 05:37-05:47 survived both a layout switch and
     * the end of the session, while the 98 rebinds it read back as correct at
     * 05:47-05:53 were gone. TradingView persists instance add/remove at once
     * and input bindings only on a layout save — so abandoning discarded the
     * repair reliably and did nothing about the damage. With ~16 refresh-driven
     * runs a day, every round left the layout further apart.
     *
     * Saving a partial repair is therefore strictly better than the
     * alternative: the targets that were reached keep their sources, the ones
     * that were not stay on defaults — which is exactly where abandoning left
     * them anyway. Repair still stops at the first such layout, so what is
     * persisted remains a prefix of the rollout, and report.ok is still false
     * through the target that failed.
     */
    partiallyRepairedChartUrls: string[];
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
  /**
   * Whether anyone wrote to the managed layouts between the last CI run and
   * this one. Measured BEFORE this run's first mutation, so a difference is
   * attributable to a second writer -- normally the operator's browser, whose
   * autosave nothing in CI serialises against.
   */
  outOfBandDrift: OutOfBandVerdict;
  save: { expected: number; succeeded: SaveConsumerResult[]; failed: FailedTarget[] };
  producerRefresh: { requested: boolean; ok: boolean; removedInstances: number; error: string };
  consumerRefresh: { requested: boolean; ok: boolean; removedInstances: number; errors: string[] };
  sources: {
    expected: number;
    checked: number;
    drifted: number;
    consumers: VerifyConsumerSourceResult[];
    failed: FailedTarget[];
    /** Gesetzt, wenn die Quell-Pruefung bewusst NICHT geurteilt hat. */
    notJudgedReason?: string;
  };
  bindings: {
    expectedConsumers: number;
    checkedConsumers: number;
    /**
     * The layouts THIS run planned to save, and the ones it deliberately left
     * alone.
     *
     * plannedChartUrls is the layout list this run set out to save: the
     * narrowed set for repair-only, the full list for write and verify-only.
     * skippedChartUrls is the difference, and it is the field that says a
     * narrowing happened at all: empty unless the mode is repair-only.
     *
     * The field was called narrowedToChartUrls until 2026-08-23 and misread
     * twice under that name -- once in this comment, once in a report --
     * both times as "empty for write". Renamed rather than re-explained.
     *
     * These two exist because the pair above cannot answer the only question
     * a post-mortem asks about repair-only. `checkedConsumers: 7` against
     * `expectedConsumers: 10` reads exactly the same whether the run skipped
     * three CLEAN layouts on purpose -- the mode working -- or whether three
     * targets were unreadable -- the mode failing. Opposite conclusions, same
     * two numbers, and until 2026-08-23 the narrowing lived only in a local
     * variable that died with the process. This is the sole post-mortem
     * surface of the mode: the run cannot be re-executed to find out, because
     * the next refresh has already moved the layout on.
     *
     * expectedConsumers stays the FULL config on purpose. It is what the
     * repository expects; plannedChartUrls is what this run decided. A
     * reader needs both to see that a decision was made at all.
     */
    plannedChartUrls: string[];
    skippedChartUrls: string[];
    checkedBindings: number;
    mismatches: number;
    consumers: (VerifyConsumerResult & { attempts?: VerifyAttempt[] })[];
    failed: FailedTarget[];
    /** Dateinamen der Fehler-Beweise, relativ zum hochgeladenen Artefakt. */
    evidence: string[];
  };
};

function getFlag(name: string, fallback: string): string {
  const args = process.argv.slice(2);
  const index = args.indexOf(name);
  return index === -1 || !args[index + 1] ? fallback : args[index + 1];
}

/**
 * Read the bindings of every verify target without changing anything.
 *
 * verifyConsumerBindings is called with repair=false and forceRebind=false, so
 * this walks the layouts read-only. A target that cannot be read is simply
 * absent from the result, which the comparison turns into "unknown" rather than
 * into a false drift.
 *
 * Returns two views of the same pass: `observed` (label/actual pairs) feeds
 * compareAgainstBaseline, and `consumers` (scriptName/mismatches) feeds
 * selectLayoutsNeedingRepair — repair-only's layout-scoping decision reuses
 * this read instead of paying for a second browser pass.
 */
async function observeBindingsOnly(
  session: Awaited<ReturnType<typeof newTradingViewSession>>,
  config: RolloutConfig,
): Promise<{ observed: ObservedConsumer[]; consumers: RepairCandidateConsumer[] }> {
  const observed: ObservedConsumer[] = [];
  const consumers: RepairCandidateConsumer[] = [];
  for (const layout of groupTargetsByLayout(config.verifyTargets, config.primaryChartUrl)) {
    try {
      // The navigation sits inside the same swallow as the read below it, on
      // purpose: this pass runs before the primary chart is even visited (see
      // the ordering comment at the call site), so a flake reaching a
      // SECONDARY layout here must not abort the run before the traded chart
      // is ever touched. The shipped config visits the primary chart first --
      // "a late failure leaves the traded chart repaired and the rest
      // untouched, never the reverse" -- and an unreachable layout up here
      // must degrade to unread targets (which the coverage guard below turns
      // into "unknown"), not a fatal error that reverses that property.
      if (!session.page.url().startsWith(layout.chartUrl)) {
        // gotoChartAndAwaitScript, not gotoChart: the bare navigation resolves
        // before the legend is rebuilt, and the FIRST target read afterwards
        // dies on "Existing chart instance not found" against a healthy chart
        // — the exact race the helper's docstring records for the drill
        // (#4295). This pass hit it on 2026-08-14 twice in a row (runs
        // 31831209411 and 31833390287): SMC Decision Board, first target on
        // the first layout, was never read, the coverage guard answered
        // "unknown", and a write run whose every save succeeded went red.
        // The wait is on the SAME predicate verifyConsumerBindings throws on,
        // so a genuinely absent first target still times out into the catch
        // below rather than passing here and failing there.
        await gotoChartAndAwaitScript(session.page, layout.chartUrl, layout.targets[0].scriptName);
      }
      for (const target of layout.targets) {
        try {
          const result = await verifyConsumerBindings(session, target, false, false);
          observed.push({
            scriptName: result.scriptName,
            selections: result.bindings.map((binding) => ({ label: binding.label, actual: binding.actual })),
          });
          consumers.push({ scriptName: result.scriptName, mismatches: result.mismatches });
        } catch (error) {
          // The target stays absent — an unread target must not read as
          // unchanged — but never silently: the two 2026-08-14 misses left
          // ZERO log lines, and the cause had to be reconstructed from the
          // absence of trace output.
          console.warn(
            `[rollout] pre-mutation observation could not read ${target.scriptName}: ${String(error)}`,
          );
        }
      }
    } catch (error) {
      // The layout itself could not be reached (e.g. a page.goto timeout, or
      // the settle wait above ran out). Every target on it is simply absent
      // from `observed`, same as a single unread target above.
      console.warn(
        `[rollout] pre-mutation observation could not reach ${layout.chartUrl} `
        + `(${layout.targets.map((target) => target.scriptName).join(", ")} stay unread): ${String(error)}`,
      );
    }
  }
  return { observed, consumers };
}

/**
 * Read the last published binding snapshot from disk.
 *
 * A present-but-malformed shape (missing file, unparsable JSON, or a
 * tradingViewObserved.bindings field that is not an array) must never abort
 * the run -- it is the "unknown" verdict, decided downstream by
 * compareAgainstBaseline, not a fetch-time error. Shared by both call sites
 * below: a mutating run loads it before its first mutation, a read-only run
 * loads it after its own normal verification completes (see the finally
 * block in main()).
 */
function loadPublishedBaseline(baselinePath: string): ObservedConsumer[] | null {
  try {
    const parsed = JSON.parse(fs.readFileSync(baselinePath, "utf-8"));
    const raw = parsed?.tradingViewObserved?.bindings;
    return Array.isArray(raw) ? (raw as ObservedConsumer[]) : null;
  } catch {
    return null;
  }
}

async function main(): Promise<void> {
  const started = Date.now();
  const executionPlan = resolveExecutionPlan(process.argv.slice(2), process.env);
  const repoRoot = process.cwd();
  const configPath = path.resolve(getFlag("--config", "automation/tradingview/config/consumer-rollout.json"));
  const outPath = path.resolve(getFlag("--out", "artifacts/monitoring/tradingview_consumer_bindings.json"));
  // Hoisted above the mode branch below: a mutating run reads this before its
  // first mutation, a read-only run reads it again in the finally block after
  // its own verification completes (Finding 3, 2026-08-03) -- both need the
  // same path.
  const baselinePath = path.resolve(
    getFlag("--baseline", "artifacts/monitoring/previous/tradingview_consumer_bindings.json"),
  );
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
  // Ein Stempel je Lauf: die Beweisdateien eines Laufs gehoeren sichtbar
  // zusammen und kollidieren nicht mit denen des naechsten.
  const evidenceRunId = observedAt.replace(/[:.]/g, "-");

  const report: RolloutReport = {
    schemaVersion: 2,
    executionMode: executionPlan.mode,
    observedAt,
    generatedAt: observedAt,
    completedAt: null,
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
      partiallyRepairedChartUrls: [],
      savedWithoutAttestation,
    },
    outOfBandDrift: {
      status: "unknown",
      reason: "the pre-mutation observation has not run yet",
      changed: [],
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
      // Filled in the finally block, from the same layoutsNeedingRepair the
      // skip and both completeness gates read — one decision, one source.
      plannedChartUrls: [],
      skippedChartUrls: [],
      checkedBindings: 0,
      mismatches: 0,
      evidence: [],
      consumers: [],
      failed: [],
    },
  };

  const session = await newTradingViewSession();
  // Hoisted above the try block: the finally block's completeness gate (see
  // report.ok below) has to read this too, and a `let` declared inside `try`
  // is not visible in its own `finally`. Stays empty for every mode except
  // repair-only -- the skip check in the layout loop below is itself gated on
  // executionPlan.mode === "repair-only", so an empty array here never
  // narrows a write or verify-only run.
  let layoutsNeedingRepair: string[] = [];
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
    // Trennt "darf nicht SCHREIBEN" von "darf nicht MESSEN" — Begruendung und
    // Messung in resolveLibraryDriftGate. Kurz: der Abbruch existiert, weil ein
    // SAVE die Consumer auf einen unveroeffentlichten Pin rollen wuerde
    // (CE10272). Ein verify-only-Lauf speichert nichts; ihn abzubrechen kostete
    // nur die Beobachtung, und zwar vollstaendig: vom 2026-08-28 bis 2026-08-29
    // starb JEDER tv-save-Lauf mit `checkedConsumers: 0`, weil die Save-Queue
    // fast immer in ein Drift-Fenster faellt.
    const driftGate = resolveLibraryDriftGate({
      verdict: libraryObservation.verdict,
      mode: executionPlan.mode,
    });
    if (driftGate.abort) {
      throw new Error(
        `Library publish drift: the manifest says ${libraryObservation.scriptName} is published at `
        + `version ${libraryObservation.manifestPublishedVersion}, but TradingView lists `
        + `${libraryObservation.observedVersion}. Refusing to roll consumers onto a pin that is not what is published.`,
      );
    }
    if (libraryObservation.verdict === "drift") {
      console.warn(`[rollout] ${driftGate.reason}`);
    }
    if (libraryObservation.verdict === "unknown") {
      console.warn(
        `[rollout] could not read the published version of ${libraryObservation.scriptName} from the pine facade — `
        + "the run continues, but its library-publish evidence is UNKNOWN, not confirmed.",
      );
    }

    // Before anything is written. After the first save, a difference could be
    // this run's own doing and proves nothing about a second writer. A
    // read-only run never writes, so it has no "before the first mutation"
    // moment to anchor on -- it compares AFTER its own normal verification
    // completes instead (see the finally block below, which reuses
    // report.tradingViewObserved.bindings rather than paying for a second
    // observeBindingsOnly pass here).
    if (executionPlan.mode !== "verify-only") {
      const preMutation = await observeBindingsOnly(session, config);
      report.outOfBandDrift = compareAgainstBaseline({
        observed: preMutation.observed,
        baseline: loadPublishedBaseline(baselinePath),
        expectedScriptNames: config.verifyTargets.map((target) => target.scriptName),
      });
      if (report.outOfBandDrift.status !== "clean") {
        console.warn(`[rollout] out-of-band drift ${report.outOfBandDrift.status}: ${report.outOfBandDrift.reason}`);
      }
      // Reuses this same read rather than a second browser pass: a consumer
      // this read never saw (an unreachable layout, or a target the per-target
      // catch above swallowed) is absent from preMutation.consumers, and
      // selectLayoutsNeedingRepair treats that absence as needing repair too
      // -- an observation outage widens the run, it never narrows it.
      if (executionPlan.mode === "repair-only") {
        layoutsNeedingRepair = selectLayoutsNeedingRepair(
          preMutation.consumers,
          config.verifyTargets.map((target) => ({
            scriptName: target.scriptName,
            chartUrl: target.chartUrl ?? config.primaryChartUrl,
          })),
        );
      }
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

    // Source verification runs BEFORE the instance refreshes, and the order is
    // load-bearing in both directions (root-caused 2026-08-02):
    //
    //  * Its reload below is the point — verify TradingView's persisted
    //    saved-script state, not the Monaco buffers this run just edited.
    //  * That same hard reload reverts the chart to its SAVED layout, which
    //    silently discards any unsaved instance the refreshes insert. Sitting
    //    between refresh and binding verification, it made six R4 runs report
    //    "Existing chart instance not found" / stale 60-input dialogs about
    //    instances that had genuinely been rolled back moments earlier
    //    (30694013096, 30696257671, 30698519321, 30700161400, 30702240413,
    //    30718040533) — and sent four detection-side fixes (#4304, #4307,
    //    #4313, #4320) after probes that were telling the truth.
    //
    // Up here it verifies exactly what it should while there is nothing
    // unsaved to destroy. From the refreshes onward the flow stays on the
    // layout without an unconditional reload until the binding loop's own
    // save decision.
    //
    // The sentence that used to close this paragraph — "abandoning now rolls
    // back the inserts too, which strengthens the free-rollback property" —
    // was measured FALSE on run 758 (2026-08-22): TradingView persists an
    // instance add/remove at once and input bindings only on a layout save,
    // so abandoning discarded the 98 rebinds and left the 12 re-inserted
    // instances in place. The free-rollback property is real for BINDINGS,
    // which is exactly why the reload has to sit above the refreshes — but it
    // never covered the inserts. Since #5013 the binding loop does not abandon
    // a partial repair at all; it saves it. The measurement and the operator
    // decision are documented at partiallyRepairedChartUrls above.
    if (report.save.failed.length === 0) {
      if (executionPlan.saveSources && report.save.succeeded.length > 0) {
        await gotoChart(session.page, config.primaryChartUrl);
        await ensurePineEditor(session.page);
      }

      // Unter Library-Drift wird die Quell-Pruefung UEBERSPRUNGEN, nicht
      // stillschweigend mit 0 gefuellt: ihr Erwartungswert kommt aus dem
      // ausgecheckten Baum, dessen Uebereinstimmung mit TradingView die Drift
      // gerade offen laesst. `notJudgedReason` macht den Unterschied zwischen
      // "geprueft, nichts gefunden" und "nicht geprueft" im Artefakt sichtbar —
      // eine 0 ohne Grund ist die teuerste Sorte Entwarnung.
      if (!driftGate.judgeSources && libraryObservation.verdict === "drift") {
        report.sources.notJudgedReason = driftGate.reason;
      }
      for (const target of sourceVerificationTargets) {
        // Die Schleifenzeile bleibt WOERTLICH: tv_producer_refresh_layouts.test.ts
        // pinnt sie, weil Quell- und Bindungspruefung nur am Save-Erfolg haengen
        // duerfen und nie an einer Nebensache — die Laeufe 29929470730 und
        // 29946386778 meldeten `sources.checked 0`, weil der kosmetische Refresh
        // sie blockierte. #5177 schrieb die Zeile um und stellte genau diesen
        // Pin rot (macOS-Job, nicht required -> Auto-Merge liess es durch).
        //
        // Der Ausstieg hier ist KEINE Nebensache, sondern eine Aussagegrenze:
        // unter Library-Drift stammt der Erwartungswert der Quellen aus dem
        // ausgecheckten Baum, dessen Uebereinstimmung mit TradingView die Drift
        // gerade offen laesst. Ausgewiesen wird das oben als
        // `sources.notJudgedReason`, nicht als stille 0.
        if (!driftGate.judgeSources) break;
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

    // Gated on saves ALONE. The cosmetic refresh above used to gate this block
    // too, so a single refresh timeout skipped the load-bearing verification
    // entirely (live runs 29929470730 and 29946386778, 2026-07-22; at the time
    // that meant `sources.checked 0` as well — source verification has since
    // moved ABOVE the refreshes, see the ordering comment there).
    if (report.save.failed.length === 0) {
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
      const partiallyRepairedChartUrls: string[] = [];
      let repairBindings = executionPlan.repairBindings;

      for (const layout of groupTargetsByLayout(config.verifyTargets, config.primaryChartUrl)) {
        if (!session.page.url().startsWith(layout.chartUrl)) {
          await gotoChart(session.page, layout.chartUrl);
        }
        // Captured before the targets run: it decides whether THIS layout was
        // mutated, and a failure inside the layout must not retroactively make
        // it look untouched.
        const mutatingLayout = repairBindings;

        // Im repair-only-Modus wird NUR angefasst, was der Vor-Mutations-
        // Snapshot als defekt gemeldet hat. Saubere Layouts bleiben unberuehrt --
        // ein Reparaturlauf darf kein zweiter Zerstoerer werden.
        if (executionPlan.mode === "repair-only" && !layoutsNeedingRepair.includes(layout.chartUrl)) {
          console.error(`[tv-trace] repair-skip-clean-layout ${layout.chartUrl}`);
          continue;
        }

        let layoutRepairedCleanly = true;
        // The targets that made this layout unclean, by name. The boolean above
        // says THAT the layout is partial; the alert a human reads has to say
        // WHICH script blocked it -- the 2026-08-22 drift alerts named the
        // effect ("bindings drifted") while the cause was one script whose
        // settings dialog never opens.
        const blockingTargets: string[] = [];

        for (const target of layout.targets) {
          let result: VerifyConsumerResult | null = null;
          let lastError = "unknown verification failure";
          // One entry per attempt, so the ARTIFACT alone separates a single
          // flake from N identical deterministic failures. The per-attempt
          // detail used to live only in the CI log; the bar is
          // preflight_retry_log.jsonl.
          const attempts: { attempt: number; durationMs: number; error: string }[] = [];
          for (let attempt = 1; attempt <= 2; attempt += 1) {
            const startedAt = Date.now();
            try {
              result = await verifyConsumerBindings(session, target, repairBindings, repairBindings);
              lastError = "";
              attempts.push({ attempt, durationMs: Date.now() - startedAt, error: "" });
              break;
            } catch (error) {
              lastError = String((error as Error)?.message ?? error);
              attempts.push({ attempt, durationMs: Date.now() - startedAt, error: lastError });
              if (attempt < 2) await gotoChart(session.page, layout.chartUrl).catch(() => undefined);
            }
          }
          if (result) report.bindings.consumers.push({ ...result, attempts });
          else {
            // Endgueltig gescheitert: die Seite steht noch im Fehlerzustand
            // (nach dem letzten Versuch folgt kein gotoChart mehr), also ist
            // JETZT der einzige Moment, in dem sich festhalten laesst, wie es
            // aussah. Ein Bild + die Legendengeometrie pro gescheitertem
            // Skript; ein gruener Lauf schreibt nichts.
            const evidence = await captureLegendFailureEvidence(
              session.page,
              target.scriptName,
              evidenceRunId,
            ).catch(() => null);
            if (evidence) {
              const evidencePath = writeLegendFailureEvidence(evidence);
              report.bindings.evidence.push(evidencePath);
              console.log(
                `::warning title=Settings never opened::${target.scriptName} — `
                + `evidence ${path.basename(evidencePath)}`
                + (evidence.aim ? `, click point hit: ${evidence.aim.topElement}` : ""),
              );
            }
            report.bindings.failed.push({
              target: target.scriptName,
              error: lastError,
              attempts,
              evidence: evidence?.screenshotPath ? path.basename(evidence.screenshotPath) : "",
            });
          }
          // Exactly the run's own success criterion, per target: report.ok is
          // gated on bindings.failed and bindings.mismatches. It deliberately
          // does NOT include result.ok, which also carries
          // unknownParentRuntimeError -- that signal is evidence only, because
          // the residual window after the repair still collects dead-parent
          // errors from the OTHER consumers this run has not repaired yet.
          // Abandoning on it would abandon every layout of a healthy rollout.
          if (!result || result.mismatches.length > 0) {
            layoutRepairedCleanly = false;
            blockingTargets.push(target.scriptName);
          }
        }

        if (!executionPlan.saveLayout || !mutatingLayout) continue;

        if (!layoutRepairedCleanly) {
          // Operator decision 2026-08-22: SAVE the partial repair instead of
          // discarding it. This reverses the rule that stood here, and the
          // reversal is the point -- see partiallyRepairedChartUrls above for
          // the measurement that killed the old premise ("not saving is an
          // exact, free rollback"). It holds for bindings and not for
          // instances, so abandoning threw away the repair and left the damage.
          //
          // Deliberately NOT changed: repair still stops here, so what gets
          // persisted stays a PREFIX of the rollout rather than an arbitrary
          // subset, and report.ok is still false through the target that
          // failed. No fall-through to a reload either -- the reload WAS the
          // rollback, and rolling back is exactly what we no longer want.
          partiallyRepairedChartUrls.push(layout.chartUrl);
          repairBindings = false;
          // Loud, not just a JSON field. This branch WRITES an incomplete
          // binding set onto the operator's traded chart -- a real degradation,
          // and the kind that used to look like success. It names the blocking
          // scripts so the reader does not have to open the run to learn which
          // one to fix.
          console.log(
            `::warning title=Partial layout repair saved::${layout.chartUrl} — `
            + `${blockingTargets.length} of ${layout.targets.length} targets stayed on defaults; `
            + `blocked by: ${blockingTargets.join(", ")}`,
          );
        }

        try {
          await saveChangedChartLayout(session.page);
          savedChartUrls.push(layout.chartUrl);
          report.mutations.layoutSaved = true;
        } catch (error) {
          // The save never confirmed, so what reached this layout is unknown.
          // Stop mutating rather than stack another layout on top of it; the
          // failure gates report.ok below. This is now the ONLY way a layout
          // ends up in abandonedChartUrls -- an incomplete repair is saved.
          abandonedChartUrls.push(layout.chartUrl);
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
        report.mutations.partiallyRepairedChartUrls = partiallyRepairedChartUrls;
        // A run that hit nothing must have saved every layout it planned to.
        // Without this a green report could still cover a strict subset -- the
        // failure this whole block exists to prevent. When something DID go
        // wrong, the layouts after it are unvisited on purpose (repair stops)
        // and report.ok is already false through the target that caused it.
        //
        // partiallyRepairedChartUrls joins this predicate for the same reason
        // abandonedChartUrls did: it marks the layout where the run stopped
        // widening. It does NOT mark an unsaved layout any more -- that one was
        // saved on purpose (operator decision 2026-08-22).
        //
        // Mode-aware since 2026-08-23. `planned` used to be
        // resolveLayoutSavePoints(config.verifyTargets, ...) -- the full layout
        // list regardless of mode -- while repair-only deliberately skips every
        // clean layout right above. The two disagreed exactly when the mode
        // worked: measured against the real config, planned=[vWgAWyfC,
        // hKHTmKhu, twh98JLB] against savedChartUrls=[vWgAWyfC] pushed
        // bindings.failed for the two layouts the run was RIGHT not to touch,
        // so a successful repair reported itself as failed (exit 1). Same
        // defect the 2026-08-23 ruling fixed for checkedConsumers; this is its
        // second site, and resolveExpectedLayoutSavePoints is its sibling.
        const planned = resolveExpectedLayoutSavePoints(
          config.verifyTargets,
          config.primaryChartUrl,
          executionPlan.mode,
          layoutsNeedingRepair,
        );
        const missed = planned.filter((chartUrl) => !savedChartUrls.includes(chartUrl));
        const nothingWentWrong = abandonedChartUrls.length === 0
          && partiallyRepairedChartUrls.length === 0
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
    // In the finally block so it is written even when the run dies mid-repair:
    // a crashed narrow run is exactly when a reader needs to know what it had
    // decided to leave alone.
    //
    // What lands, per mode (measured, not assumed): write and verify-only get
    // the FULL layout list in plannedChartUrls and an empty
    // skippedChartUrls -- they plan every layout and skip none. A repair-only
    // run that died BEFORE the pre-mutation read gets an empty
    // plannedChartUrls and every layout in skippedChartUrls, which is the
    // honest answer there: it touched nothing, no narrowing had been decided
    // yet.
    report.bindings.plannedChartUrls = resolveExpectedLayoutSavePoints(
      config.verifyTargets,
      config.primaryChartUrl,
      executionPlan.mode,
      layoutsNeedingRepair,
    );
    report.bindings.skippedChartUrls = resolveSkippedLayouts(
      config.verifyTargets,
      config.primaryChartUrl,
      executionPlan.mode,
      layoutsNeedingRepair,
    );
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
    // Operator decision 2026-08-03 (Finding 3): read-only runs compare too,
    // report-only. Read-only never took the `mode !== "verify-only"` branch
    // above, so outOfBandDrift is still the constructor's "has not run yet"
    // placeholder at this point. Its own normal verification loop just read
    // every verifyTarget's bindings (repairBindings/forceRebind are both
    // false for verify-only -- see resolveExecutionPlan) into
    // report.bindings.consumers, and report.tradingViewObserved.bindings
    // above is exactly that reading, reshaped to what compareAgainstBaseline
    // consumes. Reusing it here means a read-only run gets a real verdict
    // without paying for a second observeBindingsOnly pass -- there is
    // nothing "pre-mutation" to protect in a run that never mutates.
    //
    // report.ok is NOT gated by this verdict: the
    // `executionPlan.mode === "verify-only"` arm of the exemption below
    // short-circuits before report.outOfBandDrift.status is ever read on a
    // read-only run. This block exists to populate the published artifact
    // honestly, not to turn a read-only run red.
    if (executionPlan.mode === "verify-only") {
      report.outOfBandDrift = compareAgainstBaseline({
        observed: report.tradingViewObserved.bindings.map((consumer) => ({
          scriptName: consumer.scriptName,
          selections: consumer.selections.map((selection) => ({
            label: selection.label,
            actual: selection.actual,
          })),
        })),
        baseline: loadPublishedBaseline(baselinePath),
        expectedScriptNames: config.verifyTargets.map((target) => target.scriptName),
      });
      if (report.outOfBandDrift.status !== "clean") {
        console.warn(
          `[rollout] out-of-band drift (read-only, report-only) ${report.outOfBandDrift.status}: `
          + report.outOfBandDrift.reason,
        );
      }
    }
    report.durationSeconds = Math.round((Date.now() - started) / 100) / 10;
    // The END of the observation, as opposed to observedAt/generatedAt which are
    // both the start. Without it, "when did this run touch the chart?" is only
    // answerable from the CI log.
    report.completedAt = new Date().toISOString();
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
      // Extracted (2026-08-23 ruling) so repair-only's narrowed completeness
      // check -- "checked everything expected" means every consumer on the
      // layouts selectLayoutsNeedingRepair named, not report.bindings.
      // expectedConsumers, which is the whole config regardless of mode --
      // can be proven directly against synthetic inputs. write and
      // verify-only visit every layout, so this stays byte-identical to the
      // old `checkedConsumers === expectedConsumers && mismatches === 0`.
      && bindingsAreComplete({
        targets: config.verifyTargets,
        primaryChartUrl: config.primaryChartUrl,
        mode: executionPlan.mode,
        layoutsNeedingRepair,
        checkedConsumers: report.bindings.checkedConsumers,
        mismatches: report.bindings.mismatches,
      })
      // A second writer touched the managed layouts since the last CI run, or
      // the comparison could not be made. The save is NOT withheld -- that
      // would freeze the consumers on an old pinned library while the producer
      // moves on (operator decision 2026-08-01) -- so this field carries the
      // red on its own. Never rely on another clause to catch it: an
      // out-of-band binding change leaves sources.drifted at 0.
      //
      // Exempted for a read-only run, and ONLY because it writes nothing:
      // there is no second writer to attribute a difference to. It does still
      // MEASURE -- the finally block above compares its own verification
      // reading against the baseline and records a real clean/drifted/unknown
      // verdict, at no extra browser cost. That measurement is the point: a
      // read-only run also republishes the baseline, so without it the morning
      // cron would quietly absorb an operator's overnight write before any
      // mutating run ever looked. Report, do not gate.
      && (executionPlan.mode === "verify-only" || report.outOfBandDrift.status === "clean");
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

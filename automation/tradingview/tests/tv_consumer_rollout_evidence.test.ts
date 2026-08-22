import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import {
  bindingsAreComplete,
  buildRolloutProvenance,
  resolveExecutionPlan,
  resolveExpectedConsumerTargets,
  resolveExpectedLayoutSavePoints,
  resolveLibraryPublishObservation,
  resolveSkippedLayouts,
  sha256Bytes,
} from "../lib/tv_consumer_rollout_evidence.js";

test("verify-only produces an immutable, mutation-free execution plan", () => {
  const plan = resolveExecutionPlan(["--verify-only"], {});
  assert.deepEqual(plan, {
    mode: "verify-only",
    saveSources: false,
    refreshProducer: false,
    repairBindings: false,
    saveLayout: false,
  });
  assert.equal(Object.isFrozen(plan), true);
});

test("verify-only rejects every writing input before browser launch", () => {
  assert.throws(
    () => resolveExecutionPlan(["--verify-only"], { TV_FORCE_REBIND: "true" }),
    /conflicts with TV_FORCE_REBIND=true/,
  );
  assert.throws(
    () => resolveExecutionPlan(["--verify-only"], { TV_REFRESH_PRODUCER: "true" }),
    /conflicts with TV_REFRESH_PRODUCER=true/,
  );
  assert.throws(
    () => resolveExecutionPlan(["--verify-only"], { TV_CONSUMER_MAPPING_JSON: '[{"source":"x"}]' }),
    /conflicts with non-empty TV_CONSUMER_MAPPING_JSON/,
  );
  assert.equal(resolveExecutionPlan(["--verify-only"], { TV_CONSUMER_MAPPING_JSON: "[]" }).mode, "verify-only");
});

test("normal execution preserves coordinated refresh and rebind semantics", () => {
  assert.deepEqual(resolveExecutionPlan([], {}), {
    mode: "write",
    saveSources: true,
    refreshProducer: false,
    repairBindings: false,
    saveLayout: false,
  });
  assert.deepEqual(resolveExecutionPlan([], {
    TV_FORCE_REBIND: "true",
    TV_REFRESH_PRODUCER: "true",
  }), {
    mode: "write",
    saveSources: true,
    refreshProducer: true,
    repairBindings: true,
    saveLayout: true,
  });
  assert.throws(
    () => resolveExecutionPlan([], { TV_REFRESH_PRODUCER: "true" }),
    /requires TV_FORCE_REBIND=true/,
  );
});

test("provenance hashes exact config bytes and fails closed on dirty inputs", () => {
  const repoRoot = fs.mkdtempSync(path.join(os.tmpdir(), "tv-rollout-evidence-"));
  try {
    execFileSync("git", ["init", "-q"], { cwd: repoRoot });
    execFileSync("git", ["config", "user.email", "test@example.invalid"], { cwd: repoRoot });
    execFileSync("git", ["config", "user.name", "Test"], { cwd: repoRoot });
    fs.mkdirSync(path.join(repoRoot, "config"), { recursive: true });
    fs.writeFileSync(path.join(repoRoot, "config/rollout.json"), '{"saveTargets":[]}\n');
    fs.writeFileSync(path.join(repoRoot, "config/product.json"), '{"manifestVersion":3}\n');
    fs.writeFileSync(
      path.join(repoRoot, "config/release.json"),
      '{"library":{"expectedVersion":170,"publishedVersion":170,"publishStatus":"published"}}\n',
    );
    fs.writeFileSync(path.join(repoRoot, "consumer.pine"), "//@version=6\r\nindicator(\"Consumer\")\r\n");
    execFileSync("git", ["add", "."], { cwd: repoRoot });
    execFileSync("git", ["commit", "-qm", "fixture"], { cwd: repoRoot });

    const build = () => buildRolloutProvenance({
      repoRoot,
      configPath: path.join(repoRoot, "config/rollout.json"),
      productManifestPath: path.join(repoRoot, "config/product.json"),
      libraryReleaseManifestPath: path.join(repoRoot, "config/release.json"),
      sourceTargets: [{ source: "consumer.pine", scriptName: "Consumer" }],
      bindingTargets: [{ source: "consumer.pine", scriptName: "Consumer", labels: ["BUS Ready"] }],
      producerName: "Producer",
    });

    const clean = build();
    assert.equal(clean.inputsMatchCommit, true);
    assert.equal(clean.rolloutConfigSha256, sha256Bytes('{"saveTargets":[]}\n'));
    assert.equal(clean.productManifestVersion, 3);
    assert.equal(clean.libraryReleaseVersion, 170);
    assert.equal(clean.repositoryExpected.libraryRelease.matches, true);
    assert.equal(clean.repositoryExpected.sources[0]?.repoRelativePath, "consumer.pine");
    assert.equal(clean.repositoryExpected.bindings[0]?.labels[0], "BUS Ready");

    fs.appendFileSync(path.join(repoRoot, "consumer.pine"), "// dirty\n");
    assert.equal(build().inputsMatchCommit, false);
  } finally {
    fs.rmSync(repoRoot, { recursive: true, force: true });
  }
});

test("unpublished or mismatched library state remains explicit fail-closed evidence", () => {
  const repoRoot = fs.mkdtempSync(path.join(os.tmpdir(), "tv-rollout-release-"));
  try {
    execFileSync("git", ["init", "-q"], { cwd: repoRoot });
    execFileSync("git", ["config", "user.email", "test@example.invalid"], { cwd: repoRoot });
    execFileSync("git", ["config", "user.name", "Test"], { cwd: repoRoot });
    fs.writeFileSync(path.join(repoRoot, "rollout.json"), "{}\n");
    fs.writeFileSync(path.join(repoRoot, "product.json"), '{"manifestVersion":3}\n');
    fs.writeFileSync(
      path.join(repoRoot, "release.json"),
      '{"library":{"expectedVersion":171,"publishedVersion":170,"publishStatus":"candidate"}}\n',
    );
    fs.writeFileSync(path.join(repoRoot, "consumer.pine"), "//@version=6\nindicator(\"Consumer\")\n");
    execFileSync("git", ["add", "."], { cwd: repoRoot });
    execFileSync("git", ["commit", "-qm", "fixture"], { cwd: repoRoot });
    const evidence = buildRolloutProvenance({
      repoRoot,
      configPath: path.join(repoRoot, "rollout.json"),
      productManifestPath: path.join(repoRoot, "product.json"),
      libraryReleaseManifestPath: path.join(repoRoot, "release.json"),
      sourceTargets: [{ source: "consumer.pine", scriptName: "Consumer" }],
      bindingTargets: [],
      producerName: "Producer",
    });
    assert.equal(evidence.repositoryExpected.libraryRelease.matches, false);
  } finally {
    fs.rmSync(repoRoot, { recursive: true, force: true });
  }
});

test("a manifest that agrees with itself is not evidence that the library is published", () => {
  // 2026-08-01: a chained rollout ran on a pre-refresh tree and reported
  // repositoryExpected.libraryRelease.matches === true at version 180 while
  // main was already on 182. It could not have reported anything else --
  // expectedVersion and publishedVersion are two fields of the SAME manifest
  // file in the SAME checkout, so that check passes for any internally
  // consistent tree, stale or not. The observation below is the only field in
  // the report read from outside the checkout.
  const stale = resolveLibraryPublishObservation({
    scriptName: "smc_micro_profiles_generated",
    manifestPublishedVersion: 180,
    observedVersion: 182,
  });
  assert.equal(stale.verdict, "drift");
  assert.equal(stale.observedVersion, 182);

  const current = resolveLibraryPublishObservation({
    scriptName: "smc_micro_profiles_generated",
    manifestPublishedVersion: 182,
    observedVersion: 182,
  });
  assert.equal(current.verdict, "match");

  // The other direction is drift too: a manifest claiming a version the facade
  // does not list yet means the consumers' import pins point at nothing.
  const unpublished = resolveLibraryPublishObservation({
    scriptName: "smc_micro_profiles_generated",
    manifestPublishedVersion: 183,
    observedVersion: 182,
  });
  assert.equal(unpublished.verdict, "drift");
});

test("an unreadable facade stays unknown instead of being rounded to either verdict", () => {
  // fetchPublishedLibraryVersionViaFacade returns null for an unreachable
  // listing AND for a library missing from it. Neither is evidence about the
  // library, so neither may become "match" (which would restore the vacuous
  // green this replaces) or "drift" (which would fail every run during a
  // facade outage). build_pine_library_version_snapshot.ts already draws this
  // distinction; it is kept here rather than re-decided.
  const observation = resolveLibraryPublishObservation({
    scriptName: "smc_micro_profiles_generated",
    manifestPublishedVersion: 182,
    observedVersion: null,
  });
  assert.equal(observation.verdict, "unknown");
  assert.notEqual(observation.verdict, "match");
  assert.equal(observation.observedVersion, null);
});

// ---------------------------------------------------------------------------
// 2026-08-23 ruling: Task 3's repair-only skip (scripts/tv_batch_consumer_
// rollout.ts) leaves report.bindings.checkedConsumers short of the constant,
// mode-independent report.bindings.expectedConsumers the moment it correctly
// skips a clean layout -- so a fully successful narrow repair could never
// reach report.ok === true. resolveExpectedConsumerTargets and
// bindingsAreComplete are the fix, extracted as pure functions specifically
// so this reachability claim can be proven directly: main() itself needs a
// live TradingView session and cannot be unit-tested.
// ---------------------------------------------------------------------------

const REPAIR_TARGETS = [
  { scriptName: "SMC Decision Board", chartUrl: "https://tv/chart/A/" },
  { scriptName: "SMC Setup Check", chartUrl: "https://tv/chart/A/" },
  { scriptName: "SMC Hold Manager", chartUrl: "https://tv/chart/B/" },
];

test("repair-only narrows the expected set to only the layouts needing repair", () => {
  // Layout B never showed a mismatch, so the run only ever opens layout A.
  const expected = resolveExpectedConsumerTargets(
    REPAIR_TARGETS,
    "https://tv/chart/A/",
    "repair-only",
    ["https://tv/chart/A/"],
  );
  assert.deepEqual(expected.map((t) => t.scriptName), ["SMC Decision Board", "SMC Setup Check"]);
});

test("write and verify-only ignore layoutsNeedingRepair entirely: expected is always every target", () => {
  for (const mode of ["write", "verify-only"] as const) {
    // Even though layoutsNeedingRepair (mode-irrelevant for these two) names
    // only layout A, the expected set must still be the FULL config -- these
    // modes visit every layout, unconditionally.
    const expected = resolveExpectedConsumerTargets(
      REPAIR_TARGETS,
      "https://tv/chart/A/",
      mode,
      ["https://tv/chart/A/"],
    );
    assert.equal(expected.length, REPAIR_TARGETS.length);
  }
});

test("repair-only CAN reach ok:true after skipping a clean layout", () => {
  // Layout B was clean in the pre-mutation read and therefore never visited;
  // only A's two targets were checked, both clean. This is exactly the
  // successful-narrow-repair case the 2026-08-22/23 finding said could never
  // reach report.ok === true before this fix.
  assert.equal(
    bindingsAreComplete({
      targets: REPAIR_TARGETS,
      primaryChartUrl: "https://tv/chart/A/",
      mode: "repair-only",
      layoutsNeedingRepair: ["https://tv/chart/A/"],
      checkedConsumers: 2,
      mismatches: 0,
    }),
    true,
  );
});

test("repair-only does NOT reach ok:true when a visited target kept a mismatch", () => {
  // Same skip as above (layout B untouched, 2 of 3 targets checked), but one
  // of the VISITED targets (on layout A, the one the run repaired) still
  // reports a mismatch. Completeness alone must not paper over a real defect.
  assert.equal(
    bindingsAreComplete({
      targets: REPAIR_TARGETS,
      primaryChartUrl: "https://tv/chart/A/",
      mode: "repair-only",
      layoutsNeedingRepair: ["https://tv/chart/A/"],
      checkedConsumers: 2,
      mismatches: 1,
    }),
    false,
  );
});

test("write and verify-only are unchanged: incomplete against the FULL target list still fails", () => {
  // Same checkedConsumers=2/mismatches=0 as the repair-only success case
  // above, but under write/verify-only that is only 2 of 3 EXPECTED targets
  // -- these modes never narrow, so this must stay incomplete exactly as it
  // did before repair-only existed.
  for (const mode of ["write", "verify-only"] as const) {
    assert.equal(
      bindingsAreComplete({
        targets: REPAIR_TARGETS,
        primaryChartUrl: "https://tv/chart/A/",
        mode,
        layoutsNeedingRepair: ["https://tv/chart/A/"],
        checkedConsumers: 2,
        mismatches: 0,
      }),
      false,
    );
    // Checking every target with zero mismatches still reaches ok, unchanged.
    assert.equal(
      bindingsAreComplete({
        targets: REPAIR_TARGETS,
        primaryChartUrl: "https://tv/chart/A/",
        mode,
        layoutsNeedingRepair: ["https://tv/chart/A/"],
        checkedConsumers: REPAIR_TARGETS.length,
        mismatches: 0,
      }),
      true,
    );
  }
});

// ---------------------------------------------------------------------------
// The SECOND completeness check, found by the whole-branch review on
// 2026-08-23. tv_batch_consumer_rollout.ts has a "layouts never saved" clause
// that compared savedChartUrls against the full, mode-independent layout list
// -- the same defect the block above fixed for checkedConsumers, at a second
// site 100 lines away. Measured against the real config: planned=[vWgAWyfC,
// hKHTmKhu, twh98JLB], savedChartUrls=[vWgAWyfC] => missed=[hKHTmKhu,
// twh98JLB] => bindings.failed => report.ok=false => exit 1, on a repair-only
// run that had done exactly the right thing.
// ---------------------------------------------------------------------------

// Three targets across two layouts, matching the real config's shape: the
// primary layout carries two consumers, a second layout carries one.
const SAVE_POINT_TARGETS = [
  { scriptName: "SMC Decision Board", chartUrl: "https://tv/chart/A/" },
  { scriptName: "SMC Setup Check", chartUrl: "https://tv/chart/A/" },
  { scriptName: "SMC Hold Manager", chartUrl: "https://tv/chart/B/" },
];

test("repair-only narrows the expected SAVE points to the layouts needing repair", () => {
  assert.deepEqual(
    resolveExpectedLayoutSavePoints(
      SAVE_POINT_TARGETS,
      "https://tv/chart/A/",
      "repair-only",
      ["https://tv/chart/A/"],
    ),
    ["https://tv/chart/A/"],
  );
});

test("a narrow repair that saved every layout it opened reports NOTHING missed", () => {
  // The exact reproduction of the finding, in the shape the rollout computes
  // it: planned minus savedChartUrls must be empty for a run that repaired
  // layout A and correctly never opened layout B.
  const planned = resolveExpectedLayoutSavePoints(
    SAVE_POINT_TARGETS,
    "https://tv/chart/A/",
    "repair-only",
    ["https://tv/chart/A/"],
  );
  const savedChartUrls = ["https://tv/chart/A/"];
  assert.deepEqual(planned.filter((url) => !savedChartUrls.includes(url)), []);

  // ...and the pre-fix expression, kept here as the negative control: the
  // unnarrowed list is what pushed bindings.failed on a healthy run.
  const unnarrowed = resolveExpectedLayoutSavePoints(
    SAVE_POINT_TARGETS,
    "https://tv/chart/A/",
    "write",
    ["https://tv/chart/A/"],
  );
  assert.deepEqual(
    unnarrowed.filter((url) => !savedChartUrls.includes(url)),
    ["https://tv/chart/B/"],
  );
});

test("a narrow repair that failed to save a layout it DID open still reports it missed", () => {
  // Narrowing must not swallow a real failure: layout A needed repair, was
  // opened, and its save never confirmed.
  const planned = resolveExpectedLayoutSavePoints(
    SAVE_POINT_TARGETS,
    "https://tv/chart/A/",
    "repair-only",
    ["https://tv/chart/A/", "https://tv/chart/B/"],
  );
  assert.deepEqual(
    planned.filter((url) => !["https://tv/chart/B/"].includes(url)),
    ["https://tv/chart/A/"],
  );
});

test("write and verify-only save points are unchanged by layoutsNeedingRepair", () => {
  const full = ["https://tv/chart/A/", "https://tv/chart/B/"];
  for (const mode of ["write", "verify-only"] as const) {
    // Even with layoutsNeedingRepair naming only A -- and even with it empty,
    // which is what these two modes actually pass -- the expected save points
    // stay the full list, byte-identical to resolveLayoutSavePoints.
    assert.deepEqual(
      resolveExpectedLayoutSavePoints(SAVE_POINT_TARGETS, "https://tv/chart/A/", mode, ["https://tv/chart/A/"]),
      full,
    );
    assert.deepEqual(
      resolveExpectedLayoutSavePoints(SAVE_POINT_TARGETS, "https://tv/chart/A/", mode, []),
      full,
    );
  }
});

// ---------------------------------------------------------------------------
// I5: the artifact has to say what the run left out.
// ---------------------------------------------------------------------------

test("the skipped layouts are named, so a narrow run is distinguishable from a blind one", () => {
  // checkedConsumers 2 / expectedConsumers 3 is ambiguous on its own: two
  // targets checked because layout B was deliberately skipped, or because
  // layout B could not be read? This is the field that answers it.
  assert.deepEqual(
    resolveSkippedLayouts(SAVE_POINT_TARGETS, "https://tv/chart/A/", "repair-only", ["https://tv/chart/A/"]),
    ["https://tv/chart/B/"],
  );
  // A repair-only run that found NOTHING to repair skipped everything -- and
  // says so, rather than looking like a run that narrowed to nothing by
  // accident.
  assert.deepEqual(
    resolveSkippedLayouts(SAVE_POINT_TARGETS, "https://tv/chart/A/", "repair-only", []),
    ["https://tv/chart/A/", "https://tv/chart/B/"],
  );
});

test("write and verify-only skip nothing, whatever layoutsNeedingRepair says", () => {
  for (const mode of ["write", "verify-only"] as const) {
    assert.deepEqual(
      resolveSkippedLayouts(SAVE_POINT_TARGETS, "https://tv/chart/A/", mode, ["https://tv/chart/A/"]),
      [],
    );
  }
});

test("narrowedTo and skipped partition the full layout list, in every mode", () => {
  // The two artifact fields must be readable together without a third source:
  // for repair-only they add up to the full plan, and for the other modes the
  // narrowing is provably absent rather than merely unset.
  const full = resolveExpectedLayoutSavePoints(SAVE_POINT_TARGETS, "https://tv/chart/A/", "write", []);
  for (const mode of ["write", "verify-only", "repair-only"] as const) {
    for (const needing of [[], ["https://tv/chart/A/"], ["https://tv/chart/A/", "https://tv/chart/B/"]]) {
      const narrowed = resolveExpectedLayoutSavePoints(SAVE_POINT_TARGETS, "https://tv/chart/A/", mode, needing);
      const skipped = resolveSkippedLayouts(SAVE_POINT_TARGETS, "https://tv/chart/A/", mode, needing);
      assert.deepEqual([...narrowed, ...skipped].sort(), [...full].sort());
      assert.deepEqual(narrowed.filter((url) => skipped.includes(url)), []);
    }
  }
});

test("the rollout wires the narrowing into BOTH completeness gates and the artifact", () => {
  // The pure functions above can only prove the arithmetic. These pins prove
  // the rollout actually calls them -- the C2 defect was precisely that one of
  // the two gates had been left on the unnarrowed list while the other was
  // fixed, and no single-task review could see both at once.
  const rollout = fs.readFileSync(
    path.join(import.meta.dirname, "..", "..", "..", "scripts", "tv_batch_consumer_rollout.ts"),
    "utf-8",
  );
  assert.ok(
    rollout.includes("const planned = resolveExpectedLayoutSavePoints("),
    "the layouts-never-saved gate must use the mode-aware save points",
  );
  assert.ok(
    !rollout.includes("resolveLayoutSavePoints(config.verifyTargets, config.primaryChartUrl)"),
    "the unnarrowed save-point call is the C2 defect and must not come back",
  );
  assert.ok(rollout.includes("report.bindings.narrowedToChartUrls = resolveExpectedLayoutSavePoints("));
  assert.ok(rollout.includes("report.bindings.skippedChartUrls = resolveSkippedLayouts("));
});

test("only a known drift gates report.ok; unknown does not", () => {
  // The rollout throws on drift before the first write, but report.ok must
  // encode the condition itself rather than rely on that control flow staying
  // where it is. Pinned here as the exact expression the rollout uses.
  const rollout = fs.readFileSync(
    path.join(import.meta.dirname, "..", "..", "..", "scripts", "tv_batch_consumer_rollout.ts"),
    "utf-8",
  );
  assert.ok(rollout.includes('report.tradingViewObserved.libraryRelease.verdict !== "drift"'));
  // Probed before anything is written, not after.
  const probeAt = rollout.indexOf("fetchPublishedLibraryVersionViaFacade");
  const firstSaveAt = rollout.indexOf("saveConsumerSource(session, target)");
  assert.ok(probeAt > 0 && firstSaveAt > 0 && probeAt < firstSaveAt);
});

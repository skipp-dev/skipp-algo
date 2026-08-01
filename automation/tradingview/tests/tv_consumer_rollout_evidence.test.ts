import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import {
  buildRolloutProvenance,
  resolveExecutionPlan,
  resolveLibraryPublishObservation,
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

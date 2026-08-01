import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { resolveConsumerRefreshTargets } from "../lib/tv_shared.js";

const _dir = path.dirname(fileURLToPath(import.meta.url));
const ROLLOUT = path.join(_dir, "..", "..", "..", "scripts", "tv_batch_consumer_rollout.ts");

// Saving a consumer's SOURCE does not change the instance already applied to a
// layout — TradingView keeps it on the version it was added with. That is why
// the producer is re-applied after a save, and until 2026-08-01 the consumer
// never was. The rule the helper encodes stands on its own: an instance whose
// source this run saved may be a version behind, so it has to be re-applied.
//
// It is NOT, however, what broke runs 30694013096 / 30696257671 / 30698519321.
// Run 30700161400 carried this fix and still failed on CTX SessionMssBull,
// with `script-refresh-instance-counts SMC Context Overlay:0->0` — there was no
// prior instance to be stale, and the freshly inserted one missed the row too.
// The cause of THAT is under investigation; see formatMissingSourceRowEvidence
// in scripts/tv_verify_consumer_bindings.ts. Do not read these tests as
// evidence for a diagnosis they never established.

const R4 = {
  producerName: "SMC Context Bus",
  primaryChartUrl: "https://www.tradingview.com/chart/Jb2Vp6xs/",
  saveTargets: [
    { scriptName: "SMC Context Bus" },
    { scriptName: "SMC Context Overlay" },
  ],
  verifyTargets: [
    {
      scriptName: "SMC Context Overlay",
      chartUrl: "https://www.tradingview.com/chart/Jb2Vp6xs/",
    },
  ],
};

test("a consumer whose source was just saved is re-applied", () => {
  const targets = resolveConsumerRefreshTargets(R4);

  assert.deepEqual(targets, [
    {
      scriptName: "SMC Context Overlay",
      chartUrl: "https://www.tradingview.com/chart/Jb2Vp6xs/",
    },
  ]);
});

test("the producer is not returned — it has its own refresh pass", () => {
  const targets = resolveConsumerRefreshTargets(R4);

  assert.equal(
    targets.some((t) => t.scriptName === "SMC Context Bus"),
    false,
    "refreshing the producer twice would drop the consumer bindings again",
  );
});

test("a consumer whose source was NOT saved is left alone", () => {
  // Its instance cannot have gained an input, so re-applying it would drop
  // healthy bindings for nothing.
  const targets = resolveConsumerRefreshTargets({
    ...R4,
    saveTargets: [{ scriptName: "SMC Context Bus" }],
  });

  assert.deepEqual(targets, []);
});

test("a verify target without its own chartUrl falls back to the primary layout", () => {
  const targets = resolveConsumerRefreshTargets({
    ...R4,
    verifyTargets: [{ scriptName: "SMC Context Overlay" }],
  });

  assert.deepEqual(targets, [
    {
      scriptName: "SMC Context Overlay",
      chartUrl: "https://www.tradingview.com/chart/Jb2Vp6xs/",
    },
  ]);
});

test("the same consumer on two layouts is refreshed on both, once each", () => {
  const targets = resolveConsumerRefreshTargets({
    ...R4,
    verifyTargets: [
      { scriptName: "SMC Context Overlay", chartUrl: "https://www.tradingview.com/chart/AAA/" },
      { scriptName: "SMC Context Overlay", chartUrl: "https://www.tradingview.com/chart/BBB/" },
      { scriptName: "SMC Context Overlay", chartUrl: "https://www.tradingview.com/chart/AAA/" },
    ],
  });

  assert.deepEqual(targets, [
    { scriptName: "SMC Context Overlay", chartUrl: "https://www.tradingview.com/chart/AAA/" },
    { scriptName: "SMC Context Overlay", chartUrl: "https://www.tradingview.com/chart/BBB/" },
  ]);
});

test("saving nothing refreshes nothing", () => {
  // A verify-only run saves no source, so no instance can have gone stale
  // through this path.
  assert.deepEqual(resolveConsumerRefreshTargets({ ...R4, saveTargets: [] }), []);
});

test("the rollout actually calls it, in the binding-repair path", () => {
  // Found by falsifying the tests above: deleting the CALL SITE left all six
  // of them green, because they pin the helper and not its wiring. A helper
  // nothing invokes is exactly the "green without observation" shape this
  // whole fix exists to remove.
  const source = fs.readFileSync(ROLLOUT, "utf-8");

  assert.match(
    source,
    /resolveConsumerRefreshTargets\(config\)/,
    "the rollout must call resolveConsumerRefreshTargets",
  );
  assert.match(
    source,
    /executionPlan\.repairBindings\)\s*\{[\s\S]*?resolveConsumerRefreshTargets\(config\)/,
    "the call must sit in the repairBindings path — a refresh without the "
      + "following repair leaves the consumer unbound",
  );
  assert.match(
    source,
    /resolveConsumerRefreshTargets\(config\)[\s\S]*?refreshChartScriptInstance\(\s*session\.page,\s*consumer\.scriptName/,
    "each resolved consumer must actually be re-applied",
  );
});

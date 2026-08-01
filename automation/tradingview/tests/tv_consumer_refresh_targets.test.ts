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
// the producer is re-applied after a save. Until 2026-08-01 the consumer never
// was, so a consumer whose own source GAINED an input kept a stale instance:
// the new rows simply do not exist in its settings dialog and the rebind dies
// with "Source combobox not found". Runs 30694013096, 30696257671, 30698519321
// all failed that way on CTX SessionMssBull.

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

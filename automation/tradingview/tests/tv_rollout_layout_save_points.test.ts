import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { groupTargetsByLayout, resolveLayoutSavePoints } from "../lib/tv_consumer_rollout_evidence.js";

// The rollout rebinds every consumer, then saved the chart layout ONCE — on
// whichever page the loop happened to end on. With targets spread over two
// charts that persisted only the last one, and because `gotoChart` is a hard
// `page.goto`, the rebinds on the layout being left were discarded by the
// reload before any save could reach them.
//
// The run still reported ok:true / 9-of-9 / mismatches:0, because every
// consumer was read back in the SAME session that wrote it. That is the
// 2026-07-25 incident the save was added to prevent, one layout deeper.

const _dir = path.dirname(fileURLToPath(import.meta.url));
const CONFIG = path.join(_dir, "..", "config", "consumer-rollout.json");

const PRIMARY = "https://primary/";
const SECOND = "https://second/";

test("a single-layout rollout saves once", () => {
  assert.deepEqual(
    resolveLayoutSavePoints([{}, {}, {}], PRIMARY),
    [PRIMARY],
  );
});

test("every layout the run touches gets a save point", () => {
  assert.deepEqual(
    resolveLayoutSavePoints([{}, {}, { chartUrl: SECOND }, { chartUrl: SECOND }], PRIMARY),
    [PRIMARY, SECOND],
  );
});

test("returning to a layout saves it again", () => {
  // The reload on the way back discarded nothing only because the first visit
  // was saved; the second visit produces new unsaved state of its own.
  assert.deepEqual(
    resolveLayoutSavePoints([{}, { chartUrl: SECOND }, {}], PRIMARY),
    [PRIMARY, SECOND, PRIMARY],
  );
});

test("an empty target list has nothing to save", () => {
  assert.deepEqual(resolveLayoutSavePoints([], PRIMARY), []);
});

test("the live config needs more than one save point", () => {
  // The regression guard: the shipped config spreads consumers over two charts,
  // with the primary operator chart FIRST — so a single trailing save persists
  // the secondary layout and silently drops the seven consumers on the chart
  // the operator actually trades from.
  const config = JSON.parse(fs.readFileSync(CONFIG, "utf-8")) as {
    primaryChartUrl: string;
    verifyTargets: Array<{ chartUrl?: string }>;
  };
  const points = resolveLayoutSavePoints(config.verifyTargets, config.primaryChartUrl);

  assert.ok(points.length >= 2, `expected multiple layouts, got ${JSON.stringify(points)}`);
  assert.equal(points[0], config.primaryChartUrl, "the primary operator chart is visited first");
  assert.ok(
    points.includes(config.primaryChartUrl),
    "the primary chart must be among the layouts that get saved",
  );
  // Every distinct layout in the config must be covered.
  const distinct = new Set(config.verifyTargets.map((t) => t.chartUrl ?? config.primaryChartUrl));
  for (const chartUrl of distinct) {
    assert.ok(points.includes(chartUrl), `no save point for ${chartUrl}`);
  }
});

// --- the layout as the atomic unit -----------------------------------------
//
// Saving at every boundary stops the run from dropping whole layouts, but on
// its own it still persists a layout whose repair only partly succeeded: save
// consumer 1-4, fail on 5, and the operator's chart is left half rebound.
//
// The layout is the unit that can be committed or discarded as a whole -- one
// save persists every rebind on it, one reload discards every rebind on it --
// so the rollout decides per GROUP, not per target. Grouping is what makes
// that unit addressable.

test("targets are grouped into the layouts the run visits, in order", () => {
  assert.deepEqual(
    groupTargetsByLayout(
      [{ id: "a" }, { id: "b" }, { id: "c", chartUrl: SECOND }],
      PRIMARY,
    ),
    [
      // Targets are grouped, not rewritten: an explicit chartUrl stays on the
      // target, and a target that inherits the primary chart is not annotated.
      { chartUrl: PRIMARY, targets: [{ id: "a" }, { id: "b" }] },
      { chartUrl: SECOND, targets: [{ id: "c", chartUrl: SECOND }] },
    ],
  );
});

test("a layout the run returns to is its own group", () => {
  // It has to be saved again: the reload on the way back discarded nothing only
  // because the first visit was already persisted, and the second visit
  // produces new unsaved state of its own.
  assert.deepEqual(
    groupTargetsByLayout([{ id: "a" }, { id: "b", chartUrl: SECOND }, { id: "c" }], PRIMARY).map(
      (group) => group.chartUrl,
    ),
    [PRIMARY, SECOND, PRIMARY],
  );
});

test("no targets means no layouts to act on", () => {
  assert.deepEqual(groupTargetsByLayout([], PRIMARY), []);
});

test("grouping accounts for every target exactly once", () => {
  const targets = [{ id: "a" }, { id: "b", chartUrl: SECOND }, { id: "c", chartUrl: SECOND }, { id: "d" }];
  const grouped = groupTargetsByLayout(targets, PRIMARY).flatMap((group) => group.targets);
  // A target silently dropped here would be a consumer the rollout never
  // rebinds while still reporting on the layouts it visited.
  assert.deepEqual(grouped, targets);
});

test("the live config puts the traded chart in the first group", () => {
  // The prefix property is only worth having because of this ordering. Repair
  // stops at the first layout that could not be fully repaired, so what is
  // persisted is always a complete prefix of the rollout. With the primary
  // operator chart FIRST that means a late failure leaves the traded chart
  // repaired and the rest untouched — never the reverse.
  const config = JSON.parse(fs.readFileSync(CONFIG, "utf-8")) as {
    primaryChartUrl: string;
    verifyTargets: Array<{ chartUrl?: string; scriptName: string }>;
  };
  const groups = groupTargetsByLayout(config.verifyTargets, config.primaryChartUrl);

  assert.ok(groups.length >= 2, `expected multiple layouts, got ${groups.length}`);
  assert.equal(groups[0]?.chartUrl, config.primaryChartUrl);
  assert.ok(
    (groups[0]?.targets.length ?? 0) > 1,
    "the primary chart carries several consumers, which is why partial persistence on it matters",
  );
});

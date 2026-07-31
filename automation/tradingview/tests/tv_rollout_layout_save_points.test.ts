import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { resolveLayoutSavePoints } from "../lib/tv_consumer_rollout_evidence.js";

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

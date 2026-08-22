import assert from "node:assert/strict";
import { test } from "node:test";

import { selectLegendNeighbourhood } from "../lib/tv_shared.js";

// 2026-08-22: diagnosing why `SMC Long-Dip Alerts` opened its NEIGHBOUR's
// settings took hours, because nothing recorded WHERE the legend rows actually
// were. The failure evidence now carries the geometry, and this is its pure
// half: which rows are worth writing down. The target alone is not enough —
// the whole point is comparing it against what sits directly above and below,
// since that is what a mis-aimed click hits.
//
// Rows arrive in DOM order, which is NOT visual order; the neighbourhood is
// defined by vertical position.

const row = (text: string, y: number, extra: Partial<{ x: number; width: number; height: number }> = {}) => ({
  text,
  box: { x: extra.x ?? 0, y, width: extra.width ?? 200, height: extra.height ?? 20 },
});

const legend = [
  row("SMC Long-Dip Dashboard · 12.0", 100),
  row("SMC Long-Dip Strategy · 70.0", 120),
  row("SMC Long-Dip Alerts · 69.0", 140),
  row("SMC Setup Check · 8.0", 160),
  row("SMC Breakout Overlay · 6.0", 180),
];

test("the target and both its vertical neighbours are selected", () => {
  const picked = selectLegendNeighbourhood(legend, "SMC Long-Dip Alerts");
  assert.deepEqual(
    picked.map((entry) => entry.text),
    ["SMC Long-Dip Strategy · 70.0", "SMC Long-Dip Alerts · 69.0", "SMC Setup Check · 8.0"],
  );
});

test("rows are ordered by position, not by the order they were found", () => {
  const shuffled = [legend[4], legend[0], legend[3], legend[2], legend[1]];
  const picked = selectLegendNeighbourhood(shuffled, "SMC Long-Dip Alerts");
  assert.deepEqual(
    picked.map((entry) => entry.box.y),
    [120, 140, 160],
  );
});

test("a target at the top or bottom yields the one neighbour it has", () => {
  assert.deepEqual(
    selectLegendNeighbourhood(legend, "SMC Long-Dip Dashboard").map((entry) => entry.box.y),
    [100, 120],
  );
  assert.deepEqual(
    selectLegendNeighbourhood(legend, "SMC Breakout Overlay").map((entry) => entry.box.y),
    [160, 180],
  );
});

test("a prefix of another script name does not match it", () => {
  // "SMC Long-Dip" is a prefix of four real script names; matching on a bare
  // startsWith would make the neighbourhood meaningless.
  const picked = selectLegendNeighbourhood(legend, "SMC Long-Dip");
  assert.deepEqual(picked, [], "a partial name must select nothing, not the first row that starts with it");
});

test("the version chip is not part of the name", () => {
  // TradingView appends "· <version>" to the legend text; the caller passes the
  // bare script name and must still find its row.
  const picked = selectLegendNeighbourhood([row("SMC Setup Check · 8.0", 10)], "SMC Setup Check");
  assert.equal(picked.length, 1);
});

test("an absent target selects nothing rather than guessing", () => {
  assert.deepEqual(selectLegendNeighbourhood(legend, "SMC Hold Manager"), []);
});

test("an empty legend is not an error", () => {
  assert.deepEqual(selectLegendNeighbourhood([], "SMC Setup Check"), []);
});

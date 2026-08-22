import assert from "node:assert/strict";
import { test } from "node:test";

import {
  legendBoxIsTooSmallToClick,
  resolveLegendDoubleClickPoint,
} from "../lib/tv_shared.js";

// 2026-08-22, runs 758 and 771 on the primary rollout chart: every attempt to
// open `SMC Long-Dip Alerts` opened the settings dialog of `SMC Setup Check` or
// `SMC Breakout Overlay` — its two neighbours in the rollout order — and
// targeting Setup Check opened Long-Dip Alerts. Eight identity-mismatch traces
// say it directly (`<target> != <dialog actually visible>`), and the failure
// predates that run's producer refresh by twelve minutes, so the refresh
// clobber is NOT its cause.
//
// The click point was computed with fixed insets and never clamped to the
// element. For a clipped or partially scrolled row — which reports exactly such
// a box — the point landed outside the row, and page.mouse.dblclick takes raw
// coordinates with no actionability check, so it hit the row next to it.
//
// These are the pure arithmetic. The DOM hit-test that now guards the click is
// Playwright-against-TradingView and is proven only by the next CI run — stated
// so nobody over-reads this file.

const boxes = [
  { name: "a normal legend row", x: 100, y: 200, width: 200, height: 20 },
  { name: "a short row", x: 0, y: 0, width: 120, height: 14 },
  { name: "a narrow row", x: 10, y: 10, width: 40, height: 12 },
  // The three that the unclamped formula escaped:
  { name: "a clipped sliver", x: 0, y: 0, width: 10, height: 4 },
  { name: "a one-line-tall row", x: 5, y: 5, width: 60, height: 5 },
  { name: "a very narrow row", x: 0, y: 0, width: 14, height: 18 },
];

for (const box of boxes) {
  test(`the double-click point stays inside ${box.name}`, () => {
    const point = resolveLegendDoubleClickPoint(box);
    assert.ok(
      point.x >= box.x && point.x <= box.x + box.width,
      `x ${point.x} escaped [${box.x}, ${box.x + box.width}] — that is the neighbouring row`,
    );
    assert.ok(
      point.y >= box.y && point.y <= box.y + box.height,
      `y ${point.y} escaped [${box.y}, ${box.y + box.height}] — that is the row below`,
    );
  });
}

test("the old unclamped formula really did escape — this is the bug, pinned", () => {
  // Kept executable so the regression cannot come back as "looks equivalent".
  const unclamped = (b: { x: number; y: number; width: number; height: number }) => ({
    x: b.x + Math.max(16, Math.min(56, b.width * 0.25)),
    y: b.y + Math.max(6, Math.min(b.height / 2, Math.max(b.height - 6, 6))),
  });
  const sliver = { x: 0, y: 0, width: 10, height: 4 };
  const old = unclamped(sliver);
  assert.ok(old.x > sliver.width, "the old x was outside the row (to the right)");
  assert.ok(old.y > sliver.height, "the old y was outside the row (below it)");

  const fixed = resolveLegendDoubleClickPoint(sliver);
  assert.ok(fixed.x <= sliver.width && fixed.y <= sliver.height);
});

test("a normal row still gets an off-centre point, not the centre", () => {
  // The inset is deliberate: TradingView renders a hover toolbar over the
  // middle of a legend row, so aiming dead-centre hits the toolbar instead.
  const point = resolveLegendDoubleClickPoint({ x: 0, y: 0, width: 200, height: 20 });
  assert.equal(point.x, 50);
  assert.equal(point.y, 10);
});

test("a box with no interior is refused rather than clicked", () => {
  assert.equal(legendBoxIsTooSmallToClick({ width: 0, height: 20 }), true);
  assert.equal(legendBoxIsTooSmallToClick({ width: 200, height: 1 }), true);
  assert.equal(legendBoxIsTooSmallToClick({ width: 200, height: 20 }), false);
});

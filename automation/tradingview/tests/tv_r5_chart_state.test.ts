import assert from "node:assert/strict";
import test from "node:test";

import {
  chartIntervalDisplayLabel,
  chartIntervalFromDisplayLabel,
  compareChartState,
  perturbationInterval,
  type ChartStateSnapshot,
} from "../lib/tv_validation_model.js";

// R5-REBUILD-ROLLBACK asserts priorChartStateRestored=1. The runbook's step 1
// ("record the current chart symbol, timeframe, layout, and attached scripts")
// was never executed, so there is no record of the state that preceded the
// validation — and the state that DID precede it was the defective layout
// carrying the pre-CE10156-fix instance. Restoring that would reinstate the
// defect this gate exists to have fixed.
//
// The baseline is therefore captured now, from the repaired chart, and the
// drill proves the CAPABILITY: capture, perturb, restore, save, verify after a
// reload. These pins fix what "restored" is allowed to mean.

const BASE: ChartStateSnapshot = {
  layoutName: "SMC HTF Context R5 Validation",
  symbol: "NASDAQ:AAPL",
  interval: "5",
  timezone: "UTC",
  studies: ["Vol", "SMC Session Context", "SMC HTF Confluence"],
};

test("an identical state is restored", () => {
  const verdict = compareChartState(BASE, { ...BASE });
  assert.equal(verdict.restored, true);
  assert.deepEqual(verdict.differences, []);
});

test("study order does not matter", () => {
  const verdict = compareChartState(BASE, {
    ...BASE,
    studies: ["SMC HTF Confluence", "Vol", "SMC Session Context"],
  });
  assert.equal(verdict.restored, true);
});

test("a missing study is not a restore", () => {
  const verdict = compareChartState(BASE, { ...BASE, studies: ["Vol", "SMC Session Context"] });
  assert.equal(verdict.restored, false);
  assert.match(verdict.differences.join("|"), /studies missing after restore: SMC HTF Confluence/);
});

test("a study that was never captured is not a restore either", () => {
  // A drill that left something extra behind has not put the chart back.
  const verdict = compareChartState(BASE, { ...BASE, studies: [...BASE.studies, "SMC Debug"] });
  assert.equal(verdict.restored, false);
  assert.match(verdict.differences.join("|"), /not captured: SMC Debug/);
});

test("each scalar field is reported by name", () => {
  for (const [field, changed] of [
    ["layoutName", { layoutName: "Untitled" }],
    ["symbol", { symbol: "NASDAQ:MSFT" }],
    ["interval", { interval: "15" }],
    ["timezone", { timezone: "Europe/Berlin" }],
  ] as Array<[string, Partial<ChartStateSnapshot>]>) {
    const verdict = compareChartState(BASE, { ...BASE, ...changed });
    assert.equal(verdict.restored, false, `${field} must be compared`);
    assert.match(verdict.differences.join("|"), new RegExp(`^${field}:`, "m"));
  }
});

test("an unreadable field fails closed instead of matching", () => {
  // Two nulls are not agreement. A reader that broke would otherwise certify
  // every rollback it could not observe.
  const blind = compareChartState(
    { ...BASE, symbol: null },
    { ...BASE, symbol: null },
  );
  assert.equal(blind.restored, false);
  assert.match(blind.differences.join("|"), /symbol: unreadable/);
});

test("an empty capture certifies nothing", () => {
  const empty: ChartStateSnapshot = { layoutName: null, symbol: null, interval: null, timezone: null, studies: [] };
  const verdict = compareChartState(empty, empty);
  assert.equal(verdict.restored, false);
  assert.match(verdict.differences.join("|"), /nothing was captured/);
});

// ── interval label round-trip ────────────────────────────────────────────────
//
// The drill captures what the control SHOWS and later has to put the chart back
// on it. Feeding "1h" straight into setChartInterval returns false — "1h" is
// not a digit string, so chartIntervalDisplayLabel maps it to null — and the
// restore would fail on every hourly chart for a reason the drill created
// itself. These pin the inverse.

test("every display label maps back to the interval that produces it", () => {
  for (const interval of ["1", "5", "15", "30", "45", "60", "120", "240", "1440"]) {
    const label = chartIntervalDisplayLabel(interval);
    assert.notEqual(label, null, `${interval} must have a label`);
    assert.equal(
      chartIntervalFromDisplayLabel(label as string),
      interval,
      `${interval} -> ${label} -> back`,
    );
  }
});

test("the measured labels map to the intervals the cases use", () => {
  assert.equal(chartIntervalFromDisplayLabel("5"), "5");
  assert.equal(chartIntervalFromDisplayLabel("1h"), "60");
  assert.equal(chartIntervalFromDisplayLabel("4h"), "240");
  assert.equal(chartIntervalFromDisplayLabel("1D"), "1440");
});

test("an unrecognised label fails closed instead of guessing", () => {
  for (const label of ["", "auto", "1W", "3M", "h", "1 h"]) {
    assert.equal(chartIntervalFromDisplayLabel(label), null, `${label} must not be guessed at`);
  }
});

test("the perturbation always moves the chart off its captured interval", () => {
  for (const label of ["5", "15", "1h", "4h", null]) {
    assert.notEqual(perturbationInterval(label), chartIntervalFromDisplayLabel(label ?? "") ?? "-");
  }
});

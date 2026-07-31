import assert from "node:assert/strict";
import test from "node:test";

import {
  HTF_FRAME_LABELS,
  chartIntervalDisplayLabel,
  evaluateReplayCase,
  evaluateSourceCloseBoundaries,
  mapHtfDiagnostics,
} from "../lib/tv_validation_model.js";

// R5-REBUILD-HTF-15M/1H/4H assert that a confirmed HTF source close advances
// ONLY at a boundary of its own frame — the non-repainting property of the
// confirmed-offset plus lookahead_on pattern. R5-REBUILD-FAIL-CLOSED asserts
// that an equal or lower requested frame reports unavailable. Both read
// SMC_HTF_Confluence.pine's Data Window rows, so the translation and the
// boundary arithmetic are pinned here.

test("frame labels match the plot titles SMC_HTF_Confluence.pine publishes", () => {
  assert.deepEqual(HTF_FRAME_LABELS, { "15": "HTF 15m", "60": "HTF 1h", "240": "HTF 4h" });
});

test("an available frame maps to available, confirmed and a UTC source close", () => {
  const diagnostics = mapHtfDiagnostics(
    { "HTF 15m Available": "1.0000", "HTF 15m Source Close": "1,761,572,700,000.00" },
    "15",
  );
  assert.deepEqual(diagnostics, {
    available: "1",
    sourceCloseUtc: "2025-10-27T13:45:00Z",
    sourceConfirmed: "1",
  });
});

test("a masked-unavailable frame is a confirmed absence, not an unknown", () => {
  const diagnostics = mapHtfDiagnostics(
    { "HTF 15m Available": "0.0000", "HTF 15m Source Close": "∅" },
    "15",
  );
  assert.equal(diagnostics.available, "0");
  assert.equal(diagnostics.sourceConfirmed, "0");
  assert.equal("sourceCloseUtc" in diagnostics, false);
  // This is exactly what FAIL-CLOSED asserts.
  assert.equal(
    evaluateReplayCase(["equalOrLowerRequestedFrameAvailable=0"], { equalOrLowerRequestedFrameAvailable: diagnostics.available }).passed,
    true,
  );
});

test("an absent script yields NO keys, so FAIL-CLOSED cannot pass on an empty chart", () => {
  // The decisive difference: "the script says unavailable" (above) vs "the
  // script is not on the chart" (here) must not look alike.
  assert.deepEqual(mapHtfDiagnostics({}, "15"), {});
  assert.equal(evaluateReplayCase(["available=0"], mapHtfDiagnostics({}, "15")).passed, false);
});

test("an unknown frame is refused rather than guessed", () => {
  assert.deepEqual(mapHtfDiagnostics({ "HTF 15m Available": "1.0000" }, "30"), {});
});

// ── evaluateSourceCloseBoundaries ────────────────────────────────────────────

const at = (n: number) => `2025-10-27T13:${String(n).padStart(2, "0")}:00Z`;

test("a 15m frame held across three 5m bars and then stepped is clean", () => {
  const verdict = evaluateSourceCloseBoundaries(
    [
      { atUtc: at(45), sourceCloseUtc: "2025-10-27T13:45:00Z", available: "1" },
      { atUtc: at(50), sourceCloseUtc: "2025-10-27T13:45:00Z", available: "1" },
      { atUtc: at(55), sourceCloseUtc: "2025-10-27T13:45:00Z", available: "1" },
      { atUtc: at(0), sourceCloseUtc: "2025-10-27T14:00:00Z", available: "1" },
    ],
    15,
  );
  assert.equal(verdict.advancesOnlyAtBoundary, true, verdict.violations.join("; "));
  assert.equal(verdict.distinctSourceCloses, 2);
  assert.equal(verdict.advances, 1);
});

test("an advance that is not a whole frame is a violation", () => {
  const verdict = evaluateSourceCloseBoundaries(
    [
      { atUtc: at(45), sourceCloseUtc: "2025-10-27T13:45:00Z", available: "1" },
      { atUtc: at(50), sourceCloseUtc: "2025-10-27T13:50:00Z", available: "1" },
    ],
    15,
  );
  assert.equal(verdict.advancesOnlyAtBoundary, false);
  assert.match(verdict.violations.join(" "), /not a multiple of the 15min frame/);
});

// Measured on NASDAQ:AAPL 2026-07-31: the confirmed 1h close reads 19:30Z and
// the 4h close 17:30Z, because TradingView aligns intraday bars to the SESSION
// (09:30 ET) rather than to midnight UTC. An absolute-grid assertion — which
// the first version of this function carried — would have called both of those
// violations. The property the cases pin is the ADVANCE, not the offset.
test("a session-aligned frame is clean as long as it advances by whole frames", () => {
  const verdict = evaluateSourceCloseBoundaries(
    [
      { atUtc: at(30), sourceCloseUtc: "2026-07-30T18:30:00Z", available: "1" },
      { atUtc: at(30), sourceCloseUtc: "2026-07-30T19:30:00Z", available: "1" },
    ],
    60,
  );
  assert.equal(verdict.advancesOnlyAtBoundary, true, verdict.violations.join("; "));

  const fourHour = evaluateSourceCloseBoundaries(
    [
      { atUtc: at(30), sourceCloseUtc: "2026-07-30T13:30:00Z", available: "1" },
      { atUtc: at(30), sourceCloseUtc: "2026-07-30T17:30:00Z", available: "1" },
    ],
    240,
  );
  assert.equal(fourHour.advancesOnlyAtBoundary, true, fourHour.violations.join("; "));
});

test("an off-frame advance is still a violation on a session-aligned series", () => {
  const verdict = evaluateSourceCloseBoundaries(
    [
      { atUtc: at(30), sourceCloseUtc: "2026-07-30T18:30:00Z", available: "1" },
      { atUtc: at(45), sourceCloseUtc: "2026-07-30T18:45:00Z", available: "1" },
    ],
    60,
  );
  assert.equal(verdict.advancesOnlyAtBoundary, false);
  assert.match(verdict.violations.join(" "), /not a multiple of the 60min frame/);
});

test("a backwards move is a violation", () => {
  const verdict = evaluateSourceCloseBoundaries(
    [
      { atUtc: at(0), sourceCloseUtc: "2025-10-27T14:00:00Z", available: "1" },
      { atUtc: at(45), sourceCloseUtc: "2025-10-27T13:45:00Z", available: "1" },
    ],
    15,
  );
  assert.equal(verdict.advancesOnlyAtBoundary, false);
  assert.match(verdict.violations.join(" "), /backwards/);
});

test("a run that never caught an advance proves nothing and must not pass", () => {
  const verdict = evaluateSourceCloseBoundaries(
    [
      { atUtc: at(45), sourceCloseUtc: "2025-10-27T13:45:00Z", available: "1" },
      { atUtc: at(50), sourceCloseUtc: "2025-10-27T13:45:00Z", available: "1" },
    ],
    15,
  );
  assert.equal(verdict.advancesOnlyAtBoundary, false);
  assert.match(verdict.violations.join(" "), /no within-session advance/);
});

test("a missing source close is a violation, not a skipped sample", () => {
  const verdict = evaluateSourceCloseBoundaries(
    [
      { atUtc: at(45), sourceCloseUtc: "2025-10-27T13:45:00Z", available: "1" },
      { atUtc: at(50), sourceCloseUtc: null, available: "1" },
      { atUtc: at(0), sourceCloseUtc: "2025-10-27T14:00:00Z", available: "1" },
    ],
    15,
  );
  assert.equal(verdict.advancesOnlyAtBoundary, false);
  assert.match(verdict.violations.join(" "), /no source close published/);
});

test("a 4h frame is evaluated on its own grid", () => {
  const verdict = evaluateSourceCloseBoundaries(
    [
      { atUtc: at(0), sourceCloseUtc: "2025-10-27T12:00:00Z", available: "1" },
      { atUtc: at(5), sourceCloseUtc: "2025-10-27T16:00:00Z", available: "1" },
    ],
    240,
  );
  assert.equal(verdict.advancesOnlyAtBoundary, true, verdict.violations.join("; "));
  // The same pair would be a violation on a 15m grid only via step size, so
  // check the frame is really what drives it.
  assert.equal(evaluateSourceCloseBoundaries(
    [
      { atUtc: at(0), sourceCloseUtc: "2025-10-27T12:00:00Z", available: "1" },
      { atUtc: at(5), sourceCloseUtc: "2025-10-27T14:00:00Z", available: "1" },
    ],
    240,
  ).advancesOnlyAtBoundary, false);
});

test("an empty observation set cannot certify anything", () => {
  assert.equal(evaluateSourceCloseBoundaries([], 15).advancesOnlyAtBoundary, false);
  assert.equal(evaluateSourceCloseBoundaries([{ atUtc: at(0), sourceCloseUtc: "2025-10-27T14:00:00Z", available: "1" }], 0).advancesOnlyAtBoundary, false);
});

// Measured 2026-07-31: typing "15" leaves the interval control reading "15",
// but "60" reads "1h" and "240" reads "4h". Comparing against the typed value
// reported applied=false for every hourly frame, so FAIL-CLOSED could not be
// driven onto 60 or 240 at all. (It failed rather than measuring the wrong
// timeframe, which is the behaviour we want — but the chart never moved.)
test("interval labels match what TradingView shows, not what is typed", () => {
  assert.equal(chartIntervalDisplayLabel("5"), "5");
  assert.equal(chartIntervalDisplayLabel("15"), "15");
  assert.equal(chartIntervalDisplayLabel("60"), "1h");
  assert.equal(chartIntervalDisplayLabel("240"), "4h");
  assert.equal(chartIntervalDisplayLabel("1440"), "1D");
});

test("an unmappable interval returns null so the caller fails closed", () => {
  for (const bad of ["", "0", "-5", "5m", "abc", "1.5"]) {
    assert.equal(chartIntervalDisplayLabel(bad), null, `expected null for ${JSON.stringify(bad)}`);
  }
  // 90 minutes is a real TradingView interval and is NOT a whole hour.
  assert.equal(chartIntervalDisplayLabel("90"), "90");
});


// Market gaps, measured 2026-07-31 on NASDAQ:AAPL: stepping from a checkpoint
// at the session open made the confirmed 1h close jump Friday 20:00Z -> Monday
// 14:30Z (3990 minutes). No bars exist in between, so that is not the value
// moving inside an open HTF bar — but it is also not evidence that it never
// does. Tolerated, and not counted toward certification.
test("a market gap is tolerated but certifies nothing on its own", () => {
  const verdict = evaluateSourceCloseBoundaries(
    [
      { atUtc: "step-0", sourceCloseUtc: "2025-10-24T20:00:00Z", available: "1" },
      { atUtc: "step-1", sourceCloseUtc: "2025-10-27T14:30:00Z", available: "1" },
    ],
    60,
  );
  assert.equal(verdict.gapCrossings, 1);
  assert.equal(verdict.cleanAdvances, 0);
  assert.equal(verdict.advancesOnlyAtBoundary, false, "a gap alone must not certify");
  assert.match(verdict.violations.join(" "), /market-gap crossing/);
});

test("a within-session advance certifies even when the run also crossed a gap", () => {
  const verdict = evaluateSourceCloseBoundaries(
    [
      { atUtc: "step-0", sourceCloseUtc: "2025-10-24T20:00:00Z", available: "1" },
      { atUtc: "step-1", sourceCloseUtc: "2025-10-27T14:30:00Z", available: "1" },
      { atUtc: "step-2", sourceCloseUtc: "2025-10-27T15:30:00Z", available: "1" },
    ],
    60,
  );
  assert.equal(verdict.gapCrossings, 1);
  assert.equal(verdict.cleanAdvances, 1);
  assert.equal(verdict.advancesOnlyAtBoundary, true, verdict.violations.join("; "));
});

test("a mid-bar move is still a violation and is not excused as a gap", () => {
  const verdict = evaluateSourceCloseBoundaries(
    [
      { atUtc: "step-0", sourceCloseUtc: "2025-10-27T14:30:00Z", available: "1" },
      { atUtc: "step-1", sourceCloseUtc: "2025-10-27T14:50:00Z", available: "1" },
      { atUtc: "step-2", sourceCloseUtc: "2025-10-27T15:50:00Z", available: "1" },
    ],
    60,
  );
  assert.equal(verdict.advancesOnlyAtBoundary, false);
  assert.match(verdict.violations.join(" "), /not a multiple of the 60min frame/);
});

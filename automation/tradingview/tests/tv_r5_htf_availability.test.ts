import assert from "node:assert/strict";
import test from "node:test";

import {
  HTF_FRAME_LABELS,
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

test("a value off the frame grid is a violation even if the step size fits", () => {
  const verdict = evaluateSourceCloseBoundaries(
    [
      { atUtc: at(46), sourceCloseUtc: "2025-10-27T13:46:00Z", available: "1" },
      { atUtc: at(1), sourceCloseUtc: "2025-10-27T14:01:00Z", available: "1" },
    ],
    15,
  );
  assert.equal(verdict.advancesOnlyAtBoundary, false);
  assert.match(verdict.violations.join(" "), /not on the 15min grid/);
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
  assert.match(verdict.violations.join(" "), /never caught an advance/);
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

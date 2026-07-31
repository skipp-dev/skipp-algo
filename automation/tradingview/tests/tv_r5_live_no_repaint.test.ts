import assert from "node:assert/strict";
import test from "node:test";

import {
  buildLiveSample,
  evaluateLiveNoRepaint,
  liveConfirmedFieldTitles,
  type LiveSample,
} from "../lib/tv_validation_model.js";

// R5-REBUILD-LIVE-NO-REPAINT is the one case that cannot be replayed: it needs
// an OPEN regular session, because the property under test is what happens to
// confirmed values while a higher-frame bar is still forming. These pins fix
// the verdict logic so the live run only has to supply observations.

function sample(
  atUtc: string,
  sourceCloseUtc: string | null,
  trend: string,
  atr: string,
  tick: string,
): LiveSample {
  return {
    atUtc,
    available: sourceCloseUtc === null ? "0" : "1",
    sourceCloseUtc,
    confirmed: { "HTF 15m Trend": trend, "HTF 15m ATR Ratio": atr },
    // "Close" stands in for the live main-series row; it moving is what proves
    // the feed was actually running.
    raw: { Close: tick },
  };
}

test("confirmed values holding across an open source bar passes", () => {
  const verdict = evaluateLiveNoRepaint(
    [
      sample("2026-07-31T14:00:10Z", "2026-07-31T13:45:00Z", "1", "1.20", "100.10"),
      sample("2026-07-31T14:00:40Z", "2026-07-31T13:45:00Z", "1", "1.20", "100.14"),
      sample("2026-07-31T14:01:10Z", "2026-07-31T13:45:00Z", "1", "1.20", "100.09"),
      sample("2026-07-31T14:01:40Z", "2026-07-31T13:45:00Z", "1", "1.20", "100.21"),
    ],
    15,
  );
  assert.equal(verdict.confirmedValuesStableInsideOpenSourceBar, true);
  assert.deepEqual(verdict.violations, []);
  assert.equal(verdict.longestHoldSamples, 4);
  assert.equal(verdict.lookaheadLeaks, 0);
});

test("a confirmed value changing inside one open source bar is a repaint", () => {
  const verdict = evaluateLiveNoRepaint(
    [
      sample("2026-07-31T14:00:10Z", "2026-07-31T13:45:00Z", "1", "1.20", "100.10"),
      sample("2026-07-31T14:00:40Z", "2026-07-31T13:45:00Z", "1", "1.20", "100.14"),
      sample("2026-07-31T14:01:10Z", "2026-07-31T13:45:00Z", "-1", "1.20", "100.09"),
      sample("2026-07-31T14:01:40Z", "2026-07-31T13:45:00Z", "-1", "1.20", "100.21"),
    ],
    15,
  );
  assert.equal(verdict.confirmedValuesStableInsideOpenSourceBar, false);
  assert.equal(verdict.violations.length, 1);
  assert.match(verdict.violations[0], /HTF 15m Trend.*changed 1 -> -1.*repaint/);
});

test("advancing by a whole frame at the boundary is legal, and stays legal after it", () => {
  const verdict = evaluateLiveNoRepaint(
    [
      sample("2026-07-31T14:14:10Z", "2026-07-31T13:45:00Z", "1", "1.20", "100.10"),
      sample("2026-07-31T14:14:40Z", "2026-07-31T13:45:00Z", "1", "1.20", "100.14"),
      sample("2026-07-31T14:15:10Z", "2026-07-31T13:45:00Z", "1", "1.20", "100.09"),
      // the 14:00 bar closed; the confirmed value steps by exactly one frame
      sample("2026-07-31T14:15:40Z", "2026-07-31T14:00:00Z", "-1", "1.31", "100.21"),
      sample("2026-07-31T14:16:10Z", "2026-07-31T14:00:00Z", "-1", "1.31", "100.24"),
    ],
    15,
  );
  assert.equal(verdict.confirmedValuesStableInsideOpenSourceBar, true);
  assert.equal(verdict.boundaryAdvances, 1);
  assert.equal(verdict.distinctSourceCloses, 2);
});

test("a source close ahead of the wall clock is a lookahead leak", () => {
  const verdict = evaluateLiveNoRepaint(
    [
      sample("2026-07-31T14:00:10Z", "2026-07-31T14:15:00Z", "1", "1.20", "100.10"),
      sample("2026-07-31T14:00:40Z", "2026-07-31T14:15:00Z", "1", "1.20", "100.14"),
      sample("2026-07-31T14:01:10Z", "2026-07-31T14:15:00Z", "1", "1.20", "100.09"),
    ],
    15,
  );
  assert.equal(verdict.confirmedValuesStableInsideOpenSourceBar, false);
  assert.equal(verdict.lookaheadLeaks, 3);
  assert.match(verdict.violations[0], /AHEAD of the wall clock/);
});

test("a frozen feed cannot certify stability", () => {
  // Same confirmed values AND the same live row every time: the market was shut
  // or the tab was suspended. Holding still against nothing is not evidence.
  const verdict = evaluateLiveNoRepaint(
    [
      sample("2026-07-31T22:00:10Z", "2026-07-31T19:45:00Z", "1", "1.20", "100.10"),
      sample("2026-07-31T22:00:40Z", "2026-07-31T19:45:00Z", "1", "1.20", "100.10"),
      sample("2026-07-31T22:01:10Z", "2026-07-31T19:45:00Z", "1", "1.20", "100.10"),
      sample("2026-07-31T22:01:40Z", "2026-07-31T19:45:00Z", "1", "1.20", "100.10"),
    ],
    15,
  );
  assert.equal(verdict.chartWasTicking, false);
  assert.equal(verdict.confirmedValuesStableInsideOpenSourceBar, false);
  assert.match(verdict.violations.join("|"), /not live, so stability is vacuous/);
});

test("a chart that publishes nothing fails closed rather than passing empty", () => {
  const verdict = evaluateLiveNoRepaint(
    [
      sample("2026-07-31T14:00:10Z", null, "", "", "100.10"),
      sample("2026-07-31T14:00:40Z", null, "", "", "100.14"),
    ],
    15,
  );
  assert.equal(verdict.confirmedValuesStableInsideOpenSourceBar, false);
  assert.equal(verdict.usableSamples, 0);
  assert.match(verdict.violations.join("|"), /nothing to certify/);
});

test("never seeing the same open bar twice is not a pass", () => {
  // Sampling far enough apart that every sample lands in a different source bar
  // would report perfect stability while never having looked inside one.
  const verdict = evaluateLiveNoRepaint(
    [
      sample("2026-07-31T14:00:10Z", "2026-07-31T13:45:00Z", "1", "1.20", "100.10"),
      sample("2026-07-31T14:16:10Z", "2026-07-31T14:00:00Z", "1", "1.21", "100.14"),
      sample("2026-07-31T14:31:10Z", "2026-07-31T14:15:00Z", "1", "1.22", "100.19"),
    ],
    15,
  );
  assert.equal(verdict.longestHoldSamples, 1);
  assert.equal(verdict.confirmedValuesStableInsideOpenSourceBar, false);
  assert.match(verdict.violations.join("|"), /never looked inside an open bar/);
});

test("an empty run certifies nothing", () => {
  const verdict = evaluateLiveNoRepaint([], 15);
  assert.equal(verdict.confirmedValuesStableInsideOpenSourceBar, false);
  assert.equal(verdict.chartWasTicking, false);
});

test("buildLiveSample reads the confirmed rows the frame actually publishes", () => {
  const parsed = {
    "HTF 15m Available": "1",
    "HTF 15m Source Close": "1769866200000",
    "HTF 15m Trend": "1",
    "HTF 15m ATR Ratio": "1.2043",
    "HTF 1h Trend": "-1",
    Close: "100.10",
  };
  const built = buildLiveSample(parsed, "15", "2026-07-31T14:00:10Z");
  assert.equal(built.available, "1");
  assert.equal(built.sourceCloseUtc, "2026-01-31T13:30:00Z");
  assert.deepEqual(built.confirmed, { "HTF 15m Trend": "1", "HTF 15m ATR Ratio": "1.2043" });
  assert.equal(built.raw.Close, "100.10");
});

test("the confirmed field set is frame-scoped", () => {
  assert.deepEqual(liveConfirmedFieldTitles("15"), ["HTF 15m Trend", "HTF 15m ATR Ratio"]);
  assert.deepEqual(liveConfirmedFieldTitles("240"), ["HTF 4h Trend", "HTF 4h ATR Ratio"]);
  assert.deepEqual(liveConfirmedFieldTitles("7"), []);
});

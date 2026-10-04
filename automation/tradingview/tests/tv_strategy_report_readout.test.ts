import assert from "node:assert/strict";
import test from "node:test";

import {
  classifyReportText,
  parseReadoutArgs,
  reportRangeIsDegenerate,
  symbolSlug,
} from "../../../scripts/tv_strategy_report_readout.js";

// Browserless pins for the strategy-report readout. The texts are the bottom
// panel as TradingView rendered it on 2026-10-04 (AAPL, 15m).

const NO_TRADES =
  "SMC Long-Dip Strategy\nJul 1, 2025 — Oct 3, 2026\n1 M USD\nDefault detalization\nScript execution\n1\n\nThis report requires trade data\n\nThe strategy report appears after the script makes even one trade.";
const WITH_TRADES =
  "SMC Long-Dip Strategy\nJul 1, 2025 — Oct 3, 2026\n1 M USD\n\nKey stats\n\nTotal PnL\n+20.57USD+0.00%\nTrades distribution\n27\nTotal trades\nWinners\n13 trades";

test("a report without trades reads as zero trades, with its range", () => {
  assert.deepEqual(classifyReportText(NO_TRADES), { state: "no_trades", totalTrades: 0, range: "Jul 1, 2025 — Oct 3, 2026" });
});

test("a report with trades yields the trade count", () => {
  assert.deepEqual(classifyReportText(WITH_TRADES), { state: "trades", totalTrades: 27, range: "Jul 1, 2025 — Oct 3, 2026" });
});

test("a panel that is still loading is neither", () => {
  assert.equal(classifyReportText("SMC Long-Dip Strategy").state, "unknown");
  assert.equal(classifyReportText("").state, "unknown");
});

test("a single-day range marks a report that has not loaded its data", () => {
  assert.equal(reportRangeIsDegenerate("Oct 4, 2026 — Oct 4, 2026"), true);
  assert.equal(reportRangeIsDegenerate(null), true);
  assert.equal(reportRangeIsDegenerate("Jul 1, 2025 — Oct 3, 2026"), false);
});

test("arguments: defaults, and refusals", () => {
  const args = parseReadoutArgs(["--out", "/tmp/x"]);
  assert.equal(args.interval, "15");
  assert.equal(args.session, "keep");
  assert.deepEqual(args.stages, ["Armed", "Confirmed", "Ready", "Best", "Strict"]);
  assert.throws(() => parseReadoutArgs([]), /--out/);
  assert.throws(() => parseReadoutArgs(["--out", "x", "--stages", "Ready,Sloppy"]), /unknown stage/);
  // a repeated stage is served from cache without the loading edge the wait requires
  assert.throws(() => parseReadoutArgs(["--out", "x", "--stages", "Ready,Armed,Ready"]), /duplicate stage/);
  assert.throws(() => parseReadoutArgs(["--out", "x", "--session", "24 hours"]), /unknown session/);
});

test("symbol slug drops the exchange prefix", () => {
  assert.equal(symbolSlug("NASDAQ:AAPL"), "AAPL");
  assert.equal(symbolSlug("BRK.B"), "BRK.B");
});

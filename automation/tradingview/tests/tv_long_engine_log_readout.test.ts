import assert from "node:assert/strict";
import test from "node:test";

import { parseLogArgs, parseLongEvent, splitLogLines } from "../../../scripts/tv_long_engine_log_readout.js";

// Browserless pins for the long-engine log readout. Lines as the Pine logs
// panel rendered them on 2026-10-04 (XOM, 15m).

const PANEL = [
  "SMC Long-Dip Suite",
  "[2026-05-18T11:00:00.000+02:00]: LONG ARMED | src=OB | trig=159.05 | inv=157.73 | ready=Awaiting Confirm | strict=Blocked: Trust Insufficient | reason=OB setup expired",
  "[2026-05-19T10:00:00.000+02:00]: OVH-BASELINE session summary: evaluated=7 served_blocked=0",
  "not a log line",
].join("\n");

test("only timestamped lines are log lines", () => {
  assert.equal(splitLogLines(PANEL).length, 2);
});

test("a LONG line parses into event and fields; a value may contain a colon", () => {
  const ev = parseLongEvent(splitLogLines(PANEL)[0]);
  assert.equal(ev?.event, "LONG ARMED");
  assert.equal(ev?.time, "2026-05-18T11:00:00.000+02:00");
  assert.equal(ev?.fields.src, "OB");
  assert.equal(ev?.fields.strict, "Blocked: Trust Insufficient");
  assert.equal(ev?.fields.reason, "OB setup expired");
});

test("the Ready diagnosis line parses as LONG PENDING with its failing gates", () => {
  const ev = parseLongEvent("[2026-10-05T15:00:00.000+02:00]: LONG PENDING | ready=Awaiting Next Bar | failing=accel second_derivative");
  assert.equal(ev?.event, "LONG PENDING");
  assert.equal(ev?.fields.failing, "accel second_derivative");
});

test("other log lines are not lifecycle events", () => {
  assert.equal(parseLongEvent(splitLogLines(PANEL)[1]), null);
});

test("arguments: defaults and refusals", () => {
  const a = parseLogArgs(["--out", "x"]);
  assert.equal(a.session, "keep");
  assert.equal(a.symbols.length, 5);
  assert.throws(() => parseLogArgs([]), /--out/);
  assert.throws(() => parseLogArgs(["--out", "x", "--session", "24 hours"]), /unknown session/);
});

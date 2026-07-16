import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import test from "node:test";

import type { Page, WebSocket } from "playwright";

import { decodeTradingViewMessages, TradingViewRuntimeErrorMonitor } from "../lib/tv_runtime_errors.js";

function framed(value: unknown): string {
  const payload = JSON.stringify(value);
  return `~m~${payload.length}~m~${payload}`;
}

test("decodes multiple TradingView protocol messages from one frame", () => {
  const first = { m: "study_error", p: ["cs", "study123", "unknown parent id"] };
  const second = { m: "study_completed", p: ["cs", "study456"] };
  assert.deepEqual(decodeTradingViewMessages(framed(first) + framed(second)), [first, second]);
});

test("ignores malformed and non-JSON framed payloads", () => {
  assert.deepEqual(decodeTradingViewMessages("noise~m~4~m~nope"), []);
});

test("monitor attaches, scopes records, snapshots, and clears", () => {
  const page = new EventEmitter();
  const socket = new EventEmitter();
  const monitor = new TradingViewRuntimeErrorMonitor();
  monitor.attach(page as unknown as Page);
  page.emit("websocket", socket as unknown as WebSocket);

  socket.emit("framereceived", { payload: framed({ m: "study_error", p: ["cs", "study123", "division by zero"] }) });
  socket.emit("framereceived", { payload: framed({ m: "study_error", p: ["cs", "study456", "unknown parent id"] }) });

  const snapshot = monitor.snapshot();
  assert.equal(snapshot.length, 1);
  assert.equal(snapshot[0]?.studyId, "study456");
  assert.equal(snapshot[0]?.message, "unknown parent id");

  monitor.clear();
  assert.deepEqual(monitor.snapshot(), []);
  assert.equal(snapshot.length, 1, "clear must not mutate an existing snapshot");
});

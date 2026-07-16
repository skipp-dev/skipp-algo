import assert from "node:assert/strict";
import test from "node:test";

import { decodeTradingViewMessages } from "../lib/tv_runtime_errors.js";

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

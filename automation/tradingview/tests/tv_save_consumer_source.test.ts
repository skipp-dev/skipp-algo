import assert from "node:assert/strict";
import test from "node:test";

import { pineSourceSha256 } from "../../../scripts/tv_save_consumer_source.js";

test("pineSourceSha256 normalizes line endings but detects source changes", () => {
  const unix = "//@version=6\nindicator(\"x\")\n";
  const windows = unix.replaceAll("\n", "\r\n");
  assert.equal(pineSourceSha256(unix), pineSourceSha256(windows));
  assert.notEqual(pineSourceSha256(unix), pineSourceSha256(`${unix}plot(close)\n`));
});

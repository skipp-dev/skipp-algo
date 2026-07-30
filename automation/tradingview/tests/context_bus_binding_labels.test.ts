import assert from "node:assert/strict";
import test from "node:test";

import { parseBusBindingLabels } from "../lib/bus_binding_labels.mjs";

test("transport parser keeps Engine BUS and Context BUS contracts separate from ordinary sources", () => {
  const source = `
    input.source(close, "BUS Ready")
    input.source(close, "CTX SchemaVersion")
    input.source(close, "Price Source")
    input.source(close, "CTX SessionDirection")
  `;

  assert.deepEqual(parseBusBindingLabels(source), [
    "BUS Ready",
    "CTX SchemaVersion",
    "CTX SessionDirection",
  ]);
});

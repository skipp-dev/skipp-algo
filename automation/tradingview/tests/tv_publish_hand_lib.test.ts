import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { consumerPins, deriveExpectedVersion } from "../lib/tv_publish_hand_lib.js";

function scratchRepo(files: Record<string, string>): string {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "handlib-"));
  fs.mkdirSync(path.join(root, "SMC++"), { recursive: true });
  for (const [rel, body] of Object.entries(files)) {
    fs.writeFileSync(path.join(root, rel), body, "utf-8");
  }
  return root;
}

test("a library is not its own consumer", () => {
  const root = scratchRepo({
    "SMC++/smc_draw.pine": 'library("smc_draw")\nimport preuss_steffen/smc_draw/3 as d\n',
  });
  assert.deepEqual(consumerPins(root, "smc_draw"), []);
});

test("pins are collected from the repo root and SMC++", () => {
  const root = scratchRepo({
    "SMC_Long_Dip_Suite.pine": "import preuss_steffen/smc_draw/3 as d\n",
    "SMC++/smc_context_engine_private.pine": "import preuss_steffen/smc_draw/3 as d\n",
  });
  assert.equal(consumerPins(root, "smc_draw").length, 2);
});

test("zero pins is a legal bootstrap, not an error", () => {
  const root = scratchRepo({ "SMC_Long_Dip_Suite.pine": "// nothing pins draw\n" });
  const resolved = deriveExpectedVersion(root, "smc_draw");
  assert.equal(resolved.version, null);
  assert.deepEqual(resolved.pins, []);
});

test("unanimous pins become the expectation", () => {
  const root = scratchRepo({
    "SMC_Long_Dip_Suite.pine": "import preuss_steffen/smc_draw/4 as d\n",
    "SMC_Breakout_Overlay.pine": "import preuss_steffen/smc_draw/4 as d\n",
  });
  assert.equal(deriveExpectedVersion(root, "smc_draw").version, 4);
});

test("disagreeing pins abort and name every file and version", () => {
  const root = scratchRepo({
    "SMC_Long_Dip_Suite.pine": "import preuss_steffen/smc_draw/4 as d\n",
    "SMC_Breakout_Overlay.pine": "import preuss_steffen/smc_draw/3 as d\n",
  });
  assert.throws(
    () => deriveExpectedVersion(root, "smc_draw"),
    (e: Error) =>
      /Consumer pins disagree/.test(e.message)
      && /SMC_Long_Dip_Suite\.pine pins \/4/.test(e.message)
      && /SMC_Breakout_Overlay\.pine pins \/3/.test(e.message),
  );
});

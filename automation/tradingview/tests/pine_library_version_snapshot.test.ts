import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  buildSnapshot,
  discoverConsumerPins,
  parseImportPins,
  type ConsumerPin,
} from "../../../scripts/build_pine_library_version_snapshot.js";

test("parseImportPins extracts library + pinned version from import lines", () => {
  const src = [
    'import preuss_steffen/smc_core_types/1 as ct',
    'import preuss_steffen/smc_micro_profiles_generated/152 as mp',
    "// import preuss_steffen/smc_utils/9 as u  (commented — still an import token)",
    "indicator(\"x\")",
  ].join("\n");
  const pins = parseImportPins(src, "SMC_Core_Engine.pine");
  assert.deepEqual(
    pins.map((p) => [p.library, p.pinnedVersion]),
    [
      ["smc_core_types", 1],
      ["smc_micro_profiles_generated", 152],
      ["smc_utils", 9],
    ],
  );
  assert.equal(pins[0].file, "SMC_Core_Engine.pine");
});

test("parseImportPins ignores non-preuss imports and lines without a pin", () => {
  const src = [
    "import someone_else/lib/3 as x",
    "import preuss_steffen/smc_utils as u", // no /<version>
    "plot(close)",
  ].join("\n");
  assert.deepEqual(parseImportPins(src, "f.pine"), []);
});

test("buildSnapshot flags drift only when the TV version is KNOWN and differs", () => {
  const pins = new Map<string, ConsumerPin[]>([
    ["smc_micro_profiles_generated", [{ file: "SMC_Dashboard.pine", library: "smc_micro_profiles_generated", pinnedVersion: 1 }]],
    ["smc_utils", [{ file: "SMC_Core_Engine.pine", library: "smc_utils", pinnedVersion: 5 }]],
    ["smc_bus_private", [{ file: "SMC_Core_Engine.pine", library: "smc_bus_private", pinnedVersion: 1 }]],
  ]);
  const tvVersions = new Map<string, number | null>([
    ["smc_micro_profiles_generated", 152], // drift: 1 != 152
    ["smc_utils", 5], // in sync
    ["smc_bus_private", null], // unknown → never drift
  ]);

  const snap = buildSnapshot(pins, tvVersions, 1_000);

  const byName = Object.fromEntries(snap.libraries.map((l) => [l.name, l]));
  assert.equal(byName["smc_micro_profiles_generated"].consumers[0].drift, true);
  assert.equal(byName["smc_micro_profiles_generated"].anyConsumerDrift, true);
  assert.equal(byName["smc_utils"].consumers[0].drift, false);
  assert.equal(byName["smc_bus_private"].consumers[0].drift, false, "unknown TV version must not masquerade as drift");
  assert.equal(byName["smc_bus_private"].tvVersionKnown, false);

  assert.equal(snap.anyDrift, true);
  assert.equal(snap.librariesDrifted, 1);
  assert.equal(snap.librariesProbed, 2, "only libs with a known TV version count as probed");
  assert.equal(snap.generated_at_unix, 1_000);
  assert.equal(snap.generatedAt, new Date(1_000_000).toISOString());
});

test("buildSnapshot sorts libraries by name and consumers by file", () => {
  const pins = new Map<string, ConsumerPin[]>([
    ["smc_utils", [
      { file: "SMC_Long_Strategy.pine", library: "smc_utils", pinnedVersion: 1 },
      { file: "SMC_Core_Engine.pine", library: "smc_utils", pinnedVersion: 1 },
    ]],
    ["smc_core_types", [{ file: "SMC_Core_Engine.pine", library: "smc_core_types", pinnedVersion: 1 }]],
  ]);
  const snap = buildSnapshot(pins, new Map([["smc_utils", 1], ["smc_core_types", 1]]), 0);
  assert.deepEqual(snap.libraries.map((l) => l.name), ["smc_core_types", "smc_utils"]);
  assert.deepEqual(
    snap.libraries[1].consumers.map((c) => c.file),
    ["SMC_Core_Engine.pine", "SMC_Long_Strategy.pine"],
  );
});

test("buildSnapshot with an empty facade result marks nothing probed, nothing drifted", () => {
  const pins = new Map<string, ConsumerPin[]>([
    ["smc_utils", [{ file: "SMC_Core_Engine.pine", library: "smc_utils", pinnedVersion: 1 }]],
  ]);
  const snap = buildSnapshot(pins, new Map([["smc_utils", null]]), 0, "facade unreachable");
  assert.equal(snap.anyDrift, false);
  assert.equal(snap.librariesProbed, 0);
  assert.equal(snap.facadeError, "facade unreachable");
});

test("discoverConsumerPins walks .pine files and skips excluded dirs", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "pinever-"));
  try {
    fs.writeFileSync(path.join(root, "Consumer.pine"), "import preuss_steffen/smc_utils/1 as u\n");
    fs.mkdirSync(path.join(root, "tests"));
    fs.writeFileSync(path.join(root, "tests", "Fixture.pine"), "import preuss_steffen/smc_utils/99 as u\n");
    fs.mkdirSync(path.join(root, "pine", "generated"), { recursive: true });
    fs.writeFileSync(path.join(root, "pine", "generated", "Gen.pine"), "import preuss_steffen/smc_utils/42 as u\n");

    const byLib = discoverConsumerPins(root);
    assert.deepEqual([...byLib.keys()], ["smc_utils"]);
    // Only the root consumer counts — tests/ and pine/ are excluded.
    assert.deepEqual(byLib.get("smc_utils")!.map((p) => [p.file, p.pinnedVersion]), [["Consumer.pine", 1]]);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

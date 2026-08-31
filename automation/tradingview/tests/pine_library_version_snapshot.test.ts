import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  buildSnapshot,
  discoverLibraryDataAsOf,
  discoverConsumerPins,
  parseLibraryDataAsOf,
  parseLibraryDeclaration,
  parseLibraryPayloadVolume,
  parseImportPins,
  type ConsumerPin,
} from "../../../scripts/build_pine_library_version_snapshot.js";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

test("parseImportPins extracts library + pinned version from import lines", () => {
  const src = [
    'import preuss_steffen/smc_core_types/1 as ct',
    'import preuss_steffen/smc_micro_profiles_generated/152 as mp',
    "// import preuss_steffen/smc_utils/9 as u  (commented — still an import token)",
    "indicator(\"x\")",
  ].join("\n");
  const pins = parseImportPins(src, "SMC_Long_Dip_Suite.pine");
  assert.deepEqual(
    pins.map((p) => [p.library, p.pinnedVersion]),
    [
      ["smc_core_types", 1],
      ["smc_micro_profiles_generated", 152],
      ["smc_utils", 9],
    ],
  );
  assert.equal(pins[0].file, "SMC_Long_Dip_Suite.pine");
});

test("parseImportPins ignores non-preuss imports and lines without a pin", () => {
  const src = [
    "import someone_else/lib/3 as x",
    "import preuss_steffen/smc_utils as u", // no /<version>
    "plot(close)",
  ].join("\n");
  assert.deepEqual(parseImportPins(src, "f.pine"), []);
});

test("parseLibraryDeclaration extracts a repo-owned library without requiring a consumer", () => {
  assert.equal(
    parseLibraryDeclaration('//@version=6\nlibrary("smc_context_engine_private", overlay = false)\n'),
    "smc_context_engine_private",
  );
  assert.equal(parseLibraryDeclaration('indicator("not a library")\n'), null);
});

test("parseLibraryDataAsOf accepts only a valid exported ISO date", () => {
  assert.equal(parseLibraryDataAsOf('export const string ASOF_DATE = "2026-07-20"'), "2026-07-20");
  assert.equal(parseLibraryDataAsOf('export const string ASOF_DATE = "2026-02-31"'), null);
  assert.equal(parseLibraryDataAsOf('const string ASOF_DATE = "2026-07-20"'), null);
});

test("buildSnapshot flags drift only when the TV version is KNOWN and differs", () => {
  const pins = new Map<string, ConsumerPin[]>([
    ["smc_micro_profiles_generated", [{ file: "SMC_Decision_Board.pine", library: "smc_micro_profiles_generated", pinnedVersion: 1 }]],
    ["smc_utils", [{ file: "SMC_Long_Dip_Suite.pine", library: "smc_utils", pinnedVersion: 5 }]],
    ["smc_bus_private", [{ file: "SMC_Long_Dip_Suite.pine", library: "smc_bus_private", pinnedVersion: 1 }]],
  ]);
  const tvVersions = new Map<string, number | null>([
    ["smc_micro_profiles_generated", 152], // drift: 1 != 152
    ["smc_utils", 5], // in sync
    ["smc_bus_private", null], // unknown → never drift
  ]);

  const snap = buildSnapshot(
    pins,
    tvVersions,
    1_000,
    "",
    new Map([["smc_micro_profiles_generated", "2026-07-20"]]),
  );

  const byName = Object.fromEntries(snap.libraries.map((l) => [l.name, l]));
  assert.equal(byName["smc_micro_profiles_generated"].consumers[0].drift, true);
  assert.equal(byName["smc_micro_profiles_generated"].anyConsumerDrift, true);
  assert.equal(byName["smc_micro_profiles_generated"].dataAsOf, "2026-07-20");
  assert.equal(byName["smc_micro_profiles_generated"].dataAsOfKnown, true);
  assert.equal(byName["smc_micro_profiles_generated"].dataAsOfUnix, 1_784_505_600);
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
      { file: "SMC_Long_Dip_Strategy.pine", library: "smc_utils", pinnedVersion: 1 },
      { file: "SMC_Long_Dip_Suite.pine", library: "smc_utils", pinnedVersion: 1 },
    ]],
    ["smc_core_types", [{ file: "SMC_Long_Dip_Suite.pine", library: "smc_core_types", pinnedVersion: 1 }]],
  ]);
  const snap = buildSnapshot(pins, new Map([["smc_utils", 1], ["smc_core_types", 1]]), 0);
  assert.deepEqual(snap.libraries.map((l) => l.name), ["smc_core_types", "smc_utils"]);
  assert.deepEqual(
    snap.libraries[1].consumers.map((c) => c.file),
    ["SMC_Long_Dip_Strategy.pine", "SMC_Long_Dip_Suite.pine"],
  );
});

test("buildSnapshot with an empty facade result marks nothing probed, nothing drifted", () => {
  const pins = new Map<string, ConsumerPin[]>([
    ["smc_utils", [{ file: "SMC_Long_Dip_Suite.pine", library: "smc_utils", pinnedVersion: 1 }]],
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
    fs.writeFileSync(
      path.join(root, "OrphanLibrary.pine"),
      'library("smc_context_engine_private", overlay = false)\n',
    );
    fs.mkdirSync(path.join(root, "tests"));
    fs.writeFileSync(path.join(root, "tests", "Fixture.pine"), "import preuss_steffen/smc_utils/99 as u\n");
    fs.mkdirSync(path.join(root, "pine", "generated"), { recursive: true });
    fs.writeFileSync(path.join(root, "pine", "generated", "Gen.pine"), "import preuss_steffen/smc_utils/42 as u\n");

    const byLib = discoverConsumerPins(root);
    assert.deepEqual([...byLib.keys()].sort(), ["smc_context_engine_private", "smc_utils"]);
    // Only the root consumer counts — tests/ and pine/ are excluded.
    assert.deepEqual(byLib.get("smc_utils")!.map((p) => [p.file, p.pinnedVersion]), [["Consumer.pine", 1]]);
    assert.deepEqual(
      byLib.get("smc_context_engine_private"),
      [],
      "a declared library with no consumer must still be monitored",
    );
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("discoverLibraryDataAsOf reads generated library watermarks", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "pine-asof-"));
  try {
    fs.mkdirSync(path.join(root, "pine", "generated"), { recursive: true });
    fs.writeFileSync(
      path.join(root, "pine", "generated", "smc_micro_profiles_generated.pine"),
      'export const string ASOF_DATE = "2026-07-20"\n',
    );
    const values = discoverLibraryDataAsOf(root, ["smc_micro_profiles_generated", "smc_utils"]);
    assert.equal(values.get("smc_micro_profiles_generated"), "2026-07-20");
    assert.equal(values.get("smc_utils"), null);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

// ── ADR-0029: payload volume ────────────────────────────────────

test("parseLibraryPayloadVolume reads a single-literal universe export", () => {
  const src = [
    "export const int UNIVERSE_SIZE = 3",
    'export const string UNIVERSE_TICKERS = "AAPL,MSFT,NVDA"',
    'export const string CLEAN_RECLAIM_TICKERS = "AAPL"',
  ].join("\n");

  const volume = parseLibraryPayloadVolume(src);

  assert.equal(volume.known, true);
  assert.equal(volume.universeSize, 3);
  assert.equal(volume.universeSymbols, 3);
  assert.equal(volume.listSymbols, 1);
});

test("parseLibraryPayloadVolume sums the sharded concatenation form", () => {
  // The form a healthy 6929-symbol universe actually renders as: UNIVERSE_TICKERS
  // is emitted at max_chars=3900, so the export is an expression, not a literal.
  // A parser shaped like ASOF_DATE_RE would score this as 0 and invert the alert.
  const parts = [
    'const string UNIVERSE_TICKERS_PART_1 = "AAPL,MSFT"',
    'const string UNIVERSE_TICKERS_PART_2 = "NVDA,TSLA,AMD"',
    'export const string UNIVERSE_TICKERS = UNIVERSE_TICKERS_PART_1 + "," + UNIVERSE_TICKERS_PART_2',
  ];
  const src = ["export const int UNIVERSE_SIZE = 5", ...parts].join("\n");

  const volume = parseLibraryPayloadVolume(src);

  assert.equal(volume.known, true);
  assert.equal(volume.universeSymbols, 5);
});

test("parseLibraryPayloadVolume measures the artifact that shipped empty", () => {
  const src = [
    "export const int UNIVERSE_SIZE = 6929",
    'export const string UNIVERSE_TICKERS = ""',
    'export const string CLEAN_RECLAIM_TICKERS = ""',
  ].join("\n");

  const volume = parseLibraryPayloadVolume(src);

  assert.equal(volume.known, true);
  assert.equal(volume.universeSize, 6929);
  assert.equal(volume.universeSymbols, 0);
  assert.equal(volume.listSymbols, 0);
});

test("parseLibraryPayloadVolume reports unknown rather than empty when absent", () => {
  const volume = parseLibraryPayloadVolume("// hand-authored library, no payload exports");

  assert.equal(volume.known, false);
  assert.equal(volume.universeSymbols, 0);
});

test("buildSnapshot carries payload volume per library", () => {
  const pins = new Map<string, ConsumerPin[]>([
    ["smc_micro_profiles_generated", [
      { file: "SMC_Long_Dip_Suite.pine", library: "smc_micro_profiles_generated", pinnedVersion: 161 },
    ]],
  ]);
  const payload = new Map([
    ["smc_micro_profiles_generated", { known: true, universeSize: 6929, universeSymbols: 0, listSymbols: 0 }],
  ]);

  const snap = buildSnapshot(pins, new Map([["smc_micro_profiles_generated", 161]]), 1_800_000_000, "", new Map(), payload);

  assert.equal(snap.libraries[0].payloadKnown, true);
  assert.equal(snap.libraries[0].payloadUniverseSymbols, 0);
  assert.equal(snap.libraries[0].payloadListSymbols, 0);
});

test("buildSnapshot defaults payload to unknown when no measurement was supplied", () => {
  const pins = new Map<string, ConsumerPin[]>([
    ["smc_profile_engine", [{ file: "SMC_Core_Engine.pine", library: "smc_profile_engine", pinnedVersion: 1 }]],
  ]);

  const snap = buildSnapshot(pins, new Map([["smc_profile_engine", 1]]), 1_800_000_000);

  assert.equal(snap.libraries[0].payloadKnown, false);
});

// ── Cross-language parser contract (ADR-0029) ───────────────────
//
// The payload parser exists twice — scripts/smc_payload_volume.py (publish
// gate) and this builder (Grafana metric) — because the TS side cannot import
// Python. Nothing but these shared cases keeps the two in step: the name pin in
// tests/test_pine_library_version_bridge.py catches a renamed list, not a
// divergent shard summation.

type ParserCase = {
  name: string;
  why: string;
  pine: string;
  expect: {
    known: boolean;
    universeSize: number | null;
    universeSymbols: number;
    listSymbols: number;
  };
};

const PARSER_CASES: ParserCase[] = JSON.parse(
  fs.readFileSync(
    path.join(REPO_ROOT, "tests", "fixtures", "payload_volume_parser_cases.json"),
    "utf-8",
  ),
).cases;

test("shared parser contract has cases and covers the sharded form", () => {
  // Guards against a fixture that silently empties or loses the trap case.
  assert.ok(PARSER_CASES.length >= 6, "parser contract fixture looks truncated");
  assert.ok(
    PARSER_CASES.some((c) => c.pine.includes("_PART_1")),
    "the sharded case is the whole point — it must not disappear",
  );
});

for (const parserCase of PARSER_CASES) {
  test(`parseLibraryPayloadVolume matches the shared contract: ${parserCase.name}`, () => {
    const volume = parseLibraryPayloadVolume(parserCase.pine);

    assert.equal(volume.known, parserCase.expect.known, parserCase.why);
    assert.equal(volume.universeSize, parserCase.expect.universeSize, parserCase.why);
    assert.equal(volume.universeSymbols, parserCase.expect.universeSymbols, parserCase.why);
    assert.equal(volume.listSymbols, parserCase.expect.listSymbols, parserCase.why);
  });
}

test("parseLibraryPayloadVolume agrees with the seed manifest's Python measurement", () => {
  // The checked-in seed artifact is the shared anchor: the generator wrote the
  // Python measurement into the manifest, this parses the .pine beside it.
  const seed = path.join(REPO_ROOT, "tests", "fixtures", "generated_seed", "pine", "generated");
  const manifest = JSON.parse(
    fs.readFileSync(path.join(seed, "smc_micro_profiles_generated.json"), "utf-8"),
  );
  const gate = manifest.productivity_gate;

  const volume = parseLibraryPayloadVolume(
    fs.readFileSync(path.join(seed, "smc_micro_profiles_generated.pine"), "utf-8"),
  );

  assert.equal(volume.known, gate.payload_known);
  assert.equal(volume.universeSymbols, gate.universe_tickers_count);
  assert.equal(volume.listSymbols, gate.list_total);
});

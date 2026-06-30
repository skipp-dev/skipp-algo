import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  hasExpectedImportPathEvidence,
  verifyOverlayPublishContract,
  type OverlayContractInput,
} from "../../../scripts/tv_publish_overlay_library.js";

const SCRIPT_NAME = "smc_overlay_generated";
const IMPORT_PATH = "preuss_steffen/smc_overlay_generated/1";
const ALIAS = "ov";

function buildOverlayManifest(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    schema_version: "3.0.0",
    library_name: SCRIPT_NAME,
    library_owner: "preuss_steffen",
    library_version: 1,
    recommended_import_path: IMPORT_PATH,
    pine_library: "pine/generated/smc_overlay_generated.pine",
    core_import_snippet: `import ${IMPORT_PATH} as ${ALIAS}`,
    cadence_class: "fast_overlay",
    derived_from_source_artifact: true,
    asof_date: "2026-05-27",
    asof_time: "2026-05-28T22:15:00Z",
    overlay_field_count: 29,
    ...overrides,
  };
}

const VALID_LIBRARY_TEXT = [
  "//@version=6",
  `library("${SCRIPT_NAME}")`,
  "",
  '// ── Bake Watermark ──',
  'export const string ASOF_DATE = "2026-05-27"',
  "",
  "// ── Market Regime ──",
  'export const string MARKET_REGIME = "NEUTRAL"',
  "",
].join("\n");

type Fixture = {
  dir: string;
  input: OverlayContractInput;
};

function writeFixture(
  overrides: { libraryText?: string; manifest?: Record<string, unknown> | string } = {},
): Fixture {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "tv-overlay-contract-"));
  const pineDir = path.join(dir, "pine", "generated");
  fs.mkdirSync(pineDir, { recursive: true });

  const libraryPath = path.join(pineDir, "smc_overlay_generated.pine");
  const manifestPath = path.join(pineDir, "smc_overlay_generated.json");

  fs.writeFileSync(libraryPath, overrides.libraryText ?? VALID_LIBRARY_TEXT, "utf-8");
  const manifestValue =
    overrides.manifest === undefined
      ? JSON.stringify(buildOverlayManifest())
      : typeof overrides.manifest === "string"
        ? overrides.manifest
        : JSON.stringify(overrides.manifest);
  fs.writeFileSync(manifestPath, manifestValue, "utf-8");

  return {
    dir,
    input: {
      library: libraryPath,
      manifest: manifestPath,
      scriptName: SCRIPT_NAME,
      importPath: IMPORT_PATH,
      alias: ALIAS,
      version: 1,
    },
  };
}

test("overlay contract accepts a faithful library + manifest pair", () => {
  const { input } = writeFixture();
  const details = verifyOverlayPublishContract(input);
  assert.equal(details.scriptName, SCRIPT_NAME);
  assert.equal(details.importPath, IMPORT_PATH);
  assert.equal(details.alias, ALIAS);
  assert.equal(details.version, 1);
});

test("overlay contract rejects a missing library source", () => {
  const { input } = writeFixture();
  fs.rmSync(input.library);
  assert.throws(() => verifyOverlayPublishContract(input), /Missing overlay library source/);
});

test("overlay contract rejects a missing manifest", () => {
  const { input } = writeFixture();
  fs.rmSync(input.manifest);
  assert.throws(() => verifyOverlayPublishContract(input), /Missing overlay manifest/);
});

test("overlay contract rejects a wrong library header", () => {
  const { input } = writeFixture({
    libraryText: '//@version=6\nlibrary("smc_micro_profiles_generated")\n',
  });
  assert.throws(() => verifyOverlayPublishContract(input), /Overlay library header mismatch/);
});

test("overlay contract rejects a manifest library_name mismatch", () => {
  const { input } = writeFixture({
    manifest: buildOverlayManifest({ library_name: "something_else" }),
  });
  assert.throws(() => verifyOverlayPublishContract(input), /library_name mismatch/);
});

test("overlay contract rejects a recommended_import_path mismatch", () => {
  const { input } = writeFixture({
    manifest: buildOverlayManifest({ recommended_import_path: "preuss_steffen/smc_overlay_generated/2" }),
  });
  assert.throws(() => verifyOverlayPublishContract(input), /recommended_import_path mismatch/);
});

test("overlay contract rejects a core_import_snippet without the import line", () => {
  const { input } = writeFixture({
    manifest: buildOverlayManifest({ core_import_snippet: "import preuss_steffen/smc_overlay_generated/1 as mp" }),
  });
  assert.throws(() => verifyOverlayPublishContract(input), /core_import_snippet must contain/);
});

test("overlay contract rejects a manifest library_version mismatch", () => {
  const { input } = writeFixture({
    manifest: buildOverlayManifest({ library_version: 99 }),
  });
  assert.throws(() => verifyOverlayPublishContract(input), /library_version mismatch/);
});

test("overlay contract rejects an invalid JSON manifest", () => {
  const { input } = writeFixture({ manifest: "{ not valid json" });
  assert.throws(() => verifyOverlayPublishContract(input), /not valid JSON/);
});

test("overlay contract rejects a non-positive version", () => {
  const { input } = writeFixture();
  assert.throws(
    () => verifyOverlayPublishContract({ ...input, version: 0 }),
    /version must be a positive integer/,
  );
});

test("import-path evidence detects the expected path and rejects absence", () => {
  assert.equal(
    hasExpectedImportPathEvidence("publish dialog showing import preuss_steffen/smc_overlay_generated/1 as ov", IMPORT_PATH),
    true,
  );
  assert.equal(hasExpectedImportPathEvidence("no path here", IMPORT_PATH), false);
  assert.equal(
    hasExpectedImportPathEvidence("publish dialog showing import preuss_steffen/smc_overlay_generated/10 as ov", IMPORT_PATH),
    false,
  );
  assert.equal(
    hasExpectedImportPathEvidence("publish dialog showing import preuss_steffen/smc_overlay_generated/1 as ov", ""),
    false,
  );
});

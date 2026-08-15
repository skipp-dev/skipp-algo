/**
 * recordHandLibRelease: the committed record of a verified hand-lib publish.
 *
 * The function is the producer half of the currency gate
 * (tests/test_handlib_release_manifest.py consumes the file). What matters
 * here is merge behaviour: ten publishers write the SAME file in one
 * orchestrator run, each must preserve the others' entries, and the
 * serialization must be order-independent so the weekly repin PR's diff
 * shows version movement, not key shuffling.
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import {
  HANDLIB_RELEASE_MANIFEST,
  recordHandLibRelease,
} from "../lib/tv_publish_hand_lib.js";

function tmpRepo(): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), "handlib-manifest-"));
}

function readManifest(root: string): { schemaVersion: number; libraries: Record<string, { publishedVersion: number }> } {
  return JSON.parse(
    fs.readFileSync(path.join(root, HANDLIB_RELEASE_MANIFEST), "utf-8"),
  );
}

test("creates the manifest with schemaVersion 1 when absent", () => {
  const root = tmpRepo();
  const written = recordHandLibRelease(root, "smc_utils", {
    publishedVersion: 5,
    publishedAt: "2026-08-14T00:00:00Z",
    versionVerificationMode: "facade_list",
  });
  assert.equal(written, path.join(root, HANDLIB_RELEASE_MANIFEST));
  const manifest = readManifest(root);
  assert.equal(manifest.schemaVersion, 1);
  assert.equal(manifest.libraries.smc_utils.publishedVersion, 5);
});

test("a second library's write preserves the first entry", () => {
  const root = tmpRepo();
  recordHandLibRelease(root, "smc_utils", {
    publishedVersion: 5,
    publishedAt: "2026-08-14T00:00:00Z",
    versionVerificationMode: "facade_list",
  });
  recordHandLibRelease(root, "smc_draw", {
    publishedVersion: 3,
    publishedAt: "2026-08-14T00:01:00Z",
    versionVerificationMode: "facade_list",
  });
  const manifest = readManifest(root);
  assert.equal(manifest.libraries.smc_utils.publishedVersion, 5);
  assert.equal(manifest.libraries.smc_draw.publishedVersion, 3);
});

test("re-publishing a library overwrites only its own entry", () => {
  const root = tmpRepo();
  recordHandLibRelease(root, "smc_utils", {
    publishedVersion: 5,
    publishedAt: "2026-08-14T00:00:00Z",
    versionVerificationMode: "facade_list",
  });
  recordHandLibRelease(root, "smc_draw", {
    publishedVersion: 3,
    publishedAt: "2026-08-14T00:01:00Z",
    versionVerificationMode: "facade_list",
  });
  recordHandLibRelease(root, "smc_utils", {
    publishedVersion: 6,
    publishedAt: "2026-08-14T00:02:00Z",
    versionVerificationMode: "facade_list",
  });
  const manifest = readManifest(root);
  assert.equal(manifest.libraries.smc_utils.publishedVersion, 6);
  assert.equal(manifest.libraries.smc_draw.publishedVersion, 3);
});

test("a manifest with an unknown schemaVersion is refused, not rewritten as v1", () => {
  const root = tmpRepo();
  const manifestPath = path.join(root, HANDLIB_RELEASE_MANIFEST);
  fs.mkdirSync(path.dirname(manifestPath), { recursive: true });
  const v2 = { schemaVersion: 2, libraries: {}, addedInV2: "evidence" };
  fs.writeFileSync(manifestPath, JSON.stringify(v2, null, 2) + "\n", "utf-8");
  assert.throws(
    () => recordHandLibRelease(root, "smc_utils", {
      publishedVersion: 5,
      publishedAt: "T",
      versionVerificationMode: "facade_list",
    }),
    /schemaVersion 2.*only.*understands 1/s,
  );
  // The refusal must leave the newer file untouched — the whole point.
  assert.deepEqual(JSON.parse(fs.readFileSync(manifestPath, "utf-8")), v2);
});

test("a manifest without a libraries object is refused as damaged", () => {
  const root = tmpRepo();
  const manifestPath = path.join(root, HANDLIB_RELEASE_MANIFEST);
  fs.mkdirSync(path.dirname(manifestPath), { recursive: true });
  fs.writeFileSync(manifestPath, '{"schemaVersion": 1}\n', "utf-8");
  assert.throws(
    () => recordHandLibRelease(root, "smc_utils", {
      publishedVersion: 5,
      publishedAt: "T",
      versionVerificationMode: "facade_list",
    }),
    /no libraries object.*git checkout/s,
  );
});

test("the write leaves no temp file beside the manifest", () => {
  // writeJson goes through a same-directory `.…tmp` + rename since the
  // 2026-08-15 review (a torn in-place write would turn the NEXT verified
  // publish into a parse failure). The observable contract from here: the
  // directory holds exactly the manifest afterwards, no strays.
  const root = tmpRepo();
  recordHandLibRelease(root, "smc_utils", {
    publishedVersion: 5,
    publishedAt: "T",
    versionVerificationMode: "facade_list",
  });
  const dir = path.dirname(path.join(root, HANDLIB_RELEASE_MANIFEST));
  const leftovers = fs.readdirSync(dir).filter((name) => name.endsWith(".tmp"));
  assert.deepEqual(leftovers, []);
  assert.equal(readManifest(root).libraries.smc_utils.publishedVersion, 5);
});

test("serialization is byte-identical regardless of write order", () => {
  const entryA = { publishedVersion: 5, publishedAt: "T", versionVerificationMode: "facade_list" };
  const entryB = { publishedVersion: 3, publishedAt: "T", versionVerificationMode: "facade_list" };

  const rootAB = tmpRepo();
  recordHandLibRelease(rootAB, "smc_utils", entryA);
  recordHandLibRelease(rootAB, "smc_draw", entryB);

  const rootBA = tmpRepo();
  recordHandLibRelease(rootBA, "smc_draw", entryB);
  recordHandLibRelease(rootBA, "smc_utils", entryA);

  const bytesAB = fs.readFileSync(path.join(rootAB, HANDLIB_RELEASE_MANIFEST), "utf-8");
  const bytesBA = fs.readFileSync(path.join(rootBA, HANDLIB_RELEASE_MANIFEST), "utf-8");
  assert.equal(bytesAB, bytesBA);
});

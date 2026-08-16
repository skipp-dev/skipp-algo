import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { pineDeclarationTitlePattern } from "../lib/tv_shared.js";
import {
  assertConsumerEditorSource,
  assertConsumerPreWriteSource,
  expectedDeclarationOf,
  pineSourceSha256,
} from "../../../scripts/tv_save_consumer_source.js";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");

test("pineSourceSha256 normalizes line endings but detects source changes", () => {
  const unix = "//@version=6\nindicator(\"x\")\n";
  const windows = unix.replaceAll("\n", "\r\n");
  assert.equal(pineSourceSha256(unix), pineSourceSha256(windows));
  assert.notEqual(pineSourceSha256(unix), pineSourceSha256(`${unix}plot(close)\n`));
});

test("pineDeclarationTitlePattern anchors on the declaration, not on mentions", () => {
  const pattern = pineDeclarationTitlePattern("SMC Long-Dip Suite");
  assert.ok(pattern.test('indicator("SMC Long-Dip Suite", overlay = true)'));
  assert.ok(pattern.test("indicator('SMC Long-Dip Suite', overlay = true)"));
  assert.ok(pattern.test('strategy ( "SMC Long-Dip Suite" )'));
  // A consumer that BINDS to the suite mentions the title in label strings —
  // that must never satisfy the suite's declaration match.
  assert.ok(!pattern.test('input.source(close, "SMC Long-Dip Suite: BUS Armed")'));
  assert.ok(!pattern.test('indicator("SMC Long-Dip Suite Copy")'));
  assert.ok(!pattern.test('indicator("Other")\n// SMC Long-Dip Suite'));
  // Mixed quotes are not a declaration.
  assert.ok(!pattern.test("indicator(\"SMC Long-Dip Suite')"));
});

test("pineDeclarationTitlePattern escapes regex metacharacters in titles", () => {
  const pattern = pineDeclarationTitlePattern("SMC (v2) + Dip?");
  assert.ok(pattern.test('indicator("SMC (v2) + Dip?", overlay = true)'));
  assert.ok(!pattern.test('indicator("SMC (v2) x Dipz", overlay = true)'));
});

test("consumer write guard classifies declaration drift as a repairable saved-document state", () => {
  const target = {
    source: "SMC_Long_Dip_Suite.pine",
    scriptName: "SMC Long-Dip Suite",
  };
  const correctSuiteModel = '//@version=6\nindicator("SMC Long-Dip Suite")\nplot(close)\n';
  const staleAlertsModel = '//@version=6\nindicator("SMC Long-Dip Alerts")\nplot(close)\n';
  assert.equal(assertConsumerPreWriteSource(target, correctSuiteModel), "declaration");
  assert.equal(
    assertConsumerPreWriteSource(target, staleAlertsModel),
    "document_title_model_transition",
  );
  assert.throws(
    () => assertConsumerPreWriteSource(target, "// no Pine declaration"),
    /active Pine model has no declaration/,
  );
});

test("consumer write guard requires staged and post-save hashes to match the repo", () => {
  const target = {
    source: "SMC_Long_Dip_Alerts.pine",
    scriptName: "SMC Long-Dip Alerts",
  };
  const expected = '//@version=6\nindicator("SMC Long-Dip Alerts")\nplot(close)\n';
  const stale = expected.replace("plot(close)", "plot(open)");
  const expectedSha256 = pineSourceSha256(expected);

  assert.equal(
    assertConsumerEditorSource("staged source", target, expected, expectedSha256),
    expectedSha256,
  );
  assert.throws(
    () => assertConsumerEditorSource("post-save source", target, stale, expectedSha256),
    /expected SHA-256 .* got /,
  );
});

test("every rollout consumer's declared title is unique across the mapping", () => {
  // The drivers verify identity against expectedDeclarationOf(target): the
  // saved name where name==declaration, the explicit declarationTitle where
  // the two differ (2026-08-15, Hold Manager). This contract keeps every
  // declared title present in its own source and unambiguous across the set.
  const config = JSON.parse(
    fs.readFileSync(path.join(repoRoot, "automation/tradingview/config/consumer-rollout.json"), "utf-8"),
  ) as { saveTargets: Array<{ source: string; scriptName: string; declarationTitle?: string }> };
  assert.ok(config.saveTargets.length >= 8);
  const sources = config.saveTargets.map((target) => ({
    ...target,
    code: fs.readFileSync(path.join(repoRoot, target.source), "utf-8"),
  }));
  for (const target of sources) {
    const declared = expectedDeclarationOf(target);
    const pattern = pineDeclarationTitlePattern(declared);
    assert.ok(pattern.test(target.code), `${target.source} must declare "${declared}"`);
    for (const other of sources) {
      if (other.source === target.source) continue;
      assert.ok(
        !pattern.test(other.code),
        `declaration pattern for "${declared}" must not match ${other.source}`,
      );
    }
  }
});

// 2026-08-15, run 31868334987: the driver refused the Hold Manager validation
// script because its saved-document name ("SMC Hold Manager R2.4 Validation")
// is not its declaration ("SMC Hold Manager") — the only rollout target where
// the two differ. declarationTitle names that split explicitly.
test("an explicit declarationTitle verifies against the declaration, strictly", () => {
  const target = {
    source: "SMC_Hold_Manager.pine",
    scriptName: "SMC Hold Manager R2.4 Validation",
    declarationTitle: "SMC Hold Manager",
  };
  const buildTwoModel = '//@version=6\nindicator("SMC Hold Manager", overlay = true)\nplot(close)';

  assert.equal(assertConsumerPreWriteSource(target, buildTwoModel), "declaration");

  // The strict claim: a buffer declaring something else must throw instead of
  // sliding into the drift-repair fallback — the mapping already stated what
  // the document declares, so a mismatch is the wrong document.
  const wrongModel = '//@version=6\nindicator("SMC Long-Dip Suite", overlay = true)\nplot(close)';
  assert.throws(
    () => assertConsumerPreWriteSource(target, wrongModel),
    /does not declare SMC Hold Manager/,
  );

  const sha = pineSourceSha256(buildTwoModel);
  assert.equal(
    assertConsumerEditorSource("staged source", target, buildTwoModel, sha),
    sha,
    "the staged-source check must accept the declared title",
  );
});

test("without declarationTitle the name-equals-declaration behavior is unchanged", () => {
  const target = { source: "SMC_Long_Dip_Suite.pine", scriptName: "SMC Long-Dip Suite" };
  const model = '//@version=6\nindicator("SMC Long-Dip Suite", overlay = true)\nplot(close)';

  assert.equal(expectedDeclarationOf(target), "SMC Long-Dip Suite");
  assert.equal(assertConsumerPreWriteSource(target, model), "declaration");
});

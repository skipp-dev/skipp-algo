import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { pineDeclarationTitlePattern } from "../lib/tv_shared.js";
import {
  assertConsumerEditorSource,
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

test("consumer write guard rejects a stale Monaco model before source mutation", () => {
  const target = {
    source: "SMC_Long_Dip_Suite.pine",
    scriptName: "SMC Long-Dip Suite",
  };
  const staleAlertsModel = '//@version=6\nindicator("SMC Long-Dip Alerts")\nplot(close)\n';
  assert.throws(
    () => assertConsumerEditorSource("pre-write identity", target, staleAlertsModel),
    /active Pine model has a different declaration/,
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

test("every rollout consumer's saved script name is its unique Pine declaration title", () => {
  // verifyConsumerSource passes target.scriptName as the declaration marker;
  // this contract keeps that assumption true for the whole rollout mapping.
  const config = JSON.parse(
    fs.readFileSync(path.join(repoRoot, "automation/tradingview/config/consumer-rollout.json"), "utf-8"),
  ) as { saveTargets: Array<{ source: string; scriptName: string }> };
  assert.ok(config.saveTargets.length >= 8);
  const sources = config.saveTargets.map((target) => ({
    ...target,
    code: fs.readFileSync(path.join(repoRoot, target.source), "utf-8"),
  }));
  for (const target of sources) {
    const pattern = pineDeclarationTitlePattern(target.scriptName);
    assert.ok(pattern.test(target.code), `${target.source} must declare its saved name "${target.scriptName}"`);
    for (const other of sources) {
      if (other.source === target.source) continue;
      assert.ok(
        !pattern.test(other.code),
        `declaration pattern for "${target.scriptName}" must not match ${other.source}`,
      );
    }
  }
});

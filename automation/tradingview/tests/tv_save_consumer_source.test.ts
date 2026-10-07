import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { extractPineDeclarationTitle, pineDeclarationTitlePattern } from "../lib/tv_shared.js";
import {
  SOURCE_READBACK_IDENTITY_MISMATCH_EVENT,
  SOURCE_SAVE_PERSISTED_MISMATCH_EVENT,
  assertConsumerEditorSource,
  assertConsumerPreWriteSource,
  expectedDeclarationOf,
  judgePersistedConsumerSource,
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

// ── Persisted-store readback (run 33031264859, 2026-08-27) ──────────────────
//
// The editor-buffer readback verified this run's own staged content while the
// saved-script store held a sibling consumer's source in the slot. These pin
// the identity-first judgement of whatever the persisted store serves, and
// the wiring that makes the store — not the editor — the readback authority.

test("extractPineDeclarationTitle reads the declaration, not mentions or imports", () => {
  assert.equal(
    extractPineDeclarationTitle('//@version=6\nindicator("SMC Long-Dip Mobile", overlay = true)\n'),
    "SMC Long-Dip Mobile",
  );
  assert.equal(
    extractPineDeclarationTitle("//@version=6\nstrategy('SMC Long-Dip Strategy', overlay = true)\n"),
    "SMC Long-Dip Strategy",
  );
  assert.equal(
    extractPineDeclarationTitle('library("smc_bus_private", overlay = false)'),
    "smc_bus_private",
  );
  assert.equal(
    extractPineDeclarationTitle('//@version=6\nindicator(title = "SMC Setup Check")\n'),
    "SMC Setup Check",
  );
  // A comment or binding label mentioning a declaration must not count.
  assert.equal(extractPineDeclarationTitle('// indicator: none\ns = input.source(close, "X")'), null);
  assert.equal(extractPineDeclarationTitle(""), null);
});

test("persisted judgement accepts the slot only under its own declaration", () => {
  const target = { source: "SMC_Long_Dip_Mobile.pine", scriptName: "SMC Long-Dip Mobile" };
  const repoSource = '//@version=6\nindicator("SMC Long-Dip Mobile")\nplot(close)\n';
  const expectedSha256 = pineSourceSha256(repoSource);

  const match = judgePersistedConsumerSource(target, repoSource, expectedSha256);
  assert.deepEqual(match, { verdict: "match", actualSha256: expectedSha256 });

  // Same declaration, older body: honest drift, not an identity refusal.
  const stale = repoSource.replace("plot(close)", "plot(open)");
  const drift = judgePersistedConsumerSource(target, stale, expectedSha256);
  assert.equal(drift.verdict, "sha-mismatch");
  assert.ok(drift.verdict === "sha-mismatch" && drift.actualSha256 !== expectedSha256);

  // The proven cross-write: the Mobile slot serving the Strategy source must
  // be refused BEFORE any hash talk, with the `<name>:<foundTitle>` payload.
  const crossWrite = judgePersistedConsumerSource(
    target,
    '//@version=6\nstrategy("SMC Long-Dip Strategy")\nplot(close)\n',
    expectedSha256,
  );
  assert.equal(crossWrite.verdict, "identity-mismatch");
  assert.ok(crossWrite.verdict === "identity-mismatch");
  assert.equal(crossWrite.foundTitle, "SMC Long-Dip Strategy");
  assert.equal(crossWrite.traceDetail, "SMC Long-Dip Mobile:SMC Long-Dip Strategy");

  // A slot with no declaration at all is an identity mismatch too.
  const empty = judgePersistedConsumerSource(target, "// empty slot", expectedSha256);
  assert.equal(empty.verdict, "identity-mismatch");
  assert.ok(empty.verdict === "identity-mismatch" && empty.foundTitle === null);
  assert.equal(empty.traceDetail, "SMC Long-Dip Mobile:no-declaration");
});

test("persisted judgement honors an explicit declarationTitle (Hold Manager split)", () => {
  const target = {
    source: "SMC_Hold_Manager.pine",
    scriptName: "SMC Hold Manager R2.4 Validation",
    declarationTitle: "SMC Hold Manager",
  };
  const persisted = '//@version=6\nindicator("SMC Hold Manager", overlay = true)\nplot(close)\n';
  const judged = judgePersistedConsumerSource(target, persisted, pineSourceSha256(persisted));
  assert.equal(judged.verdict, "match");
});

test("fail-closed trace events keep their published names", () => {
  // The proof ledger's witness greps the save-job log for these exact names;
  // renaming them must be a conscious edit here, not a drive-by.
  assert.equal(SOURCE_READBACK_IDENTITY_MISMATCH_EVENT, "source-readback-identity-mismatch");
  assert.equal(SOURCE_SAVE_PERSISTED_MISMATCH_EVENT, "source-save-persisted-mismatch");
});

test("readback authority wiring: facade store first, unfiltered editor fallback, identity gate on both", () => {
  const script = fs.readFileSync(path.join(repoRoot, "scripts/tv_save_consumer_source.ts"), "utf-8");
  const verifyAt = script.indexOf("export async function verifyConsumerSource");
  const cliAt = script.indexOf("export async function runSaveConsumerSourceCli");
  assert.ok(verifyAt > 0, "verifyConsumerSource must exist");
  assert.ok(cliAt > verifyAt, "cli entry must follow verifyConsumerSource");
  const verifyBody = script.slice(verifyAt, cliAt);

  // 1) The persisted store is consulted BEFORE any editor surface.
  const facadeAt = verifyBody.indexOf("fetchSavedScriptSourceViaFacade(");
  const openAt = verifyBody.indexOf("openExistingScript(");
  assert.ok(facadeAt > 0, "verify must fetch the pine-facade saved source");
  assert.ok(openAt > facadeAt, "the editor open is the FALLBACK, after the facade store");

  // 2) The fallback read must NOT filter by the expected declaration — that
  //    expectation-filter is how run 33031264859 verified its own buffer.
  const readAt = verifyBody.indexOf("readEditorContent(");
  assert.ok(readAt > 0, "fallback read exists");
  const readCall = verifyBody.slice(readAt, verifyBody.indexOf("})", readAt));
  assert.ok(
    !readCall.includes("expectedDeclarationTitle"),
    "fallback readEditorContent must read what the open actually loaded, not hunt for the expected declaration",
  );

  // 3) Both paths flow into the identity-gated judgement and its trace event.
  assert.ok(verifyBody.includes("judgePersistedConsumerSource("), "verify must judge identity before hashes");
  assert.ok(
    verifyBody.includes("SOURCE_READBACK_IDENTITY_MISMATCH_EVENT"),
    "the identity refusal must trace source-readback-identity-mismatch",
  );

  // 4) The write path proves the persisted slot after the save.
  const saveAt = script.indexOf("export async function saveConsumerSource");
  assert.ok(saveAt > 0);
  const saveBody = script.slice(saveAt, verifyAt);
  const saveScriptAt = saveBody.indexOf("await saveScript(");
  const savePersistedAt = saveBody.indexOf("fetchSavedScriptSourceViaFacade(");
  assert.ok(saveScriptAt > 0 && savePersistedAt > saveScriptAt, "post-save persisted proof must follow the save");
  assert.ok(saveBody.includes("SOURCE_SAVE_PERSISTED_MISMATCH_EVENT"), "persisted refusal must trace its event");
});

test("extractPineDeclarationTitle resolves EVERY rollout consumer source to its declared title", () => {
  // Full population, not a sample: the persisted readback fail-closes on the
  // extracted title, so a source the extractor cannot resolve (wrapped
  // declaration, leading comment mentioning indicator(/strategy() would turn
  // into a false-red identity mismatch on the next save run. Measured
  // 2026-08-28: 12/12 resolve. A new consumer that breaks this goes red HERE,
  // in CI, not in the browser run.
  const config = JSON.parse(
    fs.readFileSync(path.join(repoRoot, "automation/tradingview/config/consumer-rollout.json"), "utf-8"),
  ) as { saveTargets: Array<{ source: string; scriptName: string; declarationTitle?: string }> };
  assert.ok(config.saveTargets.length >= 8);
  for (const target of config.saveTargets) {
    const code = fs.readFileSync(path.join(repoRoot, target.source), "utf-8");
    assert.equal(
      extractPineDeclarationTitle(code),
      expectedDeclarationOf(target),
      `${target.source}: extractor must resolve the declared title`,
    );
  }
});

// 2026-10-07, tv-save run 37568182460: Ctrl+S left the privately published Suite's slot at
// v446 (twice); a publish of the same editor state created v448. The save flow publishes
// privately published scripts between the post-save buffer check and the persisted-store proof.
test("privately published scripts are published before the persisted-store proof", async () => {
  const { PRIVATELY_PUBLISHED_SCRIPTS } = await import("../../../scripts/tv_save_consumer_source.js");
  assert.deepEqual(Object.keys(PRIVATELY_PUBLISHED_SCRIPTS), ["SMC Long-Dip Suite"]);
  const fsMod = await import("node:fs");
  const src = fsMod.readFileSync(new URL("../../../scripts/tv_save_consumer_source.ts", import.meta.url), "utf-8");
  const body = src.slice(src.indexOf("export async function saveConsumerSource("));
  const postSave = body.indexOf('assertConsumerEditorSource("post-save source"');
  const publish = body.indexOf("await publishPrivateScript(session.page");
  const facade = body.indexOf("await fetchSavedScriptSourceViaFacade(session.page, target.scriptName)");
  assert.ok(postSave > 0 && postSave < publish && publish < facade, "publish must sit between the post-save check and the facade proof");
  assert.match(body, /if \(!published\.publishConfirmed && !published\.noChangeDetected\) \{\n\s+throw new Error/);
});

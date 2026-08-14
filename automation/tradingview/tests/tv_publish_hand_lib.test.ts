import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  consumerPins,
  deriveExpectedVersion,
  resolveVersionAcceptance,
  verifyHandLibPublishContract,
  type HandLibDescriptor,
} from "../lib/tv_publish_hand_lib.js";

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

test("a facade-verified equal version is accepted", () => {
  const r = resolveVersionAcceptance({ expected: 3, published: 3, mode: "facade_list", facadeAnswered: true });
  assert.equal(r.accepted, true);
});

test("a facade-verified bump above the expectation is accepted", () => {
  const r = resolveVersionAcceptance({ expected: 3, published: 4, mode: "facade_list", facadeAnswered: true });
  assert.equal(r.accepted, true);
  assert.match(r.reason, /advanced/);
});

test("a version below the expectation is rejected", () => {
  const r = resolveVersionAcceptance({ expected: 4, published: 3, mode: "facade_list", facadeAnswered: true });
  assert.equal(r.accepted, false);
  assert.match(r.reason, /below/);
});

test("a null published version is rejected regardless of facade status", () => {
  const r = resolveVersionAcceptance({ expected: 3, published: null, mode: "not_verified", facadeAnswered: false });
  assert.equal(r.accepted, false);
  assert.match(r.reason, /not verified/);
});

test("a bootstrap with no expectation accepts any verified version, even a weak mode, once the facade answers", () => {
  const r = resolveVersionAcceptance({ expected: null, published: 1, mode: "body_fallback", facadeAnswered: true });
  assert.equal(r.accepted, true);
});

test("a version above the expectation is rejected without facade verification", () => {
  const r = resolveVersionAcceptance({ expected: 3, published: 4, mode: "version_context", facadeAnswered: false });
  assert.equal(r.accepted, false);
  assert.match(r.reason, /facade/);
});

test("a body_fallback mode with a matching version and no facade answer is rejected", () => {
  const r = resolveVersionAcceptance({ expected: 3, published: 3, mode: "body_fallback", facadeAnswered: false });
  assert.equal(r.accepted, false);
  assert.match(r.reason, /body_fallback/);
});

test("a version_context mode with a matching version and no facade answer is accepted", () => {
  const r = resolveVersionAcceptance({ expected: 3, published: 3, mode: "version_context", facadeAnswered: false });
  assert.equal(r.accepted, true);
});

test("an idempotent_no_change mode with a matching version and no facade answer is accepted", () => {
  const r = resolveVersionAcceptance({ expected: 3, published: 3, mode: "idempotent_no_change", facadeAnswered: false });
  assert.equal(r.accepted, true);
});

test("a not_verified mode with a matching version and no facade answer is rejected", () => {
  const r = resolveVersionAcceptance({ expected: 3, published: 3, mode: "not_verified", facadeAnswered: false });
  assert.equal(r.accepted, false);
  assert.match(r.reason, /not_verified/);
});

// verifyHandLibPublishContract: the two checks ported from the pre-conversion
// smc_engine_private publisher (2026-08-14 fix round, controller ruling) --
// Number.isInteger instead of Number.isFinite, and the --import-path
// coherence check. Both must run BEFORE any TradingView write, so they are
// exercised here directly against the exported contract function rather than
// indirectly through a live publish.

/** A minimal library + core pair that satisfies every check except the ones under test. */
function coherentContractFixture(): { root: string; descriptor: HandLibDescriptor } {
  const root = scratchRepo({
    "SMC++/smc_contract_fixture.pine": 'library("smc_contract_fixture")\nplot(1)\n',
    "SMC_Long_Dip_Suite.pine": "// does not import smc_contract_fixture -- zero pins is a legal bootstrap\n",
  });
  const descriptor: HandLibDescriptor = {
    scriptName: "smc_contract_fixture",
    source: "SMC++/smc_contract_fixture.pine",
    alias: "cf",
    noun: "Contract fixture",
    reportStem: "publish-contract-fixture-library",
    description: "Fixture only, never published.",
  };
  return { root, descriptor };
}

function baseCliFor(root: string, overrides: { importPath: string; version: number }) {
  return {
    library: path.join(root, "SMC++/smc_contract_fixture.pine"),
    core: path.join(root, "SMC_Long_Dip_Suite.pine"),
    repoRoot: root,
    scriptName: "smc_contract_fixture",
    alias: "cf",
    description: "Fixture only, never published.",
    out: path.join(root, "out.json"),
    openExisting: true,
    allowCreate: true,
    ...overrides,
  };
}

test("verifyHandLibPublishContract rejects a non-integer version", () => {
  const { root, descriptor } = coherentContractFixture();
  const cli = baseCliFor(root, { importPath: "preuss_steffen/smc_contract_fixture/3", version: 3.5 });
  assert.throws(
    () => verifyHandLibPublishContract(descriptor, cli),
    (e: Error) => /Contract fixture library version must be a positive integer, received: 3\.5/.test(e.message),
  );
});

test("verifyHandLibPublishContract rejects an import path naming the wrong library", () => {
  const { root, descriptor } = coherentContractFixture();
  const cli = baseCliFor(root, { importPath: "preuss_steffen/smc_other_library/3", version: 3 });
  assert.throws(
    () => verifyHandLibPublishContract(descriptor, cli),
    (e: Error) =>
      /Contract fixture import path must name smc_contract_fixture\/3, received: preuss_steffen\/smc_other_library\/3/
        .test(e.message),
  );
});

test("verifyHandLibPublishContract rejects an import path naming the wrong version", () => {
  const { root, descriptor } = coherentContractFixture();
  const cli = baseCliFor(root, { importPath: "preuss_steffen/smc_contract_fixture/2", version: 3 });
  assert.throws(
    () => verifyHandLibPublishContract(descriptor, cli),
    (e: Error) =>
      /Contract fixture import path must name smc_contract_fixture\/3, received: preuss_steffen\/smc_contract_fixture\/2/
        .test(e.message),
  );
});

test("verifyHandLibPublishContract accepts a correctly-formed import path", () => {
  const { root, descriptor } = coherentContractFixture();
  const cli = baseCliFor(root, { importPath: "preuss_steffen/smc_contract_fixture/3", version: 3 });
  const details = verifyHandLibPublishContract(descriptor, cli);
  assert.equal(details.scriptName, "smc_contract_fixture");
  assert.equal(details.version, 3);
  assert.equal(details.importPath, "preuss_steffen/smc_contract_fixture/3");
});

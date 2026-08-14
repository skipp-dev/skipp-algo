import assert from "node:assert/strict";
import test from "node:test";

import { ENGINE_LIBRARY, runPublishEnginePrivateLibraryCli }
  from "../../../scripts/tv_publish_engine_library.js";

// The wrapper's whole job is carrying smc_engine_private's identity into the
// shared publish body (automation/tradingview/lib/tv_publish_hand_lib.ts).
// Publish sequencing/behaviour (import-path evidence matching, pin scanning,
// version derivation, post-publish acceptance) now lives there and is proven
// by automation/tradingview/tests/tv_publish_hand_lib.test.ts and
// automation/tradingview/tests/tv_publish_import_path_evidence.test.ts. What
// is left to protect here is that this descriptor still names the same
// library, alias, description and report path the old hand-written script
// did -- a drift here would silently repoint the publisher without any of
// those shared-module tests noticing, because they are library-agnostic.
//
// alias specifically is functionally inert in the shared module today: it
// survives only inside an error-message string (tv_publish_hand_lib.ts:290,
// used at :325) and an unread ContractDetails field. Before this refactor a
// wrong alias aborted the publish through the core-import assertion; now
// nothing at runtime catches it, so this pin is the only thing that still
// would (2026-08-14 fix round 3).
//
// Note: the CLI entry point exported here is runPublishEnginePrivateLibraryCli
// -- it does NOT follow the tv_publish_engine_library.ts filename pattern
// (runPublishEngineLibraryCli would be the naive guess and does not exist).

test("the engine descriptor names smc_engine_private and its repo source path", () => {
  assert.equal(ENGINE_LIBRARY.scriptName, "smc_engine_private");
  assert.equal(ENGINE_LIBRARY.source, "SMC++/smc_engine_private.pine");
});

test("the engine descriptor keeps its TradingView import alias", () => {
  assert.equal(ENGINE_LIBRARY.alias, "eng");
});

test("the engine descriptor keeps its publish description", () => {
  assert.equal(
    ENGINE_LIBRARY.description,
    "SMC OB/FVG/structure engine (OrderBlock, FVG types + tracking/detection/drawing) "
    + "consumed by SMC Core. Extracted to relieve the main-script token budget (CE10117).",
  );
});

test("the engine descriptor keeps its report filename stem", () => {
  assert.equal(ENGINE_LIBRARY.reportStem, "publish-engine-private-library");
});

test("the engine publisher exports its CLI entry point under its own (non-filename-matching) name", () => {
  assert.equal(typeof runPublishEnginePrivateLibraryCli, "function");
});

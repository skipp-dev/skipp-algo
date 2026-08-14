import assert from "node:assert/strict";
import test from "node:test";

import { PROFILE_ENGINE_LIBRARY, runPublishProfileEngineLibraryCli }
  from "../../../scripts/tv_publish_profile_engine_library.js";

// The wrapper's whole job is carrying smc_profile_engine's identity into the
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

test("the profile engine descriptor names smc_profile_engine and its repo source path", () => {
  assert.equal(PROFILE_ENGINE_LIBRARY.scriptName, "smc_profile_engine");
  assert.equal(PROFILE_ENGINE_LIBRARY.source, "SMC++/smc_profile_engine.pine");
});

test("the profile engine descriptor keeps its TradingView import alias", () => {
  assert.equal(PROFILE_ENGINE_LIBRARY.alias, "pe");
});

test("the profile engine descriptor keeps its publish description", () => {
  assert.equal(
    PROFILE_ENGINE_LIBRARY.description,
    "Private profile engine consumed by SMC Core.",
  );
});

test("the profile engine descriptor keeps its report filename stem", () => {
  assert.equal(PROFILE_ENGINE_LIBRARY.reportStem, "publish-profile-engine-library");
});

test("the profile engine publisher exports its CLI entry point under its own name", () => {
  assert.equal(typeof runPublishProfileEngineLibraryCli, "function");
});

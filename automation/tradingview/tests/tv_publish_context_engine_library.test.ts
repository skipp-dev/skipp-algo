import assert from "node:assert/strict";
import test from "node:test";

import { CONTEXT_ENGINE_LIBRARY, runPublishContextEngineLibraryCli }
  from "../../../scripts/tv_publish_context_engine_library.js";

// The wrapper's whole job is carrying smc_context_engine_private's identity
// into the shared publish body (automation/tradingview/lib/tv_publish_hand_lib.ts).
// Publish sequencing/behaviour (import-path evidence matching, pin scanning,
// version derivation, post-publish acceptance, and -- unique to this
// descriptor -- the advance-exactly-one contract plus its live page-auth and
// preflight-version checks) now lives there and is proven by
// automation/tradingview/tests/tv_publish_hand_lib.test.ts and
// automation/tradingview/tests/tv_publish_import_path_evidence.test.ts. What
// is left to protect here is that this descriptor still names the same
// library, alias, description, and report path the pre-conversion script
// did, AND that it still opts into requiresExplicitVersionAdvance -- a drift
// here would silently repoint the publisher, or silently drop the advance
// contract, without any of those shared-module tests noticing (they are
// library-agnostic and descriptor-driven).

test("the context engine descriptor names smc_context_engine_private and its repo source path", () => {
  assert.equal(CONTEXT_ENGINE_LIBRARY.scriptName, "smc_context_engine_private");
  assert.equal(CONTEXT_ENGINE_LIBRARY.source, "SMC++/smc_context_engine_private.pine");
});

test("the context engine descriptor keeps its TradingView import alias", () => {
  assert.equal(CONTEXT_ENGINE_LIBRARY.alias, "cx");
});

test("the context engine descriptor keeps its publish description", () => {
  assert.equal(
    CONTEXT_ENGINE_LIBRARY.description,
    "Private confirmed-bar context frames for structure, imbalance, zones, sweeps, liquidity pools, sessions, and aggregate context.",
  );
});

test("the context engine descriptor keeps its report filename stem", () => {
  assert.equal(CONTEXT_ENGINE_LIBRARY.reportStem, "publish-context-engine-library");
});

test("the context engine descriptor still opts into the advance-exactly-one contract", () => {
  assert.equal(CONTEXT_ENGINE_LIBRARY.requiresExplicitVersionAdvance, true);
});

test("the context engine CLI export name is unchanged", () => {
  assert.equal(typeof runPublishContextEngineLibraryCli, "function");
});

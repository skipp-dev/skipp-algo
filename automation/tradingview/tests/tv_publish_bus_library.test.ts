import assert from "node:assert/strict";
import test from "node:test";

import { BUS_LIBRARY, runPublishBusLibraryCli } from "../../../scripts/tv_publish_bus_library.js";

// The wrapper's whole job is carrying smc_bus_private's identity into the
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

test("the bus descriptor names smc_bus_private and its repo source path", () => {
  assert.equal(BUS_LIBRARY.scriptName, "smc_bus_private");
  assert.equal(BUS_LIBRARY.source, "SMC++/smc_bus_private.pine");
});

test("the bus descriptor keeps its TradingView import alias", () => {
  assert.equal(BUS_LIBRARY.alias, "bp");
});

test("the bus descriptor keeps its publish description", () => {
  assert.equal(
    BUS_LIBRARY.description,
    "Private message-bus helpers consumed by SMC Core.",
  );
});

test("the bus descriptor keeps its report filename stem", () => {
  assert.equal(BUS_LIBRARY.reportStem, "publish-bus-library");
});

test("the bus publisher exports its CLI entry point under its own name", () => {
  assert.equal(typeof runPublishBusLibraryCli, "function");
});

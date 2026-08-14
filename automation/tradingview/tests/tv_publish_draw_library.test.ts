import assert from "node:assert/strict";
import test from "node:test";

import { DRAW_LIBRARY } from "../../../scripts/tv_publish_draw_library.js";

// The wrapper's whole job is carrying smc_draw's identity into the shared
// publish body (automation/tradingview/lib/tv_publish_hand_lib.ts). Publish
// sequencing/behaviour (import-path evidence matching, pin scanning, version
// derivation, post-publish acceptance) now lives there and is proven by
// automation/tradingview/tests/tv_publish_hand_lib.test.ts and
// automation/tradingview/tests/tv_publish_import_path_evidence.test.ts. What
// is left to protect here is that this descriptor still names the same
// library, alias, description and report path the old hand-written script
// did -- a drift here would silently repoint the publisher without any of
// those shared-module tests noticing, because they are library-agnostic.

test("the draw descriptor names smc_draw and its repo source path", () => {
  assert.equal(DRAW_LIBRARY.scriptName, "smc_draw");
  assert.equal(DRAW_LIBRARY.source, "SMC++/smc_draw.pine");
});

test("the draw descriptor keeps its TradingView import alias", () => {
  assert.equal(DRAW_LIBRARY.alias, "d");
});

test("the draw descriptor keeps its publish description", () => {
  assert.equal(
    DRAW_LIBRARY.description,
    "Private drawing and visualization helpers consumed by SMC Core.",
  );
});

test("the draw descriptor keeps its report filename stem", () => {
  assert.equal(DRAW_LIBRARY.reportStem, "publish-draw-library");
});

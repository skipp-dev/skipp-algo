import assert from "node:assert/strict";
import test from "node:test";

import {
  hasExpectedImportPathEvidence,
} from "../../../scripts/tv_publish_draw_library.js";

const IMPORT_PATH = "preuss_steffen/smc_draw/1";

test("draw import-path evidence requires an exact token-boundary match", () => {
  assert.equal(
    hasExpectedImportPathEvidence("publish dialog showing import preuss_steffen/smc_draw/1 as d", IMPORT_PATH),
    true,
  );
  assert.equal(hasExpectedImportPathEvidence("no path here", IMPORT_PATH), false);
  assert.equal(
    hasExpectedImportPathEvidence("publish dialog showing import preuss_steffen/smc_draw/10 as d", IMPORT_PATH),
    false,
  );
  assert.equal(
    hasExpectedImportPathEvidence("publish dialog showing import preuss_steffen/smc_draw/1 as d", ""),
    false,
  );
});

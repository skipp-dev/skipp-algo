import assert from "node:assert/strict";
import test from "node:test";

import { hasExpectedImportPathEvidence } from "../../../scripts/tv_publish_import_path_evidence.js";

test("shared import-path evidence matcher requires exact token boundaries", () => {
  const expected = "owner_a/smc_micro_profiles_generated/2";

  assert.equal(
    hasExpectedImportPathEvidence("visible import owner_a/smc_micro_profiles_generated/2 as mp", expected),
    true,
  );
  assert.equal(
    hasExpectedImportPathEvidence("visible import owner_a/smc_micro_profiles_generated/20 as mp", expected),
    false,
  );
  assert.equal(
    hasExpectedImportPathEvidence("visible import owner_a/smc_micro_profiles_generated/2.0 as mp", expected),
    false,
  );
  assert.equal(
    hasExpectedImportPathEvidence("visible import prefix_owner_a/smc_micro_profiles_generated/2 as mp", expected),
    false,
  );
  assert.equal(
    hasExpectedImportPathEvidence("visible import owner_a/smc_micro_profiles_generated/2 as mp", ""),
    false,
  );
});

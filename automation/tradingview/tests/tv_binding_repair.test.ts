import assert from "node:assert/strict";
import test from "node:test";

import { repairSelectedSource } from "../../../scripts/tv_verify_consumer_bindings.js";

test("binding repair scrolls a virtualized combobox before opening its options", async () => {
  const calls: string[] = [];
  const combo: any = {
    count: async () => 1,
    first: () => combo,
    isVisible: async () => true,
    scrollIntoViewIfNeeded: async () => { calls.push("scroll"); },
    click: async () => {
      assert.deepEqual(calls, ["scroll", "settle"]);
      calls.push("combo-click");
    },
  };
  const option: any = {
    first: () => option,
    waitFor: async () => {
      assert.equal(calls.at(-1), "combo-click");
      calls.push("option-visible");
    },
    click: async () => { calls.push("option-click"); },
  };
  const fallback: any = { last: () => fallback };
  const labels: any = {
    count: async () => 1,
    locator: () => ({ nth: () => combo }),
  };
  const page: any = {
    getByText: (value: string) => value === "BUS Ready" ? labels : fallback,
    getByRole: () => option,
    waitForTimeout: async () => { calls.push("settle"); },
  };

  await repairSelectedSource(page, "BUS Ready", "SMC Long-Dip Suite: BUS Ready");

  assert.deepEqual(calls, ["scroll", "settle", "combo-click", "option-visible", "option-click"]);
});

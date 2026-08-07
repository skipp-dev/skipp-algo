import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const mathSource = await readFile(
  new URL("../shor-math.js", import.meta.url),
  "utf8",
);
const modelSource = await readFile(
  new URL("./model.js", import.meta.url),
  "utf8",
);
const context = vm.createContext({});
vm.runInContext(mathSource, context, { filename: "shor-math.js" });
vm.runInContext(modelSource, context, { filename: "model.js" });
const model = context.ShorsDemoV2;

test("the 15 walkthrough reproduces the latest presentation", () => {
  const story = model.buildStory(15);

  assert.equal(story.stages.length, 13);
  assert.equal(story.base, 2);
  assert.equal(story.period, 4);
  assert.equal(story.fullPower, 16n);
  assert.equal(story.halfPower, 4n);
  assert.equal(story.difference, 15n);
  assert.equal(story.divisionQuotient, 1n);
  assert.equal(story.lowerCandidate, 3n);
  assert.equal(story.upperCandidate, 5n);
  assert.deepEqual(Array.from(story.factorPair), [3, 5]);
  assert.deepEqual(
    Array.from(story.rows, (row) => Number(row.remainder)),
    [1, 2, 4, 8, 1, 2, 4],
  );
  assert.deepEqual(
    Array.from(story.rows, (row) => row.repeatsExponent),
    [null, null, null, null, 0, 1, 2],
  );
});

test("the prepared 21 and 35 examples retain their expected periods", () => {
  const expectations = new Map([
    [21, { factors: [3, 7], period: 6 }],
    [35, { factors: [5, 7], period: 12 }],
  ]);

  for (const [value, expectation] of expectations) {
    const story = model.buildStory(value);
    assert.equal(story.base, 2);
    assert.equal(story.period, expectation.period);
    assert.deepEqual(Array.from(story.factorPair), expectation.factors);
    assert.equal(
      story.rows.at(story.period).repeatsExponent,
      0,
      `${value} starts its second period at x = r`,
    );
    assert.equal(story.rows.at(story.period + 2).repeatsExponent, 2);
  }
});

test("classical pre-checks produce a concise alternative story", () => {
  for (const value of [49, 60, 97]) {
    const story = model.buildStory(value);
    assert.equal(story.stages.length, 3);
    assert.notEqual(story.result.kind, "period-finding");
  }
});

test("every two-digit number produces a complete V2 story", () => {
  for (let value = 10; value <= 99; value += 1) {
    const story = model.buildStory(value);
    assert.equal(story.modulus, value);
    assert.ok(story.stages.length === 3 || story.stages.length === 13);
    assert.ok(story.stages.every((stage) => stage.title.length > 0));

    if (story.result.kind === "period-finding") {
      assert.equal(story.rows.length, story.period + 3);
      assert.equal(story.rows.at(story.period).repeatsExponent, 0);
      assert.equal(value % Number(story.lowerGcd), 0);
      assert.equal(value % Number(story.upperGcd), 0);
      assert.ok(Number(story.lowerGcd) > 1);
      assert.ok(Number(story.upperGcd) > 1);
    }
  }
});

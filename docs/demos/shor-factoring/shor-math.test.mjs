import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const source = await readFile(
  new URL("./shor-math.js", import.meta.url),
  "utf8",
);
const context = vm.createContext({});
vm.runInContext(source, context, { filename: "shor-math.js" });
const math = context.ShorsMath;

function product(values) {
  return values.reduce((result, value) => result * value, 1);
}

test("the slide examples use the expected successful periods", () => {
  const expected = new Map([
    [15, { base: 2, factorPair: [3, 5], period: 4 }],
    [21, { base: 2, factorPair: [3, 7], period: 6 }],
    [35, { base: 2, factorPair: [5, 7], period: 12 }],
  ]);

  for (const [value, expectation] of expected) {
    const result = math.classify(value);
    const attempt = result.successfulAttempt;
    assert.equal(result.kind, "period-finding");
    assert.equal(attempt.base, expectation.base);
    assert.equal(attempt.sequence.period, expectation.period);
    assert.deepEqual(
      [attempt.factor, attempt.cofactor].sort((a, b) => a - b),
      expectation.factorPair,
    );
  }
});

test("every two-digit input receives a valid classification and factorization", () => {
  for (let value = 10; value <= 99; value += 1) {
    const result = math.classify(value);
    assert.equal(product(result.primeFactors), value, `factorization of ${value}`);
    assert.ok(
      result.primeFactors.every((factor) => math.isPrime(factor)),
      `prime factors of ${value}`,
    );

    if (result.kind === "prime") {
      assert.deepEqual(Array.from(result.primeFactors), [value]);
      continue;
    }

    if (result.kind === "period-finding") {
      const attempt = result.successfulAttempt;
      assert.equal(attempt.status, "success", `successful base for ${value}`);
      assert.equal(
        attempt.factor * attempt.cofactor,
        value,
        `non-trivial split for ${value}`,
      );
      assert.ok(attempt.factor > 1 && attempt.factor < value);
      assert.equal(
        attempt.sequence.values.at(-1).value,
        1,
        `period closes for ${value}`,
      );
    }
  }
});

test("a failed base is preserved as a visible probabilistic retry", () => {
  const failedAttempt = math.analyzeBase(33, 2);
  assert.equal(failedAttempt.status, "minus-one");
  assert.equal(failedAttempt.sequence.period, 10);

  const result = math.classify(33);
  assert.ok(result.attempts.length > 1);
  assert.equal(result.attempts[0].status, "minus-one");
  assert.equal(result.successfulAttempt.status, "success");
});

test("classical shortcuts cover even values, primes, and perfect powers", () => {
  assert.equal(math.classify(60).kind, "even");
  assert.equal(math.classify(97).kind, "prime");

  const square = math.classify(49);
  assert.equal(square.kind, "perfect-power");
  assert.equal(
    square.perfectPower.base ** square.perfectPower.exponent,
    49,
  );
});

test("invalid values are rejected with a presentation-safe message", () => {
  for (const value of [9, 100, 15.5, Number.NaN]) {
    assert.throws(
      () => math.classify(value),
      /Enter a whole number from 10 to 99/,
    );
  }
});

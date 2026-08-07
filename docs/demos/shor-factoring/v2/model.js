(function attachShorDemoV2(globalScope) {
  "use strict";

  const math = globalScope.ShorsMath;
  if (math === undefined) {
    throw new Error("Shor's arithmetic engine must load before the V2 model.");
  }

  const FULL_STORY = Object.freeze([
    ["THE CHALLENGE", "A small answer hides a hard problem"],
    ["THE REFRAME", "Shor changes the question"],
    ["CHOOSE A BASE", "Start with a coprime number"],
    ["MODULAR FUNCTION", "Define the repeating function"],
    ["POWER BY POWER", "Calculate every remainder"],
    ["FULL PATTERN", "See every calculation together"],
    ["PERIOD", "The values repeat after r steps"],
    ["QUANTUM STEP", "The QFT makes the period measurable"],
    ["VALIDATE", "Check that the period is useful"],
    ["ALGEBRAIC BRIDGE", "Turn the period into two candidates"],
    ["EXTRACT FACTORS", "Greatest common divisors reveal the factors"],
    ["RESULT", "The factorization is complete"],
    ["KEY IDEA", "Quantum finds the period; classical math finds the factors"],
  ]);

  const SHORTCUT_STORY = Object.freeze([
    ["CLASSICAL PRE-CHECK", "Inspect the number before using the quantum step"],
    ["RESULT", "Use the structure that is already visible"],
    ["KEY IDEA", "Shor is reserved for the hard case"],
  ]);

  function exactPower(base, exponent) {
    return BigInt(base) ** BigInt(exponent);
  }

  function gcdBigInt(left, right) {
    let a = left < 0n ? -left : left;
    let b = right < 0n ? -right : right;

    while (b !== 0n) {
      const remainder = a % b;
      a = b;
      b = remainder;
    }

    return a;
  }

  function buildRows(modulus, attempt) {
    const period = attempt.sequence.period;
    return Array.from({ length: period + 3 }, (_, exponent) => {
      const power = exactPower(attempt.base, exponent);
      const divisor = BigInt(modulus);
      const quotient = power / divisor;
      const remainder = power % divisor;

      return {
        cycle: Math.floor(exponent / period),
        exponent,
        power,
        quotient,
        remainder,
        repeatsExponent: exponent >= period ? exponent % period : null,
      };
    });
  }

  function buildPeriodFindingStory(result) {
    const attempt = result.successfulAttempt;
    const period = attempt.sequence.period;
    const base = BigInt(attempt.base);
    const modulus = BigInt(result.value);
    const fullPower = base ** BigInt(period);
    const halfPower = base ** BigInt(period / 2);
    const lowerCandidate = halfPower - 1n;
    const upperCandidate = halfPower + 1n;
    const difference = fullPower - 1n;
    const divisionQuotient = difference / modulus;

    return {
      attempt,
      base: attempt.base,
      difference,
      divisionQuotient,
      factorPair: [attempt.factor, attempt.cofactor].sort(
        (left, right) => left - right,
      ),
      fullPower,
      halfPower,
      lowerCandidate,
      lowerGcd: gcdBigInt(lowerCandidate, modulus),
      modulus: result.value,
      period,
      primeFactors: result.primeFactors,
      result,
      rows: buildRows(result.value, attempt),
      stages: FULL_STORY.map(([kicker, title], index) => ({
        index,
        kicker,
        title,
      })),
      upperCandidate,
      upperGcd: gcdBigInt(upperCandidate, modulus),
    };
  }

  function buildShortcutStory(result) {
    return {
      factorPair:
        result.kind === "prime"
          ? [result.value]
          : result.primeFactors,
      modulus: result.value,
      primeFactors: result.primeFactors,
      result,
      stages: SHORTCUT_STORY.map(([kicker, title], index) => ({
        index,
        kicker,
        title,
      })),
    };
  }

  function buildStory(value) {
    const result = math.classify(value);
    if (result.kind === "period-finding") {
      return buildPeriodFindingStory(result);
    }
    return buildShortcutStory(result);
  }

  globalScope.ShorsDemoV2 = Object.freeze({
    buildStory,
    exactPower,
    gcdBigInt,
  });
})(globalThis);

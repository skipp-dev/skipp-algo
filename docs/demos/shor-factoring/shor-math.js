(function attachShorMath(globalScope) {
  "use strict";

  function assertTwoDigitInteger(value) {
    if (!Number.isInteger(value) || value < 10 || value > 99) {
      throw new RangeError("Enter a whole number from 10 to 99.");
    }
  }

  function gcd(left, right) {
    let a = Math.abs(left);
    let b = Math.abs(right);

    while (b !== 0) {
      const remainder = a % b;
      a = b;
      b = remainder;
    }

    return a;
  }

  function modPow(base, exponent, modulus) {
    if (!Number.isInteger(exponent) || exponent < 0) {
      throw new RangeError("The exponent must be a non-negative integer.");
    }
    if (!Number.isInteger(modulus) || modulus < 1) {
      throw new RangeError("The modulus must be a positive integer.");
    }

    let result = 1 % modulus;
    let factor = ((base % modulus) + modulus) % modulus;
    let power = exponent;

    while (power > 0) {
      if (power % 2 === 1) {
        result = (result * factor) % modulus;
      }
      factor = (factor * factor) % modulus;
      power = Math.floor(power / 2);
    }

    return result;
  }

  function isPrime(value) {
    if (!Number.isInteger(value) || value < 2) {
      return false;
    }
    if (value === 2) {
      return true;
    }
    if (value % 2 === 0) {
      return false;
    }

    for (let divisor = 3; divisor * divisor <= value; divisor += 2) {
      if (value % divisor === 0) {
        return false;
      }
    }

    return true;
  }

  function primeFactorization(value) {
    if (!Number.isInteger(value) || value < 2) {
      return [];
    }

    const factors = [];
    let remainder = value;

    for (let divisor = 2; divisor * divisor <= remainder; divisor += 1) {
      while (remainder % divisor === 0) {
        factors.push(divisor);
        remainder /= divisor;
      }
    }

    if (remainder > 1) {
      factors.push(remainder);
    }

    return factors;
  }

  function findPerfectPower(value) {
    if (!Number.isInteger(value) || value < 4) {
      return null;
    }

    const maximumExponent = Math.floor(Math.log2(value));
    for (let exponent = maximumExponent; exponent >= 2; exponent -= 1) {
      const approximateBase = Math.round(value ** (1 / exponent));
      for (
        let base = Math.max(2, approximateBase - 1);
        base <= approximateBase + 1;
        base += 1
      ) {
        if (base ** exponent === value) {
          return { base, exponent };
        }
      }
    }

    return null;
  }

  function modularSequence(base, modulus) {
    if (gcd(base, modulus) !== 1) {
      throw new RangeError("The base and modulus must be coprime.");
    }

    const values = [{ exponent: 0, value: 1 }];
    let current = 1;

    for (let exponent = 1; exponent <= modulus; exponent += 1) {
      current = (current * base) % modulus;
      values.push({ exponent, value: current });
      if (current === 1) {
        return {
          period: exponent,
          values,
        };
      }
    }

    throw new Error("No modular period was found.");
  }

  function nextPowerOfTwo(value) {
    let result = 1;
    while (result < value) {
      result *= 2;
    }
    return result;
  }

  function analyzeBase(modulus, base) {
    const commonDivisor = gcd(base, modulus);
    if (commonDivisor !== 1) {
      return {
        base,
        commonDivisor,
        status: "easy-factor",
        factor: commonDivisor,
        cofactor: modulus / commonDivisor,
      };
    }

    const sequence = modularSequence(base, modulus);
    const quantumRegisterSize = nextPowerOfTwo(modulus * modulus);
    const measuredFrequency = Math.round(
      quantumRegisterSize / sequence.period,
    );
    const approximation = measuredFrequency / quantumRegisterSize;

    if (sequence.period % 2 !== 0) {
      return {
        base,
        commonDivisor,
        sequence,
        quantumRegisterSize,
        measuredFrequency,
        approximation,
        status: "odd-period",
      };
    }

    const halfPowerResidue = modPow(
      base,
      sequence.period / 2,
      modulus,
    );
    if (halfPowerResidue === modulus - 1) {
      return {
        base,
        commonDivisor,
        sequence,
        quantumRegisterSize,
        measuredFrequency,
        approximation,
        halfPowerResidue,
        status: "minus-one",
      };
    }

    const lowerGcd = gcd(halfPowerResidue - 1, modulus);
    const upperGcd = gcd(halfPowerResidue + 1, modulus);
    const discoveredFactor = [lowerGcd, upperGcd].find(
      (candidate) => candidate > 1 && candidate < modulus,
    );

    if (discoveredFactor === undefined) {
      return {
        base,
        commonDivisor,
        sequence,
        quantumRegisterSize,
        measuredFrequency,
        approximation,
        halfPowerResidue,
        lowerGcd,
        upperGcd,
        status: "trivial-factors",
      };
    }

    const discoveredCofactor = modulus / discoveredFactor;
    const factor = Math.min(discoveredFactor, discoveredCofactor);
    const cofactor = Math.max(discoveredFactor, discoveredCofactor);

    return {
      base,
      commonDivisor,
      sequence,
      quantumRegisterSize,
      measuredFrequency,
      approximation,
      halfPowerResidue,
      lowerGcd,
      upperGcd,
      status: "success",
      factor,
      cofactor,
    };
  }

  function findPeriodAttempts(modulus) {
    const attempts = [];

    for (let base = 2; base < modulus; base += 1) {
      if (gcd(base, modulus) !== 1) {
        continue;
      }

      const attempt = analyzeBase(modulus, base);
      attempts.push(attempt);
      if (attempt.status === "success") {
        return attempts;
      }
    }

    throw new Error(`No successful period-finding base exists for ${modulus}.`);
  }

  function classify(value) {
    assertTwoDigitInteger(value);

    if (isPrime(value)) {
      return {
        kind: "prime",
        value,
        primeFactors: [value],
      };
    }

    const primeFactors = primeFactorization(value);
    if (value % 2 === 0) {
      return {
        kind: "even",
        value,
        factor: 2,
        cofactor: value / 2,
        primeFactors,
      };
    }

    const perfectPower = findPerfectPower(value);
    if (perfectPower !== null) {
      return {
        kind: "perfect-power",
        value,
        perfectPower,
        primeFactors,
      };
    }

    const attempts = findPeriodAttempts(value);
    const successfulAttempt = attempts.at(-1);
    return {
      kind: "period-finding",
      value,
      attempts,
      successfulAttempt,
      primeFactors,
    };
  }

  globalScope.ShorsMath = Object.freeze({
    analyzeBase,
    assertTwoDigitInteger,
    classify,
    findPerfectPower,
    gcd,
    isPrime,
    modPow,
    modularSequence,
    nextPowerOfTwo,
    primeFactorization,
  });
})(globalThis);

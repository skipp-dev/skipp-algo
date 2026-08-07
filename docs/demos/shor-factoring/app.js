(function startFactoringDemo() {
  "use strict";

  const math = globalThis.ShorsMath;
  if (math === undefined) {
    throw new Error("The factoring engine could not be loaded.");
  }

  const elements = {
    autoButton: document.getElementById("auto-button"),
    detailToggle: document.getElementById("detail-toggle"),
    exampleButtons: Array.from(document.querySelectorAll("[data-example]")),
    form: document.getElementById("number-form"),
    heroTitle: document.getElementById("hero-title"),
    input: document.getElementById("number-input"),
    inputError: document.getElementById("input-error"),
    inputHelp: document.getElementById("input-help"),
    nextButton: document.getElementById("next-button"),
    phaseLabel: document.getElementById("phase-label"),
    previousButton: document.getElementById("previous-button"),
    progressBar: document.querySelector("[role='progressbar']"),
    progressFill: document.getElementById("progress-fill"),
    stepCount: document.getElementById("step-count"),
    stepTitle: document.getElementById("step-title"),
    stepVisual: document.getElementById("step-visual"),
    walkthrough: document.querySelector(".walkthrough"),
  };

  let analysis;
  let steps = [];
  let currentStep = 0;
  let autoPlayTimer = null;
  let activeStepAnimationFrame = null;
  let activeStepResizeObserver = null;

  function factorText(factors) {
    return factors.join(" × ");
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

  function exactAttemptValues(result, attempt) {
    const base = BigInt(attempt.base);
    const modulus = BigInt(result.value);
    const period = BigInt(attempt.sequence.period);
    const fullPower = base ** period;
    const halfPower =
      attempt.sequence.period % 2 === 0 ? base ** (period / 2n) : null;

    if (halfPower === null) {
      return {
        base,
        fullPower,
        modulus,
        period,
      };
    }

    const lowerCandidate = halfPower - 1n;
    const upperCandidate = halfPower + 1n;
    return {
      base,
      fullPower,
      halfPower,
      lowerCandidate,
      lowerGcd: gcdBigInt(lowerCandidate, modulus),
      modulus,
      period,
      upperCandidate,
      upperGcd: gcdBigInt(upperCandidate, modulus),
    };
  }

  function buildSteps(result) {
    if (result.kind !== "period-finding") {
      return [
        {
          kind: "shortcut",
          phase: "CLASSICAL PRE-CHECK",
          result,
          title:
            result.kind === "prime"
              ? `${result.value} is already prime`
              : "A classical shortcut finds the structure",
        },
        {
          kind: "result",
          phase: "RESULT",
          result,
          title:
            result.kind === "prime"
              ? "No non-trivial factors exist"
              : `The prime factors of ${result.value}`,
        },
      ];
    }

    const walkthroughSteps = [];
    result.attempts.forEach((attempt, attemptIndex) => {
      const attemptNumber = attemptIndex + 1;
      walkthroughSteps.push(
        {
          attempt,
          attemptNumber,
          kind: "choose-base",
          phase: `STEP 1 · ATTEMPT ${attemptNumber}`,
          result,
          title:
            attemptNumber === 1
              ? "Choose a candidate base a"
              : "Choose another candidate base a",
        },
        {
          attempt,
          attemptNumber,
          kind: "periodic-function",
          phase: "STEP 2",
          result,
          title: "Define and evaluate the periodic function",
        },
        {
          attempt,
          attemptNumber,
          kind: "quantum-period",
          phase: "STEP 3",
          result,
          title: "Use the quantum computer to find the period",
        },
        {
          attempt,
          attemptNumber,
          kind: "validate-period",
          phase: "STEP 4",
          result,
          title: "Check whether the period is usable",
        },
      );

      if (attempt.status === "success") {
        walkthroughSteps.push(
          {
            attempt,
            attemptNumber,
            kind: "candidates",
            phase: "STEP 5",
            result,
            title: "Form the two factor candidates",
          },
          {
            attempt,
            attemptNumber,
            kind: "gcd",
            phase: "STEP 6",
            result,
            title: "Calculate the greatest common divisors",
          },
        );
      } else {
        walkthroughSteps.push({
          attempt,
          attemptNumber,
          kind: "retry",
          phase: "RETRY",
          result,
          title: "This base does not produce useful factors",
        });
      }
    });

    walkthroughSteps.push(
      {
        kind: "result",
        phase: "RESULT",
        result,
        title: `The factors of ${result.value}`,
      },
      {
        kind: "summary",
        phase: "THE KEY IDEA",
        result,
        title: "Period finding is the quantum shortcut",
      },
    );
    return walkthroughSteps;
  }

  function renderChooseBase(step) {
    const { attempt, attemptNumber, result } = step;
    return `
      <div class="visual-stack">
        <p class="explanation">
          We want two non-trivial factors of
          <strong>N = ${result.value}</strong>. A real run chooses a random
          integer a with 1 &lt; a &lt; N. This reproducible walkthrough uses:
        </p>
        <div class="equation">
          N = ${result.value}
          <span class="equation-divider">·</span>
          a = <span class="accent-orange">${attempt.base}</span>
        </div>
        <div class="factor-grid">
          <div class="factor-item">
            <span>Required range</span>
            <strong>1 &lt; ${attempt.base} &lt; ${result.value} ✓</strong>
          </div>
          <div class="factor-item">
            <span>First check</span>
            <strong>gcd(${attempt.base}, ${result.value}) = ${attempt.commonDivisor}</strong>
          </div>
          <div class="factor-item">
            <span>Meaning</span>
            <strong>Coprime—continue to period finding</strong>
          </div>
        </div>
        <div class="success-banner">
          Attempt ${attemptNumber}: no factor was found by the initial gcd, so
          the period-finding part of Shor's algorithm is needed.
        </div>
      </div>
    `;
  }

  function periodicRows(result, attempt) {
    const period = attempt.sequence.period;
    const rowCount = period + 3;
    return Array.from({ length: rowCount }, (_, exponent) => {
      const exactPower = BigInt(attempt.base) ** BigInt(exponent);
      const residue = math.modPow(attempt.base, exponent, result.value);
      const quotient = exactPower / BigInt(result.value);
      return {
        exactPower,
        exponent,
        quotient,
        repeatedExponent: exponent >= period ? exponent - period : null,
        residue,
      };
    });
  }

  function renderPeriodicFunction(step) {
    const { attempt, result } = step;
    const period = attempt.sequence.period;
    const rows = periodicRows(result, attempt);
    const tableRows = rows
      .map((row) => {
        const repeated = row.repeatedExponent !== null;
        const note = repeated
          ? `Repeats f(${row.repeatedExponent})`
          : row.exponent === 0
            ? "Starting value"
            : "New value";
        return `
          <tr
            class="${repeated ? "repeat-row" : ""}"
            style="--item-index: ${row.exponent}"
          >
            <td>${row.exponent}</td>
            <td>${attempt.base}<sup>${row.exponent}</sup> = ${row.exactPower}</td>
            <td>
              ${row.exactPower} = ${row.quotient} × ${result.value} + ${row.residue}
            </td>
            <td>f(${row.exponent}) = ${row.residue}</td>
            <td>${note}</td>
          </tr>
        `;
      })
      .join("");
    const sequence = rows
      .map(
        (row) =>
          `<span
            class="${row.repeatedExponent !== null ? "sequence-repeat" : ""}"
            style="--item-index: ${row.exponent}"
          >${row.residue}</span>`,
      )
      .join('<span aria-hidden="true">, </span>');

    return `
      <div class="visual-stack article-step">
        <p class="explanation">
          Define
          <strong>f(x) = ${attempt.base}<sup>x</sup> mod ${result.value}</strong>.
          “Modulo ${result.value}” means: calculate the power, divide by
          ${result.value}, and keep only the remainder.
        </p>
        <div class="equation formula-callout">
          f(x) = ${attempt.base}<sup>x</sup> mod ${result.value}
        </div>
        <div class="modulo-method" aria-label="How to calculate each modulo value">
          <div>
            <span>1 · Calculate the power</span>
            <strong>${attempt.base}<sup>x</sup></strong>
          </div>
          <div>
            <span>2 · Divide with a remainder</span>
            <strong>${attempt.base}<sup>x</sup> = q × ${result.value} + remainder</strong>
          </div>
          <div>
            <span>3 · Keep the remainder</span>
            <strong>f(x) = remainder</strong>
          </div>
        </div>
        <div class="table-responsive">
          <table class="modulo-table">
            <caption>
              Every row shows the power, division, and retained remainder
            </caption>
            <thead>
              <tr>
                <th scope="col">x</th>
                <th scope="col">Calculate the power</th>
                <th scope="col">Divide by ${result.value}</th>
                <th scope="col">Keep the remainder</th>
                <th scope="col">Pattern</th>
              </tr>
            </thead>
            <tbody>${tableRows}</tbody>
          </table>
        </div>
        <div class="sequence-line" aria-label="Residue sequence">
          ${sequence}
        </div>
        <div class="success-banner">
          At x = ${period}, the value 1 repeats. The pattern therefore has
          length <strong>r = ${period}</strong>.
        </div>
      </div>
    `;
  }

  function renderQuantumPeriod(step) {
    const { attempt, result } = step;
    const period = attempt.sequence.period;
    const basisTerms = periodicRows(result, attempt)
      .slice(0, 5)
      .map(
        (row) =>
          `<span>|${row.exponent}⟩|${row.residue}⟩</span>`,
      )
      .join('<span aria-hidden="true"> + </span>');
    return `
      <div class="visual-stack article-step">
        <p class="explanation">
          A classical search evaluates the modular powers one after another.
          The quantum computer instead creates a superposition of many x-values
          and evaluates the function across that superposition.
        </p>
        <div class="quantum-state" aria-label="Simplified quantum state">
          ${basisTerms}<span aria-hidden="true"> + …</span>
        </div>
        <div class="quantum-explanation-grid">
          <div>
            <span>1 · Superposition</span>
            <p>Many candidate x-values are represented at the same time.</p>
          </div>
          <div>
            <span>2 · Hidden repetition</span>
            <p>The function values repeat every ${period} steps.</p>
          </div>
          <div>
            <span>3 · QFT measurement</span>
            <p>Frequency peaks reveal the hidden period.</p>
          </div>
        </div>
        <div class="compact-period-layout">
          <div class="qft-animation-panel">
            <canvas
              class="qft-canvas"
              data-period="${period}"
              data-qft-canvas
              role="img"
              aria-label="Animated quantum Fourier transform: a broad superposition becomes ${period} frequency peaks"
            ></canvas>
            <div class="peak-axis" aria-hidden="true">
              <span>0</span><span>QFT frequency</span><span>Q</span>
            </div>
            <div class="qft-stage-label" data-qft-status>
              Superposition: many possible frequencies
            </div>
          </div>
          <div class="period-delivery">
            <span>Quantum output</span>
            <strong>r = ${period}</strong>
            <p>The classical part can now continue.</p>
          </div>
        </div>
        <p class="detail-only detail-text">
          Illustrated measurement:
          ${attempt.measuredFrequency}/${attempt.quantumRegisterSize}
          ≈ ${attempt.approximation.toFixed(6)}. A continued-fraction step
          reconstructs the denominator r = ${period}.
        </p>
      </div>
    `;
  }

  function validationReason(attempt, result, exactValues) {
    if (attempt.status === "odd-period") {
      return {
        heading: `r = ${attempt.sequence.period} is odd`,
        message:
          "Shor's classical post-processing needs an even period so that r/2 is an integer.",
      };
    }
    if (attempt.status === "minus-one") {
      return {
        heading: `${attempt.base}^(r/2) mod ${result.value} = ${result.value - 1}`,
        message:
          "This is congruent to −1 modulo N, which would produce only trivial gcd results.",
      };
    }
    if (attempt.status !== "success") {
      return {
        heading: "Only trivial factors were produced",
        message: "A different base is required.",
      };
    }
    return {
      heading: "The period is usable",
      message: `r is even and ${exactValues.halfPower} is not congruent to ±1 modulo ${result.value}.`,
    };
  }

  function renderValidatePeriod(step) {
    const { attempt, result } = step;
    const exactValues = exactAttemptValues(result, attempt);
    const period = attempt.sequence.period;
    const validation = validationReason(attempt, result, exactValues);

    if (period % 2 !== 0) {
      return `
        <div class="visual-stack">
          <div class="equation">r = <span class="accent-orange">${period}</span></div>
          <p class="explanation">${validation.message}</p>
          <div class="retry-banner">${validation.heading}—choose another base.</div>
        </div>
      `;
    }

    const halfPowerQuotient = exactValues.halfPower / exactValues.modulus;

    return `
      <div class="visual-stack article-step">
        <p class="explanation">
          The period must be even. Then calculate
          <strong>y = a<sup>r/2</sup></strong> and make sure it is not congruent
          to ±1 modulo N.
        </p>
        <div class="factor-grid">
          <div class="factor-item">
            <span>Parity check</span>
            <strong>r = ${period} is even ✓</strong>
          </div>
          <div class="factor-item">
            <span>Half-period power</span>
            <strong>
              y = ${attempt.base}<sup>${period}/2</sup>
              = ${attempt.base}<sup>${period / 2}</sup>
              = ${exactValues.halfPower}
            </strong>
          </div>
          <div class="factor-item modulo-breakdown">
            <span>Modulo check</span>
            <strong>
              Divide ${exactValues.halfPower} by ${result.value}
            </strong>
            <strong>
              ${exactValues.halfPower} = ${halfPowerQuotient} ×
              ${result.value} + ${attempt.halfPowerResidue}
            </strong>
            <strong class="modulo-result">
              Therefore ${exactValues.halfPower} mod ${result.value}
              = ${attempt.halfPowerResidue}
            </strong>
          </div>
        </div>
        <div class="${attempt.status === "success" ? "success-banner" : "retry-banner"}">
          <strong>${validation.heading}.</strong> ${validation.message}
        </div>
      </div>
    `;
  }

  function renderCandidates(step) {
    const { attempt, result } = step;
    const values = exactAttemptValues(result, attempt);
    const difference = values.fullPower - 1n;
    const quotient = difference / values.modulus;

    return `
      <div class="visual-stack article-step">
        <p class="explanation">
          Periodicity means that after applying modulo N, the result equals 1:
          <strong>a<sup>r</sup> mod N = 1</strong>. In ordinary division form,
          this is <strong>a<sup>r</sup> = q × N + 1</strong>. Subtracting 1
          therefore produces a number that is exactly divisible by N.
        </p>
        <div class="equation formula-callout">
          a<sup>r</sup> − 1 =
          (a<sup>r/2</sup> − 1)(a<sup>r/2</sup> + 1)
        </div>
        <div class="derivation-stack">
          <div>
            <span>1 · Evaluate the period power</span>
            <p>
              ${attempt.base}<sup>${attempt.sequence.period}</sup>
              = ${values.fullPower}
            </p>
          </div>
          <div>
            <span>2 · Verify that its remainder is 1</span>
            <p>
              ${values.fullPower} = ${quotient} × ${values.modulus} + 1,
              so ${attempt.base}<sup>${attempt.sequence.period}</sup>
              mod ${values.modulus} = 1
            </p>
          </div>
          <div>
            <span>3 · Subtract the remainder</span>
            <p>
              ${attempt.base}<sup>${attempt.sequence.period}</sup> − 1
              = ${values.fullPower} − 1 = ${difference}
            </p>
          </div>
          <div>
            <span>4 · Show exact divisibility by N</span>
            <p>
              ${difference} ÷ ${values.modulus} = ${quotient},
              therefore ${difference} = ${values.modulus} × ${quotient}
            </p>
          </div>
          <div>
            <span>5 · Factor the same number as a difference of squares</span>
            <p>
              ${difference} =
              (${values.halfPower} − 1)(${values.halfPower} + 1)
              = ${values.lowerCandidate} × ${values.upperCandidate}
            </p>
          </div>
        </div>
        <div class="candidate-grid">
          <div>
            <span>First candidate</span>
            <strong>y − 1 = ${values.halfPower} − 1 = ${values.lowerCandidate}</strong>
          </div>
          <div>
            <span>Second candidate</span>
            <strong>y + 1 = ${values.halfPower} + 1 = ${values.upperCandidate}</strong>
          </div>
        </div>
        <div class="success-banner">
          The same number ${difference} is both
          <strong>${values.modulus} × ${quotient}</strong> and
          <strong>${values.lowerCandidate} × ${values.upperCandidate}</strong>.
          This does not yet mean that the two candidates are the factors of N.
          Step 6 compares each candidate with N using gcd to reveal the shared
          factors.
        </div>
      </div>
    `;
  }

  function renderGcd(step) {
    const { attempt, result } = step;
    const values = exactAttemptValues(result, attempt);
    const factors = [Number(values.lowerGcd), Number(values.upperGcd)].sort(
      (left, right) => left - right,
    );

    return `
      <div class="visual-stack article-step">
        <p class="explanation">
          Extract the shared parts of each candidate and N with two ordinary
          greatest-common-divisor calculations.
        </p>
        <div class="gcd-grid">
          <div>
            <span>First gcd</span>
            <div class="gcd-equation">
              gcd(${values.lowerCandidate}, ${result.value})
              = <strong>${values.lowerGcd}</strong>
            </div>
          </div>
          <div>
            <span>Second gcd</span>
            <div class="gcd-equation">
              gcd(${values.upperCandidate}, ${result.value})
              = <strong>${values.upperGcd}</strong>
            </div>
          </div>
        </div>
        <div class="equation result-equation">
          ${result.value} =
          <span class="accent-green">${factors[0]} × ${factors[1]}</span>
        </div>
        <div class="success-banner">
          Both gcd results are non-trivial factors of ${result.value}.
        </div>
      </div>
    `;
  }

  function renderRetry(step) {
    const { attempt, result } = step;
    const reason =
      attempt.status === "odd-period"
        ? `The period r = ${attempt.sequence.period} is odd.`
        : attempt.status === "minus-one"
          ? `${attempt.base}^(r/2) is congruent to −1 modulo ${result.value}.`
          : "The gcd calculations would be trivial.";
    return `
      <div class="visual-stack">
        <div class="equation">
          a = ${attempt.base} <span class="accent-orange">→ retry</span>
        </div>
        <p class="explanation">${reason}</p>
        <div class="retry-banner">
          This is expected: Shor's algorithm is probabilistic. Keep N fixed and
          repeat the process with another coprime base.
        </div>
      </div>
    `;
  }

  function renderShortcut(step) {
    const { result } = step;
    if (result.kind === "prime") {
      return `
        <div class="visual-stack">
          <div class="equation">
            <span class="accent-green">${result.value} is prime</span>
          </div>
          <p class="explanation">
            No integer from 2 through √${result.value} divides ${result.value}.
            A prime has no non-trivial factor pair, so quantum period finding is
            unnecessary.
          </p>
        </div>
      `;
    }

    const explanation =
      result.kind === "even"
        ? `${result.value} is even, so 2 is an immediate factor.`
        : `${result.value} is the perfect power ${result.perfectPower.base}^${result.perfectPower.exponent}.`;
    return `
      <div class="visual-stack">
        <div class="equation">
          ${result.value} =
          <span class="accent-green">${factorText(result.primeFactors)}</span>
        </div>
        <p class="explanation">${explanation}</p>
        <div class="success-banner">
          The classical pre-check is faster and simpler than quantum period
          finding for this input.
        </div>
      </div>
    `;
  }

  function renderResult(step) {
    const { result } = step;
    if (result.kind === "prime") {
      return renderShortcut(step);
    }

    if (result.kind !== "period-finding") {
      return `
        <div class="visual-stack">
          <span class="result-mark" aria-hidden="true">✓</span>
          <div class="equation">
            ${result.value} =
            <span class="accent-green">${factorText(result.primeFactors)}</span>
          </div>
          <p class="explanation">The complete prime factorization is shown above.</p>
        </div>
      `;
    }

    const attempt = result.successfulAttempt;
    const factors = [attempt.factor, attempt.cofactor].sort(
      (left, right) => left - right,
    );
    const bothPrime = factors.every((factor) => math.isPrime(factor));
    return `
      <div class="visual-stack">
        <span class="result-mark" aria-hidden="true">✓</span>
        <div class="equation result-equation">
          ${result.value} =
          <span class="accent-green">${factors[0]} × ${factors[1]}</span>
        </div>
        <p class="explanation">
          ${
            bothPrime
              ? `${factors[0]} and ${factors[1]} are both prime. The factorization is complete.`
              : `At least one factor is composite. Continue recursively for the prime factorization ${factorText(result.primeFactors)}.`
          }
        </p>
      </div>
    `;
  }

  function renderSummary(step) {
    const { result } = step;
    const attempt = result.successfulAttempt;
    const values = exactAttemptValues(result, attempt);
    const factors = [Number(values.lowerGcd), Number(values.upperGcd)].sort(
      (left, right) => left - right,
    );
    return `
      <div class="summary-layout">
        <div class="summary-calculation">
          <p>N = ${result.value}</p>
          <p>a = ${attempt.base}</p>
          <p>gcd(${attempt.base}, ${result.value}) = 1</p>
          <p>period of ${attempt.base}<sup>x</sup> mod ${result.value}: r = ${attempt.sequence.period}</p>
          <p>
            y = ${attempt.base}<sup>${attempt.sequence.period}/2</sup>
            = ${values.halfPower}
          </p>
          <p>
            gcd(${values.lowerCandidate}, ${result.value}) = ${values.lowerGcd}
          </p>
          <p>
            gcd(${values.upperCandidate}, ${result.value}) = ${values.upperGcd}
          </p>
          <p class="summary-result">
            ${result.value} = ${factors[0]} × ${factors[1]}
          </p>
        </div>
        <div class="key-idea">
          <span>The most important idea</span>
          <p>
            The quantum computer does not factor ${result.value} directly. It
            efficiently solves the hard subproblem:
          </p>
          <strong>
            Find the period of a<sup>x</sup> mod N.
          </strong>
          <p>
            Once r = ${attempt.sequence.period} is known, classical gcd
            calculations reveal the factors.
          </p>
        </div>
      </div>
    `;
  }

  function stopStepAnimation() {
    if (activeStepAnimationFrame !== null) {
      globalThis.cancelAnimationFrame(activeStepAnimationFrame);
      activeStepAnimationFrame = null;
    }
    if (activeStepResizeObserver !== null) {
      activeStepResizeObserver.disconnect();
      activeStepResizeObserver = null;
    }
  }

  function startQuantumCanvas(canvas, period) {
    const context = canvas.getContext("2d");
    const status = canvas.parentElement.querySelector("[data-qft-status]");
    const styles = globalThis.getComputedStyle(document.documentElement);
    const colors = {
      border: styles.getPropertyValue("--border").trim(),
      green: styles.getPropertyValue("--green").trim(),
      ink: styles.getPropertyValue("--soft-ink").trim(),
      orange: styles.getPropertyValue("--orange").trim(),
      teal: styles.getPropertyValue("--teal").trim(),
    };
    const reducedMotion = globalThis.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    let width = 1;
    let height = 1;
    let startTime = null;
    let currentStage = "";

    function resize() {
      const bounds = canvas.getBoundingClientRect();
      const pixelRatio = Math.min(globalThis.devicePixelRatio || 1, 2);
      width = Math.max(1, bounds.width);
      height = Math.max(1, bounds.height);
      canvas.width = Math.round(width * pixelRatio);
      canvas.height = Math.round(height * pixelRatio);
      context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    }

    function smoothStep(value) {
      const clamped = Math.max(0, Math.min(1, value));
      return clamped * clamped * (3 - 2 * clamped);
    }

    function updateStatus(stage) {
      if (stage === currentStage) {
        return;
      }
      currentStage = stage;
      const messages = {
        applying: "Applying QFT: amplitudes interfere",
        peaks: `Result: ${period} periodic frequency peaks reveal r = ${period}`,
        reset: "Preparing the superposition again",
        superposition: "Superposition: many possible frequencies",
      };
      status.textContent = messages[stage];
      status.dataset.stage = stage;
    }

    function draw(timestamp) {
      if (startTime === null) {
        startTime = timestamp;
      }
      const elapsed = reducedMotion ? 4.2 : (timestamp - startTime) / 1000;
      const cycle = elapsed % 7;
      let transition;
      let stage;
      if (cycle < 1.2) {
        transition = 0;
        stage = "superposition";
      } else if (cycle < 3.5) {
        transition = smoothStep((cycle - 1.2) / 2.3);
        stage = "applying";
      } else if (cycle < 5.7) {
        transition = 1;
        stage = "peaks";
      } else {
        transition = 1 - smoothStep((cycle - 5.7) / 1.3);
        stage = "reset";
      }
      updateStatus(stage);

      context.clearRect(0, 0, width, height);
      const paddingX = 22;
      const top = 18;
      const baseline = height - 24;
      const chartHeight = Math.max(80, baseline - top);
      const peakCount = Math.max(2, Math.min(period, 12));
      const barCount = Math.max(24, Math.min(72, peakCount * 5));
      const barSlot = (width - paddingX * 2) / barCount;

      context.save();
      context.globalAlpha = 0.26;
      context.strokeStyle = colors.border;
      context.lineWidth = 1;
      for (let row = 1; row <= 3; row += 1) {
        const y = top + (chartHeight * row) / 4;
        context.beginPath();
        context.moveTo(paddingX, y);
        context.lineTo(width - paddingX, y);
        context.stroke();
      }
      context.restore();

      for (let index = 0; index < barCount; index += 1) {
        const x = paddingX + index * barSlot;
        const uniform =
          0.3 +
          0.055 * Math.sin(elapsed * 3 + index * 0.63) +
          0.025 * Math.cos(elapsed * 1.7 + index);
        const peakPosition = (index * peakCount) / barCount;
        const distanceToPeak = Math.abs(
          peakPosition - Math.round(peakPosition),
        );
        const peak =
          0.045 + 0.89 * Math.exp(-(distanceToPeak ** 2) / 0.007);
        const magnitude = uniform + (peak - uniform) * transition;
        const barHeight = Math.max(3, chartHeight * magnitude);
        const isPeak = peak > 0.65;

        context.save();
        context.globalAlpha =
          0.4 + transition * (isPeak ? 0.48 : -0.2);
        context.fillStyle =
          transition > 0.48 && isPeak ? colors.green : colors.teal;
        context.fillRect(
          x + Math.max(1, barSlot * 0.16),
          baseline - barHeight,
          Math.max(2, barSlot * 0.66),
          barHeight,
        );
        if (transition > 0.55 && isPeak) {
          context.globalAlpha = 0.34 * transition;
          context.fillStyle = colors.orange;
          context.beginPath();
          context.arc(
            x + barSlot / 2,
            baseline - barHeight,
            3.5 + Math.sin(elapsed * 4) * 0.7,
            0,
            Math.PI * 2,
          );
          context.fill();
        }
        context.restore();
      }

      context.save();
      context.strokeStyle = colors.border;
      context.lineWidth = 1.5;
      context.beginPath();
      context.moveTo(paddingX, baseline);
      context.lineTo(width - paddingX, baseline);
      context.stroke();
      context.restore();

      if (reducedMotion) {
        activeStepAnimationFrame = null;
        return;
      }
      activeStepAnimationFrame = globalThis.requestAnimationFrame(draw);
    }

    resize();
    if (typeof ResizeObserver !== "undefined") {
      activeStepResizeObserver = new ResizeObserver(resize);
      activeStepResizeObserver.observe(canvas);
    }
    activeStepAnimationFrame = globalThis.requestAnimationFrame(draw);
  }

  function renderCurrentStep() {
    const step = steps[currentStep];
    const renderers = {
      candidates: renderCandidates,
      "choose-base": renderChooseBase,
      gcd: renderGcd,
      "periodic-function": renderPeriodicFunction,
      "quantum-period": renderQuantumPeriod,
      result: renderResult,
      retry: renderRetry,
      shortcut: renderShortcut,
      summary: renderSummary,
      "validate-period": renderValidatePeriod,
    };

    stopStepAnimation();
    elements.phaseLabel.textContent = step.phase;
    elements.stepTitle.textContent = step.title;
    elements.stepCount.textContent = `Step ${currentStep + 1} of ${steps.length}`;
    elements.stepVisual.innerHTML = renderers[step.kind](step);
    const quantumCanvas = elements.stepVisual.querySelector("[data-qft-canvas]");
    if (quantumCanvas !== null) {
      startQuantumCanvas(
        quantumCanvas,
        Number(quantumCanvas.dataset.period),
      );
    }

    const progress = ((currentStep + 1) / steps.length) * 100;
    elements.progressFill.style.width = `${progress}%`;
    elements.progressBar.setAttribute("aria-valuemax", String(steps.length));
    elements.progressBar.setAttribute("aria-valuenow", String(currentStep + 1));
    elements.previousButton.disabled = currentStep === 0;

    const atEnd = currentStep === steps.length - 1;
    elements.nextButton.textContent = atEnd ? "Start over ↺" : "Next →";
    if (atEnd && autoPlayTimer !== null) {
      stopAutoPlay();
    }
  }

  function selectExampleButton(value) {
    elements.exampleButtons.forEach((button) => {
      const selected = Number(button.dataset.example) === value;
      button.classList.toggle("is-selected", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
  }

  function loadNumber(value) {
    try {
      math.assertTwoDigitInteger(value);
      analysis = math.classify(value);
    } catch (error) {
      elements.inputError.textContent = error.message;
      elements.inputError.hidden = false;
      elements.inputHelp.hidden = true;
      elements.input.setAttribute("aria-invalid", "true");
      return false;
    }

    stopAutoPlay();
    steps = buildSteps(analysis);
    currentStep = 0;
    elements.heroTitle.textContent = `Factor ${value} with Shor's algorithm`;
    elements.input.value = String(value);
    elements.inputError.textContent = "";
    elements.inputError.hidden = true;
    elements.inputHelp.hidden = false;
    elements.input.removeAttribute("aria-invalid");
    selectExampleButton(value);
    renderCurrentStep();
    return true;
  }

  function nextStep() {
    currentStep =
      currentStep === steps.length - 1 ? 0 : currentStep + 1;
    renderCurrentStep();
  }

  function previousStep() {
    if (currentStep > 0) {
      currentStep -= 1;
      renderCurrentStep();
    }
  }

  function stopAutoPlay() {
    if (autoPlayTimer !== null) {
      globalThis.clearInterval(autoPlayTimer);
      autoPlayTimer = null;
    }
    elements.autoButton.textContent = "Auto play";
    elements.autoButton.setAttribute("aria-pressed", "false");
  }

  function toggleAutoPlay() {
    if (autoPlayTimer !== null) {
      stopAutoPlay();
      return;
    }
    if (currentStep === steps.length - 1) {
      currentStep = 0;
      renderCurrentStep();
    }
    elements.autoButton.textContent = "Pause";
    elements.autoButton.setAttribute("aria-pressed", "true");
    autoPlayTimer = globalThis.setInterval(() => {
      if (currentStep === steps.length - 1) {
        stopAutoPlay();
        return;
      }
      currentStep += 1;
      renderCurrentStep();
    }, 6000);
  }

  elements.form.addEventListener("submit", (event) => {
    event.preventDefault();
    loadNumber(Number(elements.input.value));
  });

  elements.exampleButtons.forEach((button) => {
    button.addEventListener("click", () => {
      loadNumber(Number(button.dataset.example));
    });
  });

  elements.previousButton.addEventListener("click", previousStep);
  elements.nextButton.addEventListener("click", nextStep);
  elements.autoButton.addEventListener("click", toggleAutoPlay);
  elements.detailToggle.addEventListener("change", () => {
    elements.walkthrough.classList.toggle(
      "show-details",
      elements.detailToggle.checked,
    );
  });

  document.addEventListener("keydown", (event) => {
    if (
      event.target instanceof HTMLInputElement ||
      event.target instanceof HTMLButtonElement
    ) {
      return;
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      nextStep();
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      previousStep();
    } else if (event.key === " ") {
      event.preventDefault();
      toggleAutoPlay();
    }
  });

  loadNumber(21);
})();

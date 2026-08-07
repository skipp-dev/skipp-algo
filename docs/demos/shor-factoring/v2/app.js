(function startSlideLedWalkthrough() {
  "use strict";

  const math = globalThis.ShorsMath;
  const model = globalThis.ShorsDemoV2;
  if (math === undefined || model === undefined) {
    throw new Error("The V2 walkthrough could not load its arithmetic model.");
  }

  const elements = {
    content: document.getElementById("stage-content"),
    counter: document.getElementById("stage-counter"),
    error: document.getElementById("input-error"),
    form: document.getElementById("number-form"),
    input: document.getElementById("number-input"),
    kicker: document.getElementById("stage-kicker"),
    next: document.getElementById("next-button"),
    presets: Array.from(document.querySelectorAll("[data-example]")),
    previous: document.getElementById("previous-button"),
    progress: document.getElementById("progress-fill"),
    resultPreview: document.getElementById("result-preview"),
    stage: document.getElementById("stage"),
    stageButtons: document.getElementById("stage-buttons"),
    title: document.getElementById("stage-title"),
  };

  let story = model.buildStory(15);
  let stageIndex = 0;
  let powerIndex = 0;
  let powerTimer = null;

  function factorText(factors) {
    return factors.join(" × ");
  }

  function powerExpression(base, exponent, power) {
    return `${base}<sup>${exponent}</sup> = ${power}`;
  }

  function fullResultText(currentStory) {
    if (currentStory.result.kind === "prime") {
      return `${currentStory.modulus} is prime`;
    }
    return `${currentStory.modulus} = ${factorText(currentStory.primeFactors)}`;
  }

  function renderChallenge(currentStory) {
    const factors = currentStory.factorPair;
    return `
      <div class="challenge-layout">
        <div class="challenge-copy reveal">
          <p class="large-copy">
            Ask someone which smaller numbers multiply to make
            <strong>${currentStory.modulus}</strong>, and the answer feels easy.
            Scale the number to hundreds of digits, and the same question can
            defeat classical computers.
          </p>
          <p class="support-copy">
            Shor's algorithm does not guess the factors directly. It turns
            factoring into a pattern-finding problem that a quantum computer
            can address efficiently.
          </p>
        </div>
        <div class="comparison reveal reveal-delay-1">
          <div class="comparison-example easy">
            <span>A SMALL NUMBER</span>
            <strong>${currentStory.modulus} = ${factors[0]} × ${factors[1]}</strong>
            <p>Seconds by hand.</p>
          </div>
          <div class="comparison-arrow" aria-hidden="true">→</div>
          <div class="comparison-example hard">
            <span>A CRYPTOGRAPHIC-SCALE NUMBER</span>
            <strong>N = ? × ?</strong>
            <p>Impractical for known classical methods at sufficient scale.</p>
          </div>
        </div>
      </div>
    `;
  }

  function renderReframe(currentStory) {
    return `
      <div class="reframe-layout">
        <p class="large-copy reveal">
          The quantum shortcut is to find the hidden period of
          <strong>a<sup>x</sup> mod N</strong>. Once that period is known,
          ordinary arithmetic finishes the factorization.
        </p>
        <ol class="process-flow" aria-label="Shor's algorithm in three moves">
          <li class="reveal">
            <span>1</span>
            <div>
              <strong>Choose a base a</strong>
              <p>Check that a and N are coprime.</p>
            </div>
          </li>
          <li class="reveal reveal-delay-1">
            <span>2</span>
            <div>
              <strong>Find the period r</strong>
              <p>The quantum part exposes the repeating pattern.</p>
            </div>
          </li>
          <li class="reveal reveal-delay-2">
            <span>3</span>
            <div>
              <strong>Calculate two gcd values</strong>
              <p>The classical part extracts the factors.</p>
            </div>
          </li>
        </ol>
        <div class="takeaway reveal reveal-delay-3">
          <span>Our example</span>
          <strong>N = ${currentStory.modulus}</strong>
        </div>
      </div>
    `;
  }

  function renderChooseBase(currentStory) {
    const failedCount = currentStory.result.attempts.length - 1;
    const retryNote =
      failedCount === 0
        ? ""
        : `
          <p class="inline-note">
            ${failedCount} earlier coprime ${failedCount === 1 ? "base was" : "bases were"}
            unsuitable. A real probabilistic run simply retries; this
            walkthrough continues with the first successful base.
          </p>
        `;
    return `
      <div class="equation-story">
        <p class="large-copy reveal">
          Choose a number a with
          <strong>1 &lt; a &lt; ${currentStory.modulus}</strong>. We use
          <strong class="orange">a = ${currentStory.base}</strong>.
        </p>
        <div class="equation-panel reveal reveal-delay-1">
          <p>First, check for an easy factor:</p>
          <div class="hero-equation">
            gcd(${currentStory.base}, ${currentStory.modulus}) =
            <span class="green">${currentStory.attempt.commonDivisor}</span>
          </div>
        </div>
        <div class="meaning-line reveal reveal-delay-2">
          <span class="status-dot"></span>
          <p>
            ${currentStory.base} and ${currentStory.modulus} are coprime.
            The gcd did not reveal a factor, so period finding is needed.
          </p>
        </div>
        ${retryNote}
      </div>
    `;
  }

  function renderDefineFunction(currentStory) {
    const exampleRow =
      currentStory.rows.find((row) => row.power >= BigInt(currentStory.modulus)) ??
      currentStory.rows[1];
    return `
      <div class="definition-layout">
        <p class="large-copy reveal">
          Define
          <strong>f(x) = ${currentStory.base}<sup>x</sup> mod ${currentStory.modulus}</strong>.
          “Modulo ${currentStory.modulus}” means: calculate the power, divide
          by ${currentStory.modulus}, and keep only the remainder.
        </p>
        <div class="hero-equation function-equation reveal reveal-delay-1">
          f(x) = ${currentStory.base}<sup>x</sup> mod ${currentStory.modulus}
        </div>
        <div class="modulo-demo reveal reveal-delay-2">
          <span>ONE COMPLETE EXAMPLE</span>
          <div class="modulo-demo-grid">
            <p>
              <small>Calculate</small>
              ${powerExpression(
                currentStory.base,
                exampleRow.exponent,
                exampleRow.power,
              )}
            </p>
            <p>
              <small>Divide with remainder</small>
              ${exampleRow.power} =
              ${exampleRow.quotient} × ${currentStory.modulus} +
              <strong>${exampleRow.remainder}</strong>
            </p>
            <p>
              <small>Keep the remainder</small>
              f(${exampleRow.exponent}) =
              <strong class="green">${exampleRow.remainder}</strong>
            </p>
          </div>
        </div>
        <p class="support-copy reveal reveal-delay-3">
          The next stage lets you inspect this calculation separately for
          every power.
        </p>
      </div>
    `;
  }

  function renderPowerByPower(currentStory) {
    const row = currentStory.rows[powerIndex];
    const repeatText =
      row.repeatsExponent === null
        ? row.exponent === 0
          ? "This is the starting value."
          : "This remainder has not repeated the start yet."
        : `This repeats f(${row.repeatsExponent}) = ${row.remainder}.`;
    const progress = ((powerIndex + 1) / currentStory.rows.length) * 100;

    return `
      <div class="power-workbench">
        <div class="power-selector reveal">
          <div>
            <span>POWER ${powerIndex + 1} OF ${currentStory.rows.length}</span>
            <strong>x = ${row.exponent}</strong>
          </div>
          <div class="power-actions">
            <button
              class="icon-button"
              type="button"
              data-action="previous-power"
              aria-label="Previous power"
              ${powerIndex === 0 ? "disabled" : ""}
            >←</button>
            <button
              class="button button-secondary compact-button"
              type="button"
              data-action="play-powers"
            >${powerTimer === null ? "Play calculations" : "Pause"}</button>
            <button
              class="icon-button"
              type="button"
              data-action="next-power"
              aria-label="Next power"
              ${powerIndex === currentStory.rows.length - 1 ? "disabled" : ""}
            >→</button>
          </div>
        </div>
        <div class="mini-progress" aria-hidden="true">
          <span style="width: ${progress}%"></span>
        </div>
        <div class="calculation-steps">
          <div class="calculation-line reveal">
            <span>STEP 1 · INSERT x</span>
            <p>
              f(${row.exponent}) =
              ${currentStory.base}<sup>${row.exponent}</sup>
              mod ${currentStory.modulus}
            </p>
          </div>
          <div class="calculation-line reveal reveal-delay-1">
            <span>STEP 2 · CALCULATE THE POWER</span>
            <p>${powerExpression(currentStory.base, row.exponent, row.power)}</p>
          </div>
          <div class="calculation-line reveal reveal-delay-2">
            <span>STEP 3 · DIVIDE BY ${currentStory.modulus}</span>
            <p>
              ${row.power} =
              ${row.quotient} × ${currentStory.modulus} +
              <strong class="orange">${row.remainder}</strong>
            </p>
          </div>
          <div class="calculation-line result-line reveal reveal-delay-3">
            <span>STEP 4 · KEEP THE REMAINDER</span>
            <p>
              ${row.power} mod ${currentStory.modulus} =
              <strong class="green">${row.remainder}</strong>
            </p>
          </div>
          <div class="calculation-line pattern-line reveal reveal-delay-4">
            <span>STEP 5 · CHECK THE PATTERN</span>
            <p>${repeatText}</p>
          </div>
        </div>
      </div>
    `;
  }

  function renderFullPattern(currentStory) {
    const rows = currentStory.rows
      .map((row) => {
        const repeat =
          row.repeatsExponent === null
            ? row.exponent === 0
              ? "Start"
              : "First period"
            : `Repeats x = ${row.repeatsExponent}`;
        return `
          <tr class="${row.repeatsExponent === null ? "" : "repeat-row"}">
            <th scope="row">${row.exponent}</th>
            <td>
              ${currentStory.base}<sup>${row.exponent}</sup> = ${row.power}
            </td>
            <td>
              ${row.power} =
              ${row.quotient} × ${currentStory.modulus} + ${row.remainder}
            </td>
            <td><strong>${row.remainder}</strong></td>
            <td>${repeat}</td>
          </tr>
        `;
      })
      .join("");

    return `
      <div class="full-pattern-layout">
        <p class="large-copy reveal">
          Place the individual calculations side by side. The remainder is the
          function value; the highlighted rows are the beginning of the next
          copy of the pattern.
        </p>
        <div class="table-scroll reveal reveal-delay-1">
          <table class="power-table">
            <caption>
              Complete calculation of
              f(x) = ${currentStory.base}<sup>x</sup> mod ${currentStory.modulus}
            </caption>
            <thead>
              <tr>
                <th scope="col">x</th>
                <th scope="col">Power</th>
                <th scope="col">Division with remainder</th>
                <th scope="col">f(x)</th>
                <th scope="col">Pattern</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
        <p class="table-conclusion reveal reveal-delay-2">
          At x = ${currentStory.period}, f(x) returns to 1. The next two rows
          repeat the values at x = 1 and x = 2.
        </p>
      </div>
    `;
  }

  function renderPeriod(currentStory) {
    const circles = currentStory.rows
      .map((row, index) => {
        const isRepeat = row.repeatsExponent !== null;
        return `
          <li
            class="period-node ${isRepeat ? "is-repeat" : ""}"
            style="--node-index: ${index}"
          >
            <span>x = ${row.exponent}</span>
            <strong>${row.remainder}</strong>
            <small>
              ${isRepeat ? `repeats x = ${row.repeatsExponent}` : "first period"}
            </small>
          </li>
        `;
      })
      .join("");
    const firstCycle = currentStory.rows
      .slice(0, currentStory.period)
      .map((row) => row.remainder)
      .join(" → ");
    const nextValues = currentStory.rows
      .slice(currentStory.period)
      .map((row) => row.remainder)
      .join(" → ");

    return `
      <div class="period-layout">
        <p class="large-copy reveal">
          The sequence returns to its starting value after
          <strong>${currentStory.period} steps</strong>. The next two values
          confirm that a new copy of the same pattern has begun.
        </p>
        <ol class="period-track">${circles}</ol>
        <div class="cycle-reading reveal reveal-delay-3">
          <p>
            <span>First period</span>
            <strong>${firstCycle}</strong>
          </p>
          <p>
            <span>Next period begins</span>
            <strong>${nextValues}</strong>
          </p>
        </div>
        <div class="period-answer reveal reveal-delay-4">
          Period length <strong>r = ${currentStory.period}</strong>
        </div>
      </div>
    `;
  }

  function renderQuantum(currentStory) {
    const terms = currentStory.rows
      .slice(0, Math.min(currentStory.period + 1, 7))
      .map(
        (row) =>
          `<span>|${row.exponent}⟩|${row.remainder}⟩</span>`,
      )
      .join('<i aria-hidden="true"> + </i>');
    const peaks = Array.from(
      { length: currentStory.period },
      (_, index) => `
        <span
          class="qft-peak"
          style="--peak-index: ${index}; --peak-height: ${
            48 + ((index * 29) % 43)
          }%"
        ></span>
      `,
    ).join("");

    return `
      <div class="quantum-layout">
        <p class="large-copy reveal">
          A quantum computer represents many x-values in superposition. The
          repeated function values create interference; the Quantum Fourier
          Transform converts that hidden repetition into measurable peaks.
        </p>
        <div class="quantum-state reveal reveal-delay-1">
          ${terms}<i aria-hidden="true"> + …</i>
        </div>
        <div class="qft-visual reveal reveal-delay-2" aria-label="${currentStory.period} illustrated QFT frequency peaks">
          <div class="wave-field" aria-hidden="true"></div>
          <div class="qft-arrow">
            <span>QUANTUM FOURIER TRANSFORM</span>
            <strong>QFT →</strong>
          </div>
          <div class="peak-field">${peaks}</div>
        </div>
        <div class="quantum-output reveal reveal-delay-3">
          <span>Simplified quantum output</span>
          <strong>r = ${currentStory.period}</strong>
          <p>The classical part now receives the period.</p>
        </div>
      </div>
    `;
  }

  function renderValidation(currentStory) {
    const residue = currentStory.attempt.halfPowerResidue;
    const quotient =
      currentStory.halfPower / BigInt(currentStory.modulus);
    return `
      <div class="validation-layout">
        <p class="large-copy reveal">
          The period must be even. Then compute
          <strong>y = a<sup>r/2</sup></strong> and verify that its modulo value
          is neither +1 nor −1.
        </p>
        <div class="validation-sequence">
          <div class="validation-item reveal">
            <span>1 · IS r EVEN?</span>
            <strong>r = ${currentStory.period} is even ✓</strong>
          </div>
          <div class="validation-item reveal reveal-delay-1">
            <span>2 · CALCULATE THE HALF-PERIOD POWER</span>
            <strong>
              y = ${currentStory.base}<sup>${currentStory.period}/2</sup>
              = ${currentStory.base}<sup>${currentStory.period / 2}</sup>
              = ${currentStory.halfPower}
            </strong>
          </div>
          <div class="validation-item reveal reveal-delay-2">
            <span>3 · CHECK THE MODULO VALUE</span>
            <strong>
              ${currentStory.halfPower} =
              ${quotient} × ${currentStory.modulus} + ${residue}
            </strong>
            <p>
              Therefore ${currentStory.halfPower} mod
              ${currentStory.modulus} = ${residue}.
            </p>
          </div>
          <div class="validation-item is-success reveal reveal-delay-3">
            <span>4 · EXCLUDE ±1</span>
            <strong>${residue} is neither 1 nor ${currentStory.modulus - 1} ✓</strong>
            <p>
              ${currentStory.modulus - 1} represents −1 modulo
              ${currentStory.modulus}. The period is usable.
            </p>
          </div>
        </div>
      </div>
    `;
  }

  function renderAlgebraicBridge(currentStory) {
    return `
      <div class="bridge-layout">
        <p class="large-copy reveal">
          The period tells us that
          <strong>${currentStory.base}<sup>${currentStory.period}</sup> mod ${currentStory.modulus} = 1</strong>.
          Write that fact as ordinary division, subtract the remainder, and
          factor the result as a difference of squares.
        </p>
        <div class="derivation">
          <div class="derivation-row reveal">
            <span>PERIOD POWER</span>
            <p>
              ${currentStory.base}<sup>${currentStory.period}</sup>
              = ${currentStory.fullPower}
            </p>
          </div>
          <div class="derivation-row reveal reveal-delay-1">
            <span>DIVISION WITH REMAINDER</span>
            <p>
              ${currentStory.fullPower} =
              ${currentStory.divisionQuotient} × ${currentStory.modulus} + 1
            </p>
          </div>
          <div class="derivation-row reveal reveal-delay-2">
            <span>SUBTRACT 1</span>
            <p>
              ${currentStory.fullPower} − 1 =
              ${currentStory.difference} =
              ${currentStory.modulus} × ${currentStory.divisionQuotient}
            </p>
          </div>
          <div class="derivation-row is-highlighted reveal reveal-delay-3">
            <span>DIFFERENCE OF SQUARES</span>
            <p>
              ${currentStory.difference} =
              (${currentStory.halfPower} − 1)(${currentStory.halfPower} + 1)
              = ${currentStory.lowerCandidate} × ${currentStory.upperCandidate}
            </p>
          </div>
        </div>
        <div class="bridge-explanation reveal reveal-delay-4">
          <p>
            The same number is both
            <strong>${currentStory.modulus} × ${currentStory.divisionQuotient}</strong>
            and
            <strong>${currentStory.lowerCandidate} × ${currentStory.upperCandidate}</strong>.
          </p>
          <p>
            That shared structure is why the two gcd calculations can expose
            factors of N.
          </p>
        </div>
      </div>
    `;
  }

  function renderGcd(currentStory) {
    return `
      <div class="gcd-layout">
        <p class="large-copy reveal">
          Compare each candidate with N. The greatest common divisor extracts
          the part that the candidate and N share.
        </p>
        <div class="gcd-calculations">
          <div class="gcd-card reveal reveal-delay-1">
            <span>FIRST CANDIDATE</span>
            <p>y − 1 = ${currentStory.lowerCandidate}</p>
            <strong>
              gcd(${currentStory.lowerCandidate}, ${currentStory.modulus})
              = <b>${currentStory.lowerGcd}</b>
            </strong>
          </div>
          <div class="gcd-card reveal reveal-delay-2">
            <span>SECOND CANDIDATE</span>
            <p>y + 1 = ${currentStory.upperCandidate}</p>
            <strong>
              gcd(${currentStory.upperCandidate}, ${currentStory.modulus})
              = <b>${currentStory.upperGcd}</b>
            </strong>
          </div>
        </div>
        <div class="meaning-line reveal reveal-delay-3">
          <span class="status-dot"></span>
          <p>
            Both results are greater than 1 and smaller than
            ${currentStory.modulus}. They are non-trivial factors.
          </p>
        </div>
      </div>
    `;
  }

  function renderResult(currentStory) {
    return `
      <div class="result-layout">
        <p class="result-label reveal">FACTORIZATION COMPLETE</p>
        <div class="final-equation reveal reveal-delay-1">
          ${currentStory.modulus} =
          <span>${currentStory.factorPair[0]} × ${currentStory.factorPair[1]}</span>
        </div>
        <p class="large-copy reveal reveal-delay-2">
          The quantum stage supplied
          <strong>r = ${currentStory.period}</strong>. The classical gcd stage
          turned that period into the factors
          <strong>${currentStory.factorPair[0]}</strong> and
          <strong>${currentStory.factorPair[1]}</strong>.
        </p>
        ${
          currentStory.primeFactors.length > 2
            ? `
              <p class="inline-note reveal reveal-delay-3">
                Continue recursively for the complete prime factorization:
                ${currentStory.modulus} = ${factorText(currentStory.primeFactors)}.
              </p>
            `
            : ""
        }
      </div>
    `;
  }

  function renderTakeaway(currentStory) {
    return `
      <div class="takeaway-layout">
        <div class="takeaway-statement reveal">
          <span>THE MOST IMPORTANT IDEA</span>
          <strong>
            The quantum computer does not factor
            ${currentStory.modulus} directly.
          </strong>
          <p>
            It efficiently solves the hard subproblem: find the period of
            a<sup>x</sup> mod N.
          </p>
        </div>
        <div class="handoff-flow">
          <div class="handoff quantum-handoff reveal reveal-delay-1">
            <span>QUANTUM</span>
            <strong>Find r = ${currentStory.period}</strong>
          </div>
          <div class="handoff-arrow reveal reveal-delay-2" aria-hidden="true">→</div>
          <div class="handoff classical-handoff reveal reveal-delay-3">
            <span>CLASSICAL</span>
            <strong>
              gcd → ${currentStory.factorPair[0]} and
              ${currentStory.factorPair[1]}
            </strong>
          </div>
        </div>
        <div class="final-equation compact-final reveal reveal-delay-4">
          ${currentStory.modulus} =
          <span>${currentStory.factorPair[0]} × ${currentStory.factorPair[1]}</span>
        </div>
      </div>
    `;
  }

  function shortcutExplanation(currentStory) {
    const { result } = currentStory;
    if (result.kind === "prime") {
      return {
        explanation:
          `No integer from 2 through √${result.value} divides ${result.value}.`,
        heading: `${result.value} is already prime`,
        result: "No non-trivial factor pair exists.",
      };
    }
    if (result.kind === "even") {
      return {
        explanation:
          `${result.value} is even, so division by 2 reveals a factor immediately.`,
        heading: "The even-number check finds a factor",
        result: `${result.value} = ${factorText(result.primeFactors)}`,
      };
    }
    return {
      explanation:
        `${result.value} is the exact power ${result.perfectPower.base}^${result.perfectPower.exponent}.`,
      heading: "The perfect-power check finds the structure",
      result: `${result.value} = ${factorText(result.primeFactors)}`,
    };
  }

  function renderShortcut(currentStory, currentStage) {
    const copy = shortcutExplanation(currentStory);
    if (currentStage === 0) {
      return `
        <div class="shortcut-layout">
          <p class="large-copy reveal">
            Shor's full period-finding routine starts only after fast classical
            checks remove easy cases: primes, even numbers, and perfect powers.
          </p>
          <div class="equation-panel reveal reveal-delay-1">
            <span>PRE-CHECK RESULT</span>
            <div class="hero-equation">${copy.heading}</div>
          </div>
          <p class="support-copy reveal reveal-delay-2">${copy.explanation}</p>
        </div>
      `;
    }
    if (currentStage === 1) {
      return `
        <div class="result-layout">
          <p class="result-label reveal">CLASSICAL RESULT</p>
          <div class="final-equation reveal reveal-delay-1">${copy.result}</div>
          <p class="large-copy reveal reveal-delay-2">${copy.explanation}</p>
        </div>
      `;
    }
    return `
      <div class="takeaway-layout">
        <div class="takeaway-statement reveal">
          <span>USE THE SIMPLEST VALID METHOD</span>
          <strong>The quantum routine is not needed for every input.</strong>
          <p>
            Classical pre-checks are part of Shor's algorithm. They prevent an
            expensive period-finding run when the answer is already easy to
            obtain.
          </p>
        </div>
        <div class="final-equation compact-final reveal reveal-delay-2">
          ${copy.result}
        </div>
      </div>
    `;
  }

  const renderers = [
    renderChallenge,
    renderReframe,
    renderChooseBase,
    renderDefineFunction,
    renderPowerByPower,
    renderFullPattern,
    renderPeriod,
    renderQuantum,
    renderValidation,
    renderAlgebraicBridge,
    renderGcd,
    renderResult,
    renderTakeaway,
  ];

  function stopPowerPlayback() {
    if (powerTimer !== null) {
      globalThis.clearTimeout(powerTimer);
      powerTimer = null;
    }
  }

  function scheduleNextPower() {
    stopPowerPlayback();
    powerTimer = globalThis.setTimeout(() => {
      if (stageIndex !== 4) {
        stopPowerPlayback();
        return;
      }
      if (powerIndex >= story.rows.length - 1) {
        powerIndex = 0;
      } else {
        powerIndex += 1;
      }
      elements.content.innerHTML = renderPowerByPower(story);
      scheduleNextPower();
    }, 1800);
  }

  function renderStageButtons() {
    elements.stageButtons.innerHTML = story.stages
      .map(
        (stage, index) => `
          <button
            type="button"
            class="stage-button ${index === stageIndex ? "is-current" : ""}"
            data-stage="${index}"
            ${index === stageIndex ? 'aria-current="step"' : ""}
            aria-label="Open step ${index + 1}: ${stage.title}"
          >
            <span>${String(index + 1).padStart(2, "0")}</span>
            <small>${stage.kicker}</small>
          </button>
        `,
      )
      .join("");
  }

  function renderStage() {
    stopPowerPlayback();
    const currentStage = story.stages[stageIndex];
    elements.kicker.textContent = currentStage.kicker;
    elements.title.textContent = currentStage.title;
    elements.counter.textContent =
      `Step ${stageIndex + 1} of ${story.stages.length}`;
    elements.progress.style.width =
      `${((stageIndex + 1) / story.stages.length) * 100}%`;
    elements.previous.disabled = stageIndex === 0;
    elements.next.textContent =
      stageIndex === story.stages.length - 1 ? "Start again ↺" : "Next →";
    elements.content.innerHTML =
      story.result.kind === "period-finding"
        ? renderers[stageIndex](story)
        : renderShortcut(story, stageIndex);
    renderStageButtons();

    elements.stage.classList.remove("stage-enter");
    globalThis.requestAnimationFrame(() => {
      elements.stage.classList.add("stage-enter");
    });
  }

  function setStage(nextStage) {
    stageIndex = Math.max(0, Math.min(story.stages.length - 1, nextStage));
    if (stageIndex !== 4) {
      powerIndex = 0;
    }
    renderStage();
  }

  function setStory(value) {
    stopPowerPlayback();
    story = model.buildStory(value);
    stageIndex = 0;
    powerIndex = 0;
    elements.input.value = String(value);
    elements.error.hidden = true;
    elements.resultPreview.textContent = fullResultText(story);
    elements.presets.forEach((button) => {
      const isActive = Number(button.dataset.example) === value;
      button.classList.toggle("is-active", isActive);
      button.setAttribute("aria-pressed", String(isActive));
    });
    renderStage();
  }

  elements.form.addEventListener("submit", (event) => {
    event.preventDefault();
    try {
      const value = Number(elements.input.value);
      math.assertTwoDigitInteger(value);
      setStory(value);
    } catch (error) {
      elements.error.textContent = error.message;
      elements.error.hidden = false;
    }
  });

  elements.presets.forEach((button) => {
    button.addEventListener("click", () => {
      setStory(Number(button.dataset.example));
    });
  });

  elements.previous.addEventListener("click", () => {
    setStage(stageIndex - 1);
  });

  elements.next.addEventListener("click", () => {
    setStage(
      stageIndex === story.stages.length - 1 ? 0 : stageIndex + 1,
    );
  });

  elements.stageButtons.addEventListener("click", (event) => {
    const button = event.target.closest("[data-stage]");
    if (button !== null) {
      setStage(Number(button.dataset.stage));
    }
  });

  elements.content.addEventListener("click", (event) => {
    const button = event.target.closest("[data-action]");
    if (button === null || story.result.kind !== "period-finding") {
      return;
    }

    const action = button.dataset.action;
    if (action === "previous-power") {
      stopPowerPlayback();
      powerIndex = Math.max(0, powerIndex - 1);
      elements.content.innerHTML = renderPowerByPower(story);
    } else if (action === "next-power") {
      stopPowerPlayback();
      powerIndex = Math.min(story.rows.length - 1, powerIndex + 1);
      elements.content.innerHTML = renderPowerByPower(story);
    } else if (action === "play-powers") {
      if (powerTimer === null) {
        scheduleNextPower();
      } else {
        stopPowerPlayback();
        elements.content.innerHTML = renderPowerByPower(story);
      }
    }
  });

  document.addEventListener("keydown", (event) => {
    if (
      event.target instanceof HTMLInputElement ||
      event.target instanceof HTMLButtonElement
    ) {
      return;
    }
    if (event.key === "ArrowLeft") {
      setStage(stageIndex - 1);
    } else if (event.key === "ArrowRight") {
      setStage(
        stageIndex === story.stages.length - 1 ? 0 : stageIndex + 1,
      );
    }
  });

  renderStage();
})();

# Shor's Algorithm Factoring Demos

Both presentation demos explain how Shor's algorithm turns quantum period
finding into a factorization. They accept every whole number from 10 through 99
and handle composite, prime, even, and perfect-power inputs.

## Choose a version

### Version 2 — presentation-led walkthrough

Open `v2/index.html`.

Version 2 follows the narrative and visual rhythm of the latest
`Shor_Algorithm_Factoring_15_Demo.pptx` deck. It uses the same progression from
the factoring challenge to period finding, QFT, difference of squares, and the
final gcd calculations.

The power-by-power stage exposes every part of each modular calculation:
substitution, exponentiation, division with remainder, and the retained
remainder. The next stage assembles those calculations into the complete table,
and the period stage shows the first three values of the following period.

### Version 1 — original walkthrough

Open `index.html`.

Version 1 keeps the original compact interactive flow and its advanced quantum
detail toggle.

## Open either demo

1. Open this folder in Finder.
2. Double-click `index.html` or open `v2/index.html`.
3. Put the browser into full-screen presentation mode.

The demo does not need a web server, an internet connection, or an installation.

## Present Version 2

- Enter a two-digit number and select **Build walkthrough**.
- Use **15**, **21**, or **35** for the prepared full-length examples.
- Use the numbered story rail, **Previous**, **Next**, or the left and right
  arrow keys to move through the thirteen stages: the twelve presentation
  beats plus the added power-by-power deep dive.
- On **Power by power**, use the local arrow buttons or
  **Play calculations** to reveal every modular calculation separately.
- The **Period** stage then assembles the sequence and shows three values from
  the next period.

## Present Version 1

- Enter a two-digit number and select **Factor this number**.
- Use **15**, **21**, or **35** for the prepared examples.
- The walkthrough follows six explicit stages: choose `a`, build the complete
  modulo table, find the period, validate it, form two candidates, and calculate
  both greatest common divisors.
- The modulo table shows every exact power, quotient, multiplication by `N`,
  and retained remainder through the first three repeated values.
- The period-validation and candidate steps expand the division identities
  line by line, including why the same number can be written as both a multiple
  of `N` and a difference-of-squares product.
- Each step animates its calculation in reading order. The quantum step cycles
  from a broad superposition through QFT interference to the period peaks.
- Reduced-motion system preferences replace the animation cycle with the final
  explanatory state.
- Select **Show advanced quantum details** for the simulated measurement value.
- Use **Previous**, **Next**, or the left and right arrow keys to move between
  steps.
- Use **Auto play** or the Space key for an automatic walkthrough.

## What is simulated

All modular arithmetic, periods, gcd calculations, and factors are computed
exactly in the browser. The quantum Fourier-transform spectrum and measurement
are deterministic illustrations of the period-finding stage; the page does not
connect to quantum hardware.

## Verify the arithmetic

From the repository root, run:

```bash
node --test \
  docs/demos/shor-factoring/shor-math.test.mjs \
  docs/demos/shor-factoring/v2/model.test.mjs
```

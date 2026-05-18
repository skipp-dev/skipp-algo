# Live-vs-Walk-forward Brier Ratio Calibration Note — 2026-05-18

**Status:** accepted as operator-prior baseline until enough live promotion history exists
**Related gate:** `governance/promotion_gate.py::DEFAULT_LIVE_VS_WF_RATIO_MAX`
**Related floor:** `governance/promotion_gate.py::DEFAULT_LIVE_VS_WF_RATIO_MIN`

## Question

`live_vs_wf_ratio_max = 1.5` gates the ratio:

```text
live_brier / walkforward_brier
```

The open finding was that `1.5` did not have an empirical calibration source.

## Evidence inventory

A repository search on 2026-05-18 found no committed promotion-history artifact
with enough paired `live_brier` and `walkforward_brier` observations to estimate
an empirical quantile for this ratio. The production bundle currently carries
these fields, but the checked-in fixtures are mostly schema/CLI evidence rather
than a live-promotion distribution.

Therefore, there is no defensible in-repo Q90/Q95 ratio estimate yet.

## Decision

Keep `live_vs_wf_ratio_max = 1.5` as an explicit **operator-prior baseline**, not
as an empirical threshold.

Rationale:

- `1.5` means live Brier may degrade by up to 50% versus the walk-forward
  expectation before promotion blocks.
- This is intentionally conservative for early live incubation: it catches clear
  overfit/regime-shift degradation without requiring enough live data to
  estimate a stable tail quantile.
- The threshold must not be described as backtest-derived until a future
  recalibration report computes the empirical distribution.

## Recalibration contract

The first empirical recalibration must run when either condition is met:

1. at least **100 promoted family windows** have paired positive finite
   `live_brier` and `walkforward_brier`, or
2. the regular ADR-0008 operator-judgment review date arrives.

The recalibration procedure is:

1. Load all promoted family windows with finite `live_brier` and strictly
   positive finite `walkforward_brier`.
2. Compute `ratio = live_brier / walkforward_brier`.
3. Report `n`, Q05, Q50, Q75, Q90, Q95, max, and per-family breakdown.
4. Re-anchor `live_vs_wf_ratio_max` at Q90 rounded up to one decimal unless the
   review explicitly accepts a stricter policy.
5. Re-evaluate the lower sanity floor if Q05 is materially below `0.05` or if
   repeated `suspicious_too_good` warnings are explained by measurement error.

## Lower sanity floor

`live_vs_wf_ratio_min = 0.05` is a warning-only floor. A ratio below 0.05 means
live Brier is more than 20x better than walk-forward Brier. That should be rare;
it is more likely to indicate leakage, a single-regime artifact, or an upstream
metric pipeline issue than a stable model improvement.

The floor emits `check = "suspicious_too_good"`, `severity = "warning"`, and
keeps promotion non-blocking unless another blocker is present.

## Non-positive denominator rule

`walkforward_brier <= 0` is not a valid ratio denominator. It is now classified
as a data-integrity blocker, not as missing info and not as a warning.

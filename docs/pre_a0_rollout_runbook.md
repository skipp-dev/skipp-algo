# PRE-A0 rollout and rollback runbook

## User semantics

PRE-A0 is an unconfirmed early warning. It must never use `level=A0`, confirmed
wording, A0 color or A0 emoji. ETA is a range. A percentage is allowed only
when a compatible, unexpired calibration artifact is loaded.

## Modes

- `off`: no scoring or display.
- `shadow`: score and record outcomes without UI or notification.
- `observe`: operator-only display without notification.
- `notify`: direct PRE-A0 push to the configured Slack `#main` webhook with a
  hard hourly budget; requires all promotion gates plus
  `RT_PRE_A0_DEPLOYMENT_APPROVED=1`.

The required controls are `RT_PRE_A0_MODE`, `RT_PRE_A0_MODEL_PATH`,
`RT_PRE_A0_ALLOWED_HORIZONS` and `RT_PRE_A0_MAX_ALERTS_PER_HOUR`. Missing,
corrupt, incompatible or expired model state disables PRE-A0 only.

## Promotion checklist

1. Dataset audit has zero critical leakage findings and sealed test provenance.
2. Model beats base rate and deterministic ETA on untouched walk-forward data.
3. Brier, ECE, reliability and important slices are stable in shadow.
4. Alert budget, dedup, model expiry, missingness and rollback tests are green.
5. Operator UX and wording reviewed.
6. Separate explicit deployment approval obtained immediately before change.

## Immediate rollback

Set `RT_PRE_A0_MODE=off`. Confirm A0/A1/A2 and FMP polling are unchanged.
Retain the model identifier, feature version, inputs and outcomes for review.

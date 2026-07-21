# PRE-A0 rollout and rollback runbook

## User semantics

PRE-A0 is an unconfirmed early warning. It must never use `level=A0`, confirmed
wording, A0 color or A0 emoji. ETA is a range. A percentage is allowed only
when a compatible, unexpired calibration artifact is loaded.

## Modes

- `off`: no scoring or display.
- `shadow`: score and record outcomes without UI or notification.
- `observe`: operator-only display without notification.
- `notify`: separate PRE-A0 channel with hard hourly budget; requires all
  promotion gates plus `RT_PRE_A0_DEPLOYMENT_APPROVED=1`.

## Pilot (separate from notify)

Added 2026-07-21 on explicit operator decision: a read-only pilot tailer
(`services/a0_fast_detector/pilot_alert_tailer.py`) may consume the `observe`
operator log and post IMMINENT transitions to a dedicated pilot Slack channel
**before** the shadow/promotion evidence exists. This is deliberately NOT the
`notify` mode and does not touch its gates: the worker keeps refusing
`notify`, and the pilot path is separately gated by `RT_PRE_A0_PILOT=1` plus
an https webhook env. Pilot messages keep the user semantics above (no A0
claim, no confirmed wording, ETA as a range, never a probability) and carry an
explicit "Pilotbetrieb / keine Handlungsempfehlung" disclaimer. Dedup per
symbol+direction cooldown and a hard hourly budget apply. Rollback: unset
`RT_PRE_A0_PILOT` (or set `RT_PRE_A0_MODE=shadow`) and redeploy.

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

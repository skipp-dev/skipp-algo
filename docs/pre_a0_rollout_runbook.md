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

## Retraining from live shadow data

The bootstrap artifact (`71831770…`, calibrated on 2026-07-08 only, 210 test
rows) has a degenerate feature envelope — e.g. `direction_stability` trained
as `[1.0, 1.0]` while live values span `[0, 1]`, and `price_progress` trained
up to `5.6` while live values reach four digits. Every quiet-universe score
therefore raises `pre_a0_feature_out_of_range_total` by construction. Since
2026-07-21 the runtime no longer scores `NONE`-state snapshots (they are still
sampled for training), so the dashboard violation panels are a real alarm
again. The durable fix is retraining on live shadow snapshots.

Since 2026-07-24 the `pre-a0-input-drift` Grafana alert gates its
`pre_a0_feature_out_of_range_total` term on a non-bootstrap `pre_a0_model_info`
artifact id, so this by-construction range noise no longer pages while
`71831770…` is deployed; the missingness term still pages, and the range term
re-arms automatically once the retrained artifact goes live (dashboard panels
are unchanged and still show the raw violations).

**Precondition:** `build_walk_forward_manifest` requires at least three
complete session days of snapshots. Collection only works since the
2026-07-21 evidence-flow fixes; the first compliant retrain is possible once
three complete sessions exist on the volume.

1. Pull snapshots and journals from the Railway volume (from a directory
   linked via `railway link --project skipp-algo --service a0-fast-shadow`;
   note `railway ssh -- <cmd>` mangles quoted arguments, so drive the shell
   over stdin and strip the `\r`/prompt noise before decoding):

   ```bash
   printf 'cd /app/data && tar czf - pre-a0-snapshots a0-fast-parity | base64\nexit\n' \
     | railway ssh > shadow-raw.out
   # keep only base64 lines, join, decode from the first "H4sI", untar
   ```

2. Prepare leakage-bounded datasets (fails closed below three sessions):

   ```bash
   .venv/bin/python -m scripts.prepare_pre_a0_training_data \
     services/a0_fast_detector/bootstrap/pre-a0-model.json \
     <extracted>/pre-a0-snapshots train.json test.json provenance.json \
     <extracted>/a0-fast-parity/a0_shadow_databento_*.jsonl \
     --code-revision "$(git rev-parse HEAD)"
   ```

3. Train and evaluate, then follow the promotion checklist above:

   ```bash
   .venv/bin/python -m scripts.train_pre_a0_model train.json artifact.json \
     --split-hash "$(jq -r .split_manifest.split_sha256 provenance.json)" \
     --review-after <ISO8601 expiry; the artifact hard-expires after this>
   .venv/bin/python -m scripts.evaluate_pre_a0_model artifact.json test.json eval.json \
     --validated-artifact-output artifact-validated.json
   ```

The new artifact replaces `services/a0_fast_detector/bootstrap/pre-a0-model.json`
(and `RT_PRE_A0_MODEL_PATH` if it points elsewhere) only after the promotion
checklist passes.

### Adding the 30s horizon at the next retrain (operator decision 2026-07-22)

Goal: the next artifact carries `horizons: [30, 60, 180]` so
`RT_PRE_A0_ALLOWED_HORIZONS=30,60,180` becomes valid. Setting the env alone
does NOT work today: the runtime requires configured horizons to be a subset
of the artifact's horizons (`configured_horizon_not_supported` disables
PRE-A0 entirely), and the bootstrap artifact carries only `[60, 180]`.

Verified facts this plan relies on (all checked 2026-07-22 on `main`):

- Labels always record all three outcomes — `HORIZONS = (30, 60, 180)` and
  `y_30` in `open_prep/pre_a0_labels.py`. The 30s outcome is already in every
  collected evidence session; no collection change is needed.
- `scripts/prepare_pre_a0_training_data.py` derives the dataset's horizons
  from the *reference artifact* passed as its first argument (it iterates
  `artifact.horizons` and writes them into `train.json`), and
  `scripts/train_pre_a0_model.py` copies `train.json`'s horizons into the new
  artifact.
- `compute_artifact_id` does NOT include `horizons` (identity =
  contract/schema/feature/split/model/calibration), so a reference copy with
  extended horizons still passes `verify_artifact_id` in the prepare step.

Procedure — identical to the standard retrain above except for step 0:

0. Create the reference copy with extended horizons (do not edit the deployed
   bootstrap file in place):

   ```bash
   jq '.horizons = [30, 60, 180]' \
     services/a0_fast_detector/bootstrap/pre-a0-model.json \
     > /tmp/pre-a0-model-ref-30-60-180.json
   ```

1. Run `prepare_pre_a0_training_data` with the reference copy as the first
   argument. The dataset now materializes horizon-30 rows from the existing
   `y_30` labels; `train.json` carries `[30, 60, 180]`.
2. Train, evaluate, promotion checklist — unchanged. The new artifact gets a
   fresh content-derived id and `horizons: [30, 60, 180]`.
3. Deploy the new artifact (replace the bootstrap file / repoint
   `RT_PRE_A0_MODEL_PATH`), then — and only then — set
   `RT_PRE_A0_ALLOWED_HORIZONS=30,60,180` on `a0-fast-shadow`.

Timing: evidence collection is compliant since the 2026-07-21 evidence-flow
fixes; with complete sessions on 2026-07-22/23/24 the three-session
precondition (`build_walk_forward_manifest`) is met after the 2026-07-24
close, so the first compliant retrain window opens 2026-07-25. The pilot
tailer is horizon-agnostic (it alerts on IMMINENT state transitions), so the
pilot keeps running unchanged throughout.

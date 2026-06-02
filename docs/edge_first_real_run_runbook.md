# Edge-Validation — First Real Run Runbook (EV-13)

**Purpose.** The EV-04…EV-12 stack built the complete edge-evidence pipeline.
This runbook is the credential-bound operator procedure for the **first real
run** against live Databento data. It produces the first timestamped artifact
in `governance/promotion_decisions/` — the thing that turns "tool" into
"evidence".

> Honest status before this run: `governance/promotion_decisions/` is empty.
> No real decision has ever been archived. Everything to date is synthetic /
> unit-tested machinery. This procedure changes that.

---

## 0. Prerequisites (environment-bound)

| Requirement | Check |
| --- | --- |
| `DATABENTO_API_KEY` exported in the shell | `echo $env:DATABENTO_API_KEY` is non-empty |
| Databento entitlement for the target dataset/schema | dataset access confirmed in the Databento portal |
| Python venv active | `& ..\.venv\Scripts\python.exe -V` |
| Working dir | run all commands from the nested `skipp-algo/skipp-algo` code dir |

The API key is read from the environment. **Never** pass it on the command
line or paste it into a tool prompt — type it directly into your shell.

---

## 1. Pull real bars + detect structure → pipeline input

`scripts/pull_databento_edge_input.py` fetches OHLCV, runs the canonical SMC
structure detector, and emits the exact JSON `run_edge_pipeline` consumes. The
emitted `bars` are the **resampled timeframe bars** the structure events anchor
on — not the raw fetch granularity — so the pipeline's anchor / forward-window
arithmetic matches the live scorer.

```powershell
& ..\.venv\Scripts\python.exe -m scripts.pull_databento_edge_input `
  --symbol AAPL `
  --dataset XNAS.ITCH `
  --schema ohlcv-1m `
  --timeframe 15m `
  --start 2024-01-01 `
  --end   2025-06-01 `
  --output artifacts/edge_runs/AAPL_15m_input.json
```

Notes:
- `--schema` (fetch granularity) **must be ≤** `--timeframe` (structure
  timeframe). Default `ohlcv-1m` → `15m` is the primary configuration
  (`governance/family_walkforward.py` pins horizons on the 15m frame).
- `--as-of` defaults to the **last bar's timestamp**, so the EV-04 point-in-time
  guard is always armed against the data's own horizon. Override only with a
  deliberate, documented boundary.
- The wrapper **refuses loudly** (exit 1) if the symbol yields no resampled
  bars or no detected structure — an honest empty result, never a vacuous
  payload.

### Sample-size reality check (do this before spending a long window)

The PSR producer needs **≥ 30 triggered returns per family**
(`MIN_OBSERVATIONS_FOR_PSR`). A family with fewer triggered setups is honestly
reported as *not measured* — not a failure, but not evidence either. Pick a
window long enough that the families you care about clear 30 triggered events.

---

## 2. Run the pipeline → archive the decision + verdict

```powershell
& ..\.venv\Scripts\python.exe -m scripts.run_edge_pipeline `
  --input  artifacts/edge_runs/AAPL_15m_input.json `
  --output artifacts/edge_runs/AAPL_15m_report.json `
  --archive-dir governance/promotion_decisions
```

Exit codes (mirror `run_promotion_gate`):
- `0` — all families promoted.
- `2` — at least one family blocked (this is the **expected, honest** first
  result; promotion requires metrics this scaffold does not yet produce — see
  §4).
- `1` — configuration error (bad input, lookahead leak, etc.). Read stderr.

On success it prints the verdict summary and the archived path, e.g.:

```
pipeline ok: 312 event(s) -> 4 decision(s); verdicts {'edge_supported': 0, 'no_edge': 1, 'inconclusive': 3, 'not_evaluated': 0}
archived: governance/promotion_decisions/promotion_decisions_2026-06-01T....json
```

---

## 3. Read the verdict honestly

The archived report drives the EV-08 verdict and the EV-09 panel:

```powershell
& ..\.venv\Scripts\python.exe -m governance.family_verdict `
  --report (Get-ChildItem governance/promotion_decisions/promotion_decisions_*.json | Sort-Object Name | Select-Object -Last 1).FullName
```

Verdict semantics (anti-HARKing, EV-08):
- **edge_supported** — gate promoted **and** the pre-registered `primary_metric`
  (PSR) was genuinely measured **and** `observed_n ≥ min_sample_n`.
- **inconclusive** — gate promoted but a pre-registration check failed (metric
  not measured, or sample too small). **An edge is NOT claimed.**
- **no_edge** — measured and the family did not promote.
- **not_evaluated** — no gate decision for a registered family.

---

## 4. Expected first-run outcome (set expectations)

`scripts/build_family_metrics.py` started as an EV-06 scaffold but the C-sprint
producers are now wired: it computes **PSR** and **MinTRL** from the returns
directly, the raw per-family p-value whose **`fdr_pvalue`** is filled as a
Benjamini–Hochberg q-value at the bundle level (EV-16), and — *when the caller
supplies the corresponding evidence* — **brier / ece / psi** (EV-15 calibration
pairs), **conformal** (EV-17 block) and **`psi_slope`** (EV-18 monitoring
windows). None of these are hardcoded `None` any more; a metric is left `None`
only when its evidence is genuinely absent, and the gate then blocks that family
honestly rather than guessing.

**A first run that returns exit `2` with mostly `inconclusive` verdicts is still
a correct, honest result** when the optional calibration/conformal/psi_trend
evidence is not yet assembled — it proves the pipeline runs end-to-end on real
data and archives a real decision without fabricating a pass. The remaining gap
for a *strict* promotion is the upstream `regime_degraded` boolean (C5), which
the metrics producer does not compute — it must come from the regime detector,
never be set blindly to clear the gate.

### 4a. EV-24 — brier / ece are now MEASURED, not "not yet measured"

Before EV-24 the real-run path emitted purely *structural* events with no
per-event score, so `brier` / `ece` stayed `None` and the gate blocked every
decision on "calibration not yet measured". EV-24 closes that loop **without
fabricating anything**:

1. `family_event_adapter` attaches a single, transparent **raw score** per event
   — an ATR-normalised geometry-strength feature
   (`atr_normalised_geometry_strength_v1`, `governance/family_event_score.py`).
   It is point-in-time (trailing ATR only) and is omitted when ATR cannot be
   computed; the event then stays unscored, never invented.
2. `family_calibration.walk_forward_calibration` maps that raw score to an
   **out-of-sample** probability with a 2-parameter Platt logistic fit
   walk-forward, with a **time-aware purge + family embargo** on the label
   window so overlapping-label leakage cannot inflate the metric (review GAP 1;
   López de Prado 2018, ch. 7). Below `MIN_OOS_SAMPLES = 40` pooled OOS points
   it emits **no block**, leaving the family honestly "not yet measured".
3. The pooled `(probability, outcome)` pairs flow through `to_build_spec` into
   the gate, so `brier` / `ece` become a real measurement.

**Honest caveats (do not over-read the number):**

- The calibration target is `sign(return)` — a **win-rate diagnostic, NOT an
  edge proof** (review GAP 2). A well-calibrated win-rate says nothing about
  PnL; **PSR / MinTRL / FDR remain the primary edge gate.** This is recorded in
  the `ev24_calibration_target = sign_return_secondary_diagnostic` provenance.
- ECE is biased and binning-dependent at small n — prefer **Brier** (GAP 3).
- A **measured fail is a success of the method, not a failure to fix.** The v1
  score must NOT be tuned to clear the Brier/ECE caps; doing so would convert an
  honest measurement back into fabricated evidence.
- Still deferred (genuinely absent → still `None`): `conformal`, `psi_slope`,
  `live` / `reference_probabilities` (PSI), and the block-bootstrap Brier CI
  gate (GAP 4 follow-up).

---

## 5. Known load-bearing assumptions (review before trusting numbers)

These are chosen, documented trade assumptions — not bugs, but they shape every
number above and must be reviewed before any number is acted on:

- **Trade definition (variant A, `family_returns.py`)** — zone families enter at
  the zone midpoint on first retest touch, exit at the close
  `family_outcome_horizon` bars later; level families enter immediately at the
  break/sweep level. Fixed 5 bps round-turn cost. No target/stop optimisation.
- **Late-touch horizon clamp** — a touch late in the forward window has its exit
  clamped to the last available bar, shortening the intended hold. Review
  whether to lengthen the window or drop such trades.
- **Adapter lookahead vs. outcome horizon** — forward windows
  (BOS 8 / OB 12 / FVG 20 / SWEEP 8) intentionally differ from the exit horizons
  (BOS 8 / OB 6 / FVG 4 / SWEEP 3).
- **`as_of` timezone** — naive ISO `as_of` is treated as **UTC** to match the
  UTC epoch anchor timestamps (EV-12 fix). Pass tz-aware ISO if you mean
  something else.

---

## 6. Failure triage

| Symptom | Likely cause | Action |
| --- | --- | --- |
| `error: ... no detected SMC structure` | window too short / wrong timeframe | widen `--start/--end`, confirm `--timeframe` |
| `error: ... no resampled <tf> bars` | symbol absent in fetch / bad symbol | verify symbol + dataset entitlement |
| `error: ... lookahead leak refused` | `as_of` earlier than some bar | correct `--as-of` or omit to auto-default |
| `error: need at least 30 returns for PSR` | too few triggered setups | longer window or different symbol |
| exit `1` with a Databento/network message | transient API / auth | the client retries transient errors; check the key for auth failures |

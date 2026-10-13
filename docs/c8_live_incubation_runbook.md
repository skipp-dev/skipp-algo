# C8 — Live-Incubation Runbook

**Status:** scaffolded for Phase-A (paper) → Phase-B (live_small) → Phase-C (live_full).
**Owner:** Steffen.  Phase-Gates are **manual sign-off only** — no auto-promotion.

This runbook ties together the components shipped in sprint C8:

- `scripts/smc_to_ibkr_adapter.py` — SMC setup → IBKR order intent (T1, PR #269)
- `scripts/live_risk_limits.py` — pre-order caps + kill-switch (T2, #262)
- `scripts/run_smc_live_incubation.py` — orchestrator with audit log (T3, #271)
- `scripts/compute_live_drift.py` — live-vs-backtest drift detector (T4, #273)
- `scripts/backfill_live_outcomes.py` — outcome feedback loop (T5, #270)
- `tab_live_incubation.py` — dashboard tab (T6, follow-up sprint)

---

## Pre-Phase-A Checklist

Before submitting the **first paper trade**, all of the following must be green:

- [ ] C2 (walk-forward) merged in `main`
- [ ] C3 (bootstrap CIs) merged in `main`
- [ ] C4 (permutation null) merged in `main`
- [ ] C5 (regime stratification) merged in `main`
- [ ] C6 (track-record gate) merged in `main`
- [ ] C7 dashboard reachable (track-record + calibration tabs render)
- [ ] IBKR paper-trading account active and TWS/Gateway running
- [ ] At least 1 variant carries gate-status `amber` or `green`
- [ ] `live_risk_limits.RiskLimits` configured with realistic per-account caps

---

## Phase-A — Paper (4 weeks minimum)

**Goal:** confirm that the production wiring (adapter → risk → submit → audit
→ outcome backfill) does not silently corrupt PnL or hit-rate vs the
backtest.  Real money is **not** at risk in this phase.

**Configuration:**

```bash
python -m scripts.run_smc_live_incubation \
  --phase paper \
  --setups cache/live/setups_$(date -u +%Y%m%d).jsonl \
  --gate-statuses cache/live/gate_status.json \
  --audit-output cache/live/incubation_$(date -u +%Y%m%d).jsonl
```

`phase=paper` forces `paper_mode=True` in every emitted intent and scales
position size to **10 %** of the backtest sizing.

**Pass criteria (manual sign-off after 4 weeks):**

- ≥ 45 paper trades closed
- |paper-Sharpe / OOS-Sharpe − 1| < 0.30 (drift_score ≥ 0.70 — stricter
  than the code's `acceptable` band of 0.65; equivalent to verdict
  `acceptable` or `pass` in `scripts/compute_live_drift.py::_VERDICT_BANDS`)
- Slippage-distribution KS p-value > 0.05 vs the configured 0.5 % mean.
  **Synthetic-reference caveat (stat-review S5, #2674):** when the drift
  JSON discloses ``slippage_ks_reference_type: synthetic_normal`` (the
  uncalibrated placeholder Normal(0.005, 0.003) used in the absence of
  backtest slippage samples), the evaluator scores this criterion as
  *not machine-evaluable* (``passed: null``) rather than comparing a
  p-value against folklore parameters — supply backtest samples or
  sign off manually with that limitation on the record.
- Hit-rate inside the C3 bootstrap CI
- Watchdog ``aggregate_severity`` is not ``red`` (stat-review S1,
  #2674): the watchdog's 4-detector consensus (KS-p, PSI, mean-shift,
  variance-ratio) can stand RED — e.g. stable mean PnL with blown-out
  tails — while the Sharpe-ratio drift_score still reads `pass`. The
  evaluator consumes the watchdog report's severity directly; a missing
  report fails closed.

**Statistical power caveat (stat-review F5, 2026-06-10):** at n = 20
trades the annualised-Sharpe estimator has a standard error of roughly
3.5 Sharpe units, so the drift_score at this sample size is dominated
by sampling noise: a variant whose *true* drift_score is 0.50 (should
fail) still clears the ≥ 0.70 line in roughly 43 % of 20-trade samples,
while a variant whose true drift_score is 1.00 (perfect replication)
clears it only ~53 % of the time. Phase-A sign-off therefore validates
the **wiring** (adapter → risk → audit → backfill), not performance.
Do not cite a Phase-A drift_score as evidence of edge.

**Fail / halt triggers:**

- Kill-switch fires once → halt, debug, do not advance
- Drift verdict `concerning` two days in a row → halt, debug
- Drift verdict `fail` ever → halt, post-mortem, **do not advance**

---

## Phase-B — Live Small (3–6 months)

**Only enter Phase-B after Phase-A is signed off.**

**Configuration:**

```bash
python -m scripts.run_smc_live_incubation \
  --phase live_small \
  --setups …  --gate-statuses …  --audit-output …
```

`phase=live_small` keeps `paper_mode=False` and uses
`PHASE_B_RECOMMENDED_SIZE_SCALE` (10–25 %) from the adapter.  Real money
is at risk in this phase — every kill-switch breach must trigger an
incident review before the next session.

**Pass criteria:**

- ≥ 30 live trades closed
- live-Sharpe ÷ backtest-Sharpe ≥ 0.50 (drift_score ≥ 0.50 — looser
  than Phase-A. With code's `_VERDICT_BANDS` at 0.85/0.65/0.40, a
  drift_score of 0.50 sits *inside* the `concerning` band (0.40–0.65)
  but above the `fail` cutoff at 0.40. The verdict must still be
  `pass` or `acceptable`, i.e. drift_score ≥ 0.65; the 0.50 line is
  therefore a *necessary but not sufficient* watch-marker for Phase-B
  reviews.)
- Kill-switch never fired
- Max-DD live < 2× backtest-Max-DD
- Drift verdict `pass` or `acceptable`
- Slippage K-S reference type **must be** `backtest_samples` (see
  ``slippage_ks_reference_type`` in the drift JSON; `synthetic_normal`
  is acceptable for Phase-A but blocks Phase-B sign-off)
- ``window_complete: true`` on the watchdog report (no missing date
  files in the 30-day window; see ``window_coverage`` in the report).
  **Which report (stat-review F2, 2026-06-10):** this refers to a
  `scripts/run_drift_watchdog.py` run whose ``--outcomes-dir`` points at
  the **incubation** outcome stream (the directory fed by
  `backfill_live_outcomes` for this variant) — *not* the watchdog's
  default `artifacts/open_prep/outcomes` directory, which tracks the
  open_prep scanner and says nothing about incubation coverage.
- Watchdog ``aggregate_severity`` is not ``red`` (stat-review S1,
  #2674; same report as the ``window_complete`` criterion above).

If all pass → **the track record is externally sellable.**

---

## Phase-C — Live Full

Only enter Phase-C after Phase-B is signed off.  `phase=live_full` removes
the size scaling.  Position-sizing per Kelly-criterion is out of scope for
C8 and tracked under the future Scale-Phase backlog.

---

## Daily monitoring (during all live phases)

The daily cron is a four-step pipeline. Each step writes an atomic
artefact and is safe to retry:

```bash
DATE=$(date -u +%Y-%m-%d)        # ISO-8601 — must use dashes so the
                                  # drift_loader regex matches.

# 1. Backfill outcomes onto the audit log (idempotent).
python -m scripts.backfill_live_outcomes \
  cache/live/incubation_${DATE}.jsonl

# 2. Convert audit JSONL → drift-input JSONL (variant/return/slippage/hit).
python -m scripts.build_backtest_reference drift-input \
  --audit-jsonl cache/live/incubation_${DATE}.jsonl \
  --output cache/live/drift_input_${DATE}.jsonl

# 3. Refresh backtest_reference from the latest C2/C3 artefacts.
python -m scripts.build_backtest_reference backtest-reference \
  --walk-forward cache/calibration/walk_forward_${DATE}.json \
  --bootstrap-ci cache/calibration/bootstrap_ci_${DATE}.json \
  --output cache/calibration/backtest_reference_${DATE}.json

# 4. Compute live-vs-backtest drift.
python -m scripts.compute_live_drift \
  --live-jsonl cache/live/drift_input_${DATE}.jsonl \
  --backtest-calibration cache/calibration/backtest_reference_${DATE}.json \
  --output cache/live/drift_${DATE}.json
```

The C7 `tab_live_incubation` panel renders the resulting JSON and the
audit-log kill-switch entries.  The drift loader (C8/T6) only matches
ISO-formatted filenames (`drift_YYYY-MM-DD.json`), so step 4's
`--output` MUST use the dashed `${DATE}` form above.

Weekly manual review by Steffen reads the last seven `drift_*.json`
files plus the audit log for halt records.

---

## Machine evaluation of pass criteria (stat-review F1/F6, 2026-06-10)

The pass-criteria checklists above are mirrored in code as
`PHASE_PASS_CRITERIA` in `scripts/run_smc_live_incubation.py` and are
**machine-evaluated** by `scripts/evaluate_phase_criteria.py`:

```bash
python -m scripts.evaluate_phase_criteria \
  --criteria-phase paper --variant <variant> \
  --drift-json cache/live/drift_${DATE}.json \
  --audit-jsonl cache/live/incubation_${DATE}.jsonl \
  --watchdog-json artifacts/drift_watchdog/drift_report_${DATE}.json \
  --phase-started 2026-05-01 \
  --output cache/live/phase_eval_${DATE}.json
```

`run_smc_live_incubation --phase live_small` refuses to start without a
fresh **passing** `paper` evaluation report (`--phase-eval-report`), and
`--phase live_full` requires a passing `live_small` report. The
evaluator is fail-closed: criteria it cannot verify from the artefacts
count as **not passed**, and the Phase-C Scale-Phase/Kelly marker never
machine-passes by design. A passing report is **input to** the manual
sign-off, never a promotion by itself.

## Sequential looks & verdict history (stat-review F11, 2026-06-10)

Drift verdicts are computed **daily**, so a 4-week Phase-A involves
~20 looks and a 6-month Phase-B ~120 looks at the same statistic. Two
consequences for review discipline:

- The halt triggers (`concerning` twice in a row, `fail` ever) are
  repeated tests — their false-alarm probability over a phase is much
  higher than any single day's, which is acceptable for a *halt* rule
  (fail-safe) but means a single noisy halt is not by itself evidence
  the variant is broken. Debug before discarding.
- The pass decision must NOT be made by cherry-picking a favourable
  day. Sign-off reads the **verdict history over the whole phase**
  (count of `concerning`/`fail` days, trajectory of drift_score), not
  the final day's snapshot. Picking the best of N daily snapshots
  inflates the effective false-pass rate well beyond the single-look
  numbers quoted in the Phase-A power caveat.

## Why no auto-promotion

`live_full` carries **real capital at full size**.  The decision to flip
from `live_small` → `live_full` requires inspection of the audit log,
the drift artifacts, and the calibration report — none of which can be
fully automated without re-introducing curve-fit risk.  All
phase-promotions are therefore signed off manually by the account
owner.

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

- ≥ 20 paper trades closed
- |paper-Sharpe / OOS-Sharpe − 1| < 0.30 (drift_score ≥ 0.70 → verdict
  `pass` or `acceptable`)
- Slippage-distribution KS p-value > 0.05 vs the configured 0.5 % mean
- Hit-rate inside the C3 bootstrap CI

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
- live-Sharpe ÷ backtest-Sharpe ≥ 0.50 (drift_score ≥ 0.50)
- Kill-switch never fired
- Max-DD live < 2× backtest-Max-DD
- Drift verdict `pass` or `acceptable`

If all pass → **the track record is externally sellable.**

---

## Phase-C — Live Full

Only enter Phase-C after Phase-B is signed off.  `phase=live_full` removes
the size scaling.  Position-sizing per Kelly-criterion is out of scope for
C8 and tracked under the future Scale-Phase backlog.

---

## Daily monitoring (during all live phases)

A cron job runs the drift detector each session close:

```bash
python -m scripts.compute_live_drift \
  --live-jsonl cache/live/incubation_$(date -u +%Y%m%d).jsonl \
  --backtest-calibration cache/calibration/c2_walk_forward.json \
  --output cache/live/drift_$(date -u +%Y%m%d).json
```

The C7 `tab_live_incubation` panel renders the resulting JSON and the
audit-log kill-switch entries.

Weekly manual review by Steffen reads the last seven `drift_*.json`
files plus the audit log for halt records.

---

## Why no auto-promotion

`live_full` carries **real capital at full size**.  The decision to flip
from `live_small` → `live_full` requires inspection of the audit log,
the drift artifacts, and the calibration report — none of which can be
fully automated without re-introducing curve-fit risk.  All
phase-promotions are therefore signed off manually by the account
owner.

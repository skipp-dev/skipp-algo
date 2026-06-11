# ADR-0023 — Move-size resolution: live-rollout handover

> **Audience.** The next agent/engineer who picks up the ADR-0023 magnitude
> work after PR #2581 (`feat/adr0023-magnitude-resolution-gate`) merges. This
> doc is the single place that explains **what was proven, what is wired, what
> is still dormant, and exactly how to operate the staged rollout** — so none
> of it has to be re-derived from memory.
>
> **Status (2026-06-05).** §2 acceptance bar RESOLVED on real data. The
> `magnitude_resolution_floor` check is wired into the promotion gate but
> **DORMANT** (passive). No family is sized on the move-size objective yet.
> Direction-Brier tier-2 gate stays in force.

---

## 0. TL;DR

- We proved on real OPRA data that **signal strength predicts move *size*** for
  **BOS** and **SWEEP** (clears the pre-registered §2 bar; not chance).
- For **FVG** and **OB** the effect is **real but too weak** (AUC < 0.60) — a
  recorded honest negative, not a failure of the method.
- The gate plumbing exists and is **safe-by-default**: where there is no
  measurement it does nothing (lax) or only logs an info note (strict). It can
  only ever *block*, never silently *enable* sizing.
- Rollout is **3 staged steps**. We are at the start of **Stage 1 (shadow /
  measure-only)**. Stages 2 and 3 are NOT started.
- **All four families are monitored in Stage 1** — BOS/SWEEP as the candidates,
  FVG/OB as the negative-control group.

---

## 1. What was proven (the §2 result, plain language)

The pre-registered question (frozen in
[ADR-0023](../adr/0023-tier-2-size-gate-magnitude-retarget.md) §2, copied
read-only into
[adr0023_magnitude_retarget_findings.md](./adr0023_magnitude_retarget_findings.md)):

> Does the v1 geometry-family score resolve **move-size** out-of-sample
> strongly enough — by a bar fixed *before* the run — to justify re-targeting
> the tier-2 `risk_sizeable` sizing gate from a direction objective to a
> move-size objective?

The bar (all must hold, OOS, purged walk-forward):

1. Magnitude AUC point estimate **≥ 0.60** AND bootstrap 95 % CI lower bound
   **≥ 0.55** (B ≥ 1000).
2. Score-alone resolution **>** 95th percentile of the label-permutation null
   (B ≥ 1000).
3. No direction-Brier regression beyond harness tolerance.
4. `MIN_OOS_SAMPLES = 40`, else inconclusive.

**Real-data verdict** (seed 230022, B=1000/1000, score-alone, OOS purged
walk-forward; dataset `~/.local/share/skipp/vpin_followup/events_v3_abs_opra.json`):

| Family | n_oos | mag AUC | AUC 95% CI low | resolution vs perm-null p95 | perm p | Verdict |
|--------|-------|---------|----------------|------------------------------|--------|---------|
| BOS    | 2375  | 0.618   | 0.595          | 0.0118 > 0.0014              | .001   | **PASS** |
| SWEEP  | 410   | 0.663   | 0.610          | 0.0209 > 0.0063              | .001   | **PASS** |
| FVG    | 1985  | 0.553   | 0.528          | resolution ok, **AUC<0.60**  | —      | FAIL (auc_floor + auc_ci) |
| OB     | 1805  | 0.562   | 0.537          | resolution ok, **AUC<0.60**  | —      | FAIL (auc_floor) |

Interpretation:
- **AUC** = probability the score ranks a bigger move above a smaller one. 0.50
  is a coin-flip; ≥0.60 was the floor we required.
- **Permutation-null** answers "could a score this resolving appear by chance?"
  — for BOS/SWEEP, no (p≈.001).
- The 0.60 floor was set **independently and in advance** ⇒ no goalpost-move.
  FVG/OB miss it honestly.

**Net:** 2 of 4 families (BOS, SWEEP) clear the full bar. FVG/OB are logged as
real-but-sub-threshold negatives.

> **Still pending before any real sizing:** the §5 secondary check —
> **E[PnL] after costs**. A resolution pass that does NOT convert to positive
> sized E[PnL] after trading costs is a recordable negative, *not* grounds to
> ship sizing. This is unmeasured today and gates Stage 3.

---

## 2. What is wired in code (and what stays dormant)

PR #2581 (`feat/adr0023-magnitude-resolution-gate`) adds an **additive,
dormant** check. "Additive" = it can only add a blocker; it never lowers an
existing bar. "Dormant" = with no measurement supplied it is passive.

### 2.1 New module — `governance/magnitude_resolution_gate.py`

Pure-python §2 estimators. Public API:

| Symbol | Role |
|--------|------|
| `MagnitudeResolutionResult` | frozen dataclass — per-family verdict + numbers |
| `bootstrap_auc_ci(...)` | bootstrap 95 % CI on magnitude AUC (B≥1000) |
| `permutation_resolution_null(...)` | label-permutation resolution null (B≥1000) |
| `_permutation_p_value(observed, null)` | one-sided p of observed vs null |
| `evaluate_family_magnitude_resolution(...)` | runs the full §2 bar for one family |
| `magnitude_resolution_report(...)` | human-readable multi-family report |

Frozen constants (the bar — **do not retune to chase a pass**):

```
MAG_AUC_FLOOR        = 0.60
MAG_AUC_CI_LOW_FLOOR = 0.55
PERM_NULL_PERCENTILE = 0.95
DEFAULT_N_BOOTSTRAP  = 1000
DEFAULT_N_PERMUTATION= 1000
DEFAULT_SEED         = 230_022
MAGNITUDE_GATE_SOURCE_TAG = "adr0023_magnitude_resolution_floor_v1"
```

> Line 205 `rng = random.Random(seed)` is ledgered in
> `tests/test_random_tempfile_ledger_pin.py`. If you move it, update the
> ledger.

### 2.2 CLI runner — `scripts/run_magnitude_resolution_gate.py`

Runs the bar over an events file per family and prints/returns the report. This
is the executable behind Stage 1's daily job.

### 2.3 Promotion-gate wiring — `governance/promotion_gate.py`

`FamilyMetrics` gains two **optional** snapshot fields:

```python
magnitude_resolution_pass: bool | None = None   # True/False/not-measured
magnitude_auc:             float | None = None
```

`evaluate()` gains an `ok_magnitude` branch (the 3-state safety logic — this is
the heart of "dormant"):

| `magnitude_resolution_pass` | gate mode | behaviour |
|-----------------------------|-----------|-----------|
| `None` (not measured) | **lax** | `ok_magnitude=True` — **DORMANT, no-op** (today's state) |
| `None` (not measured) | **strict** | emits a non-blocking `info` blocker `magnitude_resolution_floor` |
| `True` | any | records `magnitude_resolution_pass=1.0` (+ `magnitude_auc`); ok |
| `False` | any | **hard `blocker`** `magnitude_resolution_floor` — sizing denied |

Key safety property: a missing measurement can never *enable* magnitude sizing.
Worst case in strict mode it's an info note. Only an explicit measured-`False`
hard-blocks.

### 2.4 Supporting wiring

- `governance/types.py` — `magnitude_resolution_floor` added to
  `BLOCKER_CHECK_NAMES`.
- `governance/family_verdict.py` — `magnitude_resolution_floor` added to
  `_CALIBRATION_CHECKS` (so it participates in the tier-2 `risk_sizeable`
  verdict family).
- `scripts/run_promotion_gate.py` — `magnitude_auc` added to `_NUMERIC_FIELDS`;
  bool-mapping for `magnitude_resolution_pass`.

---

## 3. The staged rollout (authoritative)

Three stages. **We are at the START of Stage 1.** Do NOT skip ahead — each
stage has an explicit gate to the next.

### Stage 1 — Shadow / measure-only (CURRENT)

- The promotion pipeline **measures and records** `magnitude_auc` +
  `magnitude_resolution_pass` for **all four families** every run.
- Purely **logging** — gate stays lax, nothing blocks, nothing sizes.
- **All four families are monitored**, not just BOS/SWEEP. Rationale:
  - BOS/SWEEP are the **candidates** — confirm they stay stably *above* the bar.
  - FVG/OB are the **negative control** — confirm they stay stably *below*. If
    all four jump above the bar on the same day, that's a pipeline/data
    artifact, not skill — the controls catch it.
  - Drift is bidirectional: FVG/OB could rise over the bar (e.g. after feature
    work); monitoring only the winners would be a blind spot.
- Measuring ≠ arming. The hard/blocking mode (Stage 2) and real sizing
  (Stage 3) still apply **only** to families that clear the unchanged bar.

**Exit criterion → Stage 2:** BOS and SWEEP each clear the §2 bar in **k of n**
consecutive weekly evaluations (recommend k≥3 of n=4) AND FVG/OB stay below.
This multi-window confirmation guards against the multiple-testing inflation of
re-checking four families weekly.

### Stage 2 — Arm strict mode for the qualified families only

- Flip the qualified families (today: BOS, SWEEP) to **strict**, so a measured
  `False` hard-blocks their tier-2 `risk_sizeable` promotion.
- FVG/OB remain measured-only (lax) — untouched.
- Still **no change to sizing logic** — this only makes the floor *enforced*
  for the winners, so a later regression auto-demotes them.

**Exit criterion → Stage 3:** Stage 2 stable over multiple windows AND the §5
E[PnL]-after-cost secondary check (below) passes for the qualified families.

### Stage 3 — Re-target sizing to move-size (winners only)

- For BOS/SWEEP, switch the tier-2 sizing objective from direction-Brier to the
  move-size objective.
- **Only if** E[PnL]-after-cost is positive and sized (§5). A statistically
  resolving signal that doesn't survive trading costs is a negative — stop.
- FVG/OB stay magnitude-agnostic (direction-based) indefinitely, unless they
  later clear the unchanged bar in Stage 1 monitoring.

---

## 4. Stage 1 — detailed daily operation

This is the concrete "what runs each day, how it's evaluated, recorded, and
judged" spec for the shadow phase.

### 4.1 Daily job — IMPLEMENTED

The Stage-1 runner exists: `scripts/run_magnitude_shadow_ledger.py`. It is the
thin shadow wrapper around the §2 estimator and does steps 1–3 below in one
invocation (still measure-only; nothing is wired into the promotion gate).

1. **Input:** the current events file
   (`~/.local/share/skipp/vpin_followup/events_v3_abs_opra.json` today; in live
   ops, the rolling production events export). Use `-` to read from stdin.
2. **Run** (pure-python, deterministic seed):
   ```bash
   EV=~/.local/share/skipp/vpin_followup/events_v3_abs_opra.json
   PYTHONPATH=. .venv/bin/python scripts/run_magnitude_shadow_ledger.py "$EV" \
     --seed 230022
   ```
   This grades **each** of BOS, SWEEP, FVG, OB against the §2 bar and appends
   one row per family to the ledger. Exit code: `0` if any family PASSES, `2` if
   measurable but none passes, `3` if every sample is too thin, `1` on
   usage/config error. The only piece still TODO is the *scheduler* that runs
   this daily and the report in §4.5.
3. **Per family, captured automatically:** `n_oos`, `magnitude_auc`,
   `auc_ci_low`, `baseline_resolution`, `perm_null_p95`, `perm_p`, `passes`
   (bool), `status` (PASS/FAIL/INCONCLUSIVE), `fail_reasons` (e.g. `auc_floor`,
   `auc_ci`, `resolution_null`), `role` (candidate/control), plus `seed` and the
   events content hash for provenance.

### 4.2 Recording (append-only ledger) — IMPLEMENTED

- The runner appends **one row per family per day** to an append-only JSONL
  ledger, default `artifacts/governance/magnitude_resolution_shadow.jsonl`
  (override with `--ledger`). Writes go through `atomic_write_text`; re-running
  for the same `(date, family, events_hash)` is idempotent (latest row wins) and
  history is never truncated.
- Columns:

  ```
  date, events_hash, seed, family, n_oos, magnitude_auc, auc_ci_low,
  baseline_resolution, perm_null_p95, perm_p, passes, fail_reasons
  ```
- Never overwrite history — drift analysis needs the full series.
- The same numbers feed the promotion-gate snapshot fields
  (`magnitude_resolution_pass`, `magnitude_auc`) so the **gate sees them too**,
  but in Stage 1 the gate is lax ⇒ they are recorded, not enforced.

### 4.3 Daily evaluation rules

Per family, a day is classified as:
- **PASS** — all §2 conditions hold (AUC≥0.60, CI-low≥0.55, resolution>null
  p95, no dir-Brier regression, n_oos≥40).
- **FAIL(reasons)** — at least one condition missed; record which.
- **INCONCLUSIVE** — `n_oos < 40` (do not count as PASS or FAIL).

### 4.4 Weekly judgement (the part that matters)

Daily PASS/FAIL is noisy; **decisions are made weekly**, not daily:
- Compute, per family, the **k-of-n** streak over the trailing window
  (recommend n = last 4 weekly evaluations, k ≥ 3).
- **BOS/SWEEP healthy** = k-of-n PASS AND CI-low not trending toward 0.55.
- **FVG/OB control healthy** = stays FAIL/below the bar (expected).
- **Red flags to escalate (do NOT auto-advance):**
  - All four families PASS in the same window ⇒ suspect data/pipeline artifact;
    investigate before trusting any of them.
  - A candidate (BOS/SWEEP) drops below the bar ⇒ note it; if it persists
    k-of-n, that family is **not** Stage-2 eligible.
  - A control (FVG/OB) crosses *above* the bar ⇒ real signal; it becomes a new
    candidate, but must itself satisfy k-of-n before promotion — the bar is
    unchanged.

### 4.5 Stage 1 reporting

- A short weekly summary (can hang off the existing weekly dashboard —
  [weekly_dashboard_readme.md](./weekly_dashboard_readme.md)) showing, per
  family: latest AUC, CI-low, pass/fail, k-of-n streak, and a sparkline of AUC
  over time.
- Explicitly state the Stage-2 exit criterion status ("BOS 3/4 ✓, SWEEP 4/4 ✓,
  FVG 0/4 (control), OB 0/4 (control) → eligible to arm Stage 2: BOS+SWEEP").

---

## 5. Other modules / construction-sites to keep in mind

1. **E[PnL]-after-cost secondary check (§5 of the findings doc).** BLOCKS
   Stage 3. Statistically resolving ≠ profitable after costs. Must be built and
   pass for BOS/SWEEP before any real sizing change.
   *Status 2026-06-11: built.* Estimator (`governance/epnl_after_cost.py`),
   gate CLI (`scripts/run_epnl_after_cost_gate.py`) and the empirical cost
   model (`governance/execution_costs.py` +
   `scripts/calibrate_execution_costs.py`) exist; the gate consumes the
   conservative (CI-high) round-turn cost via `--cost-calibration`
   (fail-closed when unmeasurable). Awaiting C8 Phase-A paper sessions to
   produce ≥ 20 measurable fills before the §5 verdict can be recorded.

2. **The pipeline step that fills the snapshot fields.** Today
   `magnitude_resolution_pass`/`magnitude_auc` default to `None` ⇒ the gate is
   dormant. The Stage-1 runner (`scripts/run_magnitude_shadow_ledger.py`) now
   produces the per-family verdicts; the remaining task is to feed the latest
   ledger row into the promotion-gate `FamilyMetrics` snapshot (still lax in
   Stage 1) and to schedule the runner daily.

3. **Direction-Brier gate stays parallel.** The old tier-2 direction objective
   is NOT removed. Both objectives coexist; magnitude is additive. Don't delete
   the direction gate when arming magnitude.

4. **Strict-vs-lax mode path** (`promotion_gate.py`, `t.strict_provenance`).
   Stage 2 is literally "flip qualified families to strict for this check".
   Understand `REQUIRED_PROVENANCE_KEYS` / ADR-0016 no-ML waiver interactions so
   arming magnitude doesn't accidentally trip unrelated provenance info-blockers.

5. **`family_verdict.py` tier-2 `risk_sizeable` / `_CALIBRATION_CHECKS`.**
   `magnitude_resolution_floor` now participates here. Confirm the tier-2
   verdict aggregation treats a dormant (None) magnitude check as non-fatal —
   it does today, but re-verify after any verdict refactor.

6. **Multiple-testing discipline.** Re-checking 4 families weekly inflates the
   chance of a spurious pass. The k-of-n confirmation + the permutation-null
   already guard this; keep them. Do not lower k to rush a promotion.

7. **Monitoring / drift (ongoing).** BOS/SWEEP pass *today*. Markets move.
   Stage 1 monitoring must keep running even after Stage 3, so a family that
   falls below the bar is auto-demoted from magnitude sizing.

8. **Adjacent recently-closed axes (context, do not reopen without cause):**
   - **ADR-0020 options-flow** — corrected to a clean NULL on fairly-tested
     `tcbbo` quote-classified data. **Meta-Label C stays LOCKED; options-flow
     axis EXHAUSTED.** Do not resurrect signed-flow as a magnitude feature.
   - **ADR-0021 cross-asset HY lead-lag + `rejection_blocks` auxiliary** — live
     producer-contract; honesty tests were realigned (see #2582). If you touch
     `smc_integration/structure_contract.py` AUXILIARY_KEYS, update the matching
     honesty tests.

---

## 6. File / PR map

| Artifact | What |
|----------|------|
| `governance/magnitude_resolution_gate.py` | §2 estimators (NEW, #2581) |
| `scripts/run_magnitude_resolution_gate.py` | CLI runner / one-shot §2 report (NEW, #2581) |
| `scripts/run_magnitude_shadow_ledger.py` | Stage-1 shadow ledger runner (NEW) |
| `tests/test_magnitude_resolution_gate.py` | 11 unit tests (NEW, #2581) |
| `tests/test_magnitude_shadow_ledger.py` | Stage-1 ledger unit tests (NEW) |
| `governance/promotion_gate.py` | `FamilyMetrics` fields + `ok_magnitude` branch (EDIT, #2581) |
| `governance/types.py` | `magnitude_resolution_floor` in `BLOCKER_CHECK_NAMES` (EDIT, #2581) |
| `governance/family_verdict.py` | check added to `_CALIBRATION_CHECKS` (EDIT, #2581) |
| `scripts/run_promotion_gate.py` | `magnitude_auc` numeric field + bool map (EDIT, #2581) |
| `docs/governance/adr0023_magnitude_retarget_findings.md` | §2 results, RESOLVED (EDIT, #2581) |
| `docs/governance/adr0023_live_rollout_handover.md` | **this file** |
| `docs/adr/0023-tier-2-size-gate-magnitude-retarget.md` | the frozen ADR + §2 bar |

PR #2581 = `feat/adr0023-magnitude-resolution-gate` (the magnitude work).
PR #2582 = `chore/atomic-write-exempt-pull-tick-trades` (3 unrelated main
unblockers; merges first).

---

## 7. Immediate next actions for the next agent

1. ~~Build the **Stage-1 daily runner**~~ — **DONE**:
   `scripts/run_magnitude_shadow_ledger.py` grades all four families and appends
   to the append-only shadow ledger (§4.1–4.2). Remaining: **schedule** it daily
   and **feed the latest ledger row** into the promotion-gate snapshot (still
   lax).
2. Stand up the **weekly Stage-1 report** (§4.5) on the existing dashboard.
3. Start building the **E[PnL]-after-cost** secondary check (§5 / item 1) — it
   is the true blocker for any real sizing change.
4. Do **not** arm strict mode or change sizing until the Stage-1 → Stage-2 exit
   criterion (§3) is met with real, multi-window data.

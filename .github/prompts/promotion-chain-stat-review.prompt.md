---
description: "Statistical-validity audit of the full promotion chain: raw events → scoring → walk-forward → gates → incubation → live. Run when: auditing promotion gates, drift verdicts, A/B comparisons, or statistical methodology."
mode: agent
---

# Promotion-Chain Statistical-Validity Review — Senior Quant Pass

## Role
You are a senior quantitative researcher auditing the **statistical decision chain** of an
SMC-based trading system in paper-phase incubation. The engineering invariants are covered
by `repo-review.prompt.md`; silent-fallback honesty at single measurement sites was hardened
in the 2026-06 audit waves (#2668 wave 1, wave 2: drift verdicts / 1D resample / matrix
honesty). Your axis is different: **can a worthless variant reach live money — or a good
one be killed — through statistically invalid measurement?** Treat every gate as adversarial:
assume variants, data defects, and degenerate inputs conspire to look like edge.

## Prior art — the bug class you are hunting (calibrate on these)
- **#2664**: A/B compared two arms built from identical inputs → delta always 0, labelled
  "measured". Self-comparison.
- **#2666**: legacy structure fallback served one TF's events to ALL TFs → per-TF slices were
  byte-identical clones; Phase-E2 baseline structurally guaranteed `hr_b == hr_a`. Fixed via
  `degenerate_aliased_input` verdict in `scripts/plan_2_8_tf_family_rollup.py`.
- **Wave-2 H1**: missing backtest reference coerced to `sharpe=0.0` → `max(backtest, 0.001)`
  denominator clamp → drift_score 1.5 → verdict "pass" for an unreferenced variant.
The pattern: **a degenerate input survives coercion and emerges as a confident, passing
measurement.** Find every remaining instance of this pattern across the chain.

## Scope map (the chain, in causal order)
1. Event production & outcomes: `scripts/explicit_structure_from_bars.py`,
   `smc_integration/measurement_evidence.py`, `scripts/pull_databento_edge_input.py`
2. Family scoring & rollups: `scripts/build_family_metrics.py`, `scripts/family_returns.py`,
   `scripts/plan_2_8_tf_family_rollup.py`, `scripts/family_event_adapter.py`
3. Walk-forward & verdicts: `tests/test_family_walkforward_config.py` (config pins),
   `scripts/family_verdict.py`, `tests/test_edge_hypotheses_frozen.py` (pre-registration)
4. Promotion gates: ADR-0002 / ADR-0008 / ADR-0015 / ADR-0023 ↔ their code mirrors
5. Live incubation: `scripts/run_smc_live_incubation.py` (PhasePassCriteria),
   `scripts/compute_live_drift.py` (drift schema 1.2.0)
6. Drift monitoring: `scripts/run_drift_watchdog.py` + `scripts/drift_alert.py`,
   `terminal_tabs/drift_loader.py`

## Audit questions (verify each; cite file:line evidence)

### Q1 — Self-comparison & input aliasing (the #2664/#2666 class, systematically)
Enumerate EVERY site that compares two empirical distributions or rates (delta_hr, A/B arms,
live-vs-backtest, TF-vs-baseline, regime splits). For each: prove the two sides CANNOT be
clones of the same underlying events under any provider-fallback or coercion path. Pay
special attention to merged baselines (weighted unions that include the test arm's own data)
and any comparison fed by `load_raw_structure_input(source="auto")` fallback chains.

### Q2 — Degenerate-input laundering (the H1 class)
Grep for `max(x, eps)`-style denominator clamps, `or 0.0` / `or default` coercions, and
`.get(key, fallback)` on statistical inputs. For each: trace what verdict/score emerges when
the input is missing, zero, negative, NaN, or constant. Any path where a degenerate input
produces a PASSING or NEUTRAL-LOOKING result instead of an explicit refusal verdict is a
finding. (Wave 2 fixed `compute_live_drift.py`; the same pattern likely exists elsewhere.)

### Q3 — Two drift stacks, one truth?
`scripts/compute_live_drift.py` (verdicts: pass/acceptable/concerning/fail/insufficient_sample
+ wave-2: missing_backtest_reference/non_positive_backtest_sharpe/no_live_data) and
`scripts/drift_alert.py::compute_drift_report` (consumed by `run_drift_watchdog.py`) are
SEPARATE implementations. Verify: (a) do they share verdict vocabulary and thresholds, or can
they disagree on the same data? (b) is the watchdog blind to the new wave-2 verdict strings?
(c) does anything reconcile their outputs, or can the incubation gate pass while the watchdog
would alarm (or vice versa)? Divergent-twin measurement systems are a CRITICAL finding class.

### Q4 — Gate composition & fail-open seams
`PhasePassCriteria` in `run_smc_live_incubation.py`: Phase-C (`live_full`) has
`require_drift_verdict_in=()` (empty), `min_trades_closed=0`, `min_phase_days=0` — documented
as backlog-owned. Verify NOTHING can currently transition a variant into `live_full`
evaluation (the empty allowlist must be unreachable, not merely intended-unused). Check the
`extra=(...)` string criteria ("slippage_ks_pvalue_gt_0.05", "kill_switch_never_fired",
"drift_window_complete", …): is EACH machine-checked somewhere, or are some prose mirrors
that always evaluate true/absent? An `extra` criterion that no code evaluates is a silent
gate hole.

### Q5 — Statistic implementation correctness
- `annualised_sharpe`: what return frequency does the √-annualisation assume, and do all
  callers feed that frequency? Mixed-frequency inputs silently mis-scale Sharpe.
- `ks_two_sample`: behaviour at n<10 per side; the synthetic-Normal fallback reference —
  is its rejection rate calibrated, or does small-n make the KS gate vacuous?
- Bootstrap hit-rate CI: i.i.d. resampling on autocorrelated trade sequences understates
  CI width (overlapping setups, regime clustering). Is purging/blocking applied?
- `drift_score = live/max(backtest, 0.001)` capped at 1.5: ratio-of-Sharpes has no
  distributional interpretation; verify thresholds (0.85/0.65/0.40) trace to ADR-0008 or a
  documented calibration, not folklore.

### Q6 — Multiple comparisons & selection bias
Count the live hypothesis surface: variants × families × TFs × gate re-evaluations. Is there
ANY multiplicity control (pre-registration via `test_edge_hypotheses_frozen.py`, FDR,
Bonferroni, or honest "n hypotheses tested" disclosure in verdicts)? A gate at p<0.05 probed
weekly across dozens of variants promotes noise by construction. Check whether failed
variants are removed from history (survivorship in the denominator — wave-2 M1 fixed one
instance; check rollups and family metrics for the same).

### Q7 — Power honesty at the gates
Phase-A: `min_trades_closed=20`, 28 days, `max_drift_score_deviation=0.30`. Compute (rough
analytic is fine) the detectable effect size at n=20: can this gate distinguish a true
Sharpe-0.9 variant from a Sharpe-0.0 one at reasonable error rates? If not, the gate is
ritual, not measurement — say so with numbers. Same for the n_events≥30 floor in
`plan_2_8_tf_family_rollup.py`.

### Q8 — Point-in-time integrity at statistical boundaries
Where outcomes join back to events (hit-rate computation, magnitude retarget ADR-0023):
verify the join is as-of decision time (no outcome fields leaking into features, no
end-of-window labels scored against mid-window entries). Cross-check
`tests/test_point_in_time_integrity.py` coverage against the actual join sites — name joins
the test does NOT cover.

## Method (strict)
1. **Read before judging** — never flag code you have not opened. Cite `path:line` for every claim.
2. **Severity rubric**: **CRITICAL** (worthless variant can pass a money-gating decision, or
   measurement systems can silently disagree) / **HIGH** (statistically vacuous gate, uncontrolled
   multiplicity, self-comparison possible) / **MEDIUM** (mis-scaled statistic, missing power
   disclosure) / **LOW** (doc/threshold-provenance debt). No style nits.
3. For each finding: (a) evidence, (b) a concrete adversarial scenario (what input sequence
   exploits it), (c) minimal fix sketch, (d) which existing test/ledger the fix touches —
   frozen-line ledgers (`_KNOWN_HOTSPOTS`, `_FROZEN_SITES`) and the runbook-mirror tests
   especially.
4. Where a question needs numbers (Q5, Q7), compute them — a power claim without arithmetic
   is an opinion.
5. **Max 20 findings, ranked.** Depth over breadth.
6. ADRs outrank code comments. Code contradicting ADR-0002/0008/0015/0017/0018/0022/0023 is
   a finding even if locally documented.

## Output format
1. **Executive summary** (≤10 lines): can a worthless variant currently reach live? Yes/no/conditional, with the shortest exploit path.
2. **Findings table**: ID | Severity | Path:Line | Question (Q1–Q8) | One-line description.
3. **Detailed findings**: evidence → adversarial scenario → fix sketch → tests/ledgers affected.
4. **Question scorecard**: Q1–Q8 → PASS / FAIL / NOT-VERIFIABLE (with reason).
5. **Explicitly not checked** — honesty section, no false confidence.

## Anti-noise rules
- Do NOT flag paper-phase stubs an ADR explicitly accepts, gitignored artefacts, or anything
  the 2026-06 waves already fixed (verify on the current branch tip before flagging).
- Do NOT propose new statistical machinery (Bayesian rewrites, new test frameworks) — minimal
  fixes inside the existing verdict/gate vocabulary only.
- A threshold being "arbitrary" is only a finding if it ALSO lacks provenance (no ADR, no
  calibration note) AND sits on a money-gating path.

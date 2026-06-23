# Architectural Decisions

> Canonical ADR-style log of deliberate architecture choices for
> `skippALGO/skipp-algo`. Each entry records a decision, the rationale,
> alternatives considered, and the rejection reasons for the paths
> not taken. Entries are append-only; superseded decisions stay visible
> with a `Status: superseded` header and a pointer to the replacement.
>
> For the meaning of the sprint codes, phase names, and domain
> abbreviations used throughout these entries, see the
> [Glossary](GLOSSARY.md).

## Format

Each ADR is a `### YYYY-MM-DD - <slug>` H3 section with the following
labelled subsections (all required):

- **Context** — the situation that triggered the decision.
- **Decision** — the chosen path, in imperative voice ("we do X").
- **Alternatives considered** — enumerated list; each item names the
  alternative and the single-sentence reject reason.
- **Consequences** — what the decision costs us and what it buys.
- **Evidence** — links to tests, benchmarks, or upstream references
  that ground the decision.
- **Status** — one of `accepted`, `superseded by <slug>`, `deferred`.

---

## Entries

### 2026-04-21 - 3-layer HTF trend stack over Flux-style 7-TF bias

**Context.** Competitor scripts (notably
[Flux Market Structure Dashboard](https://www.tradingview.com/script/vXui7vrm-Market-Structure-Dashboard-Flux-Charts/))
advertise 7-TF configurable bias stacks. Marketing pressure suggested
matching feature count. The measurement lane's per-bucket calibration
story is incompatible with user-chosen TF weights.

**Decision.** Keep the ICT-standard 3-layer trend hierarchy
(`4H / 1D / 1W`) plus the adaptive IPDA dach-TF above layer 3.
Expand only the *benchmark* chart-TF coverage
(`5m / 15m / 1H / 4H`) — see Plan 2.8 S3.1. Reject Flux-style
user-configurable 7-TF bias stacks.

**Alternatives considered.**

- *Flux-style 7-TF user-configurable bias stack.* Rejected: breaks
  per-family × per-context calibration because the scorer becomes
  user-specific and thus non-reproducible.
- *4th intraday trend layer immediately (30m or 2H).* Deferred to
  Q4-gate review (W13): can only land if the three §3.2 gates pass
  (HR uplift >= 3pp in >= 2 buckets, Brier regression <= 0.02, every
  bucket >= 30 events). 30m also rejected vs 2H because it sits too
  close to the 15m chart-TF and adds noise rather than signal.
- *Sub-minute LTF (5s / 15s) for microstructure.* Deferred to 2027
  Q1+: requires Databento tick integration in the benchmark side
  and breaks the Free-Tier reproducibility guarantee.

**Consequences.**

- Calibration story stays compact and reproducible. The
  "measured not claimed" positioning remains defensible.
- Feature-count comparison tables put us at apparent disadvantage
  (3 TFs vs. 7). Mitigated via the tooltips on `Trend TF 1/2/3`
  inputs (they document the intent explicitly) and via the README
  Academic Grounding section.
- Preprint appendix (Q4) can report a single calibrated scorer
  rather than a per-user family of scorers.

**Evidence.**

- [`docs/smc_improvement_plan_addendum_2_8_mtf_scope_2026-04-21.md`](./smc_improvement_plan_addendum_2_8_mtf_scope_2026-04-21.md)
  (the full decision memo).
- [`tests/test_plan_2_8_s0_pine_trend_tf_tooltips.py`](../tests/test_plan_2_8_s0_pine_trend_tf_tooltips.py)
  pins the tooltip accuracy.
- [`tests/test_plan_2_8_s3_1_chart_tf_expansion.py`](../tests/test_plan_2_8_s3_1_chart_tf_expansion.py)
  pins the 4-TF benchmark default.
- [`tests/test_plan_2_8_s3_1_per_tf_partitioning.py`](../tests/test_plan_2_8_s3_1_per_tf_partitioning.py)
  pins per-TF artifact partitioning.
- [`scripts/plan_2_8_q4_gate_evaluator.py`](../scripts/plan_2_8_q4_gate_evaluator.py)
  is the W13 gate evaluator; passing it is a precondition for
  reconsidering the "4th trend layer deferred" branch.

**Status.** accepted.

### 2026-06-14 - governance-hierarchy-evidence-and-org-scope-gate

**Context.** A supply-chain / CI-integrity audit required a hard
evidence snapshot of the *effective* governance stack for
`skippALGO/skipp-algo`: organization rulesets, repository rulesets,
and branch protection on `main`. Prior notes correctly flagged that
org-wide rulesets were not fully verifiable, but the gap had to be
made explicit, reproducible, and separated from the already-verifiable
repo/branch controls.

Live GitHub API checks on 2026-06-14 showed:

* token scopes = `gist, read:org, repo, workflow` (no `admin:org`),
* repo rulesets retrievable and active,
* branch protection retrievable and active,
* org ruleset endpoint blocked (`admin:org` required).

**Decision.** We treat governance evidence as a three-tier contract and
report each tier independently:

1. **Org tier** is `NOT-VERIFIABLE` unless the current GitHub token has
   `admin:org` and `gh api orgs/<org>/rulesets` succeeds.
2. **Repo tier** is `PASS` only when active rulesets are fetched and
   their effective conditions/rules are recorded.
3. **Branch tier** is `PASS` only when
   `branches/main/protection` confirms the required checks and force-push
   policy.

For this snapshot, org is explicitly blocked by scope; repo and branch
are accepted as verified controls.

**Alternatives considered.**

- *Mark org tier as pass using `read:org` plus inference from UI/docs.*
  Rejected — this would create false confidence; API evidence is the
  source of truth for enforceable governance state.
- *Collapse org+repo+branch into one boolean governance verdict.*
  Rejected — hides where evidence is strong vs. where scope blocks
  visibility.
- *Defer documentation until `admin:org` is granted.* Rejected — the
  current limitation is itself a governance-relevant fact and must be
  visible now.

**Consequences.**

- Audit outputs now distinguish **verified controls** from
  **scope-blocked controls** without ambiguity.
- Repo/branch posture is evidence-backed today (active rulesets,
  required `fast-gates`, no force-push on `main`).
- Org-wide posture remains an explicit action item gated on auth scope,
  not a silent omission.

**Evidence.**

- Auth scope check (`gh auth status -h github.com`):
  `Token scopes: 'gist', 'read:org', 'repo', 'workflow'`.
- Org ruleset query (`gh api orgs/skippALGO/rulesets`):
  `HTTP 404` + explicit hint: requires `admin:org`.
- Repo rulesets (`gh api repos/skippALGO/skipp-algo/rulesets`):
  active rulesets `main-governance` (id `15245308`) and
  `skipp-algo` (id `12576994`).
- Repo ruleset detail:
  - `main-governance` targets `~DEFAULT_BRANCH`, requires strict status
    check `fast-gates`, and enforces squash-merge policy.
  - `skipp-algo` targets `~ALL`, enforces Copilot code review policy.
- Branch protection (`gh api repos/skippALGO/skipp-algo/branches/main/protection`):
  strict required check `fast-gates`; `allow_force_pushes=false`.

**Status.** accepted.

### 2026-04-22 - Degrade per-family HR display on sub-saturation corpora

**Context.** The Phase H2 smoke on 2026-04-22 surfaced
`ZONE_HR_OB=0.8636` from a 258-event corpus while the v3 audit
corpus (n=952 OB events) showed OB HR=0.3675 — a 50 pp gap. The
existing `ZONE_CAL_CONFIDENCE=0.15` signal was visible but not
enforced: Pine rendered the overstated number regardless.

**Decision.** Gate the per-family `ZONE_HR_<FAM>` Pine exports on
`ZONE_CAL_CONFIDENCE >= 0.30`. Below the threshold the consumer
emits the sentinel `-1.0` and Pine renders `—`. A new scalar
export `ZONE_CAL_TRUST ∈ {FRESH, DEGRADED, STALE, UNAVAILABLE}`
carries the classification for the Dashboard trust row.

The `0.30` threshold reflects the saturation curve in
`compute_calibration_confidence`: 300 events at `smECE = 0` —
well above the Blasiok-Nakkiran 30/bucket floor — produce
`confidence ≈ 0.30`. Below that, the sub-saturation/ECE-penalty
combination dominates and the rendered HR is statistically
indistinguishable from noise.

**Alternatives considered.**
- *Hard-zero degraded HRs.* Rejected — `0.0` is the "pre-calibration"
  default and would collapse two semantically distinct states.
- *Render the value with a warning badge.* Rejected — the H2 smoke
  proved that an inline badge does not prevent users from reading
  the number as truth.
- *NaN sentinel.* Rejected — Pine `const float` has no `na`; `-1.0`
  is clamp-safe and unambiguous.
- *Degrade on `UNAVAILABLE` too.* Rejected — `UNAVAILABLE` means
  "no calibration data flowed through" and the upstream defaults
  already carry the neutral `0.0` values that Pine consumers guard
  with `zone_hr_<fam> <= 0.0`. The sentinel is reserved for
  "calibration ran, result not trustworthy".

**Consequences.**
- Eliminates the 50 pp OB misdisplay without waiting for WS2.
- Adds the `ZONE_CAL_TRUST` export as a forward-compatible hook
  for the WS2 Trust-State refactor — `STALE` is already in the
  vocabulary, to be wired in when freshness metadata lands.
- Existing Pine guards (`SMC_Dashboard.pine` L1399, L1593:
  `mp.ZONE_HR_FVG <= 0.0`) catch the new `-1.0` sentinel without
  Pine-side code changes.
- One-line change to the Q3 H2 smoke expectation (it now reports
  `DEGRADED`, not 0.8636).

**Evidence.**
- [`scripts/smc_zone_priority_consumer.py`](../scripts/smc_zone_priority_consumer.py)
  `classify_trust_state` and `degrade_family_hit_rates`.
- [`tests/test_smc_zone_priority_consumer.py`](../tests/test_smc_zone_priority_consumer.py)
  `test_aggregator_degrades_ob_hr_on_subsaturation_sample` pins
  the regression.
- [`docs/FVG_LABEL_AUDIT_Q3.md`](FVG_LABEL_AUDIT_Q3.md) §5 (the
  OB prior mismatch).

**Status.** accepted.

### 2026-04-23 - Soft-fail the live-news refresh push step

**Context.** Since 2026-04-20 the
[`smc-live-newsapi-refresh.yml`](../.github/workflows/smc-live-newsapi-refresh.yml)
cron has produced 52 consecutive run failures. Root cause is *not* the
refresh logic — the snapshot is built and uploaded as an artifact every
run — but the trailing `git push` step, which `main`'s branch protection
rejects because direct pushes are no longer allowed (PRs only). Every
failure paged on-call without representing real data degradation.

A separate but adjacent symptom landed the same day in
[#24 (`a8d8ffb7`)](https://github.com/skippALGO/skipp-algo/pull/24):
143 `STALE_META_*_DOMAIN` failures from the `provider_health` release
gate were caused by static `asof_ts` stamps in
`reports/largecap_watchlist.json` and the live-news snapshot. That fix
is a *hard* fix (loaders now stamp `asof_ts` at load time when
`asof_strategy: "now"` is set) and restores the gate's intended
semantics — it is **not** the soft-bypass this ADR records.

**Decision.** Mark the *commit/push* step in
`smc-live-newsapi-refresh.yml` as `continue-on-error: true` and
downgrade push/rebase failure annotations from `::error::` to
`::warning::` (commits `3b9f9458` / [#25](https://github.com/skippALGO/skipp-algo/pull/25)).
The artifact upload (`actions/upload-artifact@v4` of
`smc_live_news_snapshot.json`) remains the **authoritative delivery
channel**; downstream consumers already prefer the artifact over
the committed copy.

The `provider_health` gate itself stays hard. Only the cosmetic
`git push` failure is soft.

**Alternatives considered.**

- *Switch the workflow to open a PR via `peter-evans/create-pull-request`.*
  Deferred — adds a second moving part (PR auto-merge policy) for a
  payload that is consumed exclusively from the artifact channel.
  Reconsider when at least one consumer reads the committed copy.
- *Carve out a branch-protection exemption for the
  `github-actions[bot]` actor.* Rejected — weakens the
  PR-only invariant for every workflow on `main`, not just this one.
- *Stop committing the snapshot at all (artifact-only).* Deferred —
  the committed copy is still useful as a human-readable diff trail
  in `git log`. Revisit if the soft-push starts masking real
  refresh-logic regressions.
- *Keep failing loud.* Rejected — 52 consecutive failures had already
  trained on-call to ignore the alert; the signal-to-noise ratio
  inverted the gate.

**Consequences.**

- On-call paging from this workflow drops to zero unless the refresh
  *itself* fails (artifact step is still hard).
- Loss of the auto-commit timeline on `main` — diff-archaeology on
  the snapshot now requires pulling artifacts from the workflow run
  page. Acceptable because the artifact retention (90 d default) is
  longer than the operational lookback window.
- Re-hardening trigger: when branch protection learns to allow
  `[skip ci]`-tagged bot-commits, or when the workflow is migrated
  to a PR-based delivery, the `continue-on-error` line is removed
  and the warning annotation is restored to `::error::`. This ADR
  is then superseded.

**Evidence.**

- [`.github/workflows/smc-live-newsapi-refresh.yml`](../.github/workflows/smc-live-newsapi-refresh.yml)
  — `Commit snapshot updates` step carries
  `continue-on-error: true` and the inline rationale comment.
- Commit `3b9f9458` ([#25](https://github.com/skippALGO/skipp-algo/pull/25))
  — soft-push wiring + warning-level annotations.
- Commit `a8d8ffb7` ([#24](https://github.com/skippALGO/skipp-algo/pull/24))
  — adjacent `provider_health` hard fix
  (`asof_strategy: "now"` marker; not part of the soft-bypass).

**Status.** accepted.

### 2026-06-02 - product-focus-on-edge-over-governance

**Context.** Across the open PR queue (11 PRs) roughly 72% is
infrastructure/governance meta-work (ADR enforcement, pin ledgers,
frozen tripwire roster, silent-skip hardening, PR-title linter) plus
auto-generated snapshot PRs carrying run-ids. Zero open PRs deliver
demonstrable SMC trading edge. Recurring "missing module discovered
just before workflow start" incidents (`data()` title bug #2498/#2509,
roster referencing non-existent tests #2463, decision JSONs living only
on branches #2508) are structural: generators emit artefacts that
violate gates the generators do not pre-check. Full diagnosis in
[DIRECTOR_FINDINGS_2026-06-02.md](DIRECTOR_FINDINGS_2026-06-02.md).

**Decision.** We re-anchor on a single North Star: the SMC suite is a
product only when one SMC strategy shows reproducible, out-of-sample
positive edge on live Databento data, measured by the promotion gate —
not by green CI. Concretely we (a) stop running auto-snapshot outputs
as review PRs and merge the substantially-finished ADR/infra PRs to
close those themes, (b) concentrate effort on the single EV-20
edge-pipeline value stream and *evaluate* the 16 rescued decision JSONs
(#2508) rather than archive them, and (c) require a reusable pre-flight
validator (title-concern + referenced test paths + schema version) that
every generator calls before `gh pr create`.

**Alternatives considered.**

- *Keep widening governance coverage first.* Rejected — a promotion
  gate is worthless while nothing is promotable; more gates do not
  produce edge.
- *Fix each generator drift incident ad hoc as it surfaces.* Rejected —
  that is the current circular pattern; #2509 fixed one title bug but
  the class recurs without a shared pre-flight check.
- *Pause all infra work immediately.* Rejected — the near-finished ADR
  PRs are cheaper to land than to re-open later; we close them, then stop.

**Consequences.**

- Review bandwidth shifts off snapshot churn onto the EV-20 evaluation.
- Auto-snapshot history moves from `main` commits/PRs to job artifacts;
  diff-archaeology requires the workflow run page (acceptable, matches
  the existing soft-push snapshot precedent above).
- A new shared dependency: every PR-generating workflow must invoke the
  pre-flight validator; generators that skip it are a regression.
- Re-evaluation trigger: once the first EV-20 verdict (edge yes/no/unclear)
  is produced, this decision is revisited to set the next value-stream target.

**Evidence.**

- [DIRECTOR_FINDINGS_2026-06-02.md](DIRECTOR_FINDINGS_2026-06-02.md)
  — queue classification table + three-cause diagnosis.
- PR [#2509](https://github.com/skippALGO/skipp-algo/pull/2509)
  — `data(`→`chore(` generator title fix (point-fix that motivates the
  systematic pre-flight validator).
- PR [#2508](https://github.com/skippALGO/skipp-algo/pull/2508)
  — 16 rescued real edge-pipeline decision JSONs (the first evaluation input).

**Status.** accepted.

### 2026-06-09 - sprt-rollback-signal-validates-null-candidate

**Context.** The F2 promotion gate (`f2-promotion-gate-daily.yml`) has
emitted five consecutive `rollback` decisions (2026-06-03 → 2026-06-09).
The underlying Wald SPRT (one-sided, single-arm vs fixed baseline) ran
with `p0 = 0.55`, `p1 = 0.60`, `alpha = 0.05`, `beta = 0.20`.
After n = 1492 observations the test accepted H0 with
`LLR = −9.4392` — deeply below the lower Wald boundary
`B = ln(β / (1 − α)) ≈ −1.39`. The candidate arm's hit rate
(54.42 %) is essentially equal to the control rate (54.43 %);
zero uplift is detectable. The required minimum-detectable effect
(`p1 − p0 = 5 pp`) was never approached, and the Q4-gate G1 threshold
(≥ 3 pp HR uplift in ≥ 2/3 context buckets) is unreachable with the
current 4-TF candidate spec.

**Decision.** Accept the SPRT H0 verdict as a valid experimental
signal. The current candidate spec does not improve on the static
baseline. We do not override the rollback or force-promote.
Next steps: (a) investigate whether the candidate spec's
feature-weight delta was too small to produce measurable edge,
(b) review the 4-TF benchmark partitioning for data-quality issues
(bucket saturation, context leakage), and (c) design the next
candidate iteration before re-entering the SPRT cycle.

**Alternatives considered.**

- *Override rollback and force-promote.* Rejected — the experiment
  conclusively shows no improvement; promoting would entrench a
  spec with zero edge and corrupt the promotion gate's credibility.
- *Extend the trial (raise max_n).* Rejected — LLR = −9.44 is
  6.8× below the lower boundary; additional observations cannot
  plausibly reverse the verdict.
- *Widen MDE (lower p1 to 0.57).* Deferred — a narrower MDE
  increases the chance of detecting a real but small effect, but
  should only be applied to a new candidate spec that has a
  prior-justified reason for smaller expected uplift.

**Consequences.**

- The rollback reverts to the static baseline weights; no
  user-visible regression because the candidate never outperformed.
- The SPRT state must be reset before any new candidate enters the
  gate. A spec-status flip (`plumbing_only → live`) triggers the
  reset automatically via the "Detect spec-status flip" step.
- The null result is itself evidence: the 4-TF scope delivers
  no measurable edge under current market conditions. This narrows
  the search space for the next iteration.

**Evidence.**

- [`scripts/smc_sprt_stop_rule.py`](../scripts/smc_sprt_stop_rule.py)
  — SPRT engine (Wald one-sided on Bernoulli outcomes).
- [F2 promotion-gate run 2026-06-09](https://github.com/skippALGO/skipp-algo/actions/workflows/f2-promotion-gate-daily.yml)
  — `decision: rollback, reason: SPRT accepted H0 (n=1492, k=812, llr=-9.4392)`.
- `f2_promotion_gate_2026-06-09.json` (CI workflow artifact, not checked in)
  — full gate report (`hit_rate: 0.5442`, `control_hit_rate: 0.5443`,
  `p0: 0.55`, `p1: 0.60`).

**Status.** superseded by
[2026-06-10 - f2-dual-arm-raw-score-shadowing](#2026-06-10---f2-dual-arm-raw-score-shadowing) —
the dual-arm post-processor never produced a distinct treatment arm, so
the "null result" compared control against control and is not evidence
about the candidate spec.

### 2026-06-09 - c13-phase-a-no-go-and-c13b-unblock-plan

**Context.** Sprint C13 (Live-Inkubation Phase A, 2026-04-28 →
2026-05-25) was signed off as **NO-GO** at sprint day 16
([`docs/c8_phase_a_signoff_2026-05-14.md`](c8_phase_a_signoff_2026-05-14.md)).
All four SMC families (BOS, OB, FVG, SWEEP) reported zero live days,
zero trades, and unknown drift. The nine daily cron entries between
2026-05-04 and 2026-05-13 all returned `metrics = {}`,
`n_events = null`. The root cause is **T1 — IBKR Paper-Onboarding**:
the IBKR paper-trading gateway was never connected, so no order
submissions, fills, or outcomes reached the calibration pipeline. The
pipeline itself functions end-to-end (T2 cron operational, T5 families
producer running) but has nothing to process. Four of five sign-off
criteria were NOT FULFILLED; the only passing criterion (killswitch
never fired) is vacuously true with zero trades. Sprint C14 Phase-B
Promotion is gated on C13 GO and is therefore BLOCKED.

**Decision.** (1) Record the C13 NO-GO as a binding architectural
fact — no Phase-B promotion can proceed until the NO-GO is resolved.
(2) Define a minimal C13b-unblock spec
([`spec/sprints/c13b_live_incubation_unblock.md`](../spec/sprints/c13b_live_incubation_unblock.md))
that names the single prerequisite: complete IBKR Paper-Onboarding
(T1) and verify at least one paper trade flows end-to-end through
the calibration pipeline. (3) C13b is scoped to unblocking only —
it does not re-run the full 28-day incubation window; that is C13
phase-A replay once the pipeline receives data.

**Alternatives considered.**

- *Bypass C13 NO-GO and open C14 directly.* Rejected — C14 requires
  a GO verdict with real trade data; skipping the gate undermines the
  "Beweise oder kein Verkauf" binding contract.
- *Replace IBKR paper-trading with synthetic replay data.* Deferred —
  synthetic data can validate pipeline mechanics (already done) but
  cannot substitute for real broker-fill latency and slippage in
  the drift-score criterion.
- *Abandon Phase-A and redesign the incubation approach.* Rejected —
  the pipeline infrastructure is complete; the failure is a single
  operational dependency (broker connectivity), not a design flaw.

**Consequences.**

- C14 remains BLOCKED until C13b is completed and C13 is re-signed.
- The C13b spec creates a clear, single-task dependency that can be
  tracked independently of sprint scheduling.
- Once T1 is completed, the existing cron infrastructure will begin
  producing real data immediately; no code changes are required.
- The NO-GO preserves the integrity of the promotion gate system:
  every stage must earn its verdict from data.

**Evidence.**

- [`docs/c8_phase_a_signoff_2026-05-14.md`](c8_phase_a_signoff_2026-05-14.md)
  — full sign-off document with empirical data table and criteria matrix.
- [`docs/sprints/backlog/c14_phase_b_promotion.md`](sprints/backlog/c14_phase_b_promotion.md)
  — C14 spec showing the C13-GO prerequisite.
- [`spec/sprints/c13b_live_incubation_unblock.md`](../spec/sprints/c13b_live_incubation_unblock.md)
  — the unblock spec created alongside this ADR.

**Status.** accepted.

### 2026-06-10 - f2-dual-arm-raw-score-shadowing

**Context.** A routine review of the failing F2 promotion-gate run
(run 27294581196, exit 2 = rollback) uncovered two independent bugs
that together invalidate the entire F2 dual-arm experiment to date.

*Bug 1 — raw_score shadowing (severity: experiment-invalidating).*
`scripts/f2_apply_contextual_calibration.py::_record_to_event`
forwarded the ledger's `raw_score` into the rescored arm events.
`smc_core.scoring._resolve_calibration_input` prefers `raw_score`
over `predicted_prob` whenever ALL events carry one — and production
ledgers always populate it. The blended per-arm probability (the
ONLY difference between control and treatment) was therefore
discarded before scoring: all 80 pair summaries in the CI dual-arm
artifact were byte-identical between arms, reproducible locally.
**The SPRT never measured the treatment — both the 2026-06-09
(n = 1492) and 2026-06-10 (n = 1588) verdicts compared control
against control.** Existing tests masked the bug because fixtures
used `"raw_score": None` instead of the production row shape.

*Bug 2 — SPRT spec params unwired (severity: wrong verdict).*
`f2_run_promotion_gate.py` never passed `spec.sprt` into
`run_ab_comparison.compare()`; `_sprt_decision` always used the
hardcoded module constants `p0=0.55 / p1=0.60` while the registered
spec says `p0=0.544 / p1=0.574 / max_n=1200`. The spec's sprt block
was dead config. Recomputed with the registered params, the
2026-06-10 corpus (n = 1588, k = 876) gives LLR ≈ −1.43, ABOVE the
Wald lower bound ≈ −1.56 → "continue", not `accept_h0`.

**Decision.** (1) Fix both bugs: `_record_to_event` no longer
forwards `raw_score`/`raw_score_name` (set to `None` with an
explanatory docstring), and the gate now threads `spec.sprt` through
`compare(sprt_config=...)` into `_sprt_decision`. (2) Do **not** set
`f2_contextual_promotion.json` status to `rolled_back`: the rollback
verdict was produced by a broken experiment and is void, not
validated. Status stays `live`. (3) The SPRT corpus restarts fresh —
all accumulated observations are control-vs-control and carry no
information about the candidate. (4) Add regression tests that
mirror the PRODUCTION row shape (`raw_score` non-null) and that pin
spec-config precedence over module fallbacks.

**Alternatives considered.**

- *Formalize the rollback as originally planned.* Rejected — the
  H0 acceptance is an artifact of Bug 1 + Bug 2, not evidence. A
  `rolled_back` status would launder a measurement failure into an
  experimental conclusion.
- *Fix in `smc_core.scoring` (make `predicted_prob` win).* Rejected —
  the raw_score preference is correct for first-pass scoring of raw
  ledgers; only the dual-arm rescoring path must suppress it. Fixing
  at the caller keeps the blast radius minimal.
- *Keep the accumulated SPRT corpus and continue.* Rejected — every
  observation to date is control-vs-control; mixing it with
  post-fix observations would bias the LLR toward H0.

**Consequences.**

- The 2026-06-09 ADR `sprt-rollback-signal-validates-null-candidate`
  is superseded: its "null result" and all downstream conclusions
  (candidate has zero edge, search-space narrowing) are void. The
  experiment must be re-run with the fixed post-processor.
- The spec is now the single source of truth for SPRT params; the
  module constants are explicit fallbacks for spec-less callers.
- `max_n = 1200` is honoured in the report: when the terminal LLR is
  still inside the Wald bounds at `n >= max_n`, `_sprt_decision()`
  re-labels the decision `max_n_reached` (stop accumulating) instead
  of `inconclusive` (keep accumulating). Bound-crossing decisions past
  the cap stand — `terminal_decision()` is order-independent and
  aggregated totals cannot be truncated to `max_n` without
  per-observation ordering. The gate treats `max_n_reached` and
  `inconclusive` identically (hold).
- Open follow-up: the gate run showed a flip-detection cache miss
  (`f2-last-spec-status-v1-` not found), so the SPRT-state reset on
  `plumbing_only → live` flips may not have fired; track separately.

**Evidence.**

- Gate run 27294581196 + rolling-bench run 27290553924 — 80/80 pair
  summaries byte-identical between arms (verified in CI artifact AND
  local reproduction from production ledgers).
- Local fix validation: post-fix rerun yields 0/80 identical pairs;
  e.g. AMZN/1H control brier 0.230325 vs treatment 0.236398.
- `rescore_pair` itself was correct all along: per-event blended
  probs differ between arms (e.g. BOS ctrl 0.8992 vs treat 0.3538);
  the divergence was destroyed downstream at scoring time.
- Regression tests:
  `tests/test_f2_apply_contextual_calibration.py::test_arms_differ_even_when_ledger_rows_carry_raw_score`,
  `tests/test_run_ab_comparison_sprt.py::test_sprt_decision_honors_explicit_config_over_module_defaults`,
  `tests/test_run_ab_comparison_sprt.py::test_compare_threads_sprt_config_into_digest`.

### 2026-06-10 - Plan 2.8 Phase-E2 verdicts void — cross-TF structure aliasing

**Context.** The rolling measurement benchmark resolves per-symbol
structure via the legacy single-artifact fallback
(`smc_integration/structure_contract.py::_select_legacy_entry`).
`reports/smc_structure_artifact.json` carries only `1D` entries, and
the fallback silently served that `1D` entry for every requested
chart TF (`5m / 15m / 1H / 4H`). All four TF slices therefore scored
the *same* events; outcomes are TF-invariant (price-path hit/miss),
so `n_events` and `hit_rate` were byte-identical clones across TFs
(only Brier differed via bar resampling). The Phase-E2 verdicts in
`scripts/plan_2_8_tf_family_rollup.py` compare arm A against a
merged `15m + 1H` baseline, which for clones structurally guarantees
`n_b = 2 × n_a`, `hr_b == hr_a`, `delta_hr = 0.0` — yet the verdict
was labelled `measured`. Verified against a full benchmark run
(2026-06-10): FVG `320/0.571875` and BOS `47/0.7659…` identical on
all four TFs. Same epistemics class as the dual-arm raw_score
shadowing bug (PR #2664) — an A/B comparison silently comparing an
arm against itself — via a different mechanism.

**Decision.** We declare every historical Phase-E2 verdict and every
per-TF hit-rate row produced from legacy-fallback structure void as
cross-TF evidence (control-vs-control class). We do not rewrite
`docs/plan_2_8_history.jsonl` — the archive stays append-only; this
ADR is the invalidation record. We make the fallback loud
(`legacy_tf_fallback: requested <tf>, served <tf>` contract warning
plus module logger warning) and teach `_phase_e2_verdict` to label
comparisons whose arm-A slice and every contributing baseline slice
are pairwise identical (`n_events` and `hit_rate`) as
`degenerate_aliased_input` instead of `measured`.

**Alternatives considered.**

- *Hard-fail the benchmark when the fallback fires.* Rejected for
  now — per-TF structure artifacts do not exist yet, so a hard fail
  would take the daily rolling benchmark down entirely; deferred to
  the follow-up issue as a strict-mode flag once per-TF artifacts
  are produced.
- *Detect degeneracy via `delta_hr == 0.0`.* Rejected — a zero delta
  is a legitimate possible measurement; pairwise slice identity
  (exact `n_events` and `hit_rate` equality) is the actual aliasing
  signature because clones are byte-identical while honest slices
  differ.
- *Rewrite or annotate `docs/plan_2_8_history.jsonl` in place.*
  Rejected — the history archive is append-only by design; mutating
  it would destroy the audit trail that makes the invalidation
  verifiable.

**Consequences.**

- The Plan 2.8 TTF/stability evidence base restarts from zero; no
  automation acted on the verdicts (blast radius was epistemic), but
  any human conclusions drawn from historical Phase-E2 rows must be
  discarded.
- Until per-TF structure artifacts exist, the rollup will report
  `degenerate_aliased_input` daily — an honest "no evidence" signal
  replacing a false "measured" one.
- Producing real per-TF structure artifacts in the rolling workflow
  (plus the strict-mode flag) is tracked as a follow-up issue.

**Evidence.**

- [`tests/test_plan_2_8_tf_family_rollup.py`](../tests/test_plan_2_8_tf_family_rollup.py)
  pins the `degenerate_aliased_input` verdict on the aliased fixture
  and the `measured` verdict once any slice differs.
- [`tests/test_smc_integration_structure_contract_diagnostics.py`](../tests/test_smc_integration_structure_contract_diagnostics.py)
  pins the `legacy_tf_fallback` contract warning and the non-mutation
  of the input payload.
- PR #2664 documents the sibling identical-arms failure (raw_score
  shadowing) that prompted auditing other A/B surfaces.

**Status.** accepted.

### 2026-06-14 - f2-contextual-candidate-closed-null-post-fix

**Context.** The F2 dual-arm fix from
[2026-06-10 - f2-dual-arm-raw-score-shadowing](#2026-06-10---f2-dual-arm-raw-score-shadowing)
voided every prior verdict (the SPRT had been comparing control
against control) and required the experiment to be re-run with the
corrected post-processor and spec-threaded SPRT params. The
post-fix promotion-gate run is now in: `f2-promotion-gate-daily`
run 27426121665 (report dated 2026-06-12). Its dual-arm summary is
the first to show **distinct arms** — control hit-rate `0.5336`
vs treatment `0.5337`, Brier-Δ `+0.0157`, calibrated-ECE worse —
confirming Bug 1 (byte-identical arms) is fixed in the data path:
the treatment is genuinely measured and is marginally *worse* on
every calibration metric with hit-rate tied. The Wald SPRT
(one-sided, `p0=0.544 / p1=0.574 / max_n=1200`) returns
`accept_h0` with `n=1664, k=888, llr=-5.1415` — far below the Wald
lower bound `-1.5581`. Decision emitted: `rollback`,
action `noop_already_shadow` (treatment was never promoted).

**Decision.** Close the F2 contextual zone-priority candidate as a
validated **null result** and keep the treatment **shadow-only**
(production continues to serve the static global zone-priority
weights). We do not promote, and the daily gate's `rollback` /
`noop_already_shadow` outcome is the expected steady state — a red
CI exit code 2 here means "candidate rejected", not "pipeline
broken". We do **not** flip `f2_contextual_promotion.json` away
from `live`: `live` denotes an *active shadow experiment*, and no
`rolled_back` spec status exists in the gate code.

**Alternatives considered.**

- *Promote the treatment.* Rejected — the corrected SPRT accepts H0
  and the treatment is worse on Brier and ECE; promoting would ship
  a strictly inferior calibration.
- *Keep accumulating and re-decide later.* Rejected — `n=1664`
  already exceeds the registered `max_n=1200` and the LLR has
  crossed the lower Wald boundary by a wide margin (`-5.14` vs
  `-1.56`); more observations cannot rescue a candidate this far
  inside H0.
- *Declare the experiment broken and re-run from scratch (as on
  2026-06-10).* Rejected — unlike the 06-10 corpus, the arms are now
  distinct, so the measurement path is demonstrably correct; the
  verdict is evidence, not an artifact.

**Consequences.**

- The F2 contextual candidate is parked; any future contextual
  zone-priority weighting must enter as a **new** candidate with a
  fresh SPRT corpus, not as a continuation of this one.
- **Corpus reset gap (resolved, issue #2770).** The SPRT corpus `n`
  grew monotonically across the fix boundary (`1492 → 1588 → 1664`).
  The original reset path fired *only* on a `plumbing_only → live`
  status flip; the spec status stayed `live` throughout the fix, so
  no automatic reset occurred. The H0 acceptance remains
  directionally robust to that contamination (LLR strongly negative,
  treatment worse on every metric). The gap is resolved: as of this
  PR the `f2-promotion-gate-daily` workflow passes
  `--deploy-boundary ${{ github.sha }}` to
  [`scripts/f2_flip_status.py`](../scripts/f2_flip_status.py),
  which now resets the corpus whenever the SHA changes —
  independent of the status flip path.

**Evidence.**

- `f2-promotion-gate-daily` run
  [27426121665](https://github.com/skippALGO/skipp-algo/actions/runs/27426121665)
  — `decision: rollback, reason: "SPRT accepted H0 (n=1664, k=888, llr=-5.1415)"`,
  `sprt.decision=accept_h0`, `control_hit_rate=0.5336`,
  `hit_rate=0.5337`, `brier_delta=+0.0157`,
  `action=noop_already_shadow`.
- `f2_promotion_gate_2026-06-12.json` (CI workflow artifact, not
  checked in) — full dual-arm metric table.
- [`scripts/smc_sprt_stop_rule.py`](../scripts/smc_sprt_stop_rule.py)
  — Wald SPRT engine; [`scripts/f2_flip_status.py`](../scripts/f2_flip_status.py)
  — status-flip / `sprt_state_reset` helper.
- Supersedes the re-run obligation recorded in
  [2026-06-10 - f2-dual-arm-raw-score-shadowing](#2026-06-10---f2-dual-arm-raw-score-shadowing).

**Status.** accepted.

---

## 2026-06-16 — stat-review-w10: Bonferroni auto-wiring + SPRT spec-path

**Context.** Stat-review wave 10 audit (PR #2797) identified two HIGH-severity
latent defects in the promotion pipeline and one MED carry-over.

**W10-1 — Bonferroni dead code.**
`GateThresholds(n_concurrent_families=1)` was the hard-coded default in every
production run of `scripts/run_promotion_gate.py`, so the W9-6 FWER correction
(`fdr_q / k`) was never applied for multi-family batches. Fixed: `build_report()`
now accepts `n_concurrent_families` (defaults to `len(snapshots)`) and passes it
to `GateThresholds`. The CLI in `main()` passes `len(snapshots)` automatically.

**W10-2 — SPRT defaults diverge from live spec.**
`run_ab_comparison.py main()` always used module-default constants
(`SPRT_P0=0.55`, `SPRT_P1=0.60`, MDE=50bp) rather than the pre-registered F2
spec values (`p0=0.544`, `p1=0.574`, MDE=30bp), silently ignoring the experiment
design. Fixed: `--spec-path` CLI arg loads the experiment JSON and builds
`SPRTConfig` from `spec["sprt"]`; spec-path validation runs before benchmark
loading so failures are reported early. Without `--spec-path` the module defaults
remain in effect (backward-compatible).

**W9-7 carry-over — drift threshold bands uncalibrated.**
`_VERDICT_BANDS` (0.85/0.65/0.40) in `scripts/compute_live_drift.py` are
engineering-judgment placeholders without a power analysis or ROC calibration.
Values intentionally unchanged pending a multi-month live-trading dataset.
Tracked in issue #2798.

**Status.** accepted (PR #2797, squash-merged to main).

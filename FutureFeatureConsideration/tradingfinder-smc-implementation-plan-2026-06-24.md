# TradingFinder SMC — Implementation & Migration Plan

**Document type:** Authoritative implementation plan  
**Date:** 2026-06-24  
**Authored by:** GitHub Copilot, grounded in live codebase analysis  
**Source doc reviewed:** `FutureFeatureConsideration/tradingfinder-smc-comparison-2026-06-23.md`  
**Status:** Approved — implementation in progress  

---

## 1. Build-vs-buy verdict

**Build. Do not buy.**

TradingFinder's value proposition is closed Pine visualization on TradingView. It
cannot feed a measured, calibrated probability lane. SkippALGO already has
`build_signal_quality`, `label_sweep_reversal`, Brier/log-score calibration, and a
stratified outcome-measurement pipeline. Buying a black box would fork the
measurement discipline the repo has spent months hardening.

Three corrections to the source doc's original analysis:

1. **The 100-pt score budget is already full.** `build_signal_quality`
   (`scripts/smc_signal_quality.py`) allocates exactly 100 points across
   Structure(20) / Session(20) / Liquidity(15) / OB(15) / FVG(15) / Compression(15)
   with a −15 event-risk penalty. New features cannot simply "add points" — they must
   run as **shadow signals** first, prove incremental calibration lift, then earn a
   re-weighted slot via a coordinated model cutover.

2. **Feature 4 (Freshness) already partially exists** — `SIGNAL_FRESHNESS`,
   `_freshness_label`, `STRUCTURE_EVENT_AGE_BARS`, `OB_FRESH`, `FVG_FRESH` are all
   present in `measurement_evidence.py`. The work is *unification* + explicit
   invalidation/mitigation state, not a greenfield build. Move this **first** (Phase A).

3. **Feature 3 (Confluence) risks double-counting.** The 100-pt score is already an
   implicit confluence of OB+FVG+Sweep buckets. A new Confluence term must be an
   *orthogonal interaction term*, measured for incremental Brier improvement before
   it earns any weight.

---

## 2. Score migration model

The 100-pt budget migrates in two coordinated cutovers, not incrementally:

| Bucket | v1 (today) | v2 (after Phase D) | v2.1 (after Phase E) |
|---|---|---|---|
| Structure freshness | 20 | 18 | 18 |
| Session alignment | 20 | 18 | 16 |
| Liquidity / sweep *(+trap +reaction zone)* | 15 | 18 | 18 |
| OB support | 15 | 12 | 12 |
| FVG support | 15 | 12 | 12 |
| Compression | 15 | 10 | 10 |
| **Confluence** (OB ∩ FVG ∩ Sweep interaction) | — | 12 | 8 |
| **SMT divergence** | — | — | 6 |
| Event-risk penalty | −15 | −15 | −15 |
| Freshness | partial, implicit | decay multiplier + hard gate | decay multiplier + hard gate |
| **Positive sum** | **100** | **100** | **100** |

Cutover is gated by `SIGNAL_QUALITY_MODEL` env var (`"v1"` / `"v2"` / `"v2.1"`).
v1 stays computable in parallel for A/B comparison until cutover is approved.

---

## 3. Implementation phases

### Phase 0 — Scaffolding *(prerequisite for all phases)*

**Deliverables:**
- Feature flags in `open_prep/feature_flags.py`:
  `ENABLE_SWEEP_TRAP`, `ENABLE_REACTION_ZONE`, `ENABLE_CONFLUENCE_SCORE`,
  `ENABLE_FRESHNESS_V2`, `ENABLE_SMT_DIVERGENCE`, `SIGNAL_QUALITY_MODEL`.
- Model version constant + `build_signal_quality_v2` stub in
  `scripts/smc_signal_quality.py`.
- Shadow enrichment hook: `_event_signal_quality_score` computes new blocks but
  excludes them from `build_signal_quality` unless model flag ≥ cutover version.
- `tests/fixtures/smc_v2/` fixtures directory.
- Scaffold test files.

**Verify:** all existing 1690 tests pass; new flags default off; no score change.

---

### Phase A — Freshness / Invalidation unify *(was doc #4; first for cheap wins)*

**New module:** `smc_core/event_freshness.py`

```
FreshnessBucket = Literal["fresh", "aging", "stale", "invalidated", "mitigated"]

@dataclass
class FreshnessState:
    event_age_bars: int
    event_age_seconds: float
    freshness_bucket: FreshnessBucket
    freshness_penalty: float          # 0.0–1.0 multiplier (1.0 = full strength)
    invalidated_at: float | None      # POSIX timestamp; None if still valid
    mitigated_at: float | None        # POSIX timestamp; None if not mitigated
```

**Extensions:**
- Extend `_mitigation_state` (`measurement_evidence.py:504`) to populate
  `mitigated_at` timestamp alongside existing bool.
- Add `_freshness_state_light_for_event(...)` → adds `"freshness_v2"` key to
  enrichment dict (shadow — ignored by v1 `build_signal_quality`).
- In `build_signal_quality_v2`: apply `freshness_state.freshness_penalty` as a
  decay multiplier on OB / FVG / Liquidity buckets; gate: `invalidated` → tier
  capped at `C`.

**Calibration target:** stale/invalidated events under-perform fresh ones on
realized reversal — measure stratified by session / HTF bias / vol regime.

**Verify:** fixture tests in `tests/fixtures/smc_v2/` for fresh / aging / stale /
invalidated / mitigated transitions; reliability-curve improvement in shadow.

---

### Phase B — Sweep Trap Classifier *(doc #1; highest ROI — parallel-safe with A)*

**New module:** `smc_core/sweep_trap.py`

```
TrapType = Literal["immediate", "delayed", "failed"]

@dataclass
class SweepTrapResult:
    sweep_reclaim_bars: int
    trap_type: TrapType
    reclaim_strength: float           # 0.0–1.0
    fib_retrace_depth: float          # 0.0–1.0 (0 = no retrace, 1 = full sweep)
    trap_quality_score: float         # 0.0–1.0; becomes SWEEP_TRAP_QUALITY_SCORE
```

**Integration points:**
- `_liquidity_support_for_event` (`measurement_evidence.py:752`): when best sweep
  found and `is_sweep_trap_enabled()`, call `classify_sweep_trap(sweep, bars,
  anchor_idx)` and merge `SweepTrapResult` fields into the returned payload.
- `label_sweep_reversal` (`smc_core/scoring.py:805`): extend to propagate
  `trap_type` and `trap_quality_score` into `ScoredEvent.features`.
- In `build_signal_quality_v2`: `SWEEP_TRAP_QUALITY_SCORE` sub-component of
  the Liquidity bucket (budget 18 for Liquidity in v2).

**Verify:** fixture tests for `immediate` / `delayed` / `failed` trap types;
`trap_quality_score` calibration vs realized reversal outcome.

---

### Phase C — Reaction Zone *(doc #2; depends on B)*

**New module:** `smc_core/reaction_zone.py`

```
@dataclass
class ReactionZone:
    reaction_zone_low: float
    reaction_zone_high: float
    close_back_inside_zone: bool      # price closed back inside sweep zone
    wick_rejection_ratio: float       # wick-to-range ratio at reaction bar
    confirmation_body_ratio: float    # body fraction confirming the reclaim
    bars_to_confirm: int              # bars from sweep extreme to confirm
```

**Integration:** added to `_liquidity_support_for_event` payload when
`is_reaction_zone_enabled()`. Acts as confirmation gate: no confirmed reaction
zone → `trap_quality_score` discounted by 50%.

**Verify:** fixtures for confirmed vs unconfirmed reclaims; precision-lift
measurement for zone-confirmed sweeps vs bare sweeps.

---

### Phase D — Confluence sub-score *(doc #3; depends on A–C; triggers v2 cutover)*

**New module:** `smc_core/smc_confluence.py`

```
@dataclass
class ConfluenceScore:
    ob_contribution: float            # independent OB component
    fvg_contribution: float           # independent FVG component
    sweep_contribution: float         # sweep trap component
    raw_confluence_score: float       # orthogonal interaction (NOT sum of above)
    confluence_tier: Literal["HIGH", "MEDIUM", "LOW", "NONE"]
```

**Anti-double-count guardrail:** the interaction term is an XOR-style presence
score, not a re-sum of the same evidence already in OB / FVG / Liquidity buckets.
Require measured incremental Brier improvement over additive v1 before assigning
any weight.

**Score role:** new bucket (12 in v2). This is the **v1→v2 cutover** point:
`SIGNAL_QUALITY_MODEL=v2` activates `build_signal_quality_v2` with the
re-weighted budget above.

**Verify:** v2 vs v1 reliability + Brier on held-out events; tier-distribution
drift report; live shadow at least 500 events before flag flip.

---

### Phase E — SMT / Correlation Divergence *(doc #5; last; biggest lift)*

**Pre-requisite sub-phase (E.0):** correlated-pair data feed in the live engine
(`open_prep/realtime_signals.py`). Today the engine is single-symbol-centric;
Phase E.0 scopes the data-ingest change separately.

**New module (scaffold now, implement after E.0):** `smc_core/smt_divergence.py`

```
KNOWN_SMT_PAIRS = [
    ("XAUUSD", "XAGUSD"),
    ("BTCUSD", "ETHUSD"),
    ("US100", "US500"),
    ("EURUSD", "GBPUSD"),
]

@dataclass
class SMTDivergenceResult:
    pair_corr_window: int
    pair_corr_value: float
    smt_high_divergence: bool         # higher high in base, lower high in corr
    smt_low_divergence: bool          # lower low in base, higher low in corr
    smt_strength: float               # 0.0–1.0
```

**Score role:** new SMT bucket (6 in v2.1) → v2→v2.1 cutover (trims
Session 18→16, Compression 10→10, Confluence 12→8 per table).

**Verify:** correlation backfill validation; SMT divergence → reversal lift;
live multi-symbol smoke on Railway behind `ENABLE_SMT_DIVERGENCE=1`.

---

## 4. Cross-cutting: ledger guards & safe delivery

Every phase must pass the pre-push `ledger-pin-drift-guard` (~70s, 65 files).

| New code category | Likely guard files tripped |
|---|---|
| Pure math modules (no I/O, no global, no noqa, no sleep) | **None** |
| `time.sleep` in any new module | `tests/test_time_sleep_budget.py` |
| `global` statement in any new module | `tests/test_global_statement_budget.py` |
| `# noqa` suppression | `tests/test_noqa_budget.py` |
| Network I/O for correlated-pair feed (Phase E.0) | `tests/test_http_client_discipline.py`, `pin_registry.toml` (urlopen) |
| `os.unlink` / `os.remove` | `tests/test_os_unlink_remove_ledger.py` |

**Rule:** add frozen ledger entries with justification in the commit message,
then push via a clean git worktree (`git worktree add ../skipp-algo.worktrees/<topic>`)
to avoid WIP line-drift interference.

---

## 5. Observability (per phase)

Add Grafana/Alloy panels for each new field via `services/live_overlay_daemon/infra/alloy`:

- Phase A: `freshness_bucket` histogram; `invalidated_event_count` counter.
- Phase B: `trap_quality_score` distribution; `trap_type_counts` by direction.
- Phase C: `reaction_zone_confirmation_rate`; `bars_to_confirm` histogram.
- Phase D: `confluence_tier` distribution; **v1-vs-v2 score delta** panel.
- Phase E: `smt_divergence_count` by pair; `smt_strength` histogram.

---

## 6. Scope boundaries

**In scope:** native detection, enrichment, labels, calibration, staged score
migration, observability, live flag wiring for all 5 features.

**Out of scope:** any TradingFinder / Pine script integration; multi-symbol live
data infrastructure beyond what Phase E.0 explicitly scopes; changing the −15
event-risk penalty; modifying the `BOS` follow-through label pipeline.

---

## 7. File map

| File | Role | Phase |
|---|---|---|
| `open_prep/feature_flags.py` | Per-phase env flags + model version | 0 |
| `scripts/smc_signal_quality.py` | Budget constants; `build_signal_quality_v2` | 0, D |
| `smc_core/event_freshness.py` | `FreshnessState`, `classify_freshness`, `freshness_decay_multiplier` | A |
| `smc_core/sweep_trap.py` | `SweepTrapResult`, `classify_sweep_trap` | B |
| `smc_core/reaction_zone.py` | `ReactionZone`, `compute_reaction_zone` | C |
| `smc_core/smc_confluence.py` | `ConfluenceScore`, `compute_confluence` | D |
| `smc_core/smt_divergence.py` | `SMTDivergenceResult`, scaffold | E |
| `smc_integration/measurement_evidence.py` | `_freshness_state_light_for_event` + trap/zone hooks in `_liquidity_support_for_event` + shadow enrichment | A, B, C, D |
| `smc_core/scoring.py` | Extend `label_sweep_reversal` for trap fields | B |
| `tests/fixtures/smc_v2/` | Per-phase fixture data | 0–E |
| `tests/test_smc_v2_freshness.py` | Phase A fixture tests | A |
| `tests/test_smc_v2_sweep_trap.py` | Phase B fixture tests | B |
| `tests/test_smc_v2_reaction_zone.py` | Phase C fixture tests | C |
| `tests/test_smc_v2_confluence.py` | Phase D fixture tests | D |

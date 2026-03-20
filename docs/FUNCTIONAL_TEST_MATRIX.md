# Functional Test Matrix (Behavior-Driven)

This document summarizes the behavior-level test coverage introduced for SkippALGO.

Unlike pure structure/regex tests, these scenarios validate **runtime behavior** via the simulator in `tests/pine_sim.py` and the suite `tests/test_functional_features.py`.

---

## Scope

Covered components:

- Entry gate stack (`reliabilityOk`, `evidenceOk`, `evalOk`, abstain/decision handling)
- Open-window + strict alert behavior
- Engine paths (`Hybrid`, `Breakout`, `Trend+Pullback`, `Loose`)
- Exit/risk semantics (grace periods, risk-trigger exits, TP hold behavior)
- Reversal path behavior (probability floor + open-window bypass)
- Feature-flag matrix checks
- Property-style invariants over randomized scenarios
- Golden-master snapshots for deterministic event traces

---

## Coverage Map

| Area | Behavioral objective | Test module / examples |
| --- | --- | --- |
| Gate functionality | Entry blocks when any required gate fails; entry passes when all required gates pass | `TestFunctionalGateBehavior` |
| Open-window + strict mode | Strict delays apply only outside open window; open window disables strict and enables configured bypass behavior | `TestOpenWindowAndStrictBehavior` |
| Engine execution paths | Each engine has at least one deterministic entry scenario | `TestEngineFeatureScenarios` |
| Risk/exit behavior | Struct exits obey grace; risk exits bypass grace; TP-hold respects confidence threshold | `TestRiskExitFeatureBehavior` |
| Reversal features | Reversal blocked below floor outside open window; open-window directional bypass works | `TestReversalFeatureBehavior` |
| Feature-flag matrix | Key blockers (`fc`, `enh`, `vol`, `set`, `pullback`, `macro`, `mtf`, `dd`) prevent entry when disabled | `TestFeatureFlagMatrix` |
| Property invariants | No impossible transitions, no orphan exits/covers, position domain preserved under random scenarios | `TestPropertyStyleInvariants` |
| Golden master | Stable event traces and strict-delay snapshots to detect functional drift | `TestGoldenMasterSnapshots` |

---

## Simulator Notes

Simulator (`tests/pine_sim.py`) was extended to support:

- explicit `decision_final` gate in `allow_entry`
- open-window aware reversal probability gating:
  - `rev_buy_min_prob_floor = 0.0` in open window, else `0.25`
  - directional bypass flags for long/short windows
- richer diagnostics in `BarResult`:
  - `rev_buy_min_prob_floor`
  - `prob_ok_global`
  - `prob_ok_global_s`

This keeps the behavior tests close to the Pine intent while remaining fast and deterministic.

---

## How to run

```bash
pytest -q tests/test_functional_features.py
pytest -q tests/test_behavioral.py tests/test_functional_features.py
pytest -q
```

---

## Design Principles

1. **Behavior over strings**: Validate outcomes and transitions, not only source text.
2. **Deterministic first**: Golden snapshots for key lifecycles.
3. **Invariant safety net**: Randomized stress checks for impossible states.
4. **Parity support**: Tests complement (not replace) existing Indicator/Strategy parity checks.

---

## Future Extensions (optional)

- Add dataset-driven mini backtest snapshots (trend/range/vol-spike/session-open).
- Add mutation-style checks for gate bypass regressions.
- Add risk-profile scenario matrix for Dynamic TP/SL and Breakeven interactions.

---

## SMC++ Edge-Case Matrix

The current SMC++ long-dip flow is most sensitive around OB/profile ownership, sparse volume, and realtime invalidation timing. These scenarios should be covered as targeted behavior tests before treating the script as fully production-ready.

| Scenario | Setup | Expected behavior | Risk guarded |
| --- | --- | --- | --- |
| OB profile on/off parity | Run the same reclaim-confirm-ready sequence once with `use_ob_profile = true` and once with `use_ob_profile = false` | Lifecycle progression should remain consistent; only profile-derived geometry and profile-specific diagnostics may differ | Profile toggle changing entry semantics unintentionally |
| Zero-volume current bar | Feed a bar with valid price structure but zero/sparse volume while `allow_relvol_without_volume_data` is off, then on | Without fallback, RelVol-dependent stages should block; with fallback, non-strict stages may continue while strict still reflects reduced volume confidence | Sparse feed silently promoting weak setups |
| Strict LTF unavailable fallback | Disable or guard LTF availability with `allow_strict_entry_without_ltf` off, then on | Strict should hard-block when fallback is off and may pass only the LTF sub-gate when fallback is on; other strict gates must still decide the outcome | Tooltip/policy drift in strict-entry semantics |
| Backing-zone ownership transfer | Arm from an OB, then create an overlapping FVG/OB context and continue into confirmation | The setup should keep checking the original armed backing object for later invalidation instead of drifting to the newest overlap | Source drift after arm/confirm |
| Broken OB after arm | Arm on an OB and then break that exact OB before confirmation or ready | The long setup must invalidate from the armed source and emit the invalidation path once | Stale armed setups surviving broken support |
| Reclaim -> confirm -> invalidate | Produce a clean armed/confirmed sequence and then force source loss, expiry, or broken-down invalidation | Alert ladder should move forward monotonically and then terminate with `Long Invalidated` without reviving weaker states on the same setup serial | Lifecycle regressions after invalidation |
| Same-bar realtime churn | In aggressive live mode, trigger arm/early/confirm intrabar and invalidate later on the same realtime bar | Latches may preserve live visibility intrabar, but the final close-safe state should resolve deterministically and not leave contradictory preset alerts latched | Realtime-only transitions leaking into close-safe history |
| Volume-less profile object | Create or reuse an OB profile on bars with empty/zero profile volume buckets | The profile must not expose a fake POC/value area; fallback handling should stay defensive and avoid promoting profile-based quality | Fragile POC/value-area assumptions |

### Suggested execution split

- Close-safe path: run the matrix once in confirmed-only mode to verify historical reconstruction and final lifecycle states.
- Realtime path: rerun the reclaim/invalidate and same-bar churn cases in aggressive live mode to verify latch behavior and alert monotonicity.
- Profile stress path: rerun the ownership-transfer and volume-less profile cases with `use_ob_profile` toggled on and off to isolate profile-specific regressions.

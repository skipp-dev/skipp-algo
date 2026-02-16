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

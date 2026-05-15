# `rl/` — RL Execution Layer (C12, active implementation)

**Status:** Active implementation. The pipeline is end-to-end runnable on
NumPy alone (slippage calibrator, simulator, TWAP/VWAP baselines, safety
layer, drift monitor). PPO/SAC agents are gated behind optional
`stable-baselines3` backends; live onboarding is a dataset swap
(`synthetic -> blotter`), not a structural refactor.

## Modules

- `rl/types.py` — typed contracts (`ExecutionState`, `ExecutionAction`,
  `SlippageEstimate`, `TradeRecord`, `TradeBlotter`).
- `rl/slippage/almgren_chriss_calibrator.py` — `AlmgrenChrissCalibrator`
  (Bayesian linear regression, half-normal prior, BPS output with 95% CI).
- `rl/simulator/execution_env.py` — `ExecutionEnv` with a
  gymnasium-compatible `reset()` / `step()` interface.
- `rl/baselines/` — `TWAPSlicer`, `VWAPSlicer`.
- `rl/agents/` — `EpsilonGreedyTwapAgent` (always-on NumPy), `PPOSlicer`, and
  `SACSizer` (optional SB3-backed agents exposing `available`).
- `rl/safety/__init__.py` — `HardConstraintLayer`, `GuardResult`, sizing
  decisions, and order-type whitelist.
- `rl/drift/action_drift.py` — `RLDriftDetector` for PSI-based action/slice
  drift alerts.
- `rl/extensions.py` — C12.1 extensions: `cvar_reward`,
  `adversarial_bar_replay`, `RLWalkForwardConfig`, `ConstraintHitLog`.
- `rl/schemas/v1_execution_state.json` — frozen execution-state schema.

## Optional heavy backends

`requirements-rl.txt` pins:

```
gymnasium>=0.29.0
stable-baselines3>=2.3.0
torch>=2.2.0
optuna>=3.5.0
```

Without these packages the pipeline is still fully usable: TWAP/VWAP
baselines, the epsilon-greedy slicer, slippage calibrator, simulator,
safety layer, and drift monitor all run on NumPy alone. The `available`
contract (see `tests/test_rl_execution_smoke.py::test_optional_agent_dep_contract`)
guarantees that consumers can detect optional backends cleanly and fall back
to the deterministic path.

## Live-data wiring

Today the tests feed `TradeBlotter` with synthetic trades. Live the same
blotter is populated from the order lifecycle (`smc_*` / `terminal_*`)
without swapping code paths — only the dataset source changes.

## Trigger gate

`scripts/check_c12_trigger.py` checks whether live rollout on real order-flow
data is allowed (>= 4 weeks incubation of an SMC family from C8). Until that
gate returns `BLOCKED`, the RL layer stays on synthetic data and the simulator,
fully deterministic under seed.

## Sources

- Master plan: [`docs/SPRINT_PLAN_C12_RL_EXECUTION_2026-04-26.md`](../docs/SPRINT_PLAN_C12_RL_EXECUTION_2026-04-26.md)
- ML sister layer: [`ml/README.md`](../ml/README.md)
- Trigger-check script: [`scripts/check_c12_trigger.py`](../scripts/check_c12_trigger.py)
- RL smoke tests: [`tests/test_rl_execution_smoke.py`](../tests/test_rl_execution_smoke.py)
- C12.1 extension tests: [`tests/test_rl_extensions_c12_1.py`](../tests/test_rl_extensions_c12_1.py)

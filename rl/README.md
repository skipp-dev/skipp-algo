# `rl/` — RL-Execution-Schicht (C12, aktive Implementierung)

**Status:** Aktive Implementierung. Pipeline durchgängig in numpy lauffähig (Slippage-Kalibrator, Simulator, TWAP-/VWAP-Baselines, Safety-Layer, Drift-Monitor). PPO/SAC-Agenten sind als optionale `stable-baselines3`-Backends gegated; live geht der Schalter durch Datensatz-Swap (synthetic → blotter).

## Module

- `rl/types.py` — Typed Contracts (`ExecutionState`, `ExecutionAction`, `SlippageEstimate`, `TradeRecord`, `TradeBlotter`).
- `rl/slippage/` — `AlmgrenChrissCalibrator` (Bayesian linear regression, half-normal Prior, BPS-Output mit 95 %-Konfidenzintervall).
- `rl/simulator/` — `ExecutionEnv` mit echter gymnasium-/SB3-Kompatibilität, sobald `gymnasium` installiert ist (inkl. `action_space` / `observation_space`); ohne Heavy-Dependency bleibt derselbe numpy-only Vertrag erhalten. Reward = `−ImplementationShortfallₘᵦᵖₛ − λ·variance`.
- `rl/baselines/` — `TWAPSlicer`, `VWAPSlicer` (volumenprofil-gewichtet, Profil wird auf Env-Horizont interpoliert).
- `rl/agents/` — `EpsilonGreedyTwapAgent` (always-on numpy), `PPOSlicer` und `SACSizer` (try-import sb3, `available`-Flag, `RuntimeError` ohne Backend).
- `rl/safety/` — `HardConstraintLayer` (Veto-Schicht: Größen-Cap, Drawdown-Cap, Slice/Order-Type-Whitelist).
- `rl/drift/` — `RLDriftDetector` (PSI auf Slice-Size-Verteilungen, warn/alarm).
- `rl/schemas/v1_execution_state.json` — eingefrorene Schema-Datei für State- und Action-Space.

## Optionale Heavy-Backends

In `requirements-rl.txt`:

```
gymnasium>=0.29.0
stable-baselines3>=2.3.0
torch>=2.2.0
optuna>=3.5.0
```

Für den echten GPU-Pfad auf dem self-hosted Runner kommt danach
`requirements-rl-gpu.txt` dazu. Diese Datei ersetzt die generische CPU-Torch-
Installation durch das offizielle CUDA-Wheel aus dem PyTorch-Index. Der
Workflow `rl-research-training.yml` installiert und prüft diesen Override
explizit, bevor `SKIPP_RL_DEVICE=cuda` gesetzt wird.

Solange diese nicht installiert sind, ist die gesamte Pipeline trotzdem lauffähig: TWAP/VWAP-Baselines, ε-greedy Slicer, Slippage-Kalibrator, Simulator, Safety-Layer und Drift-Monitor laufen nur auf numpy. Der `available`-Flag-Vertrag (siehe `tests/test_rl_execution_smoke.py::test_optional_agent_dep_contract`) garantiert, dass Konsumenten den Optional-Pfad sauber detektieren und auf den ε-greedy-Fallback ausweichen können.

## Live-Daten-Wiring

Heute füttern Tests den `TradeBlotter` mit synthetischen Trades. Live wird derselbe Blotter aus dem Order-Lifecycle (`smc_*` / `terminal_*`) befüllt. Kein Code-Pfad-Swap nötig — nur Datensatz-Swap.

## Trigger-Gate

`scripts/check_c12_trigger.py` prüft separat, ob Live-Roll-out auf reale Order-Flow-Daten zulässig ist (≥ 4 Wochen Inkubation einer SMC-Familie aus C8). Solange das Gate `BLOCKED` zurückgibt, läuft die Pipeline auf synthetischen Daten und gegen den Simulator — vollständig deterministisch unter Seed.

## Quellen

- Master-Plan: [`docs/SPRINT_PLAN_C12_RL_EXECUTION_2026-04-26.md`](../docs/SPRINT_PLAN_C12_RL_EXECUTION_2026-04-26.md)
- ML-Schwester-Schicht: [`ml/README.md`](../ml/README.md)
- Trigger-Check-Skript: [`scripts/check_c12_trigger.py`](../scripts/check_c12_trigger.py)
- Smoke-Tests: [`tests/test_rl_execution_smoke.py`](../tests/test_rl_execution_smoke.py)

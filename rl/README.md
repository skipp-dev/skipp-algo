# `rl/` — RL-Execution Foundation (C12 vorbereitend)

**Status:** Foundation only — Schema-Vorschlag und Trigger-Gate-Stub. Kein Modell, kein Trainer, keine Inferenz.

## Was hier ist

- `rl/schemas/v1_execution_state.json` — vorgeschlagener State- und Action-Space-Vertrag für die künftige RL-Execution-Schicht (C12). Ist heute **nicht** an einen Live-Consumer angeschlossen — es ist eine Schema-Lock-Datei für später.

## Was hier **nicht** ist

- Kein `stable-baselines3`, kein `gymnasium`, kein `wandb`, kein `torch`
- Keine RL-Agenten (kein PPO, SAC, DQN)
- Keine Slippage-Kalibrierung
- Keine Trainings-Skripte
- Keine neuen Runtime-Dependencies

## Trigger-Gate

C12 ist heute **strukturell blockiert**, weil keine SMC-Familie die geforderten ≥ 4 Wochen Live-Inkubation aus C8 erfüllt. Der Check liegt in `scripts/check_c12_trigger.py` und gibt heute deterministisch `BLOCKED` mit nicht-null Exit-Code aus.

Sobald die Bedingung erfüllt ist, flippt der Check automatisch auf `GREEN` (Exit-Code 0). Der volle C12-Sprint nach `docs/SPRINT_PLAN_C12_RL_EXECUTION_2026-04-26.md` darf erst dann gestartet werden.

## Quellen

- Master-Plan: [`docs/SPRINT_PLAN_C12_RL_EXECUTION_2026-04-26.md`](../docs/SPRINT_PLAN_C12_RL_EXECUTION_2026-04-26.md)
- Public-Calibration-Datenquelle für den Trigger: [`docs/calibration/calibration_report_public.json`](../docs/calibration/calibration_report_public.json)
- Trigger-Check-Skript: [`scripts/check_c12_trigger.py`](../scripts/check_c12_trigger.py)
- Trigger-Check-Tests: [`tests/test_c12_trigger_check.py`](../tests/test_c12_trigger_check.py)

# `ml/` — ML-Layer Foundation (C10 vorbereitend)

**Status:** Foundation only — Schema-Pins, keine Trainer/Inferenz/Calibration.

## Was hier ist

- `ml/schemas/v1_input_schema.json` — SHA-Pin für `FamilyScoringMetrics` und `EventFamily` aus `smc_core/scoring.py`. Quelle für künftige ML-Trainer.
- `ml/schemas/v1_hero_features.json` — SHA-Pin für die HERO-Vokabular-Frozensets aus `scripts/smc_hero_state.py`. Quelle für die kategorialen Feature-Encoder.

## Was hier **nicht** ist

- Kein XGBoost/LightGBM/CatBoost
- Kein Optuna, kein SHAP, kein joblib
- Keine Trainings-Skripte
- Keine Inferenz-Pfade
- Keine Calibration-Pipeline
- Keine neuen Runtime-Dependencies

Begründung: Die strategische Sperre aus dem Master-Doc gilt — solange `public-calibration-dashboard.yml` keine eindeutig profitablen Setups zeigt, sind Trainer-Builds nicht produktiv. Schema-Pins kosten heute fast nichts und sperren zukünftiges Schema-Drift, das später beim Drop-In-Trainer teure Folgen hätte.

## Drift-Schutz

`tests/test_ml_input_schema_pin.py` (stdlib-only) prüft beide SHAs gegen die aktuelle Source. Drift bricht CI mit konkreter Fehlermeldung und Remediation-Hinweis.

## Wenn der volle C10-Sprint freigegeben ist

Sobald die Vorbedingungen aus `docs/SPRINT_PLAN_C10_ML_LAYER_2026-04-26.md` erfüllt sind (C2-C9 gemerged, mindestens eine Familie Outcome-tauglich), werden hier folgende Module hinzukommen:

- `ml/training/xgb_family_trainer.py` (C10-T2)
- `ml/inference/family_predictor.py` (C10-T3)
- `ml/calibration/probability_calibrator.py` (C10-T4)
- `ml/training/lgbm_family_trainer.py` (C10-T5)
- `ml/calibration/online_recalibrator.py` (C10-T6)
- `ml/features/microstructure.py`, `volatility.py`, `temporal.py` (C10-T7)

Heavy-Deps werden **dann** in `requirements-ml.txt` (separat von `requirements.txt`) eingeführt — das Slim-Dashboard-Image bleibt unangetastet.

## Quellen

- Master-Plan: [`docs/SPRINT_PLAN_C10_ML_LAYER_2026-04-26.md`](../docs/SPRINT_PLAN_C10_ML_LAYER_2026-04-26.md)
- Source-of-truth EventFamily/FamilyScoringMetrics: [`smc_core/scoring.py`](../smc_core/scoring.py)
- Source-of-truth HERO-Vokabular: [`scripts/smc_hero_state.py`](../scripts/smc_hero_state.py)
- Existierender Vokabular-Drift-Test: [`tests/test_hero_observed_vocab_pin.py`](../tests/test_hero_observed_vocab_pin.py)

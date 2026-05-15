# `ml/` — ML-Layer (C10, in active implementation)

**Status:** Implementation in progress — full pipeline scaffolded, exercisable on
synthetic data, ready to plug into live data without further structural changes.

## Modules

- `ml/types.py` — `MLPrediction`, `TrainingReport`, `EventFamily` literal.
- `ml/metrics.py` — `brier_score`, `log_loss`, `roc_auc`,
  `expected_calibration_error`, `population_stability_index`. Pure-numpy.
- `ml/walkforward.py` — Embargoed walk-forward split (López de Prado).
- `ml/training/`
  - `base.py` — `BaseFamilyTrainer`, `FamilyDataset`, `FittedModel`.
  - `logistic_baseline.py` — Pure-numpy L2-logistic regression (always-on).
  - `xgb_family_trainer.py` — XGBoost (optional, `try`-import).
  - `lgbm_family_trainer.py` — LightGBM (optional, `try`-import).
- `ml/calibration/`
  - `probability_calibrator.py` — `PlattCalibrator`, `IsotonicCalibrator` (PAV).
  - `conformal.py` — `SplitConformalClassifier`, `AdaptiveConformalClassifier`.
  - `online_recalibrator.py` — PSI / Brier-regret refit decision.
- `ml/inference/family_predictor.py` — Thread-safe per-family registry with
  atomic swap and hot-reload semantics.
- `ml/features/` — `microstructure.py` (Bid-Ask/Volume Imbalance, VPIN),
  `volatility.py` (Realized, Garman-Klass, Parkinson),
  `temporal.py` (cyclical encoding, session marker).
- `ml/drift/` — `MLDriftDetector` (PSI two-tier alerts, mirrors C9 contract)
  plus `trend.py` for PSI slope alerts and importance-weighted PSI helpers.
- `ml/stacking/meta_learner.py` — constrained logistic meta-learner for
  combining per-family probabilities.
- `ml/schemas/v1_input_schema.json`, `ml/schemas/v1_hero_features.json` —
  SHA pins on the source-of-truth feature contracts.

## Heavy dependencies (optional)

`requirements-ml.txt` pins xgboost / lightgbm / scikit-learn / optuna / shap.
None of these are required to use the `ml/` module — `LogisticBaseline`
covers the full training/inference contract on numpy alone. Heavy backends
are gated:

```python
from ml.training import XGBFamilyTrainer, LogisticBaseline

trainer_cls = XGBFamilyTrainer if XGBFamilyTrainer.available else LogisticBaseline
```

## Live-data readiness

The contract is designed so that switching from synthetic smoke tests to live
incubation data is a **dataset swap**, not a refactor:

1. Build a `FamilyDataset(family, X, y, feature_names)` from the live outcome
   stream (C8 / Phase B incubation).
2. `trainer.fit(dataset)` returns `(FittedModel, TrainingReport)`.
3. Fit a `PlattCalibrator` or `IsotonicCalibrator` on held-out raw scores.
4. `FamilyPredictor.swap({family: ModelArtifact(fitted, calibrator)})` —
   atomic, thread-safe, no consumer downtime.
5. Stream live `MLPrediction`s through `predict_batch(...)`; pipe predictions
   into `MLDriftDetector` and `OnlineRecalibrator` for the C9-mirrored
   refit / rollback loop.

`tests/test_ml_layer_smoke.py` exercises every step end-to-end on numpy-only
fixtures. Additional focused validation lives in
`tests/test_conformal_coverage.py` and `tests/test_meta_learner_smoke.py`.

## Sources

- Master plan: [`docs/SPRINT_PLAN_C10_ML_LAYER_2026-04-26.md`](../docs/SPRINT_PLAN_C10_ML_LAYER_2026-04-26.md)
- EventFamily / FamilyScoringMetrics: [`smc_core/scoring.py`](../smc_core/scoring.py)
- HERO vocabulary: [`scripts/smc_hero_state.py`](../scripts/smc_hero_state.py)
- HERO drift test: [`tests/test_hero_observed_vocab_pin.py`](../tests/test_hero_observed_vocab_pin.py)
- Schema pin test: [`tests/test_ml_input_schema_pin.py`](../tests/test_ml_input_schema_pin.py)
- End-to-end smoke: [`tests/test_ml_layer_smoke.py`](../tests/test_ml_layer_smoke.py)
- Conformal coverage test: [`tests/test_conformal_coverage.py`](../tests/test_conformal_coverage.py)
- Meta-learner smoke: [`tests/test_meta_learner_smoke.py`](../tests/test_meta_learner_smoke.py)

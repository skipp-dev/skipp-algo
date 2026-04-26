"""ML-Layer (Sprint C10).

Production-ready scaffolding for per-family probability prediction on top of
``smc_core/scoring.py:FamilyScoringMetrics``.

Heavy dependencies (xgboost/lightgbm/sklearn) are optional and gated via
``try``/``except`` imports. The pure-numpy ``LogisticBaseline`` is always
available so the full pipeline (train -> calibrate -> predict -> drift) is
exercisable on synthetic fixtures with no extra installs.

See ``docs/SPRINT_PLAN_C10_ML_LAYER_2026-04-26.md``.
"""
from ml.types import MLPrediction, TrainingReport

__all__ = ["MLPrediction", "TrainingReport"]

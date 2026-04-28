"""Training entrypoints for ml/ family models.

Backends:

- ``LogisticBaseline`` — pure-numpy gradient-descent logistic regression with
  L2 regularisation. Always available, used as the deterministic baseline and
  as the live-data-ready fallback when heavy libraries are absent.
- ``XGBFamilyTrainer`` — gradient-boosted trees via the optional ``xgboost``
  dependency.
- ``LGBMFamilyTrainer`` — gradient-boosted trees via the optional ``lightgbm``
  dependency.

Every backend implements ``BaseFamilyTrainer`` so callers can swap them at
runtime without touching the surrounding pipeline.
"""
from ml.training.base import BaseFamilyTrainer, FamilyDataset, FittedModel
from ml.training.logistic_baseline import LogisticBaseline
from ml.training.lgbm_family_trainer import LGBMFamilyTrainer
from ml.training.xgb_family_trainer import XGBFamilyTrainer

__all__ = [
    "BaseFamilyTrainer",
    "FamilyDataset",
    "FittedModel",
    "LGBMFamilyTrainer",
    "LogisticBaseline",
    "XGBFamilyTrainer",
]

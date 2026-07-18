"""MLflow model-from-code wrapper for the canonical PRE-A0 JSON contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import mlflow
import pandas as pd

from open_prep.pre_a0_model import parse_artifact, verify_artifact_id


class PreA0PythonModel(mlflow.pyfunc.PythonModel):
    def load_context(self, context) -> None:
        payload = json.loads(Path(context.artifacts["pre_a0_contract"]).read_text(encoding="utf-8"))
        artifact = parse_artifact(payload)
        if not verify_artifact_id(artifact):
            raise ValueError("PRE-A0 artifact identity mismatch")
        self.artifact = artifact

    def predict(self, model_input: pd.DataFrame, params: dict[str, Any] | None = None) -> list[float]:
        del params
        probabilities: list[float] = []
        for record in model_input.to_dict(orient="records"):
            raw = self.artifact.model.raw_score(record)
            probability = (
                self.artifact.calibration.apply(raw)
                if self.artifact.calibration
                else self.artifact.model.probability(record)
            )
            probabilities.append(probability)
        return probabilities


mlflow.models.set_model(PreA0PythonModel())

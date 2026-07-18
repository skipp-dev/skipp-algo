from __future__ import annotations

from pathlib import Path


def test_model_from_code_wrapper_uses_canonical_json_contract() -> None:
    source = Path("open_prep/pre_a0_mlflow_model.py").read_text(encoding="utf-8")
    assert "parse_artifact" in source
    assert "verify_artifact_id" in source
    assert 'context.artifacts["pre_a0_contract"]' in source
    assert "mlflow.models.set_model(PreA0PythonModel())" in source
    assert "cloudpickle" not in source.lower()

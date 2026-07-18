from __future__ import annotations

import stat
import tomllib
from pathlib import Path

import pytest

from services.mlflow_tracking.server import (
    _artifact_destination,
    _required_environment,
    _write_auth_config,
)

SERVICE_DIR = Path("services/mlflow_tracking")


def test_service_is_pinned_and_separate_from_worker_runtime() -> None:
    config = tomllib.loads((SERVICE_DIR / "railway.toml").read_text(encoding="utf-8"))
    assert config["build"]["dockerfilePath"] == "services/mlflow_tracking/Dockerfile"
    assert config["deploy"]["startCommand"] == "python -m services.mlflow_tracking.server"
    dockerfile = (SERVICE_DIR / "Dockerfile").read_text(encoding="utf-8")
    assert "python:3.12-slim@sha256:" in dockerfile
    assert "VOLUME" not in dockerfile
    assert "a0_fast_detector" not in dockerfile
    assert (SERVICE_DIR / "requirements.txt").read_text(encoding="utf-8").splitlines() == [
        "mlflow[auth]==3.14.0",
        "psycopg2-binary==2.9.10",
        "boto3==1.43.51",
    ]
    assert "mlflow" not in Path("services/a0_fast_detector/requirements.txt").read_text(
        encoding="utf-8"
    ).lower()


def test_launcher_refuses_missing_security_configuration(monkeypatch) -> None:
    for name in (
        "DATABASE_URL",
        "MLFLOW_ADMIN_USERNAME",
        "MLFLOW_ADMIN_PASSWORD",
        "MLFLOW_FLASK_SERVER_SECRET_KEY",
        "MLFLOW_SERVER_ALLOWED_HOSTS",
        "MLFLOW_ARTIFACTS_DESTINATION",
        "MLFLOW_S3_ENDPOINT_URL",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_DEFAULT_REGION",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        _required_environment()


def test_auth_config_is_private_and_denies_permissions_by_default(tmp_path: Path) -> None:
    values = {
        "DATABASE_URL": "postgresql://user:p%25word@postgres:5432/mlflow",
        "MLFLOW_ADMIN_USERNAME": "pilot-admin",
        "MLFLOW_ADMIN_PASSWORD": "url-safe-secret",
        "MLFLOW_FLASK_SERVER_SECRET_KEY": "separate-secret",
        "MLFLOW_SERVER_ALLOWED_HOSTS": "mlflow.example.test",
    }
    path = _write_auth_config(values, tmp_path / "auth.ini")
    try:
        content = path.read_text(encoding="utf-8")
        assert "default_permission = NO_PERMISSIONS" in content
        assert "grant_default_workspace_access = false" in content
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    finally:
        path.unlink(missing_ok=True)


def test_artifact_store_must_be_a_credential_free_private_bucket_uri() -> None:
    assert _artifact_destination("s3://mlflow-artifacts/mlflow") == "s3://mlflow-artifacts/mlflow"
    for invalid in (
        "file:///mlflow/artifacts",
        "s3://access:secret@bucket/mlflow",
        "s3://bucket/other-prefix",
    ):
        with pytest.raises(RuntimeError):
            _artifact_destination(invalid)

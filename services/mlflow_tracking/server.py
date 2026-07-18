"""Fail-closed Railway launcher for the authenticated MLflow pilot."""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
from pathlib import Path
from types import FrameType
from urllib.parse import urlsplit

LOGGER = logging.getLogger(__name__)

REQUIRED_ENV = (
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
)


def _required_environment() -> dict[str, str]:
    values: dict[str, str] = {}
    for name in REQUIRED_ENV:
        value = os.environ.get(name, "").strip()
        if not value:
            raise RuntimeError(f"required environment variable is missing: {name}")
        if "\n" in value or "\r" in value:
            raise RuntimeError(f"environment variable must be one line: {name}")
        values[name] = value
    return values


def _ini_value(value: str) -> str:
    return value.replace("%", "%%")


def _write_auth_config(
    values: dict[str, str], path: Path = Path("/app/.mlflow-basic-auth.ini")
) -> Path:
    content = (
        "[mlflow]\n"
        f"database_uri = {_ini_value(values['DATABASE_URL'])}\n"
        f"admin_username = {_ini_value(values['MLFLOW_ADMIN_USERNAME'])}\n"
        f"admin_password = {_ini_value(values['MLFLOW_ADMIN_PASSWORD'])}\n"
        "default_permission = NO_PERMISSIONS\n"
        "grant_default_workspace_access = false\n"
    )
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)
    return path


def _forward_signal(process: subprocess.Popen, signum: int, _frame: FrameType | None) -> None:
    if process.poll() is None:
        process.send_signal(signum)


def _artifact_destination(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.startswith("/mlflow"):
        raise RuntimeError("artifact destination must be s3://<private-bucket>/mlflow")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError("artifact destination must not contain credentials or URL options")
    return value


def main() -> int:
    values = _required_environment()
    artifact_destination = _artifact_destination(values["MLFLOW_ARTIFACTS_DESTINATION"])
    auth_config = _write_auth_config(values)
    child_environment = {**os.environ, "MLFLOW_AUTH_CONFIG_PATH": str(auth_config)}
    mlflow_executable = shutil.which("mlflow")
    if mlflow_executable is None:
        raise RuntimeError("mlflow executable is missing")
    subprocess.run(
        [mlflow_executable, "db", "upgrade", values["DATABASE_URL"]],
        check=True,
        timeout=120,
        env=child_environment,
    )
    args = [
        mlflow_executable,
        "server",
        "--app-name",
        "basic-auth",
        "--backend-store-uri",
        values["DATABASE_URL"],
        "--artifacts-destination",
        artifact_destination,
        "--host",
        "0.0.0.0",
        "--port",
        os.environ.get("PORT", "5000"),
        "--allowed-hosts",
        values["MLFLOW_SERVER_ALLOWED_HOSTS"],
        "--workers",
        os.environ.get("MLFLOW_WORKERS", "2"),
    ]
    process = subprocess.Popen(args, env=child_environment)
    signal.signal(signal.SIGTERM, lambda signum, frame: _forward_signal(process, signum, frame))
    signal.signal(signal.SIGINT, lambda signum, frame: _forward_signal(process, signum, frame))
    return process.wait()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        LOGGER.error("MLFLOW_STARTUP_FAILED type=%s", type(exc).__name__)
        raise SystemExit(1) from exc

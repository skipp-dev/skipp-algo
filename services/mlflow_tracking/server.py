"""Fail-closed Railway launcher for the authenticated MLflow pilot."""

from __future__ import annotations

import importlib
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
    "MLFLOW_SERVER_CORS_ALLOWED_ORIGINS",
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
    if parsed.scheme != "s3" or not parsed.netloc or parsed.path.rstrip("/") != "/mlflow":
        raise RuntimeError("artifact destination must be s3://<private-bucket>/mlflow")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError("artifact destination must not contain credentials or URL options")
    return value


def _validated_server_security(values: dict[str, str]) -> tuple[str, str]:
    username = values["MLFLOW_ADMIN_USERNAME"]
    password = values["MLFLOW_ADMIN_PASSWORD"]
    flask_secret = values["MLFLOW_FLASK_SERVER_SECRET_KEY"]
    if username.casefold() in {"admin", "mlflow", "root"}:
        raise RuntimeError("MLFLOW_ADMIN_USERNAME must not use a default administrative name")
    if len(password) < 32 or len(flask_secret) < 32 or password == flask_secret:
        raise RuntimeError("MLflow password and Flask secret must be distinct and at least 32 characters")

    hosts = [host.strip() for host in values["MLFLOW_SERVER_ALLOWED_HOSTS"].split(",")]
    if not hosts or any(not host or "*" in host or "://" in host or "/" in host for host in hosts):
        raise RuntimeError("MLFLOW_SERVER_ALLOWED_HOSTS must contain exact hostnames without wildcards")
    origins = [origin.strip() for origin in values["MLFLOW_SERVER_CORS_ALLOWED_ORIGINS"].split(",")]
    for origin in origins:
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path.rstrip("/")
            or parsed.query
            or parsed.fragment
            or parsed.hostname not in hosts
        ):
            raise RuntimeError("MLFLOW_SERVER_CORS_ALLOWED_ORIGINS must be exact allowed HTTPS origins")
    return ",".join(hosts), ",".join(origins)


def _s3_endpoint(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError("MLFLOW_S3_ENDPOINT_URL must be a credential-free HTTPS URL")
    return value.rstrip("/")


def _worker_count(value: str) -> str:
    try:
        workers = int(value)
    except ValueError as exc:
        raise RuntimeError("MLFLOW_WORKERS must be an integer") from exc
    if not 1 <= workers <= 4:
        raise RuntimeError("MLFLOW_WORKERS must be between 1 and 4")
    return str(workers)


def _upgrade_auth_database(database_url: str) -> None:
    """Migrate MLflow's auth schema once before starting multiple workers."""
    sqlalchemy = importlib.import_module("sqlalchemy")
    auth_db_utils = importlib.import_module("mlflow.server.auth.db.utils")
    engine = sqlalchemy.create_engine(database_url)
    try:
        auth_db_utils.migrate(engine, "head")
    finally:
        engine.dispose()


def main() -> int:
    values = _required_environment()
    artifact_destination = _artifact_destination(values["MLFLOW_ARTIFACTS_DESTINATION"])
    allowed_hosts, allowed_origins = _validated_server_security(values)
    _s3_endpoint(values["MLFLOW_S3_ENDPOINT_URL"])
    workers = _worker_count(os.environ.get("MLFLOW_WORKERS", "2"))
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
    _upgrade_auth_database(values["DATABASE_URL"])
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
        allowed_hosts,
        "--cors-allowed-origins",
        allowed_origins,
        "--x-frame-options",
        "DENY",
        "--workers",
        workers,
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

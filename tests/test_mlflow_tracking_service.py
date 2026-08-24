from __future__ import annotations

import stat
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.mlflow_tracking.server import (
    _artifact_destination,
    _required_environment,
    _s3_endpoint,
    _upgrade_auth_database,
    _validated_server_security,
    _worker_count,
    _write_auth_config,
)

SERVICE_DIR = Path("services/mlflow_tracking")


def test_service_is_pinned_and_separate_from_worker_runtime() -> None:
    config = tomllib.loads((SERVICE_DIR / "railway.toml").read_text(encoding="utf-8"))
    assert config["build"]["dockerfilePath"] == "services/mlflow_tracking/Dockerfile"
    assert config["deploy"]["startCommand"] == "python -m services.mlflow_tracking.server"
    assert config["deploy"]["healthcheckPath"] == "/health"
    assert config["deploy"]["healthcheckTimeout"] == 60
    assert config["deploy"]["restartPolicyType"] == "ON_FAILURE"
    assert config["deploy"]["restartPolicyMaxRetries"] == 3
    dockerfile = (SERVICE_DIR / "Dockerfile").read_text(encoding="utf-8")
    assert "python:3.12-slim@sha256:" in dockerfile
    assert "VOLUME" not in dockerfile
    assert "scripts/mlflow_artifact_backup.py" in dockerfile
    assert "a0_fast_detector" not in dockerfile
    assert (SERVICE_DIR / "requirements.txt").read_text(encoding="utf-8").splitlines() == [
        "mlflow[auth]==3.15.1",  # 2026-08-11 (#4596 accepted): 3.15.0/1.43.62 -> below
        "psycopg2-binary==2.9.12",
        "boto3==1.43.77",  # 2026-08-17 (#4778 dependabot): 1.43.66->1.43.71
    ]
    assert "mlflow" not in Path("services/a0_fast_detector/requirements.txt").read_text(
        encoding="utf-8"
    ).lower()


def _pinned_mlflow_version(path: Path) -> str:
    """Die gepinnte mlflow-Version aus einer requirements-Datei, Extras egal."""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        name, _, version = line.partition("==")
        if name.partition("[")[0].strip() == "mlflow":
            return version.strip()
    raise AssertionError(f"{path} pinnt kein mlflow")


def test_optional_client_pin_tracks_the_server_pin() -> None:
    """Der optionale Client darf nicht hinter dem Server zurueckbleiben.

    Gemessen 2026-08-21 (Dependabot #14, GHSA-7gwp-5pfp-969j, CVSS 9.3): der
    Server stand auf 3.15.1, `requirements-mlflow.txt` seit Wochen auf 3.14.0.
    Die beiden Pins gehoeren zusammen — derselbe Wire-Contract, dieselbe
    CVE-Flaeche — aber nichts hat sie gekoppelt, also musste ein externer
    Sicherheitsscanner die Drift finden statt ein Test hier.

    Gleichheit statt ">=": ein Client, der dem Server VORAUS ist, ist genauso
    ungetestet wie einer, der hinterherhinkt.
    """
    client = _pinned_mlflow_version(Path("requirements-mlflow.txt"))
    server = _pinned_mlflow_version(SERVICE_DIR / "requirements.txt")
    assert client == server, (
        f"requirements-mlflow.txt pinnt mlflow=={client}, der Tracking-Server "
        f"faehrt {server}. Beide Dateien im SELBEN PR nachziehen."
    )


def test_the_pin_comparison_is_not_vacuous(tmp_path: Path) -> None:
    """Positivkontrolle — sonst genuegte dem Vergleich ein konstanter Rueckgabewert.

    Bewusst gegen SYNTHETISCHE Dateien, nicht gegen die echten Pins: eine
    Zusicherung auf "3.15.1" wuerde bei jedem legitimen Bump falsch rot und
    pruefte am Ende die Versionsnummer statt den Vergleich.
    """

    def write(name: str, body: str) -> Path:
        path = tmp_path / name
        path.write_text(body, encoding="utf-8")
        return path

    # liest wirklich aus der Datei, unterscheidet Werte, ignoriert Extras
    assert _pinned_mlflow_version(write("a.txt", "mlflow==1.2.3\n")) == "1.2.3"
    assert _pinned_mlflow_version(write("b.txt", "mlflow[auth]==9.9.9\n")) == "9.9.9"
    # Kommentare und Leerzeilen zaehlen nicht als Pin
    assert (
        _pinned_mlflow_version(write("c.txt", "# mlflow==0.0.1\n\nmlflow==4.5.6  # bump\n"))
        == "4.5.6"
    )
    # ein Praefix-Namensvetter darf NICHT als mlflow durchgehen
    with pytest.raises(AssertionError, match="pinnt kein mlflow"):
        _pinned_mlflow_version(write("d.txt", "mlflow-skinny==3.15.1\nboto3==1.0.0\n"))


def test_artifact_backup_is_a_daily_terminating_verified_cron() -> None:
    config = tomllib.loads((SERVICE_DIR / "backup.railway.toml").read_text(encoding="utf-8"))
    assert config["build"]["dockerfilePath"] == "services/mlflow_tracking/Dockerfile"
    assert config["deploy"]["cronSchedule"] == "17 3 * * *"
    assert config["deploy"]["restartPolicyType"] == "NEVER"
    assert config["deploy"]["startCommand"].endswith("backup-verify --apply")


def test_launcher_refuses_missing_security_configuration(monkeypatch) -> None:
    for name in (
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
        "s3://bucket/mlflow-evil",
    ):
        with pytest.raises(RuntimeError):
            _artifact_destination(invalid)


def test_server_security_requires_strong_distinct_secrets_and_exact_origins() -> None:
    values = {
        "MLFLOW_ADMIN_USERNAME": "skipp-mlflow-admin",
        "MLFLOW_ADMIN_PASSWORD": "a" * 32,
        "MLFLOW_FLASK_SERVER_SECRET_KEY": "b" * 32,
        "MLFLOW_SERVER_ALLOWED_HOSTS": "mlflow.example.test,mlflow.railway.internal",
        "MLFLOW_SERVER_CORS_ALLOWED_ORIGINS": "https://mlflow.example.test",
    }
    assert _validated_server_security(values) == (
        "mlflow.example.test,mlflow.railway.internal",
        "https://mlflow.example.test",
    )
    for key, invalid in (
        ("MLFLOW_ADMIN_USERNAME", "admin"),
        ("MLFLOW_ADMIN_PASSWORD", "short"),
        ("MLFLOW_SERVER_ALLOWED_HOSTS", "*.example.test"),
        ("MLFLOW_SERVER_CORS_ALLOWED_ORIGINS", "http://mlflow.example.test"),
        ("MLFLOW_SERVER_CORS_ALLOWED_ORIGINS", "https://other.example.test"),
    ):
        changed = {**values, key: invalid}
        with pytest.raises(RuntimeError):
            _validated_server_security(changed)


def test_s3_endpoint_and_worker_count_fail_closed() -> None:
    assert _s3_endpoint("https://storage.railway.app/") == "https://storage.railway.app"
    assert _worker_count("2") == "2"
    for invalid in ("http://storage.example", "https://user:secret@storage.example"):
        with pytest.raises(RuntimeError):
            _s3_endpoint(invalid)
    for invalid in ("0", "5", "two"):
        with pytest.raises(RuntimeError):
            _worker_count(invalid)


def test_auth_schema_is_migrated_serially_and_engine_is_always_disposed(monkeypatch) -> None:
    calls: list[tuple[object, str]] = []
    engine = SimpleNamespace(disposed=False)
    engine.dispose = lambda: setattr(engine, "disposed", True)

    def fake_import(name: str):
        if name == "sqlalchemy":
            return SimpleNamespace(create_engine=lambda uri: engine if uri == "postgresql://db" else None)
        if name == "mlflow.server.auth.db.utils":
            return SimpleNamespace(migrate=lambda received, revision: calls.append((received, revision)))
        raise AssertionError(name)

    monkeypatch.setattr("services.mlflow_tracking.server.importlib.import_module", fake_import)
    _upgrade_auth_database("postgresql://db")
    assert calls == [(engine, "head")]
    assert engine.disposed is True


def test_auth_schema_engine_is_disposed_when_migration_fails(monkeypatch) -> None:
    engine = SimpleNamespace(disposed=False)
    engine.dispose = lambda: setattr(engine, "disposed", True)

    def fail_migration(_engine, _revision):
        raise RuntimeError("migration failed")

    modules = {
        "sqlalchemy": SimpleNamespace(create_engine=lambda _uri: engine),
        "mlflow.server.auth.db.utils": SimpleNamespace(migrate=fail_migration),
    }
    monkeypatch.setattr(
        "services.mlflow_tracking.server.importlib.import_module", modules.__getitem__
    )
    with pytest.raises(RuntimeError, match="migration failed"):
        _upgrade_auth_database("postgresql://db")
    assert engine.disposed is True

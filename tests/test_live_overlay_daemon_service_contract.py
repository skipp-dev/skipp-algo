from __future__ import annotations

import tomllib
from pathlib import Path

_SERVICE_DIR = Path(__file__).resolve().parents[1] / "services" / "live_overlay_daemon"


def _load_railway_config() -> dict:
    with open(_SERVICE_DIR / "railway.toml", "rb") as fh:
        return tomllib.load(fh)


def test_railway_config_builds_from_dockerfile() -> None:
    config = _load_railway_config()
    assert config["build"]["builder"] == "DOCKERFILE"
    assert config["build"]["dockerfilePath"] == "services/live_overlay_daemon/Dockerfile"


def test_railway_start_command_binds_to_injected_port() -> None:
    config = _load_railway_config()
    start = config["deploy"]["startCommand"]

    assert "uvicorn services.live_overlay_daemon.main:app" in start
    assert "--host 0.0.0.0" in start
    assert "--port $PORT" in start
    assert "--http h11" in start
    assert "--loop asyncio" in start


def test_railway_healthcheck_path_is_health() -> None:
    config = _load_railway_config()
    assert config["deploy"]["healthcheckPath"] == "/health"


def test_railway_declares_live_overlay_daemon_service() -> None:
    config = _load_railway_config()
    names = [svc["name"] for svc in config["services"]]
    assert "live_overlay_daemon" in names


def test_dockerfile_local_fallback_binds_to_port_env() -> None:
    dockerfile = (_SERVICE_DIR / "Dockerfile").read_text(encoding="utf-8")

    assert "CMD" in dockerfile
    assert "sh" in dockerfile and "-c" in dockerfile
    assert "uvicorn services.live_overlay_daemon.main:app" in dockerfile
    assert "--host 0.0.0.0" in dockerfile
    assert "--port ${PORT:-8000}" in dockerfile
    assert "USER appuser" in dockerfile

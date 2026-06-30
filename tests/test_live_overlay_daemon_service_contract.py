from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

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

    assert start == "python -m services.live_overlay_daemon.main"
    assert "$PORT" not in start
    assert "--port" not in start


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
    assert '["python", "-m", "services.live_overlay_daemon.main"]' in dockerfile
    assert "$PORT" not in dockerfile
    assert "--port" not in dockerfile
    assert "USER appuser" in dockerfile


def test_python_entrypoint_uses_port_env_for_uvicorn_default(monkeypatch) -> None:
    from services.live_overlay_daemon import main

    captured: dict[str, object] = {}

    def fake_run(app_obj: object, **kwargs: object) -> None:
        captured["app"] = app_obj
        captured.update(kwargs)

    monkeypatch.setenv("PORT", "8765")
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake_run))

    main.run_server()

    assert captured["app"] is main.app
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 8765
    assert captured["workers"] == 1
    assert captured["http"] == "h11"
    assert captured["loop"] == "asyncio"

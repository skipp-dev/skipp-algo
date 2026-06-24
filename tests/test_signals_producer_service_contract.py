from __future__ import annotations

import tomllib
from pathlib import Path

_SERVICE_DIR = Path(__file__).resolve().parents[1] / "services" / "signals_producer"


def _load_railway_config() -> dict:
    with open(_SERVICE_DIR / "railway.toml", "rb") as fh:
        return tomllib.load(fh)


def test_railway_config_builds_from_dockerfile() -> None:
    config = _load_railway_config()
    assert config["build"]["builder"] == "DOCKERFILE"
    assert config["build"]["dockerfilePath"] == "services/signals_producer/Dockerfile"


def test_railway_start_command_runs_signal_engine() -> None:
    config = _load_railway_config()
    start = config["deploy"]["startCommand"]
    assert "python -m open_prep.realtime_signals" in start


def test_railway_healthcheck_path_is_healthz() -> None:
    config = _load_railway_config()
    assert config["deploy"]["healthcheckPath"] == "/healthz"


def test_railway_declares_signals_producer_service() -> None:
    config = _load_railway_config()
    names = [svc["name"] for svc in config["services"]]
    assert "smc-signals-producer" in names


def test_dockerfile_copies_open_prep_and_runs_engine() -> None:
    dockerfile = (_SERVICE_DIR / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY open_prep/" in dockerfile
    # Accept both shell-form (`python -m ...`) and exec-form (`"python", "-m", ...`)
    # CMDs.  Railway overrides CMD with railway.toml:startCommand at runtime;
    # the Dockerfile CMD is the local / `docker run` fallback.
    assert (
        "python -m open_prep.realtime_signals" in dockerfile
        or '"python", "-m", "open_prep.realtime_signals"' in dockerfile
    )
    # Container must not run as root (security baseline).
    assert "USER appuser" in dockerfile


def test_requirements_file_exists() -> None:
    assert (_SERVICE_DIR / "requirements.txt").is_file()

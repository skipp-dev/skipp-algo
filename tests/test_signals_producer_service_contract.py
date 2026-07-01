from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
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
    assert start == "python -m open_prep.realtime_signals"
    assert "--telemetry-port" not in start
    assert "$PORT" not in start


def test_signal_engine_entrypoint_uses_port_env_for_telemetry_default(monkeypatch) -> None:
    """Railway startCommand relies on the Python entrypoint reading PORT itself."""
    import open_prep.realtime_signals as rs

    captured_ports: list[int] = []
    shutdowns: list[bool] = []

    class _FakeServer:
        def shutdown(self) -> None:
            shutdowns.append(True)

    class _FakeEngine:
        def __init__(self, *, poll_interval: int, top_n: int, fast_mode: bool, ultra_mode: bool) -> None:
            self.poll_interval = poll_interval
            self.top_n = top_n
            self.fast_mode = fast_mode
            self.ultra_mode = ultra_mode
            self.telemetry = rs.ScoreTelemetry()
            self._async_newsstack = None

        def poll_once(self) -> None:
            raise KeyboardInterrupt

    def _fake_start_telemetry_server(telemetry, *, port: int, engine):
        captured_ports.append(port)
        assert isinstance(telemetry, rs.ScoreTelemetry)
        assert isinstance(engine, _FakeEngine)
        return _FakeServer()

    monkeypatch.setenv("PORT", "8765")
    monkeypatch.setattr(sys, "argv", ["open_prep.realtime_signals"])
    monkeypatch.setattr(rs, "RealtimeEngine", _FakeEngine)
    monkeypatch.setattr(rs, "_start_telemetry_server", _fake_start_telemetry_server)

    rs.main()

    assert captured_ports == [8765]
    assert shutdowns == [True]


@pytest.mark.parametrize(
    ("port_value", "expected"),
    [
        ("", 8099),
        ("   ", 8099),
        ("abc", 8099),
        ("8098", 8098),
        (" 8097 ", 8097),
        ("65535", 65535),
        # Non-positive and sign-prefixed values violate the PORT contract and
        # must fall back to the default rather than being silently accepted.
        ("-1", 8099),
        ("0", 8099),
        ("080", 80),
        ("01", 1),
        ("00001", 1),
        ("+8099", 8099),
        (" -5 ", 8099),
        # Non-ASCII numerals and out-of-range values are rejected.
        ("٨٠٩٩", 8099),
        ("८१२३", 8099),
        ("65536", 8099),
        ("999999999999999999999999999999", 8099),
    ],
)
def test_signal_engine_port_env_parsing_falls_back(port_value: str, expected: int, monkeypatch) -> None:
    import open_prep.realtime_signals as rs

    monkeypatch.setenv("PORT", port_value)
    assert rs._env_int("PORT", 8099) == expected


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


def _extract_exact_pin(path: Path, package: str) -> str | None:
    needle = f"{package}=="
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "#" in line:
            line = line.split("#", 1)[0].strip()
        if line.startswith(needle):
            return line[len(needle):].strip()
    return None


def test_signals_producer_httpx_pin_matches_root_requirements() -> None:
    root_requirements = _REPO_ROOT / "requirements.txt"
    service_requirements = _SERVICE_DIR / "requirements.txt"

    root_httpx = _extract_exact_pin(root_requirements, "httpx")
    service_httpx = _extract_exact_pin(service_requirements, "httpx")

    assert root_httpx is not None, "Root requirements.txt must pin httpx with =="
    assert service_httpx is not None, "signals_producer requirements.txt must pin httpx with =="
    assert service_httpx == root_httpx, (
        "signals_producer httpx pin drifted from root requirements.txt; keep both pins aligned"
    )

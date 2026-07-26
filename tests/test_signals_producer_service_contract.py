from __future__ import annotations

import inspect
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
    quote_source_lifecycle: list[str] = []

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
            self._near_a0_repoller = None

        def start_async_newsstack(self, *, poll_interval: int) -> None:
            pass

        def start_near_a0_repoller(self, poll_interval: float) -> None:
            pass

        def start_quote_source(self) -> None:
            quote_source_lifecycle.append("start")

        def stop_quote_source(self) -> None:
            quote_source_lifecycle.append("stop")

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
    assert quote_source_lifecycle == ["start", "stop"]


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


def test_runtime_poll_budget_is_env_configurable() -> None:
    """Railway can reduce FMP volume without replacing the start command."""
    import open_prep.realtime_signals as rs

    source = inspect.getsource(rs.main)
    assert 'default=_env_int("RT_POLL_INTERVAL_SECS", DEFAULT_POLL_INTERVAL, maximum=None)' in source
    assert 'default=_env_int("RT_TOP_N", DEFAULT_TOP_N, minimum=0, maximum=None)' in source
    assert '_env_int("RT_NEAR_A0_REPOLL_SECS", 0, minimum=0)' in source


def test_poll_budget_env_is_not_clamped_to_the_tcp_port_range(monkeypatch) -> None:
    """Poll budget vars are not ports: a long interval and RT_TOP_N=0 ('all') must survive.

    Regression for reusing the PORT validator (1..65535) on these vars, which
    silently reverted RT_POLL_INTERVAL_SECS>65535 to the aggressive 20s default.
    """
    import open_prep.realtime_signals as rs

    # A daily poll interval (86400s) is far above the TCP-port ceiling but valid here.
    monkeypatch.setenv("RT_POLL_INTERVAL_SECS", "86400")
    assert rs._env_int("RT_POLL_INTERVAL_SECS", rs.DEFAULT_POLL_INTERVAL, maximum=None) == 86400

    # 0 is the documented "monitor ALL symbols" sentinel and must be accepted.
    monkeypatch.setenv("RT_TOP_N", "0")
    assert rs._env_int("RT_TOP_N", rs.DEFAULT_TOP_N, minimum=0, maximum=None) == 0

    monkeypatch.setenv("RT_NEAR_A0_REPOLL_SECS", "0")
    assert rs._env_int("RT_NEAR_A0_REPOLL_SECS", 0, minimum=0) == 0

    # Below-minimum / garbage still falls back to the default.
    monkeypatch.setenv("RT_TOP_N", "-1")
    assert rs._env_int("RT_TOP_N", rs.DEFAULT_TOP_N, minimum=0, maximum=None) == rs.DEFAULT_TOP_N

    # The default PORT bounds (1..65535) are unchanged for callers that omit them.
    monkeypatch.setenv("PORT", "86400")
    assert rs._env_int("PORT", 8099) == 8099


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


def test_dockerfile_contains_private_ai_runtime_modules() -> None:
    dockerfile = (_SERVICE_DIR / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY terminal_fmp_insights.py" in dockerfile
    assert "COPY cisco_ai_defense.py" in dockerfile
    assert "COPY open_prep_boundary.py" in dockerfile

    watch_patterns = set(_load_railway_config()["build"]["watchPatterns"])
    assert "terminal_fmp_insights.py" in watch_patterns
    assert "cisco_ai_defense.py" in watch_patterns
    assert "open_prep_boundary.py" in watch_patterns


def test_dockerfile_keeps_smc_core_dependency_minimal() -> None:
    """Importing the full package initializer pulls scoring-only modules into the lean image."""
    dockerfile = (_SERVICE_DIR / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY smc_core/resilient.py /app/smc_core/resilient.py" in dockerfile
    assert "COPY smc_core/ /app/smc_core/" not in dockerfile
    assert "touch /app/smc_core/__init__.py" in dockerfile


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


def test_signals_producer_ai_defense_pin_matches_root_requirements() -> None:
    root_requirements = _REPO_ROOT / "requirements.txt"
    service_requirements = _SERVICE_DIR / "requirements.txt"

    root_pin = _extract_exact_pin(root_requirements, "cisco-aidefense-sdk")
    service_pin = _extract_exact_pin(service_requirements, "cisco-aidefense-sdk")

    assert root_pin is not None
    assert service_pin == root_pin


def test_signal_engine_suppresses_http_client_request_urls() -> None:
    source = (_REPO_ROOT / "open_prep" / "realtime_signals.py").read_text(
        encoding="utf-8"
    )

    assert 'logging.getLogger("httpx").setLevel(logging.WARNING)' in source
    assert 'logging.getLogger("httpcore").setLevel(logging.WARNING)' in source


def test_image_ships_technical_scorer_chain() -> None:
    """The deployed producer silently ran with _noop_fetch technicals: the
    image lacked terminal_technicals.py (and its FMP-fallback import chain)
    plus the tradingview-ta dependency, so every prod signal scored
    technical_score=0.5 NEUTRAL and the RSI A1->A0 upgrades / STRONG_SELL A0
    blocks were inert — one WARNING log, no metric (audit finding P2)."""
    dockerfile = (_REPO_ROOT / "services" / "signals_producer" / "Dockerfile").read_text(encoding="utf-8")
    for module in (
        "terminal_technicals.py",
        "terminal_fmp_technicals.py",
        "open_prep_boundary.py",
    ):
        assert f"COPY {module}" in dockerfile, f"image must ship {module}"

    reqs = (_REPO_ROOT / "services" / "signals_producer" / "requirements.txt").read_text(encoding="utf-8")
    assert "tradingview-ta==" in reqs, "tradingview-ta pin missing from producer image requirements"

    # Keep the pin aligned with the root requirements (same rationale as the
    # httpx alignment comment in the producer requirements file).
    root_reqs = (_REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    root_pin = next(
        line.split("#")[0].strip()
        for line in root_reqs.splitlines()
        if line.strip().startswith("tradingview-ta==")
    )
    assert root_pin in reqs, f"producer tradingview-ta pin drifted from root ({root_pin})"


def test_railway_watch_patterns_cover_every_copied_module() -> None:
    """railway.toml watchPatterns OVERRIDE the dashboard setting, so a copied
    module missing from the list means changes to it silently do NOT redeploy
    the producer (the file's own comment says the list must be complete —
    the audit found four copied paths it did not cover)."""
    dockerfile = (_REPO_ROOT / "services" / "signals_producer" / "Dockerfile").read_text(encoding="utf-8")
    toml_text = (_REPO_ROOT / "services" / "signals_producer" / "railway.toml").read_text(encoding="utf-8")

    copy_sources = [
        line.split()[1]
        for line in dockerfile.splitlines()
        if line.startswith("COPY ") and not line.split()[1].startswith("services/")
    ]
    assert copy_sources, "no COPY sources parsed from the Dockerfile"

    import re as _re

    patterns = _re.findall(r'"([^"]+)"', toml_text.split("watchPatterns", 1)[1].split("]", 1)[0])

    def _covered(src: str) -> bool:
        for pat in patterns:
            if pat.endswith("/**") and src.rstrip("/").startswith(pat[:-3].rstrip("/")):
                return True
            if pat == src or pat == src.rstrip("/"):
                return True
        return False

    uncovered = sorted(src for src in copy_sources if not _covered(src))
    assert not uncovered, (
        "Dockerfile COPY sources not covered by railway.toml watchPatterns — "
        f"changes to them will not redeploy the producer: {uncovered}"
    )

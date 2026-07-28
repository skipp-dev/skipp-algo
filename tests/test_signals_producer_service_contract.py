from __future__ import annotations

import inspect
import json
import os
import re
import subprocess
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


def test_railway_healthcheck_path_is_flag_aware_readyz() -> None:
    config = _load_railway_config()
    assert config["deploy"]["healthcheckPath"] == "/readyz"


def test_railway_deploy_survives_failed_rotation() -> None:
    """Regression pin for the 2026-07-28 16:23-16:44 UTC prod outage.

    A routine main-push deploy FAILED its 60s /readyz healthcheck, Railway
    rotated the old container out (SIGTERM), the engine's SIGTERM handler
    exits cleanly (code 0), and ``ON_FAILURE`` does not restart clean exits —
    leaving NOTHING running mid-RTH. Two railway.toml settings close that:

    - ``healthcheckTimeout >= 300``: the first successful poll (watchlist +
      snapshot + quote fetch) must fit the readiness window even on a slow
      cold start, so routine deploys stop failing spuriously.
    - ``restartPolicyType == "ALWAYS"``: a long-lived producer must come back
      after ANY exit, clean or not. Deliberate stops go through
      ``railway down`` (removes the deployment; unaffected by policy).
    """
    config = _load_railway_config()
    assert config["deploy"]["healthcheckTimeout"] >= 300, (
        "healthcheckTimeout below 300s races the engine's first poll and "
        "fails routine deploys (2026-07-28 outage trigger)"
    )
    assert config["deploy"]["restartPolicyType"] == "ALWAYS", (
        "ON_FAILURE leaves the producer dead after a clean-exit SIGTERM "
        "during deploy rotation (2026-07-28 outage mechanism)"
    )


def test_railway_declares_signals_producer_service() -> None:
    config = _load_railway_config()
    names = [svc["name"] for svc in config["services"]]
    assert "smc-signals-producer" in names
    assert "smc-signals-producer-databento-shadow" in names


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


def test_signals_producer_databento_pin_matches_root_requirements() -> None:
    # The producer must ship the Databento SDK for its default quote path.
    # A prior shadow deploy exposed the missing image dependency as
    # ModuleNotFoundError. Keep the service and root pins aligned so both
    # builds resolve the same version.
    root_requirements = _REPO_ROOT / "requirements.txt"
    service_requirements = _SERVICE_DIR / "requirements.txt"

    root_databento = _extract_exact_pin(root_requirements, "databento")
    service_databento = _extract_exact_pin(service_requirements, "databento")

    assert root_databento is not None, "Root requirements.txt must pin databento with =="
    assert service_databento is not None, "signals_producer requirements.txt must pin databento with =="
    assert service_databento == root_databento, (
        "signals_producer databento pin drifted from root requirements.txt; keep both pins aligned"
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


# ---------------------------------------------------------------------------
# Image import-closure probe
# ---------------------------------------------------------------------------

# The modules the deployed engine actually imports at runtime, each tied to the
# code path that triggers it. A repo-local import reachable from any of these
# that the Dockerfile does not COPY only fails IN THE IMAGE — the dev checkout
# always has the whole repo on sys.path, so plain pytest can never see it
# (that is exactly how the scripts.smc_atomic_write ModuleNotFoundError, #4148,
# reached the shadow deploy).
_RUNTIME_IMPORT_TARGETS = (
    # railway.toml startCommand — the eager, import-time closure.
    "open_prep.realtime_signals",
    # RT_QUOTE_SOURCE=databento path (the default since #4168): deferred
    # imports inside RealtimeEngine._build_databento_quote_source.
    "open_prep.quote_reference",
    "open_prep.databento_quote_feed",
    # AsyncNewsstackPoller path: deferred imports inside the poll loop.
    "newsstack_fmp.config",
    "newsstack_fmp.pipeline",
    # TechnicalScorer chain: deferred with a silent _noop_fetch degrade, so an
    # image gap would not even crash — it would quietly score 0.5 NEUTRAL
    # (audit finding P2). Probing the import keeps the chain shippable.
    "terminal_technicals",
    "terminal_fmp_technicals",
)

_PROBE_BOOTSTRAP = r"""
import importlib, json, sys, traceback
from pathlib import Path

image_root = Path(sys.argv[1]).resolve()
# Drop editable-install finders (dev venv) so repo packages cannot leak in.
sys.meta_path = [
    f for f in sys.meta_path
    if not (getattr(type(f), "__module__", "") or "").startswith("__editable__")
]

def _exposes_repo(entry):
    base = Path(entry or ".").resolve()
    if base == image_root:
        return False
    return (base / "open_prep" / "__init__.py").exists() or (
        base / "services" / "signals_producer" / "Dockerfile"
    ).exists()

sys.path = [e for e in sys.path if not _exposes_repo(e)]
sys.path.insert(0, str(image_root))

failures = {}
for name in json.loads(sys.argv[2]):
    try:
        importlib.import_module(name)
    except BaseException:
        failures[name] = traceback.format_exc(limit=6)
print(json.dumps(failures))
sys.exit(1 if failures else 0)
"""


def _materialize_image_module_surface(dockerfile_text: str, root: Path) -> None:
    """Recreate /app's repo-module surface from the Dockerfile, in layer order.

    Handles the two instruction shapes the image uses for modules: ``COPY src
    dest`` (dirs symlinked file-by-file, single files symlinked) and ``RUN``
    lines with ``mkdir -p /app/...`` / ``touch /app/...`` (the deliberately
    EMPTY smc_core/__init__.py + scripts/__init__.py — an empty file, not the
    repo's initializer, mirroring the lean-image intent).
    """
    for raw in dockerfile_text.splitlines():
        line = raw.strip()
        copy = re.match(r"^COPY\s+(\S+)\s+(\S+)$", line)
        if copy:
            src, dest = copy.groups()
            if not dest.startswith("/app"):
                continue  # requirements.txt lands in /tmp — not a module
            target = root / os.path.relpath(dest, "/app")
            target.parent.mkdir(parents=True, exist_ok=True)
            source = _REPO_ROOT / src.rstrip("/")
            assert source.exists(), f"Dockerfile COPY source missing from repo: {src}"
            if source.is_dir():
                target.mkdir(exist_ok=True)
                for child in source.rglob("*.py"):
                    dst = target / child.relative_to(source)
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.symlink_to(child)
            elif not target.exists():
                target.symlink_to(source)
            continue
        if line.startswith("RUN"):
            for d in re.findall(r"mkdir -p (/app/\S+)", line):
                (root / os.path.relpath(d, "/app")).mkdir(parents=True, exist_ok=True)
            for f in re.findall(r"touch (/app/\S+)", line):
                p = root / os.path.relpath(f, "/app")
                p.parent.mkdir(parents=True, exist_ok=True)
                if p.is_symlink() or p.exists():
                    p.unlink()
                p.write_text("")


def test_image_import_surface_covers_runtime_import_closure(tmp_path) -> None:
    """Every repo-local import the engine performs at runtime must resolve
    inside the module surface the Dockerfile ships.

    Rebuilds that surface from the COPY/RUN instructions and imports the
    runtime target set in a subprocess whose sys.path sees ONLY the synthetic
    image root (+ site-packages for third-party deps, which the pin-alignment
    tests above keep honest). Dropping ``COPY scripts/smc_atomic_write.py``
    reproduces the #4148 shadow-deploy ModuleNotFoundError verbatim.
    """
    image_root = tmp_path / "app"
    image_root.mkdir()
    _materialize_image_module_surface(
        (_SERVICE_DIR / "Dockerfile").read_text(encoding="utf-8"), image_root
    )

    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    proc = subprocess.run(  # returncode asserted explicitly below
        [sys.executable, "-c", _PROBE_BOOTSTRAP, str(image_root), json.dumps(_RUNTIME_IMPORT_TARGETS)],
        capture_output=True,
        text=True,
        # Generous: import-probe subprocesses are load-sensitive (they flake
        # under parallel guard runs long before a genuine 240s import exists).
        timeout=240,
        env=env,
        cwd=str(image_root),
    )
    failures = json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else {}
    detail = "\n".join(f"--- {mod}\n{tb}" for mod, tb in failures.items())
    assert proc.returncode == 0 and not failures, (
        "Runtime import closure escapes the Dockerfile COPY surface — these "
        "imports fail inside the image (add the missing COPY, then extend "
        f"railway.toml watchPatterns):\n{detail}\nstderr: {proc.stderr[-500:]}"
    )


def test_readme_documents_deploy_critical_env_vars() -> None:
    """Producer env vars live only in the Railway dashboard (railway.toml has
    no variables section), so the README is the repo-side env contract — keep
    the deploy-critical names present so the doc cannot silently rot."""
    readme = (_SERVICE_DIR / "README.md").read_text(encoding="utf-8")
    for var in (
        "RT_QUOTE_SOURCE",
        "DATABENTO_API_KEY",
        "FMP_API_KEY",
        "SIGNALS_INTERNAL_TOKEN",
        "OPEN_PREP_SNAPSHOT_URL",
        "QUOTE_REFERENCE_SNAPSHOT_URL",
    ):
        assert var in readme, f"README env contract lost deploy-critical var {var}"

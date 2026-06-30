"""L1 regression: _load_env() must NOT overwrite already-set env vars.

Railway injects secrets directly as environment variables before the process
starts.  config._load_env() parses .env for local dev convenience and must use
``os.environ.setdefault`` semantics — i.e. only write a key when it is absent.
A regression to plain assignment would silently overwrite the Railway value
with whatever is in .env, breaking production without any test failure.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path
from unittest.mock import patch

import pytest


def _import_config_fresh() -> object:
    """Re-import config so _load_env() runs again against the patched env."""
    import services.live_overlay_daemon.config as _cfg
    importlib.reload(_cfg)
    return _cfg


class TestLoadEnvDoesNotOverwritePresetVars:
    """_load_env() honours pre-existing env vars (Railway-injected wins)."""

    def test_preset_key_survives_dotenv(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A key already in os.environ is NOT overwritten by the .env file."""
        # Write a .env file with a known key+value.
        dotenv = tmp_path / ".env"
        dotenv.write_text("DATABENTO_API_KEY=from_dotenv\n", encoding="utf-8")

        # Simulate Railway injecting its value before process start.
        monkeypatch.setenv("DATABENTO_API_KEY", "railway_injected")

        import services.live_overlay_daemon.config as cfg
        with patch("services.live_overlay_daemon.config._ENV_FILE", dotenv):
            cfg._load_env()

        assert os.environ["DATABENTO_API_KEY"] == "railway_injected", (
            "_load_env() overwrote a pre-set env var — Railway value would be lost in production"
        )

    def test_absent_key_is_filled_from_dotenv(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A key absent from os.environ IS set from the .env file (local dev path)."""
        dotenv = tmp_path / ".env"
        dotenv.write_text("_TEST_ONLY_KEY=from_dotenv\n", encoding="utf-8")

        # Make sure the key is absent.
        monkeypatch.delenv("_TEST_ONLY_KEY", raising=False)

        import services.live_overlay_daemon.config as cfg
        with patch("services.live_overlay_daemon.config._ENV_FILE", dotenv):
            cfg._load_env()

        assert os.environ.get("_TEST_ONLY_KEY") == "from_dotenv", (
            "_load_env() did not populate a missing key from .env"
        )
        # Cleanup so we don't pollute other tests.
        monkeypatch.delenv("_TEST_ONLY_KEY", raising=False)

    def test_blank_dotenv_is_a_noop(self, tmp_path: Path) -> None:
        """A .env with only comments and blank lines does not raise."""
        dotenv = tmp_path / ".env"
        dotenv.write_text("# comment\n\n# another\n", encoding="utf-8")

        import services.live_overlay_daemon.config as cfg
        # Should not raise — previous env is unchanged.
        with patch("services.live_overlay_daemon.config._ENV_FILE", dotenv):
            cfg._load_env()

    def test_missing_dotenv_is_a_noop(self, tmp_path: Path) -> None:
        """If .env does not exist _load_env() returns silently."""
        nonexistent = tmp_path / "no_such_file.env"

        import services.live_overlay_daemon.config as cfg
        with patch("services.live_overlay_daemon.config._ENV_FILE", nonexistent):
            cfg._load_env()  # must not raise


class TestSignalsServiceConfig:
    """SIGNALS_SERVICE_URL / SIGNALS_INTERNAL_TOKEN are read lazily from env."""

    def test_signals_service_config_defaults_to_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SIGNALS_SERVICE_URL", raising=False)
        monkeypatch.delenv("SIGNALS_INTERNAL_TOKEN", raising=False)
        cfg = _import_config_fresh()
        assert cfg.signals_service_url() == ""
        assert cfg.signals_internal_token() == ""

    def test_signals_service_config_reads_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SIGNALS_SERVICE_URL", "smc-signals-producer.railway.internal")
        monkeypatch.setenv("SIGNALS_INTERNAL_TOKEN", "railway-token")
        cfg = _import_config_fresh()
        assert cfg.signals_service_url() == "smc-signals-producer.railway.internal"
        assert cfg.signals_internal_token() == "railway-token"


class TestPortRangeValidation:
    """PORT must resolve to a bindable TCP port, never a silent random bind
    (PORT=0) or an out-of-range value that crashes uvicorn.
    """

    def test_valid_port_is_returned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PORT", "8765")
        cfg = _import_config_fresh()
        assert cfg.port() == 8765

    def test_zero_port_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # PORT=0 would otherwise make the OS pick a random ephemeral port,
        # which Railway routing/health checks cannot reach.
        monkeypatch.setenv("PORT", "0")
        cfg = _import_config_fresh()
        assert cfg.port() == 8000

    def test_negative_port_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PORT", "-1")
        cfg = _import_config_fresh()
        assert cfg.port() == 8000

    def test_above_max_port_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # > 65535 would raise OverflowError at socket bind time.
        monkeypatch.setenv("PORT", "70000")
        cfg = _import_config_fresh()
        assert cfg.port() == 8000

    def test_boundary_ports_are_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for value, expected in (("1", 1), ("65535", 65535)):
            monkeypatch.setenv("PORT", value)
            cfg = _import_config_fresh()
            assert cfg.port() == expected

    def test_unparseable_port_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PORT", "abc")
        cfg = _import_config_fresh()
        assert cfg.port() == 8000

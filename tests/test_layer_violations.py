"""Tests for F-08 — Layer violation reduction."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


class TestBarUtilsCanonicalLocation:
    """smc_core.bar_utils must be importable and contain the migrated helpers."""

    def test_import_normalize_bars(self) -> None:
        from smc_core.bar_utils import normalize_bars
        assert callable(normalize_bars)

    def test_import_coerce_timestamps(self) -> None:
        from smc_core.bar_utils import coerce_timestamps_to_epoch_seconds
        assert callable(coerce_timestamps_to_epoch_seconds)


class TestHtfContextCanonicalLocation:
    """smc_core.htf_context must expose all public helpers."""

    def test_import_build_htf_bias_context(self) -> None:
        from smc_core.htf_context import build_htf_bias_context
        assert callable(build_htf_bias_context)

    def test_import_select_ipda_htf(self) -> None:
        from smc_core.htf_context import select_ipda_htf
        assert select_ipda_htf("5m") == "D"


class TestSessionContextCanonicalLocation:
    """smc_core.session_context must expose all public helpers."""

    def test_import_build_session_liquidity_context(self) -> None:
        from smc_core.session_context import build_session_liquidity_context
        assert callable(build_session_liquidity_context)

    def test_default_killzones(self) -> None:
        from smc_core.session_context import DEFAULT_KILLZONES
        assert len(DEFAULT_KILLZONES) == 5


class TestBackwardCompatibleReexports:
    """scripts/ re-exports must still work for existing callers."""

    def test_htf_context_reexport(self) -> None:
        from scripts.smc_htf_context import build_htf_bias_context
        assert callable(build_htf_bias_context)

    def test_session_context_reexport(self) -> None:
        from scripts.smc_session_context import build_session_liquidity_context
        assert callable(build_session_liquidity_context)


class TestLayerGuard:
    """The layer violation guard must run and detect no new violations."""

    def test_guard_exits_clean(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "check_layer_violations",
            ROOT / "scripts" / "check_layer_violations.py",
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["check_layer_violations"] = mod
        spec.loader.exec_module(mod)
        assert mod.main() == 0

    def test_smc_integration_does_not_import_htf_from_scripts(self) -> None:
        """After migration, service.py and measurement_evidence.py must use smc_core."""
        service = (ROOT / "smc_integration" / "service.py").read_text()
        assert "from smc_core.htf_context import" in service
        assert "from scripts.smc_htf_context import" not in service

    def test_smc_integration_does_not_import_session_from_scripts(self) -> None:
        service = (ROOT / "smc_integration" / "service.py").read_text()
        me = (ROOT / "smc_integration" / "measurement_evidence.py").read_text()
        assert "from smc_core.session_context import" in service
        assert "from scripts.smc_session_context import" not in service
        assert "from smc_core.session_context import" in me
        assert "from scripts.smc_session_context import" not in me

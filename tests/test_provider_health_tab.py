"""Tests for the Provider Health tab integration in streamlit_terminal."""
from __future__ import annotations

import pytest


class TestProviderHealthTabImports:
    """Verify the imports needed by the Provider Health tab are resolvable."""

    def test_failure_action_importable(self) -> None:
        from smc_integration.provider_health import FailureAction

        assert hasattr(FailureAction, "FALLBACK")
        assert hasattr(FailureAction, "ADVISORY")
        assert hasattr(FailureAction, "SUPPRESS")
        assert hasattr(FailureAction, "HARD_DEGRADE")

    def test_failure_semantics_matrix_importable(self) -> None:
        from smc_integration.provider_health import _FAILURE_SEMANTICS_MATRIX

        assert isinstance(_FAILURE_SEMANTICS_MATRIX, tuple)
        assert len(_FAILURE_SEMANTICS_MATRIX) >= 12  # 4 domains × 3 failure types

    def test_run_provider_health_check_importable(self) -> None:
        from smc_integration.provider_health import run_provider_health_check

        assert callable(run_provider_health_check)

    def test_failure_semantics_matrix_has_all_domains(self) -> None:
        from smc_integration.provider_health import _FAILURE_SEMANTICS_MATRIX

        domains = {fs.domain for fs in _FAILURE_SEMANTICS_MATRIX}
        assert domains == {"structure", "volume", "technical", "news"}

    def test_failure_semantics_entries_are_frozen(self) -> None:
        from smc_integration.provider_health import _FAILURE_SEMANTICS_MATRIX

        for fs in _FAILURE_SEMANTICS_MATRIX:
            with pytest.raises(AttributeError):
                fs.domain = "hacked"  # type: ignore[misc]

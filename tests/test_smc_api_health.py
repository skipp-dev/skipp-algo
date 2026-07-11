"""Truth-audit T5: /health must not claim FMP available without a key."""
from __future__ import annotations

import pytest


def test_health_fmp_available_false_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from smc_tv_bridge import smc_api

    monkeypatch.delenv("FMP_API_KEY", raising=False)
    h = smc_api.health()
    assert h["fmp_key_present"] is False
    # Regardless of mock mode, no key => not really available.
    assert h["fmp_available"] is False


def test_health_reports_key_presence(monkeypatch: pytest.MonkeyPatch) -> None:
    from smc_tv_bridge import smc_api

    monkeypatch.setenv("FMP_API_KEY", "test-key")
    h = smc_api.health()
    assert h["fmp_key_present"] is True
    # fmp_available tracks (not mock) AND key present.
    assert h["fmp_available"] == (not smc_api.USE_MOCK)

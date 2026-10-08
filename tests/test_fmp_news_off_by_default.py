"""FMP news is off unless ENABLE_FMP_NEWS=1 (operator, 2026-10-08: stop every FMP news query).

Pins that, with the flag unset, no FMP news endpoint is requested anywhere:
newsstack, open_prep, SMC enrichment and the provider probe. Benzinga carries
news; FMP stays for market and fundamental data.
"""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def fmp_news_unset(monkeypatch):
    monkeypatch.delenv("ENABLE_FMP_NEWS", raising=False)
    monkeypatch.delenv("ENABLE_FMP", raising=False)


def test_flag_defaults_off(fmp_news_unset, monkeypatch):
    from open_prep.feature_flags import is_fmp_news_enabled

    assert is_fmp_news_enabled() is False
    monkeypatch.setenv("ENABLE_FMP_NEWS", "1")
    assert is_fmp_news_enabled() is True


def test_newsstack_skips_fmp_by_default_even_with_enable_fmp(fmp_news_unset, monkeypatch):
    from newsstack_fmp.config import Config

    monkeypatch.setenv("ENABLE_FMP", "1")
    assert Config().enable_fmp is False
    monkeypatch.setenv("ENABLE_FMP_NEWS", "1")
    assert Config().enable_fmp is True


@pytest.mark.parametrize(
    ("method", "kwargs"),
    [("get_fmp_articles", {"limit": 5}), ("get_stock_latest_news", {"limit": 5}), ("get_stock_news", {"limit": 5})],
)
def test_open_prep_news_methods_make_no_request_by_default(fmp_news_unset, method, kwargs):
    from open_prep.macro import FMPClient

    client = FMPClient.__new__(FMPClient)
    client._get = MagicMock(side_effect=AssertionError("FMP news must not be requested"))
    assert getattr(client, method)(**kwargs) == []
    client._get.assert_not_called()


def test_smc_news_chain_has_no_fmp():
    from scripts.smc_provider_policy import POLICY_NEWS

    assert "fmp" not in POLICY_NEWS.all_providers


def test_probe_skips_fmp_news_without_request_and_is_not_critical(fmp_news_unset, monkeypatch):
    import scripts.probe_providers as probes

    monkeypatch.setenv("FMP_API_KEY", "k")
    httpx = pytest.importorskip("httpx")
    monkeypatch.setattr(httpx, "get", MagicMock(side_effect=AssertionError("no FMP news request")))
    assert probes.probe_fmp_news()[0] == "SKIP"
    assert probes.probe_fmp_press()[0] == "SKIP"
    reloaded = importlib.reload(probes)
    news = [p for p in reloaded.PROBES if "/stable/news/" in p.name]
    assert news and all(p.critical is False for p in news)


@pytest.mark.parametrize(
    ("method", "args"),
    [("fetch_stock_latest", (0, 5)), ("fetch_press_latest", (0, 5)), ("fetch_articles", (5,)), ("fetch_general_latest", (0, 5))],
)
def test_fmp_adapter_news_methods_make_no_request_by_default(fmp_news_unset, method, args):
    """Lowest layer: direct adapter users (streamlit terminal, smc_live_news_bus) are covered too."""
    from newsstack_fmp.ingest_fmp import FmpAdapter

    adapter = FmpAdapter("k")
    try:
        adapter._safe_get = MagicMock(side_effect=AssertionError("FMP news must not be requested"))
        assert getattr(adapter, method)(*args) == []
        adapter._safe_get.assert_not_called()
    finally:
        adapter.close()

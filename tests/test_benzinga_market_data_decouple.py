"""Market-data / calendar transport is decoupled from the news provider flag.

The dual-transport endpoints (dividends/splits/ipos, movers, quotes) used to be
gated on ``benzinga_provider() == "massive"`` — the *news* transport flag. Since
the direct Benzinga free-key variants of these five endpoints were retired
2026-07-09, keying them off the news lane silently 401ed them whenever news ran
``BENZINGA_PROVIDER=direct`` (the deployed config). They now default to Massive
regardless of the news flag, overridable via ``BENZINGA_MARKET_DATA_PROVIDER``.
"""

from __future__ import annotations

import pytest

from newsstack_fmp import ingest_benzinga_calendar as cal


class TestMarketDataUsesMassive:
    def test_defaults_to_massive_when_env_unset(self, monkeypatch) -> None:
        monkeypatch.delenv("BENZINGA_MARKET_DATA_PROVIDER", raising=False)
        assert cal._market_data_uses_massive() is True

    @pytest.mark.parametrize("value", ["massive", "MASSIVE", " massive ", "anything-else"])
    def test_massive_for_non_direct_values(self, monkeypatch, value: str) -> None:
        monkeypatch.setenv("BENZINGA_MARKET_DATA_PROVIDER", value)
        assert cal._market_data_uses_massive() is True

    @pytest.mark.parametrize("value", ["direct", "DIRECT", " Direct "])
    def test_direct_override_forces_direct(self, monkeypatch, value: str) -> None:
        monkeypatch.setenv("BENZINGA_MARKET_DATA_PROVIDER", value)
        assert cal._market_data_uses_massive() is False

    def test_news_provider_flag_does_not_affect_market_data(self, monkeypatch) -> None:
        # The whole point: news=direct must NOT flip market data to the retired
        # direct route. Market-data env unset -> stays Massive.
        monkeypatch.setenv("BENZINGA_PROVIDER", "direct")
        monkeypatch.delenv("BENZINGA_MARKET_DATA_PROVIDER", raising=False)
        assert cal._market_data_uses_massive() is True


class TestDividendsRoutingDecoupled:
    def test_dividends_routes_through_massive_under_news_direct(self, monkeypatch) -> None:
        # News lane on direct + market-data env unset: fetch_dividends must call
        # the Massive reroute, not the retired direct api.benzinga.com path.
        monkeypatch.setenv("BENZINGA_PROVIDER", "direct")
        monkeypatch.delenv("BENZINGA_MARKET_DATA_PROVIDER", raising=False)

        sentinel = [{"ticker": "AAPL", "dividend": 0.25}]
        called: dict[str, object] = {}

        def _fake_massive_dividends(api_key, date_from, date_to, page_size):
            called["api_key"] = api_key
            return sentinel

        monkeypatch.setattr(cal, "_massive_dividends", _fake_massive_dividends)

        adapter = cal.BenzingaCalendarAdapter(api_key="massive-key")
        try:
            out = adapter.fetch_dividends(date_from="2026-07-01", date_to="2026-07-31")
        finally:
            adapter.close()

        assert out is sentinel
        assert called["api_key"] == "massive-key"

    def test_market_data_direct_override_takes_direct_calendar_path(self, monkeypatch) -> None:
        # Explicit override -> the direct _fetch_calendar path is taken instead
        # of the Massive reroute (proves the override actually gates routing).
        monkeypatch.setenv("BENZINGA_MARKET_DATA_PROVIDER", "direct")

        def _boom(*_a, **_k):
            raise AssertionError("Massive reroute must not run under direct override")

        monkeypatch.setattr(cal, "_massive_dividends", _boom)

        direct_rows = [{"ticker": "MSFT"}]
        captured: dict[str, object] = {}

        def _fake_fetch_calendar(self, endpoint, **kwargs):
            captured["endpoint"] = endpoint
            return direct_rows

        monkeypatch.setattr(cal.BenzingaCalendarAdapter, "_fetch_calendar", _fake_fetch_calendar)

        adapter = cal.BenzingaCalendarAdapter(api_key="k")
        try:
            out = adapter.fetch_dividends(date_from="2026-07-01", date_to="2026-07-31")
        finally:
            adapter.close()

        assert out is direct_rows
        assert captured["endpoint"] == "dividends"

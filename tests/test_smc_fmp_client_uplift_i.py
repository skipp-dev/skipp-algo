"""Coverage uplift bucket I — `scripts/smc_fmp_client.py`.

Targets the standalone FMP client's HTTP layer, parsing, and the long
tail of pipeline accessor methods that previously had no coverage:
retry behaviour, market-P/E discovery paths, sector performance
fallbacks, and the simple list/dict accessors.

All HTTP I/O is patched at module level (`urlopen`, `time.sleep`); no
network is touched.
"""

from __future__ import annotations

import io
import json
import math
import urllib.error
from datetime import UTC, date
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from scripts import smc_fmp_client as mod
from scripts.smc_fmp_client import (
    SMCFMPClient,
    _aggregate_sector_snapshot_rows,
    _coerce_finite_float,
    _prev_trading_day,
    _today_et,
)

# ── module-level helpers ───────────────────────────────────────


class TestCoerceFiniteFloat:
    def test_returns_none_for_bool(self):
        assert _coerce_finite_float(True) is None
        assert _coerce_finite_float(False) is None

    def test_returns_none_for_none_and_empty(self):
        assert _coerce_finite_float(None) is None
        assert _coerce_finite_float("") is None

    def test_returns_none_for_non_numeric_type(self):
        assert _coerce_finite_float([1.0]) is None
        assert _coerce_finite_float({"v": 1}) is None

    def test_returns_none_for_unparseable_string(self):
        assert _coerce_finite_float("not-a-number") is None

    def test_returns_none_for_inf_and_nan(self):
        assert _coerce_finite_float(math.inf) is None
        assert _coerce_finite_float(-math.inf) is None
        assert _coerce_finite_float(math.nan) is None

    def test_parses_int_float_and_string(self):
        assert _coerce_finite_float(3) == 3.0
        assert _coerce_finite_float(2.5) == 2.5
        assert _coerce_finite_float("4.25") == 4.25


class TestTodayEt:
    def test_today_et_returns_date(self):
        d = _today_et()
        assert isinstance(d, date)


class TestPrevTradingDay:
    def test_skips_weekend_from_monday_to_friday(self):
        # Monday → previous Friday
        monday = date(2026, 4, 20)
        assert _prev_trading_day(monday) == date(2026, 4, 17)

    def test_returns_previous_weekday_from_friday(self):
        friday = date(2026, 4, 17)
        assert _prev_trading_day(friday) == date(2026, 4, 16)

    def test_skips_saturday_and_sunday_from_sunday(self):
        sunday = date(2026, 4, 19)
        assert _prev_trading_day(sunday) == date(2026, 4, 17)


class TestAggregateSectorSnapshotRows:
    def test_skips_rows_without_sector(self):
        out = _aggregate_sector_snapshot_rows([{"sector": "", "averageChange": 1.0}, {"averageChange": 2.0}])
        assert out == []

    def test_skips_rows_without_numeric_change(self):
        out = _aggregate_sector_snapshot_rows([{"sector": "Tech", "averageChange": "junk"}])
        assert out == []

    def test_falls_back_to_changes_percentage(self):
        out = _aggregate_sector_snapshot_rows([{"sector": "Tech", "changesPercentage": 1.5}])
        assert out == [{"sector": "Tech", "changesPercentage": 1.5}]

    def test_averages_multiple_rows_per_sector(self):
        out = _aggregate_sector_snapshot_rows(
            [
                {"sector": "Tech", "averageChange": 1.0},
                {"sector": "Tech", "averageChange": 3.0},
                {"sector": "Energy", "averageChange": -1.0},
            ]
        )
        out_by_sector = {row["sector"]: row["changesPercentage"] for row in out}
        assert out_by_sector["Tech"] == pytest.approx(2.0)
        assert out_by_sector["Energy"] == pytest.approx(-1.0)


# ── HTTP layer (`_get`, `_parse`) ──────────────────────────────


def _make_response(payload: str) -> MagicMock:
    """Return a context-manager mock yielding a response with ``read()``."""
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = payload.encode("utf-8")
    cm.__exit__.return_value = False
    return cm


class TestParse:
    def test_parse_rejects_html_doctype(self):
        with pytest.raises(RuntimeError, match="HTML"):
            SMCFMPClient._parse("/x", "<!DOCTYPE html><html></html>")

    def test_parse_rejects_html_tag(self):
        with pytest.raises(RuntimeError, match="HTML"):
            SMCFMPClient._parse("/x", "<html><body>x</body></html>")

    def test_parse_raises_on_error_status(self):
        payload = json.dumps({"status": "error", "message": "bad key"})
        with pytest.raises(RuntimeError, match="bad key"):
            SMCFMPClient._parse("/x", payload)

    def test_parse_returns_normal_payload(self):
        out = SMCFMPClient._parse("/x", json.dumps([{"a": 1}]))
        assert out == [{"a": 1}]


class TestHttpGetRetry:
    def test_get_succeeds_first_try(self):
        c = SMCFMPClient(api_key="k")
        resp = _make_response(json.dumps([{"x": 1}]))
        with patch.object(mod, "urlopen", return_value=resp):
            out = c._get("/p", {"symbol": "AAPL"})
        assert out == [{"x": 1}]

    def test_get_retries_on_429_then_succeeds(self):
        c = SMCFMPClient(api_key="k", retry_attempts=3)
        err = urllib.error.HTTPError("u", 429, "rate", {}, io.BytesIO(b""))
        ok = _make_response(json.dumps([{"y": 2}]))
        with patch.object(mod, "urlopen", side_effect=[err, ok]), patch.object(mod.time, "sleep") as sleep_mock:
            out = c._get("/p", {})
        assert out == [{"y": 2}]
        assert sleep_mock.called

    def test_get_does_not_retry_on_404(self):
        c = SMCFMPClient(api_key="k", retry_attempts=3)
        err = urllib.error.HTTPError("u", 404, "missing", {}, io.BytesIO(b""))
        with patch.object(mod, "urlopen", side_effect=err), pytest.raises(RuntimeError, match="HTTP 404"):
            c._get("/p", {})

    def test_get_raises_after_http_retries_exhausted(self):
        c = SMCFMPClient(api_key="k", retry_attempts=2)
        err = urllib.error.HTTPError("u", 503, "down", {}, io.BytesIO(b""))
        with (
            patch.object(mod, "urlopen", side_effect=[err, err]),
            patch.object(mod.time, "sleep"),
            pytest.raises(RuntimeError, match="HTTP 503"),
        ):
            c._get("/p", {})

    def test_get_retries_url_error_then_succeeds(self):
        c = SMCFMPClient(api_key="k", retry_attempts=3)
        err = urllib.error.URLError("dns down")
        ok = _make_response(json.dumps({"z": 3}))
        with patch.object(mod, "urlopen", side_effect=[err, ok]), patch.object(mod.time, "sleep"):
            out = c._get("/p", {})
        assert out == {"z": 3}

    def test_get_raises_after_url_error_exhausted(self):
        c = SMCFMPClient(api_key="k", retry_attempts=2)
        err = urllib.error.URLError("dns down")
        with (
            patch.object(mod, "urlopen", side_effect=[err, err]),
            patch.object(mod.time, "sleep"),
            pytest.raises(RuntimeError, match="network error"),
        ):
            c._get("/p", {})

    def test_get_drops_none_params_and_injects_apikey(self):
        c = SMCFMPClient(api_key="MYKEY")
        resp = _make_response(json.dumps({}))
        with patch.object(mod, "urlopen", return_value=resp) as urlopen_mock:
            c._get("/p", {"symbol": "AAPL", "extra": None})
        called_request = urlopen_mock.call_args[0][0]
        full_url = called_request.full_url
        assert "apikey=MYKEY" in full_url
        assert "extra" not in full_url
        assert "symbol=AAPL" in full_url


# ── pipeline accessor methods ──────────────────────────────────


def _patch_get(client: SMCFMPClient, return_value: Any):
    return patch.object(client, "_get", return_value=return_value)


def _patch_get_raises(client: SMCFMPClient, exc: Exception):
    return patch.object(client, "_get", side_effect=exc)


class TestGetIndexQuote:
    def test_returns_dict_payload_directly(self):
        c = SMCFMPClient(api_key="k")
        with _patch_get(c, {"symbol": "VIX", "price": 12.3}):
            out = c.get_index_quote("^VIX")
        assert out == {"symbol": "VIX", "price": 12.3}

    def test_returns_matching_row_from_list(self):
        c = SMCFMPClient(api_key="k")
        rows = [{"symbol": "OTHER", "price": 1}, {"symbol": "AAPL", "price": 9}]
        with _patch_get(c, rows):
            out = c.get_index_quote("AAPL")
        assert out == {"symbol": "AAPL", "price": 9}

    def test_falls_back_to_first_dict_when_no_match(self):
        c = SMCFMPClient(api_key="k")
        with _patch_get(c, [{"symbol": "X", "price": 5}]):
            out = c.get_index_quote("AAPL")
        assert out == {"symbol": "X", "price": 5}

    def test_returns_empty_on_runtime_error(self):
        c = SMCFMPClient(api_key="k")
        with _patch_get_raises(c, RuntimeError("boom")):
            assert c.get_index_quote("AAPL") == {}

    def test_returns_empty_when_payload_is_garbage(self):
        c = SMCFMPClient(api_key="k")
        with _patch_get(c, "not-a-dict"):
            assert c.get_index_quote("AAPL") == {}


class TestGetCompanyProfile:
    def test_returns_empty_for_empty_symbol(self):
        c = SMCFMPClient(api_key="k")
        assert c.get_company_profile("") == {}

    def test_returns_dict_payload(self):
        c = SMCFMPClient(api_key="k")
        with _patch_get(c, {"symbol": "AAPL", "price": 100.0}):
            out = c.get_company_profile("aapl")
        assert out["symbol"] == "AAPL"

    def test_returns_matching_row_from_list(self):
        c = SMCFMPClient(api_key="k")
        rows = [{"symbol": "X", "price": 1}, {"symbol": "AAPL", "price": 2}]
        with _patch_get(c, rows):
            out = c.get_company_profile("AAPL")
        assert out == {"symbol": "AAPL", "price": 2}

    def test_falls_back_to_first_dict_when_no_match(self):
        c = SMCFMPClient(api_key="k")
        with _patch_get(c, [{"symbol": "X", "price": 1}]):
            out = c.get_company_profile("AAPL")
        assert out == {"symbol": "X", "price": 1}

    def test_returns_empty_on_runtime_error(self):
        c = SMCFMPClient(api_key="k")
        with _patch_get_raises(c, RuntimeError("boom")):
            assert c.get_company_profile("AAPL") == {}


class TestGetAnalystEstimates:
    def test_returns_empty_for_empty_symbol(self):
        c = SMCFMPClient(api_key="k")
        assert c.get_analyst_estimates("") == []

    def test_returns_list_payload(self):
        c = SMCFMPClient(api_key="k")
        with _patch_get(c, [{"epsAvg": 1.0}, {"epsAvg": 2.0}]):
            out = c.get_analyst_estimates("AAPL", limit=2)
        assert len(out) == 2

    def test_clamps_limit_to_minimum_of_one(self):
        c = SMCFMPClient(api_key="k")
        with patch.object(c, "_get", return_value=[]) as get_mock:
            c.get_analyst_estimates("AAPL", limit=0)
        assert get_mock.call_args[0][1]["limit"] == 1

    def test_uses_default_period_when_blank(self):
        c = SMCFMPClient(api_key="k")
        with patch.object(c, "_get", return_value=[]) as get_mock:
            c.get_analyst_estimates("AAPL", period="   ")
        assert get_mock.call_args[0][1]["period"] == "annual"

    def test_default_period_is_annual(self):
        c = SMCFMPClient(api_key="k")
        with patch.object(c, "_get", return_value=[]) as get_mock:
            c.get_analyst_estimates("AAPL")
        assert get_mock.call_args[0][1]["period"] == "annual"

    def test_period_quarter_normalised_to_quarterly(self):
        c = SMCFMPClient(api_key="k")
        with patch.object(c, "_get", return_value=[]) as get_mock:
            c.get_analyst_estimates("AAPL", period="quarter")
        assert get_mock.call_args[0][1]["period"] == "quarterly"

    def test_period_quarterly_passthrough(self):
        c = SMCFMPClient(api_key="k")
        with patch.object(c, "_get", return_value=[]) as get_mock:
            c.get_analyst_estimates("AAPL", period="Quarterly")
        assert get_mock.call_args[0][1]["period"] == "quarterly"

    def test_returns_empty_on_runtime_error(self):
        c = SMCFMPClient(api_key="k")
        with _patch_get_raises(c, RuntimeError("boom")):
            assert c.get_analyst_estimates("AAPL") == []


class TestGetRatiosTtm:
    def test_returns_empty_for_empty_symbol(self):
        c = SMCFMPClient(api_key="k")
        assert c.get_ratios_ttm("") == []

    def test_returns_list_payload(self):
        c = SMCFMPClient(api_key="k")
        with _patch_get(c, [{"pe": 25.0}]):
            assert c.get_ratios_ttm("AAPL") == [{"pe": 25.0}]

    def test_returns_empty_on_runtime_error(self):
        c = SMCFMPClient(api_key="k")
        with _patch_get_raises(c, RuntimeError("boom")):
            assert c.get_ratios_ttm("AAPL") == []

    def test_returns_empty_when_payload_is_dict(self):
        c = SMCFMPClient(api_key="k")
        with _patch_get(c, {"pe": 25.0}):
            assert c.get_ratios_ttm("AAPL") == []


class TestGetKeyMetricsTtm:
    def test_returns_empty_for_empty_symbol(self):
        c = SMCFMPClient(api_key="k")
        assert c.get_key_metrics_ttm("") == []

    def test_returns_list_payload(self):
        c = SMCFMPClient(api_key="k")
        with _patch_get(c, [{"marketCap": 1e12}]):
            assert c.get_key_metrics_ttm("AAPL") == [{"marketCap": 1e12}]

    def test_returns_empty_on_runtime_error(self):
        c = SMCFMPClient(api_key="k")
        with _patch_get_raises(c, RuntimeError("boom")):
            assert c.get_key_metrics_ttm("AAPL") == []


# ── market-P/E forward (the largest uncovered block) ──────────


class TestGetMarketPeForward:
    def test_uses_fallback_symbols_when_no_symbol_passed(self):
        c = SMCFMPClient(api_key="k")
        with (
            patch.object(c, "get_index_quote", return_value={"forwardPE": 21.5, "price": 500.0}),
            patch.object(c, "get_company_profile", return_value={}),
            patch.object(c, "get_ratios_ttm", return_value=[]),
            patch.object(c, "get_key_metrics_ttm", return_value=[]),
            patch.object(c, "get_analyst_estimates", return_value=[]),
        ):
            out = c.get_market_pe_forward()
        assert out == 21.5
        diag = c._last_market_pe_forward_diagnostics
        assert diag["status"] == "ok"
        assert diag["source_category"] == "direct_forward"
        assert diag["field"] == "forwardPE"
        assert "SPY" in diag["attempted_symbols"]

    def test_explicit_symbol_only_attempts_that_symbol(self):
        c = SMCFMPClient(api_key="k")
        with (
            patch.object(c, "get_index_quote", return_value={"price": 100.0, "forwardPE": 18.0}),
            patch.object(c, "get_company_profile", return_value={}),
            patch.object(c, "get_ratios_ttm", return_value=[]),
            patch.object(c, "get_key_metrics_ttm", return_value=[]),
            patch.object(c, "get_analyst_estimates", return_value=[]),
        ):
            out = c.get_market_pe_forward("aapl")
        assert out == 18.0
        diag = c._last_market_pe_forward_diagnostics
        assert diag["attempted_symbols"] == ["AAPL"]
        assert diag["symbol"] == "AAPL"

    def test_records_error_status_when_underlying_call_raises(self):
        c = SMCFMPClient(api_key="k")
        with patch.object(c, "get_index_quote", side_effect=RuntimeError("net down")):
            out = c.get_market_pe_forward("SPY")
        assert out is None
        diag = c._last_market_pe_forward_diagnostics
        assert diag["status"] == "error"
        assert "net down" in diag["error"]

    def test_analyst_derived_path_when_no_direct_pe(self):
        c = SMCFMPClient(api_key="k")
        analyst_rows = [
            {"epsAvg": 1.0},
            {"epsAvg": 2.0},
            {"epsAvg": 3.0},
            {"epsAvg": 4.0},
        ]
        with (
            patch.object(c, "get_index_quote", return_value={"price": 100.0}),
            patch.object(c, "get_company_profile", return_value={}),
            patch.object(c, "get_ratios_ttm", return_value=[]),
            patch.object(c, "get_key_metrics_ttm", return_value=[]),
            patch.object(c, "get_analyst_estimates", return_value=analyst_rows),
        ):
            out = c.get_market_pe_forward("SPY")
        assert out == pytest.approx(10.0)  # 100 / (1+2+3+4)
        diag = c._last_market_pe_forward_diagnostics
        assert diag["source_category"] == "analyst_derived"
        assert diag["estimate_count"] == 4
        assert diag["field"] == "epsAvg"

    def test_falls_back_to_approximate_ttm(self):
        c = SMCFMPClient(api_key="k")
        with (
            patch.object(c, "get_index_quote", return_value={"price": 100.0}),
            patch.object(c, "get_company_profile", return_value={}),
            patch.object(c, "get_ratios_ttm", return_value=[{"pe": 17.5}]),
            patch.object(c, "get_key_metrics_ttm", return_value=[]),
            patch.object(c, "get_analyst_estimates", return_value=[]),
        ):
            out = c.get_market_pe_forward("SPY")
        assert out == 17.5
        diag = c._last_market_pe_forward_diagnostics
        assert diag["source_category"] == "approximate_ttm"
        assert diag["field"] == "pe"

    def test_returns_none_when_nothing_resolves(self):
        c = SMCFMPClient(api_key="k")
        with (
            patch.object(c, "get_index_quote", return_value={}),
            patch.object(c, "get_company_profile", return_value={}),
            patch.object(c, "get_ratios_ttm", return_value=[]),
            patch.object(c, "get_key_metrics_ttm", return_value=[]),
            patch.object(c, "get_analyst_estimates", return_value=[]),
        ):
            out = c.get_market_pe_forward()
        assert out is None
        diag = c._last_market_pe_forward_diagnostics
        assert diag["status"] == "unavailable"

    def test_uses_previous_close_when_price_missing(self):
        c = SMCFMPClient(api_key="k")
        with (
            patch.object(c, "get_index_quote", return_value={"previousClose": 50.0}),
            patch.object(c, "get_company_profile", return_value={}),
            patch.object(c, "get_ratios_ttm", return_value=[]),
            patch.object(c, "get_key_metrics_ttm", return_value=[]),
            patch.object(
                c,
                "get_analyst_estimates",
                return_value=[{"epsAvg": 1.0}] * 4,
            ),
        ):
            out = c.get_market_pe_forward("SPY")
        assert out == pytest.approx(12.5)


# ── sector performance (multi-day fallback loop) ───────────────


class TestGetSectorPerformance:
    def test_returns_rows_on_first_attempt(self):
        c = SMCFMPClient(api_key="k")
        rows = [{"sector": "Tech", "averageChange": 1.0}]
        with patch.object(c, "_get", return_value=rows):
            out = c.get_sector_performance()
        assert out and out[0]["sector"] == "Tech"
        diag = c._last_sector_performance_diagnostics
        assert diag["status"] == "ok"
        assert diag["used_fallback_previous_trading_day"] is False
        assert diag["raw_row_count"] == 1
        assert diag["returned_row_count"] == 1

    def test_falls_back_to_previous_trading_day(self):
        c = SMCFMPClient(api_key="k")
        rows = [{"sector": "Tech", "averageChange": 1.0}]
        # First attempt empty, second returns rows
        with patch.object(c, "_get", side_effect=[[], rows]):
            out = c.get_sector_performance()
        assert out
        diag = c._last_sector_performance_diagnostics
        assert diag["used_fallback_previous_trading_day"] is True
        assert len(diag["attempted_dates"]) == 2

    def test_returns_empty_when_all_attempts_empty(self):
        c = SMCFMPClient(api_key="k")
        with patch.object(c, "_get", return_value=[]):
            out = c.get_sector_performance()
        assert out == []
        diag = c._last_sector_performance_diagnostics
        assert diag["status"] == "empty"
        assert len(diag["attempted_dates"]) == 6

    def test_records_error_status_on_runtime_error(self):
        c = SMCFMPClient(api_key="k")
        with patch.object(c, "_get", side_effect=RuntimeError("rate limited")):
            out = c.get_sector_performance()
        assert out == []
        diag = c._last_sector_performance_diagnostics
        assert diag["status"] == "error"
        assert "rate limited" in diag["error"]


# ── simple list/dict accessors ─────────────────────────────────


class TestGetStockLatestNews:
    def test_returns_list_with_symbol_param(self):
        c = SMCFMPClient(api_key="k")
        with patch.object(c, "_get", return_value=[{"title": "x"}]) as get_mock:
            out = c.get_stock_latest_news(symbol="aapl", limit=10)
        assert out == [{"title": "x"}]
        assert get_mock.call_args[0][1]["symbol"] == "AAPL"
        assert get_mock.call_args[0][1]["limit"] == 10

    def test_returns_list_without_symbol(self):
        c = SMCFMPClient(api_key="k")
        with patch.object(c, "_get", return_value=[]) as get_mock:
            out = c.get_stock_latest_news()
        assert out == []
        assert "symbol" not in get_mock.call_args[0][1]

    def test_returns_empty_on_runtime_error(self):
        c = SMCFMPClient(api_key="k")
        with patch.object(c, "_get", side_effect=RuntimeError("boom")):
            assert c.get_stock_latest_news() == []


class TestGetEarningsCalendar:
    def test_returns_list_payload(self):
        c = SMCFMPClient(api_key="k")
        rows = [{"symbol": "AAPL", "date": "2026-04-25"}]
        with patch.object(c, "_get", return_value=rows):
            out = c.get_earnings_calendar(date(2026, 4, 20), date(2026, 4, 25))
        assert out == rows

    def test_returns_empty_on_runtime_error(self):
        c = SMCFMPClient(api_key="k")
        with patch.object(c, "_get", side_effect=RuntimeError("x")):
            out = c.get_earnings_calendar(date(2026, 4, 20), date(2026, 4, 25))
        assert out == []


class TestGetMacroCalendar:
    def test_records_ok_diagnostics_on_success(self):
        c = SMCFMPClient(api_key="k")
        rows = [{"event": "CPI"}]
        with patch.object(c, "_get", return_value=rows):
            out = c.get_macro_calendar(date(2026, 4, 20), date(2026, 4, 25))
        assert out == rows
        diag = c._last_macro_calendar_diagnostics
        assert diag["status"] == "ok"
        assert diag["returned_row_count"] == 1

    def test_records_error_diagnostics_on_runtime_error(self):
        c = SMCFMPClient(api_key="k")
        with patch.object(c, "_get", side_effect=RuntimeError("dead")):
            out = c.get_macro_calendar(date(2026, 4, 20), date(2026, 4, 25))
        assert out == []
        diag = c._last_macro_calendar_diagnostics
        assert diag["status"] == "error"
        assert "dead" in diag["error"]


class TestGetTreasuryYields:
    def test_returns_yields_and_inversion(self):
        c = SMCFMPClient(api_key="k")
        with patch.object(c, "_get", return_value=[{"year2": 5.0, "year10": 4.0}]) as get_mock:
            out = c.get_treasury_yields()
        # Lane 1: must hit /stable/treasury-rates, NOT the retired /stable/treasury.
        assert get_mock.call_args[0][0] == "/stable/treasury-rates"
        # Lane 6: must use a multi-day window (not from==to==today) so
        # that weekends and US market holidays don't silently degrade
        # to zero yields. 7-day window covers up to a 4-day Thanksgiving
        # closure plus weekend.
        params = get_mock.call_args[0][1]
        from datetime import date as _date
        d_from = _date.fromisoformat(params["from"])
        d_to = _date.fromisoformat(params["to"])
        assert (d_to - d_from).days >= 3
        assert out == {"2y": 5.0, "10y": 4.0, "spread": -1.0, "inverted": True}

    def test_returns_zero_fallback_on_exception(self):
        c = SMCFMPClient(api_key="k")
        with patch.object(c, "_get", side_effect=RuntimeError("x")):
            out = c.get_treasury_yields()
        assert out == {"2y": 0.0, "10y": 0.0, "spread": 0.0, "inverted": False}

    def test_returns_zero_fallback_when_payload_is_empty(self):
        c = SMCFMPClient(api_key="k")
        with patch.object(c, "_get", return_value=[]):
            out = c.get_treasury_yields()
        assert out["2y"] == 0.0
        assert out["inverted"] is False


class TestGetInstitutionalHolders:
    def test_returns_legacy_shape_from_summary_endpoint(self):
        c = SMCFMPClient(api_key="k")
        payload = [{"numberOf13Fshares": 100, "lastNumberOf13Fshares": 80}]
        with patch.object(c, "_get", return_value=payload) as get_mock:
            out = c.get_institutional_holders("AAPL")
        # Lane 1: must hit the new summary endpoint, not the retired one.
        assert (
            get_mock.call_args[0][0]
            == "/stable/institutional-ownership/symbol-positions-summary"
        )
        # Caller compatibility: aggregated row is mapped to a single-element
        # list with legacy `shares`/`previousShares` field names.
        assert out == [{"shares": 100, "previousShares": 80}]

    def test_walks_back_quarters_until_data_found(self):
        c = SMCFMPClient(api_key="k")
        call_count = {"n": 0}

        def fake_get(path, params):
            call_count["n"] += 1
            if call_count["n"] < 3:
                return []
            return [{"numberOf13Fshares": 50, "lastNumberOf13Fshares": 40}]

        with patch.object(c, "_get", side_effect=fake_get):
            out = c.get_institutional_holders("AAPL")
        assert call_count["n"] == 3
        assert out == [{"shares": 50, "previousShares": 40}]

    def test_returns_empty_for_blank_symbol(self):
        c = SMCFMPClient(api_key="k")
        assert c.get_institutional_holders("") == []

    def test_returns_empty_when_no_quarter_has_data(self):
        c = SMCFMPClient(api_key="k")
        with patch.object(c, "_get", return_value=[]):
            assert c.get_institutional_holders("AAPL") == []

    def test_returns_empty_on_exception(self):
        c = SMCFMPClient(api_key="k")
        with patch.object(c, "_get", side_effect=RuntimeError("x")):
            assert c.get_institutional_holders("AAPL") == []


class TestGetInsiderTrading:
    def test_returns_list_payload(self):
        c = SMCFMPClient(api_key="k")
        with patch.object(c, "_get", return_value=[{"name": "x"}]) as get_mock:
            out = c.get_insider_trading("AAPL", limit=5)
        # Lane 1: must hit /stable/insider-trading/search, not the retired path.
        assert get_mock.call_args[0][0] == "/stable/insider-trading/search"
        assert out == [{"name": "x"}]
        assert get_mock.call_args[0][1]["limit"] == 5

    def test_returns_empty_for_blank_symbol(self):
        c = SMCFMPClient(api_key="k")
        assert c.get_insider_trading("") == []

    def test_returns_empty_on_exception(self):
        c = SMCFMPClient(api_key="k")
        with patch.object(c, "_get", side_effect=RuntimeError("x")):
            assert c.get_insider_trading("AAPL") == []


class TestGetTechnicalIndicator:
    def test_returns_dict_payload(self):
        c = SMCFMPClient(api_key="k")
        with patch.object(c, "_get", return_value={"rsi": 55.0}):
            out = c.get_technical_indicator("aapl", "1day", "rsi")
        assert out == {"rsi": 55.0}

    def test_returns_first_dict_from_list(self):
        c = SMCFMPClient(api_key="k")
        with patch.object(c, "_get", return_value=[{"ema": 100.0}, {"ema": 99.0}]):
            out = c.get_technical_indicator("AAPL", "1day", "ema")
        assert out == {"ema": 100.0}

    def test_passes_period_when_provided(self):
        c = SMCFMPClient(api_key="k")
        with patch.object(c, "_get", return_value={}) as get_mock:
            c.get_technical_indicator("AAPL", "1day", "ema", indicator_period=20)
        assert get_mock.call_args[0][1]["periodLength"] == 20

    def test_returns_empty_on_runtime_error(self):
        c = SMCFMPClient(api_key="k")
        with patch.object(c, "_get", side_effect=RuntimeError("x")):
            assert c.get_technical_indicator("AAPL", "1day", "ema") == {}

    def test_returns_empty_when_payload_is_garbage(self):
        c = SMCFMPClient(api_key="k")
        with patch.object(c, "_get", return_value="not-useful"):
            assert c.get_technical_indicator("AAPL", "1day", "ema") == {}


class TestSilentFallbackLoggingLane5:
    """Lane 5: silent provider-boundary degradations must surface in logs.

    Methods that swallow ``RuntimeError`` from ``_get`` and return an
    empty result MUST emit exactly one ``logger.warning`` per
    (endpoint, exception-type) per process via
    ``_log_endpoint_failure_once``.
    """

    def setup_method(self):
        # Reset the module-level dedupe set so each test starts fresh.
        from scripts.smc_fmp_client import _LOGGED_SILENT_FAILURES
        _LOGGED_SILENT_FAILURES.clear()

    @pytest.mark.parametrize(
        "method_name,args,kwargs,expected_endpoint",
        [
            ("get_index_quote", ("^VIX",), {}, "/stable/quote"),
            ("get_company_profile", ("AAPL",), {}, "/stable/profile"),
            ("get_analyst_estimates", ("AAPL",), {}, "/stable/analyst-estimates"),
            ("get_ratios_ttm", ("AAPL",), {}, "/stable/ratios-ttm"),
            ("get_key_metrics_ttm", ("AAPL",), {}, "/stable/key-metrics-ttm"),
            ("get_stock_latest_news", (), {}, "/stable/news/stock-latest"),
            ("get_insider_trading", ("AAPL",), {}, "/stable/insider-trading/search"),
            ("get_technical_indicator", ("AAPL", "1day", "ema"), {},
             "/stable/technical-indicators/ema"),
        ],
    )
    def test_method_logs_one_shot_warning_on_silent_fallback(
        self, caplog, method_name, args, kwargs, expected_endpoint,
    ):
        import logging
        c = SMCFMPClient(api_key="k")
        with patch.object(c, "_get", side_effect=RuntimeError("boom")), caplog.at_level(logging.WARNING, logger="scripts.smc_fmp_client"):
            getattr(c, method_name)(*args, **kwargs)
            # Call again; warning must NOT be re-logged.
            getattr(c, method_name)(*args, **kwargs)
        msgs = [r.message for r in caplog.records if "degraded silently" in r.message]
        assert len(msgs) == 1, msgs
        assert expected_endpoint in msgs[0]

    def test_treasury_yields_logs_on_failure(self, caplog):
        import logging
        c = SMCFMPClient(api_key="k")
        with patch.object(c, "_get", side_effect=RuntimeError("boom")), caplog.at_level(logging.WARNING, logger="scripts.smc_fmp_client"):
            out = c.get_treasury_yields()
        assert out == {"2y": 0.0, "10y": 0.0, "spread": 0.0, "inverted": False}
        assert any("/stable/treasury-rates" in r.message for r in caplog.records)

    def test_institutional_holders_logs_on_failure(self, caplog):
        import logging
        c = SMCFMPClient(api_key="k")
        with patch.object(c, "_get", side_effect=RuntimeError("boom")), caplog.at_level(logging.WARNING, logger="scripts.smc_fmp_client"):
            out = c.get_institutional_holders("AAPL")
        assert out == []
        # The walk-back loop runs up to 4 quarters, but the dedupe means
        # only ONE warning is emitted across all iterations.
        msgs = [r.message for r in caplog.records if "symbol-positions-summary" in r.message]
        assert len(msgs) == 1


class TestRetryAfterHygieneLane9:
    """Lane 9 (provider-boundary audit, 2026-04-27): when FMP returns
    ``Retry-After`` (typically on HTTP 429), ``_get`` must wait at least
    the suggested duration before the next retry, capped at 60s so a
    misconfigured ``Retry-After: 86400`` cannot wedge the CLI for a day.
    """

    def test_parse_retry_after_accepts_seconds_form(self):
        from scripts.smc_fmp_client import _parse_retry_after_seconds
        assert _parse_retry_after_seconds("0") == 0.0
        assert _parse_retry_after_seconds("12") == 12.0
        assert _parse_retry_after_seconds("12.5") == 12.5

    def test_parse_retry_after_accepts_http_date_form(self):
        from datetime import datetime, timedelta

        from scripts.smc_fmp_client import _parse_retry_after_seconds
        future = datetime.now(UTC) + timedelta(seconds=30)
        # RFC 9110 §10.2.3 HTTP-date format
        from email.utils import format_datetime
        out = _parse_retry_after_seconds(format_datetime(future, usegmt=True))
        assert out is not None
        assert 25 <= out <= 35  # tolerance for clock skew

    def test_parse_retry_after_returns_none_for_garbage(self):
        from scripts.smc_fmp_client import _parse_retry_after_seconds
        for v in (None, "", "not-a-date", object()):
            assert _parse_retry_after_seconds(v) is None

    def test_parse_retry_after_clamps_negative_to_zero(self):
        from scripts.smc_fmp_client import _parse_retry_after_seconds
        assert _parse_retry_after_seconds("-5") == 0.0
        from datetime import datetime, timedelta
        from email.utils import format_datetime
        past = datetime.now(UTC) - timedelta(seconds=30)
        assert _parse_retry_after_seconds(format_datetime(past, usegmt=True)) == 0.0

    def test_get_honors_retry_after_seconds_hint(self, monkeypatch):
        """A 429 with ``Retry-After: 7`` must cause _get to sleep at
        least 7 seconds before the second attempt."""
        import urllib.error

        import scripts.smc_fmp_client as mod

        sleeps: list[float] = []
        monkeypatch.setattr(mod.time, "sleep", lambda d: sleeps.append(d))

        attempts = {"n": 0}
        class _FakeHeaders:
            def get(self, key, default=None):
                return "7" if key == "Retry-After" else default

        def fake_urlopen(*args, **kwargs):
            attempts["n"] += 1
            if attempts["n"] == 1:
                err = urllib.error.HTTPError(
                    url="x", code=429, msg="Too Many", hdrs=_FakeHeaders(), fp=None,
                )
                err.headers = _FakeHeaders()
                raise err
            class _Resp:
                def __enter__(self): return self
                def __exit__(self, *a): return False
                def read(self): return b'[{"ok": 1}]'
            return _Resp()

        monkeypatch.setattr(mod, "urlopen", fake_urlopen)
        # Pin the resilient decorator's full-jitter RNG so the slept
        # value is deterministic. ``_get`` passes ``rng=random.random``
        # to ``resilient`` (looked up at call time), so monkeypatching
        # ``random.random`` here flows through.
        import random as _random
        monkeypatch.setattr(_random, "random", lambda: 1.0)
        c = SMCFMPClient(api_key="k", retry_attempts=2)
        out = c._get("/stable/quote", {"symbol": "AAPL"})

        assert out == [{"ok": 1}]
        assert attempts["n"] == 2
        # The decorator's own backoff caps at base_delay*rng() ≤ 0.5s,
        # so anything ≥ 7s came from the Retry-After hint.
        assert any(d >= 7.0 for d in sleeps), sleeps

    def test_get_caps_pathological_retry_after_at_60s(self, monkeypatch):
        """A misconfigured ``Retry-After: 86400`` must NOT wedge the
        client for a full day — the cap is 60s."""
        import urllib.error

        import scripts.smc_fmp_client as mod

        sleeps: list[float] = []
        monkeypatch.setattr(mod.time, "sleep", lambda d: sleeps.append(d))

        class _FakeHeaders:
            def get(self, key, default=None):
                return "86400" if key == "Retry-After" else default

        attempts = {"n": 0}
        def fake_urlopen(*args, **kwargs):
            attempts["n"] += 1
            if attempts["n"] == 1:
                err = urllib.error.HTTPError(
                    url="x", code=429, msg="Too Many", hdrs=_FakeHeaders(), fp=None,
                )
                err.headers = _FakeHeaders()
                raise err
            class _Resp:
                def __enter__(self): return self
                def __exit__(self, *a): return False
                def read(self): return b"[]"
            return _Resp()

        monkeypatch.setattr(mod, "urlopen", fake_urlopen)
        # Pin the jitter RNG so the asserted bound is deterministic.
        import random as _random
        monkeypatch.setattr(_random, "random", lambda: 1.0)
        c = SMCFMPClient(api_key="k", retry_attempts=2)
        c._get("/stable/quote", {"symbol": "AAPL"})

        # All slept values must be <= 60s.
        assert sleeps and all(d <= 60.0 for d in sleeps), sleeps

    def test_get_honors_retry_after_even_when_jitter_rng_is_zero(self, monkeypatch):
        """Regression: with ``random.random() == 0.0`` the full-jitter
        delay would be 0 and ``@resilient`` would skip ``sleep`` —
        silently dropping any ``Retry-After`` hint. The client must
        route the hint through ``delay_from_exc`` so it survives the
        ``delay > 0`` gate."""
        import urllib.error

        import scripts.smc_fmp_client as mod

        sleeps: list[float] = []
        monkeypatch.setattr(mod.time, "sleep", lambda d: sleeps.append(d))

        attempts = {"n": 0}
        class _FakeHeaders:
            def get(self, key, default=None):
                return "5" if key == "Retry-After" else default

        def fake_urlopen(*args, **kwargs):
            attempts["n"] += 1
            if attempts["n"] == 1:
                err = urllib.error.HTTPError(
                    url="x", code=429, msg="Too Many", hdrs=_FakeHeaders(), fp=None,
                )
                err.headers = _FakeHeaders()
                raise err
            class _Resp:
                def __enter__(self): return self
                def __exit__(self, *a): return False
                def read(self): return b"[]"
            return _Resp()

        monkeypatch.setattr(mod, "urlopen", fake_urlopen)
        # Pin jitter RNG to exactly 0.0 — the worst-case path that
        # previously skipped ``sleep`` entirely under the old
        # closure-based ``_sleep`` design.
        import random as _random
        monkeypatch.setattr(_random, "random", lambda: 0.0)
        c = SMCFMPClient(api_key="k", retry_attempts=2)
        c._get("/stable/quote", {"symbol": "AAPL"})

        assert attempts["n"] == 2
        # Retry-After=5 must still produce a >=5s sleep even though
        # ``capped * rng()`` would have been 0.
        assert sleeps and any(d >= 5.0 for d in sleeps), sleeps

    def test_parse_retry_after_returns_none_for_nan_and_inf(self):
        """Regression: ``time.sleep(nan)`` raises ValueError on CPython.

        Garbage float-strings like ``"NaN"`` / ``"inf"`` must therefore
        be treated as "no hint" so the caller falls through to the
        default exponential backoff.
        """
        from scripts.smc_fmp_client import _parse_retry_after_seconds
        for v in ("NaN", "nan", "inf", "+inf", "-inf", "Infinity", "-Infinity"):
            assert _parse_retry_after_seconds(v) is None, v

"""Tests proving the v5 pipeline runs without importing open_prep.

Validates:
- SMCFMPClient is method-compatible with the provider-policy adapters
- build_enrichment() never imports open_prep (including event-risk path)
- The standalone client handles errors identically to the original
- All v5 canonical modules are open_prep-free
"""

from __future__ import annotations

import importlib
import sys
import types
from datetime import date
from typing import Any
from unittest.mock import patch

import pytest

from scripts.smc_fmp_client import SMCFMPClient

# ── 1. SMCFMPClient surface ────────────────────────────────────


class TestSMCFMPClientInterface:
    """The standalone client exposes the core adapter methods plus market-P/E support."""

    def test_has_get_index_quote(self):
        c = SMCFMPClient(api_key="test")
        assert callable(c.get_index_quote)

    def test_has_get_sector_performance(self):
        c = SMCFMPClient(api_key="test")
        assert callable(c.get_sector_performance)

    def test_has_get_stock_latest_news(self):
        c = SMCFMPClient(api_key="test")
        assert callable(c.get_stock_latest_news)

    def test_has_get_earnings_calendar(self):
        c = SMCFMPClient(api_key="test")
        assert callable(c.get_earnings_calendar)

    def test_has_get_macro_calendar(self):
        c = SMCFMPClient(api_key="test")
        assert callable(c.get_macro_calendar)

    def test_has_get_technical_indicator(self):
        c = SMCFMPClient(api_key="test")
        assert callable(c.get_technical_indicator)

    def test_has_get_market_pe_forward(self):
        c = SMCFMPClient(api_key="test")
        assert callable(c.get_market_pe_forward)

    def test_has_get_key_metrics_ttm(self):
        c = SMCFMPClient(api_key="test")
        assert callable(c.get_key_metrics_ttm)

    def test_default_retry_and_timeout(self):
        c = SMCFMPClient(api_key="k")
        assert c.retry_attempts == 2
        assert c.timeout_seconds == 12.0

    def test_get_uses_resilient_decorator(self):
        """E-3 migration regression guard.

        ``_get`` constructs a ``@resilient`` wrapper per call. Verifies
        the wiring exists (``smc_core.resilient`` is imported and the
        wrapper exposes the introspection attribute) so a regression
        cannot silently revert to the hand-rolled retry loop.
        """
        import scripts.smc_fmp_client as mod
        from smc_core.resilient import resilient as _resilient_marker

        assert mod.resilient is _resilient_marker
        # Wrapping is per-call; confirm by patching urlopen and
        # capturing the ``__resilient__`` attribute that the decorator
        # attaches to the wrapper.
        captured: dict[str, object] = {}
        original_resilient = mod.resilient

        def _spy_resilient(**kwargs):
            decorator = original_resilient(**kwargs)

            def _wrap(func):
                wrapped = decorator(func)
                captured["config"] = wrapped.__resilient__  # type: ignore[attr-defined]
                return wrapped

            return _wrap

        c = SMCFMPClient(api_key="k", retry_attempts=3)
        with patch.object(mod, "resilient", side_effect=_spy_resilient), \
             patch.object(mod, "urlopen", side_effect=RuntimeError("stop")), pytest.raises(RuntimeError):
            c._get("/any", {})
        assert captured["config"]["retries"] == 2  # retry_attempts=3 → 2 extras
        assert captured["config"]["base_delay"] == 0.5
        # Bumped from 4.0 to 60.0 in PR #379 so honored ``Retry-After``
        # hints (which the FMP rate-limiter routinely sets to 30-60s)
        # survive the ``min(hint, max_delay)`` cap in @resilient.
        assert captured["config"]["max_delay"] == 60.0


# ── 2. No open_prep at runtime ─────────────────────────────────


class TestNoOpenPrepImport:
    """The v4 pipeline path never touches open_prep."""

    def test_smc_fmp_client_has_no_open_prep_imports(self):
        """The standalone client module has no import of open_prep."""
        import scripts.smc_fmp_client as mod

        src = importlib.util.find_spec(mod.__name__)
        assert src is not None and src.origin is not None
        with open(src.origin, encoding="utf-8") as _f:
            source = _f.read()
        # Check that no import statement references open_prep
        import re
        import_lines = re.findall(r"^\s*(from|import)\s+.*open_prep.*", source, re.MULTILINE)
        assert import_lines == [], f"Found open_prep imports: {import_lines}"

    def test_make_fmp_client_uses_smc_fmp_client(self):
        """_make_fmp_client imports SMCFMPClient, not open_prep.macro."""
        from scripts.generate_smc_micro_base_from_databento import _make_fmp_client

        client = _make_fmp_client("test-key")
        assert type(client).__name__ == "SMCFMPClient"
        assert type(client).__module__ == "scripts.smc_fmp_client"

    def test_build_enrichment_without_open_prep(self):
        """build_enrichment can run with open_prep completely absent."""
        from scripts.smc_provider_policy import ProviderResult

        def _mock_resolve(domain, **kw):
            return ProviderResult(data={"regime": "NEUTRAL"}, provider="fmp")

        # Temporarily remove open_prep from sys.modules and block re-import
        saved = {}
        for key in list(sys.modules):
            if key == "open_prep" or key.startswith("open_prep."):
                saved[key] = sys.modules.pop(key)

        blocker = _ImportBlocker("open_prep")
        sys.meta_path.insert(0, blocker)
        try:
            with patch("scripts.smc_provider_policy.resolve_domain", side_effect=_mock_resolve):
                from scripts.generate_smc_micro_base_from_databento import build_enrichment

                result = build_enrichment(
                    fmp_api_key="test",
                    symbols=["AAPL"],
                    enrich_regime=True,
                )
                assert result is not None
                assert result["providers"]["provider_count"] == 2
        finally:
            sys.meta_path.remove(blocker)
            sys.modules.update(saved)

    def test_build_enrichment_event_risk_without_open_prep(self):
        """build_enrichment with enrich_event_risk=True works without open_prep."""
        from scripts.smc_provider_policy import ProviderResult

        def _mock_resolve(domain, **kw):
            if domain == "calendar":
                return ProviderResult(
                    data={"earnings_today_tickers": "AAPL",
                          "high_impact_macro_today": False},
                    provider="fmp",
                )
            if domain == "news":
                return ProviderResult(
                    data={"bullish_tickers": [], "bearish_tickers": [],
                          "neutral_tickers": [], "news_heat_global": 0.0,
                          "ticker_heat_map": ""},
                    provider="fmp",
                )
            return ProviderResult(data={"regime": "NEUTRAL"}, provider="fmp")

        saved = {}
        for key in list(sys.modules):
            if key == "open_prep" or key.startswith("open_prep."):
                saved[key] = sys.modules.pop(key)

        blocker = _ImportBlocker("open_prep")
        sys.meta_path.insert(0, blocker)
        try:
            with patch("scripts.smc_provider_policy.resolve_domain", side_effect=_mock_resolve):
                from scripts.generate_smc_micro_base_from_databento import build_enrichment

                result = build_enrichment(
                    fmp_api_key="test",
                    symbols=["AAPL"],
                    enrich_regime=True,
                    enrich_news=True,
                    enrich_calendar=True,
                    enrich_event_risk=True,
                )
                assert result is not None
                assert "event_risk" in result
                assert result["event_risk"]["EVENT_PROVIDER_STATUS"] == "ok"
                assert result["providers"]["event_risk_provider"] == "smc_event_risk_builder"
        finally:
            sys.meta_path.remove(blocker)
            sys.modules.update(saved)

    def test_provider_policy_has_no_open_prep_imports(self):
        """smc_provider_policy.py never references open_prep."""
        import scripts.smc_provider_policy as mod

        src = importlib.util.find_spec(mod.__name__)
        assert src is not None and src.origin is not None
        with open(src.origin, encoding="utf-8") as _f:
            source = _f.read()
        assert "open_prep" not in source


# ── 2b. Canonical v4 modules contain no open_prep imports ──────

# These are the canonical runtime modules the v5 doc requires to be
# open_prep-free, plus all smc_core / smc_integration packages.

_V5_CANONICAL_MODULES = [
    "scripts.smc_macro_bias",
    "scripts.smc_regime_classifier",
    "scripts.smc_news_scorer",
    "scripts.smc_calendar_collector",
    "scripts.smc_library_layering",
    "scripts.smc_fmp_client",
    "scripts.smc_provider_policy",
    "scripts.smc_enrichment_types",
    "scripts.smc_event_risk_builder",
    "scripts.smc_alert_notifier",
    "scripts.generate_smc_micro_base_from_databento",
    "scripts.generate_smc_micro_profiles",
    "scripts.smc_microstructure_base_runtime",
]


class TestCanonicalModulesOpenPrepFree:
    """Every canonical v5 runtime module is free of open_prep imports."""

    @pytest.mark.parametrize("module_name", _V5_CANONICAL_MODULES)
    def test_no_open_prep_import_statement(self, module_name: str):
        """Source scan: no ``from open_prep`` or ``import open_prep``."""
        import re

        mod = importlib.import_module(module_name)
        spec = importlib.util.find_spec(mod.__name__)
        assert spec is not None and spec.origin is not None
        with open(spec.origin, encoding="utf-8") as _f:
            source = _f.read()
        hits = re.findall(
            r"^\s*(from|import)\s+open_prep\b", source, re.MULTILINE
        )
        assert hits == [], f"{module_name} has open_prep imports: {hits}"


class TestV4PackagesOpenPrepFree:
    """smc_core and smc_integration packages have zero open_prep dependency."""

    @staticmethod
    def _scan_package(pkg_path: str) -> list[str]:
        """Return any .py files under *pkg_path* that contain open_prep imports."""
        import re
        from pathlib import Path

        violations: list[str] = []
        for py in sorted(Path(pkg_path).rglob("*.py")):
            source = py.read_text(encoding="utf-8")
            if re.search(r"^\s*(from|import)\s+open_prep\b", source, re.MULTILINE):
                violations.append(str(py))
        return violations

    def test_smc_core_no_open_prep(self):
        from pathlib import Path

        pkg = Path(__file__).resolve().parent.parent / "smc_core"
        violations = self._scan_package(str(pkg))
        assert violations == [], f"smc_core files with open_prep: {violations}"

    def test_smc_integration_no_open_prep(self):
        from pathlib import Path

        pkg = Path(__file__).resolve().parent.parent / "smc_integration"
        violations = self._scan_package(str(pkg))
        assert violations == [], f"smc_integration files with open_prep: {violations}"

    def test_newsstack_fmp_no_open_prep(self):
        from pathlib import Path

        pkg = Path(__file__).resolve().parent.parent / "newsstack_fmp"
        violations = self._scan_package(str(pkg))
        assert violations == [], f"newsstack_fmp files with open_prep: {violations}"


class _ImportBlocker:
    """Meta-path finder that raises ImportError for a blocked package."""

    def __init__(self, blocked: str):
        self.blocked = blocked

    def find_module(self, fullname: str, path: Any = None) -> _ImportBlocker | None:
        if fullname == self.blocked or fullname.startswith(f"{self.blocked}."):
            return self
        return None

    def load_module(self, fullname: str) -> types.ModuleType:
        raise ImportError(
            f"open_prep import blocked by test: {fullname}"
        )


# ── 3. Error-path compatibility ────────────────────────────────


class TestErrorPaths:
    """Standalone client returns safe defaults on failures."""

    def test_get_market_pe_forward_falls_back_to_alternate_market_symbol(self):
        c = SMCFMPClient(api_key="k")

        def _quote(symbol: str) -> dict[str, Any]:
            if symbol == "IVV":
                return {"symbol": symbol, "price": 700.0}
            return {"symbol": symbol, "price": 680.0}

        def _profile(symbol: str) -> dict[str, Any]:
            if symbol == "IVV":
                return {"symbol": symbol, "forwardPE": 27.8, "price": 700.0}
            return {"symbol": symbol, "price": 680.0}

        with (
            patch.object(c, "get_index_quote", side_effect=_quote),
            patch.object(c, "get_company_profile", side_effect=_profile),
            patch.object(c, "get_ratios_ttm", return_value=[]),
            patch.object(c, "get_key_metrics_ttm", return_value=[]),
            patch.object(c, "get_analyst_estimates", return_value=[]),
        ):
            value = c.get_market_pe_forward()

        assert value == pytest.approx(27.8)
        assert c._last_market_pe_forward_diagnostics["status"] == "ok"
        assert c._last_market_pe_forward_diagnostics["source_category"] == "direct_forward"
        assert c._last_market_pe_forward_diagnostics["source_symbol"] == "IVV"
        assert c._last_market_pe_forward_diagnostics["attempted_symbols"][:2] == ["SPY", "IVV"]

    def test_get_market_pe_forward_uses_key_metrics_ttm(self):
        """key_metrics_ttm provides PE when quote/profile/ratios have none."""
        c = SMCFMPClient(api_key="k")

        with (
            patch.object(c, "get_index_quote", return_value={"price": 500.0}),
            patch.object(c, "get_company_profile", return_value={"price": 500.0}),
            patch.object(c, "get_ratios_ttm", return_value=[{}]),
            patch.object(c, "get_key_metrics_ttm", return_value=[{"peRatioTTM": 22.5}]),
            patch.object(c, "get_analyst_estimates", return_value=[]),
        ):
            value = c.get_market_pe_forward()

        assert value == pytest.approx(22.5)
        assert c._last_market_pe_forward_diagnostics["status"] == "ok"
        assert c._last_market_pe_forward_diagnostics["source_category"] == "approximate_ttm"
        assert c._last_market_pe_forward_diagnostics["field"] == "peRatioTTM"

    def test_get_market_pe_forward_reaches_stock_symbols(self):
        """When all ETF symbols fail, AAPL/MSFT are tried as stock fallbacks."""
        c = SMCFMPClient(api_key="k")

        calls: list[str] = []

        def _quote(symbol: str) -> dict[str, Any]:
            calls.append(symbol)
            if symbol == "AAPL":
                return {"price": 200.0}
            return {"price": 100.0}

        def _profile(symbol: str) -> dict[str, Any]:
            if symbol == "AAPL":
                return {"forwardPE": 31.0, "price": 200.0}
            return {"price": 100.0}

        with (
            patch.object(c, "get_index_quote", side_effect=_quote),
            patch.object(c, "get_company_profile", side_effect=_profile),
            patch.object(c, "get_ratios_ttm", return_value=[{}]),
            patch.object(c, "get_key_metrics_ttm", return_value=[{}]),
            patch.object(c, "get_analyst_estimates", return_value=[]),
        ):
            value = c.get_market_pe_forward()

        assert value == pytest.approx(31.0)
        assert "AAPL" in calls
        assert c._last_market_pe_forward_diagnostics["source_symbol"] == "AAPL"

    @patch("scripts.smc_fmp_client.urlopen")
    def test_get_index_quote_returns_empty_on_error(self, mock_urlopen):
        mock_urlopen.side_effect = RuntimeError("network error")
        c = SMCFMPClient(api_key="k", retry_attempts=1)
        assert c.get_index_quote() == {}

    @patch("scripts.smc_fmp_client.urlopen")
    def test_get_sector_performance_returns_empty_on_error(self, mock_urlopen):
        mock_urlopen.side_effect = RuntimeError("network error")
        c = SMCFMPClient(api_key="k", retry_attempts=1)
        assert c.get_sector_performance() == []

    def test_get_sector_performance_uses_snapshot_endpoint_and_aggregates_rows(self):
        c = SMCFMPClient(api_key="k")
        calls: list[tuple[str, str]] = []

        def _fake_get(path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
            calls.append((path, str(params.get("date") or "")))
            if params.get("date") == "2026-01-05":
                return []
            return [
                {"sector": "Technology", "exchange": "NYSE", "averageChange": 1.0},
                {"sector": "Technology", "exchange": "NASDAQ", "averageChange": 3.0},
                {"sector": "Healthcare", "exchange": "NYSE", "averageChange": -2.0},
            ]

        with (
            patch("scripts.smc_fmp_client._today_et", return_value=date(2026, 1, 5)),
            patch("scripts.smc_fmp_client._prev_trading_day", return_value=date(2026, 1, 2)),
            patch.object(c, "_get", side_effect=_fake_get),
        ):
            rows = c.get_sector_performance()

        assert calls == [
            ("/stable/sector-performance-snapshot", "2026-01-05"),
            ("/stable/sector-performance-snapshot", "2026-01-02"),
        ]
        assert rows == [
            {"sector": "Technology", "changesPercentage": 2.0},
            {"sector": "Healthcare", "changesPercentage": -2.0},
        ]
        assert c._last_sector_performance_diagnostics["status"] == "ok"
        assert c._last_sector_performance_diagnostics["used_fallback_previous_trading_day"] is True
        assert c._last_sector_performance_diagnostics["selected_date"] == "2026-01-02"
        assert c._last_sector_performance_diagnostics["raw_row_count"] == 3
        assert c._last_sector_performance_diagnostics["returned_row_count"] == 2

    @patch("scripts.smc_fmp_client.urlopen")
    def test_get_stock_latest_news_returns_empty_on_error(self, mock_urlopen):
        mock_urlopen.side_effect = RuntimeError("network error")
        c = SMCFMPClient(api_key="k", retry_attempts=1)
        assert c.get_stock_latest_news(limit=10) == []

    @patch("scripts.smc_fmp_client.urlopen")
    def test_get_earnings_calendar_returns_empty_on_error(self, mock_urlopen):
        mock_urlopen.side_effect = RuntimeError("network error")
        c = SMCFMPClient(api_key="k", retry_attempts=1)
        assert c.get_earnings_calendar(date(2026, 1, 1), date(2026, 1, 2)) == []

    @patch("scripts.smc_fmp_client.urlopen")
    def test_get_macro_calendar_returns_empty_on_error(self, mock_urlopen):
        mock_urlopen.side_effect = RuntimeError("network error")
        c = SMCFMPClient(api_key="k", retry_attempts=1)
        assert c.get_macro_calendar(date(2026, 1, 1), date(2026, 1, 1)) == []

    @patch("scripts.smc_fmp_client.urlopen")
    def test_get_technical_indicator_returns_empty_on_error(self, mock_urlopen):
        mock_urlopen.side_effect = RuntimeError("network error")
        c = SMCFMPClient(api_key="k", retry_attempts=1)
        assert c.get_technical_indicator("SPY", "1day", "rsi") == {}


# ── 4. Parse behaviour ─────────────────────────────────────────


class TestParsePayloads:
    """_parse rejects HTML and FMP error responses."""

    def test_html_raises(self):
        with pytest.raises(RuntimeError, match="HTML"):
            SMCFMPClient._parse("/test", "<!DOCTYPE html><html></html>")

    def test_fmp_api_error_raises(self):
        payload = '{"status": "error", "message": "Limit reached"}'
        with pytest.raises(RuntimeError, match="Limit reached"):
            SMCFMPClient._parse("/test", payload)

    def test_valid_json_list(self):
        data = SMCFMPClient._parse("/test", '[{"a": 1}]')
        assert data == [{"a": 1}]

    def test_valid_json_dict(self):
        data = SMCFMPClient._parse("/test", '{"price": 15.5}')
        assert data == {"price": 15.5}

"""Tests proving the v4 pipeline runs without importing open_prep.

Validates:
- SMCFMPClient is method-compatible with the provider-policy adapters
- build_enrichment() never imports open_prep
- The standalone client handles errors identically to the original
"""

from __future__ import annotations

import importlib
import sys
import types
from datetime import date
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from scripts.smc_fmp_client import SMCFMPClient


# ── 1. SMCFMPClient surface ────────────────────────────────────


class TestSMCFMPClientInterface:
    """The standalone client exposes the six methods the adapters need."""

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

    def test_default_retry_and_timeout(self):
        c = SMCFMPClient(api_key="k")
        assert c.retry_attempts == 2
        assert c.timeout_seconds == 12.0


# ── 2. No open_prep at runtime ─────────────────────────────────


class TestNoOpenPrepImport:
    """The v4 pipeline path never touches open_prep."""

    def test_smc_fmp_client_has_no_open_prep_imports(self):
        """The standalone client module has no import of open_prep."""
        import scripts.smc_fmp_client as mod

        src = importlib.util.find_spec(mod.__name__)
        assert src is not None and src.origin is not None
        source = open(src.origin, encoding="utf-8").read()
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

    def test_provider_policy_has_no_open_prep_imports(self):
        """smc_provider_policy.py never references open_prep."""
        import scripts.smc_provider_policy as mod

        src = importlib.util.find_spec(mod.__name__)
        assert src is not None and src.origin is not None
        source = open(src.origin, encoding="utf-8").read()
        assert "open_prep" not in source


# ── 2b. Canonical v4 modules contain no open_prep imports ──────

# These are the four runtime modules the v4 doc requires to be canonical,
# plus the orchestrator, profile generator, and all smc_core / smc_integration
# packages.

_V4_CANONICAL_MODULES = [
    "scripts.smc_regime_classifier",
    "scripts.smc_news_scorer",
    "scripts.smc_calendar_collector",
    "scripts.smc_library_layering",
    "scripts.smc_fmp_client",
    "scripts.smc_provider_policy",
    "scripts.generate_smc_micro_base_from_databento",
    "scripts.generate_smc_micro_profiles",
]


class TestCanonicalModulesOpenPrepFree:
    """Every canonical v4 runtime module is free of open_prep imports."""

    @pytest.mark.parametrize("module_name", _V4_CANONICAL_MODULES)
    def test_no_open_prep_import_statement(self, module_name: str):
        """Source scan: no ``from open_prep`` or ``import open_prep``."""
        import re

        mod = importlib.import_module(module_name)
        spec = importlib.util.find_spec(mod.__name__)
        assert spec is not None and spec.origin is not None
        source = open(spec.origin, encoding="utf-8").read()
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

    def find_module(self, fullname: str, path: Any = None) -> "_ImportBlocker | None":
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

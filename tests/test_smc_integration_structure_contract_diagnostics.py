from __future__ import annotations

import json
from pathlib import Path

from smc_integration.sources import structure_artifact_json
from smc_integration.structure_contract import normalize_structure_contracts_with_diagnostics


def test_normalize_structure_contracts_reports_dropped_legacy_entries() -> None:
    payload = {
        "entries": [
            {
                "symbol": "AAPL",
                "timeframe": "15m",
                "structure": {
                    "bos": [],
                    "orderblocks": [],
                    "fvg": [],
                    "liquidity_sweeps": [],
                },
            },
            {
                "symbol": "",
                "timeframe": "15m",
                "structure": {
                    "bos": [],
                    "orderblocks": [],
                    "fvg": [],
                    "liquidity_sweeps": [],
                },
            },
            "bad-entry",
        ]
    }

    contracts, diagnostics = normalize_structure_contracts_with_diagnostics(payload)

    assert len(contracts) == 1
    assert diagnostics["entries_total"] == 3
    assert diagnostics["entries_normalized"] == 1
    assert diagnostics["entries_dropped"] == 2
    assert diagnostics["entries_dropped_non_dict"] == 1
    assert diagnostics["entries_dropped_value_error"] == 1


def test_discover_summary_reports_legacy_drop_health_issue(monkeypatch, tmp_path: Path) -> None:
    legacy_path = tmp_path / "reports" / "smc_structure_artifact.json"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "symbol": "AAPL",
                        "timeframe": "15m",
                        "structure": {
                            "bos": [],
                            "orderblocks": [],
                            "fvg": [],
                            "liquidity_sweeps": [],
                        },
                    },
                    {
                        "symbol": "",
                        "timeframe": "15m",
                        "structure": {
                            "bos": [],
                            "orderblocks": [],
                            "fvg": [],
                            "liquidity_sweeps": [],
                        },
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(structure_artifact_json, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACTS_DIR", tmp_path / "reports" / "smc_structure_artifacts")
    monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACT_JSON", legacy_path)

    summary = structure_artifact_json.discover_normalized_contract_summary()

    assert summary["health"]["issue_count"] >= 1
    codes = {str(item.get("code", "")) for item in summary["health"]["issues"]}
    assert "LEGACY_ENTRIES_DROPPED" in codes


# ── pure helper coverage ─────────────────────────────────────────

import pytest

from smc_integration.structure_contract import (
    _auxiliary,
    _canonical_structure,
    _coerce_symbol,
    _coerce_timeframe,
    _diagnostics,
    _normalize_single,
    _select_legacy_entry,
    normalize_structure_contract,
    normalize_structure_contracts,
)


class TestCanonicalStructure:
    def test_non_dict_returns_empty(self) -> None:
        result = _canonical_structure("not_a_dict")
        assert result == {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []}

    def test_non_list_value_becomes_empty(self) -> None:
        result = _canonical_structure({"bos": "bad", "orderblocks": [], "fvg": [], "liquidity_sweeps": []})
        assert result["bos"] == []


class TestAuxiliary:
    def test_non_dict_returns_defaults(self) -> None:
        result = _auxiliary("bad")
        assert result["liquidity_lines"] == []
        assert result["ipda_range"] == {}

    def test_ipda_operating_range_fallback(self) -> None:
        result = _auxiliary({"ipda_range": "bad", "ipda_operating_range": {"high": 100}})
        assert result["ipda_range"] == {"high": 100}

    def test_ipda_both_bad(self) -> None:
        result = _auxiliary({"ipda_range": "bad", "ipda_operating_range": "also_bad"})
        assert result["ipda_range"] == {}


class TestCoerceSymbol:
    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="symbol must not be empty"):
            _coerce_symbol("")


class TestCoerceTimeframe:
    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="timeframe must not be empty"):
            _coerce_timeframe("   ")


class TestDiagnostics:
    def test_non_dict_returns_empty(self) -> None:
        result, present = _diagnostics("bad")
        assert result == {}
        assert present is False

    def test_empty_dict(self) -> None:
        result, present = _diagnostics({})
        assert result == {}
        assert present is False

    def test_populated_dict(self) -> None:
        result, present = _diagnostics({"foo": 1})
        assert result == {"foo": 1}
        assert present is True


class TestNormalizeSingleWarnings:
    def test_warnings_in_diagnostics(self) -> None:
        payload = {
            "symbol": "AAPL",
            "timeframe": "15m",
            "structure": {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []},
            "diagnostics": {"warnings": ["w1", "w2"]},
        }
        contract = _normalize_single(payload)
        assert contract.warnings == ["w1", "w2"]
        assert "warnings" in contract.structure_context


class TestNormalizeStructureContract:
    def test_non_dict_raises(self) -> None:
        with pytest.raises(ValueError, match="must be an object"):
            normalize_structure_contract("not_a_dict")

    def test_legacy_entries_without_symbol_raises(self) -> None:
        with pytest.raises(ValueError, match="symbol is required"):
            normalize_structure_contract({"entries": [{"symbol": "AAPL", "timeframe": "15m"}]})

    def test_legacy_entries_with_symbol(self) -> None:
        payload = {
            "entries": [
                {
                    "symbol": "AAPL",
                    "timeframe": "15m",
                    "structure": {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []},
                },
            ],
        }
        contract = normalize_structure_contract(payload, symbol="AAPL", timeframe="15m")
        assert contract.symbol == "AAPL"

    def test_single_payload_path(self) -> None:
        payload = {
            "symbol": "MSFT",
            "timeframe": "1D",
            "structure": {"bos": [{"x": 1}], "orderblocks": [], "fvg": [], "liquidity_sweeps": []},
        }
        contract = normalize_structure_contract(payload)
        assert contract.symbol == "MSFT"
        assert contract.counts["bos"] == 1


class TestNormalizeContractsWithDiagnosticsSinglePath:
    def test_single_payload(self) -> None:
        payload = {
            "symbol": "TSLA",
            "timeframe": "15m",
            "structure": {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []},
        }
        contracts, diag = normalize_structure_contracts_with_diagnostics(payload)
        assert len(contracts) == 1
        assert diag["entries_total"] == 1
        assert diag["entries_dropped"] == 0

    def test_non_dict_raises(self) -> None:
        with pytest.raises(ValueError, match="must be an object"):
            normalize_structure_contracts_with_diagnostics("bad")


class TestNormalizeStructureContracts:
    def test_returns_list(self) -> None:
        payload = {
            "symbol": "GOOG",
            "timeframe": "15m",
            "structure": {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []},
        }
        contracts = normalize_structure_contracts(payload)
        assert len(contracts) == 1
        assert contracts[0].symbol == "GOOG"


class TestSelectLegacyEntry:
    def test_symbol_not_found_raises(self) -> None:
        with pytest.raises(ValueError, match="not present"):
            _select_legacy_entry([{"symbol": "AAPL"}], symbol="MSFT", timeframe="15m")

    def test_exact_timeframe_match(self) -> None:
        entries = [
            {"symbol": "AAPL", "timeframe": "1D"},
            {"symbol": "AAPL", "timeframe": "15m"},
        ]
        result = _select_legacy_entry(entries, symbol="AAPL", timeframe="15m")
        assert result["timeframe"] == "15m"

    def test_fallback_to_first_symbol_match(self) -> None:
        entries = [
            {"symbol": "AAPL", "timeframe": "1D"},
        ]
        result = _select_legacy_entry(entries, symbol="AAPL", timeframe="15m")
        assert result["timeframe"] == "1D"


class TestLegacyTfFallbackWarning:
    """Cross-TF aliasing guard (2026-06-10 ADR).

    The legacy single-artifact fallback used to serve another
    timeframe's structure silently; every per-TF benchmark slice became
    an identical clone and Plan 2.8 Phase-E2 verdicts compared an arm
    against itself. The fallback stays (rolling benchmark must not
    hard-fail) but must be loud.
    """

    @staticmethod
    def _entries_payload() -> dict:
        return {
            "entries": [
                {
                    "symbol": "AAPL",
                    "timeframe": "1D",
                    "structure": {
                        "bos": [],
                        "orderblocks": [],
                        "fvg": [],
                        "liquidity_sweeps": [],
                    },
                },
            ]
        }

    def test_exact_match_has_no_fallback_warning(self) -> None:
        contract = normalize_structure_contract(
            self._entries_payload(), symbol="AAPL", timeframe="1D"
        )
        assert not any("legacy_tf_fallback" in w for w in contract.warnings)

    def test_case_insensitive_match_has_no_fallback_warning(self) -> None:
        contract = normalize_structure_contract(
            self._entries_payload(), symbol="AAPL", timeframe="1d"
        )
        assert not any("legacy_tf_fallback" in w for w in contract.warnings)

    def test_fallback_appends_warning_with_both_timeframes(self) -> None:
        contract = normalize_structure_contract(
            self._entries_payload(), symbol="AAPL", timeframe="5m"
        )
        expected = "legacy_tf_fallback: requested 5m, served 1D"
        assert expected in contract.warnings
        assert expected in contract.structure_context["warnings"]

    def test_fallback_preserves_existing_diagnostics_warnings(self) -> None:
        payload = self._entries_payload()
        payload["entries"][0]["diagnostics"] = {"warnings": ["existing"]}
        contract = normalize_structure_contract(
            payload, symbol="AAPL", timeframe="5m"
        )
        assert contract.warnings == [
            "existing",
            "legacy_tf_fallback: requested 5m, served 1D",
        ]

    def test_fallback_does_not_mutate_input_payload(self) -> None:
        payload = self._entries_payload()
        normalize_structure_contract(payload, symbol="AAPL", timeframe="5m")
        assert "diagnostics" not in payload["entries"][0]

    def test_fallback_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        with caplog.at_level(logging.WARNING, logger="smc_integration.structure_contract"):
            normalize_structure_contract(
                self._entries_payload(), symbol="AAPL", timeframe="5m"
            )
        assert any("cross-TF comparisons" in rec.getMessage() for rec in caplog.records)
